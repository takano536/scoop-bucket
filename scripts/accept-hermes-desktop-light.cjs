'use strict'

const fs = require('node:fs')
const path = require('node:path')

function argument(name) {
  const index = process.argv.indexOf(`--${name}`)
  if (index < 0 || index + 1 >= process.argv.length) {
    throw new Error(`missing --${name}`)
  }
  return process.argv[index + 1]
}

function optionalArgument(name) {
  const index = process.argv.indexOf(`--${name}`)
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : null
}

const isMain = require.main === module
const phase = isMain ? argument('phase') : null
const cdpPort = isMain ? Number(argument('cdp-port')) : null
const appRoot = isMain ? path.resolve(argument('app-root')) : null
const gatewayUrl = isMain ? argument('gateway-url').replace(/\/+$/, '') : null
const secret = isMain ? argument('secret') : null
const wrongSecret = isMain ? argument('wrong-secret') : null
const resultPath = isMain ? path.resolve(argument('result')) : null
const diagnosticsDirectory = isMain ? optionalArgument('diagnostics-directory') : null
const stageLogPath = isMain ? optionalArgument('stage-log') : null
const preview = isMain && process.argv.includes('--preview')

const DEFAULT_TIMEOUTS = Object.freeze({
  cdpTargetSearchMs: 120000,
  cdpHttpRequestMs: 5000,
  cdpConnectMs: 15000,
  cdpCallMs: 20000,
  gatewayRequestMs: 10000,
})

function timeoutError(operation, timeoutMs) {
  return new Error(`Timed out waiting for ${operation} after ${timeoutMs}ms`)
}

function withTimeout(promise, timeoutMs, operation, onTimeout) {
  let timer
  const timeout = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      reject(timeoutError(operation, timeoutMs))
      try {
        const cleanup = onTimeout?.()
        if (cleanup && typeof cleanup.catch === 'function') cleanup.catch(() => {})
      } catch {
        // The named timeout is the actionable failure; cleanup is best effort.
      }
    }, timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

function writeStage(name, details = '') {
  const suffix = details ? ` ${redact(details)}` : ''
  const line = `[acceptance] ${new Date().toISOString()} stage=${name}${suffix}`
  process.stdout.write(`${line}\n`)
  if (stageLogPath) {
    try {
      fs.appendFileSync(stageLogPath, `${line}\n`, 'utf8')
    } catch {
      // The parent process writes a stage log even if this path is unavailable.
    }
  }
}

function safeJson(value) {
  try {
    return redact(JSON.stringify(value, null, 2))
  } catch {
    return redact(String(value))
  }
}

function redact(value) {
  let text = String(value ?? '')
  for (const credential of [secret, wrongSecret]) {
    if (credential) text = text.split(credential).join('[REDACTED]')
  }
  return text.replace(/([?&](?:token|ticket)=)[^&\s]+/gi, '$1[REDACTED]')
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

class CdpClient {
  constructor(url, {
    connectTimeoutMs = DEFAULT_TIMEOUTS.cdpConnectMs,
    callTimeoutMs = DEFAULT_TIMEOUTS.cdpCallMs
  } = {}) {
    this.url = url
    this.connectTimeoutMs = connectTimeoutMs
    this.callTimeoutMs = callTimeoutMs
    this.socket = new WebSocket(url)
    this.nextId = 1
    this.pending = new Map()
    this.closed = false
    let resolveOpened
    let rejectOpened
    const openedPromise = new Promise((resolve, reject) => {
      resolveOpened = resolve
      rejectOpened = reject
    })
    this.opened = withTimeout(
      openedPromise,
      connectTimeoutMs,
      'CDP WebSocket connection',
      () => this.close()
    )
    this.socket.addEventListener('open', () => {
      resolveOpened()
    }, { once: true })
    this.socket.addEventListener('error', event => {
      const error = new Error(redact(event?.message || 'CDP WebSocket error'))
      rejectOpened(error)
      for (const waiter of this.pending.values()) waiter.reject(error)
      this.pending.clear()
    }, { once: true })
    this.socket.addEventListener('message', event => {
      let message
      try {
        message = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (!message.id) return
      const waiter = this.pending.get(message.id)
      if (!waiter) return
      this.pending.delete(message.id)
      if (message.error) waiter.reject(new Error(redact(message.error.message || JSON.stringify(message.error))))
      else waiter.resolve(message.result || {})
    })
    this.socket.addEventListener('close', () => {
      this.closed = true
      const error = new Error('CDP connection closed')
      rejectOpened(error)
      for (const waiter of this.pending.values()) waiter.reject(error)
      this.pending.clear()
    })
  }

  async call(method, params = {}, operation = `CDP ${method} response`) {
    await this.opened
    if (this.closed) throw new Error('CDP connection is closed')
    const id = this.nextId++
    const response = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      try {
        this.socket.send(JSON.stringify({ id, method, params }))
      } catch (error) {
        this.pending.delete(id)
        reject(error)
      }
    })
    return withTimeout(response, this.callTimeoutMs, operation, () => this.close())
  }

  close() {
    if (this.closed) return
    this.closed = true
    const error = new Error('CDP connection closed')
    for (const waiter of this.pending.values()) waiter.reject(error)
    this.pending.clear()
    try { this.socket.close() } catch { /* best effort */ }
  }
}

async function fetchWithTimeout(url, options, timeoutMs, operation) {
  const controller = new AbortController()
  try {
    return await withTimeout(
      fetch(url, { ...options, signal: controller.signal }),
      timeoutMs,
      operation,
      () => controller.abort()
    )
  } catch (error) {
    if (error?.name === 'AbortError') throw timeoutError(operation, timeoutMs)
    throw error
  }
}

async function findTarget() {
  const timeoutMs = DEFAULT_TIMEOUTS.cdpTargetSearchMs
  const deadline = Date.now() + timeoutMs
  let lastError = null
  writeStage('cdp-target-search-start', `port=${cdpPort}`)
  while (Date.now() < deadline) {
    try {
      const response = await fetchWithTimeout(
        `http://127.0.0.1:${cdpPort}/json/list`,
        undefined,
        DEFAULT_TIMEOUTS.cdpHttpRequestMs,
        'Electron CDP target-list response'
      )
      if (!response.ok) throw new Error(`CDP target-list returned HTTP ${response.status}`)
      const targets = await withTimeout(
        response.json(),
        DEFAULT_TIMEOUTS.cdpHttpRequestMs,
        'Electron CDP target-list body'
      )
      const target = targets.find(item => item.type === 'page' && item.webSocketDebuggerUrl)
      if (target) {
        writeStage('cdp-target-found', `type=${target.type}`)
        return target
      }
      lastError = new Error('Electron CDP endpoint has no page target yet')
    } catch (error) {
      lastError = error
    }
    await sleep(Math.min(1000, Math.max(0, deadline - Date.now())))
  }
  throw timeoutError(
    `Electron CDP page target (${redact(lastError?.message || 'no target response')})`,
    timeoutMs
  )
}

async function evaluate(client, expression, operation = 'Electron renderer Runtime.evaluate') {
  const response = await client.call('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true
  }, operation)
  if (response.exceptionDetails) {
    throw new Error(redact(response.exceptionDetails.exception?.description || response.exceptionDetails.text || 'renderer evaluation failed'))
  }
  return response.result?.value
}

async function bridge(client, method, value) {
  const literal = value === undefined ? '' : JSON.stringify(value)
  const expression = `(async () => { try { return { ok: true, value: await window.hermesDesktop.${method}(${literal}) } } catch (error) { return { ok: false, error: String(error?.message || error) } } })()`
  const result = await evaluate(client, expression, `Electron bridge ${method}`)
  assert(result && typeof result.ok === 'boolean', `${method} returned no result`)
  return result
}

function appTreeFingerprint(root) {
  const rows = []
  const walk = directory => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.isFile()) {
        const stat = fs.statSync(full)
        rows.push(`${path.relative(root, full)}|${stat.size}|${Math.trunc(stat.mtimeMs)}`)
      }
    }
  }
  walk(root)
  rows.sort()
  return rows.join('\n')
}

async function fetchJson(url, token) {
  const pathname = new URL(url).pathname
  const controller = new AbortController()
  const response = await withTimeout(
    fetch(url, {
      signal: controller.signal,
      headers: { 'X-Hermes-Session-Token': token, Accept: 'application/json' }
    }),
    DEFAULT_TIMEOUTS.gatewayRequestMs,
    `gateway HTTP response ${pathname}`,
    () => controller.abort()
  )
  const text = await withTimeout(
    response.text(),
    DEFAULT_TIMEOUTS.gatewayRequestMs,
    `gateway HTTP body ${pathname}`,
    () => controller.abort()
  )
  let body = null
  try { body = JSON.parse(text) } catch { body = text.slice(0, 300) }
  return { status: response.status, body }
}

async function fetchJsonWithRetry(url, token) {
  let last = null
  for (let attempt = 0; attempt < 15; attempt += 1) {
    try {
      const result = await fetchJson(url, token)
      if (result.status !== 502 && result.status !== 503) return result
      last = result
    } catch (error) {
      last = { error: redact(error.message) }
    }
    await sleep(500)
  }
  writeStage('gateway-http-retries-exhausted', `attempts=15 path=${new URL(url).pathname}`)
  return last || { error: 'no response' }
}

async function persistedGatewayRpc(client, method, params = {}) {
  // This bridge call mints a fresh URL from the app's persisted connection
  // secret; no token is supplied by the acceptance driver. The wire shape is
  // the upstream JSON-RPC contract at apps/shared/src/json-rpc-channel.ts,
  // and session.list is defined by apps/shared/src/gateway-contract.openrpc.json.
  const urlResult = await bridge(client, 'getGatewayWsUrl')
  assert(urlResult.ok, `persisted gateway URL mint failed: ${redact(urlResult.error)}`)
  const wsUrl = typeof urlResult.value === 'string' ? urlResult.value : urlResult.value?.wsUrl
  assert(typeof wsUrl === 'string' && /^wss?:\/\//.test(wsUrl), 'persisted gateway URL mint returned no WebSocket URL')

  const request = {
    jsonrpc: '2.0',
    id: `hermes-desktop-light-acceptance-${Date.now()}`,
    method,
    params
  }
  const response = await evaluate(client, `(async () => {
    const request = ${JSON.stringify(request)}
    return await new Promise(resolve => {
      let socket
      try {
        socket = new WebSocket(${JSON.stringify(wsUrl)})
      } catch (error) {
        resolve({ ok: false, error: String(error?.message || error) })
        return
      }

      let settled = false
      const timer = setTimeout(() => finish({ ok: false, error: 'timed out waiting for persisted WebSocket RPC' }), 15000)
      const finish = value => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        try { socket.close() } catch {}
        resolve(value)
      }

      socket.addEventListener('open', () => {
        try {
          socket.send(JSON.stringify(request))
        } catch (error) {
          finish({ ok: false, error: String(error?.message || error) })
        }
      }, { once: true })
      socket.addEventListener('message', event => {
        let frame
        try {
          frame = JSON.parse(String(event.data))
        } catch {
          return
        }
        if (!frame || frame.id !== request.id) return
        if (frame.error) finish({ ok: false, error: frame.error })
        else finish({ ok: true, result: frame.result })
      })
      socket.addEventListener('error', () => finish({ ok: false, error: 'persisted WebSocket error' }), { once: true })
      socket.addEventListener('close', event => {
        if (!settled) finish({ ok: false, error: 'persisted WebSocket closed before RPC response (code ' + event.code + ')' })
      }, { once: true })
    })
  })()`)
  assert(response && response.ok === true,
    `app persisted WebSocket ${method} RPC failed: ${redact(JSON.stringify(response))}`)
  return response.result
}

async function writeDiagnostics(error, { client, target }) {
  if (!diagnosticsDirectory) return
  try {
    fs.mkdirSync(diagnosticsDirectory, { recursive: true })
    fs.writeFileSync(
      path.join(diagnosticsDirectory, 'failure.json'),
      `${safeJson({ status: 'failed', phase, error: redact(error?.message || error) })}\n`,
      'utf8'
    )
    try {
      const response = await fetchWithTimeout(
        `http://127.0.0.1:${cdpPort}/json/list`,
        undefined,
        3000,
        'diagnostic Electron CDP target-list response'
      )
      const targets = await withTimeout(
        response.json(),
        3000,
        'diagnostic Electron CDP target-list body'
      )
      fs.writeFileSync(path.join(diagnosticsDirectory, 'cdp-targets.json'), `${safeJson(targets)}\n`, 'utf8')
    } catch (targetError) {
      fs.writeFileSync(
        path.join(diagnosticsDirectory, 'cdp-targets.json'),
        `${safeJson({ error: redact(targetError?.message || targetError) })}\n`,
        'utf8'
      )
    }
    if (target) {
      fs.writeFileSync(path.join(diagnosticsDirectory, 'cdp-selected-target.json'), `${safeJson(target)}\n`, 'utf8')
    }
    if (client && !client.closed) {
      try {
        const screenshot = await client.call(
          'Page.captureScreenshot',
          { format: 'png' },
          'diagnostic Electron screenshot'
        )
        if (screenshot?.data) {
          fs.writeFileSync(path.join(diagnosticsDirectory, 'electron-screenshot.png'), Buffer.from(screenshot.data, 'base64'))
        }
      } catch (screenshotError) {
        fs.writeFileSync(
          path.join(diagnosticsDirectory, 'electron-screenshot.error.txt'),
          `${redact(screenshotError?.message || screenshotError)}\n`,
          'utf8'
        )
      }
    }
    writeStage('diagnostics-written', `directory=${diagnosticsDirectory}`)
  } catch (diagnosticError) {
    process.stderr.write(`[acceptance] diagnostics failed: ${redact(diagnosticError?.message || diagnosticError)}\n`)
  }
}

async function run() {
  assert(Number.isInteger(cdpPort) && cdpPort > 0, 'invalid CDP port')
  assert(fs.existsSync(appRoot), `installed app root is missing: ${appRoot}`)
  let target = null
  let client = null
  const result = {
    schema: 1,
    status: 'passed',
    phase,
    preview,
    cdp: 'Chromium DevTools Protocol over the packaged app launched by its Scoop .lnk shortcut',
    gateway: { url: gatewayUrl, authenticated: false },
    localExecution: null,
    connection: {},
    sessionRoundTrip: {},
    settings: {},
    updater: {}
  }

  try {
    writeStage('validation-start', `phase=${phase}`)
    target = await findTarget()
    writeStage('cdp-connect-start')
    client = new CdpClient(target.webSocketDebuggerUrl)
    writeStage('renderer-readiness-start')
    await evaluate(client, `document.body && document.body.innerText && document.body.innerText.trim().length > 10`, 'Electron renderer readiness')
    writeStage('renderer-ready')
    const payload = {
      mode: 'remote',
      remoteAuthMode: 'token',
      remoteToken: secret,
      remoteUrl: gatewayUrl,
      allowPlainTextToken: true
    }

    if (phase === 'before') {
      writeStage('local-backend-probe-start')
      const localOfferVisible = await evaluate(client, `document.body.innerText.includes('Install Hermes locally')`, 'local-install offer visibility')
      const localProbe = await bridge(client, 'probeLocalBackend')
      assert(localProbe.ok, `local backend probe failed: ${redact(localProbe.error)}`)
      assert(localProbe.value && localProbe.value.bootstrapNeeded === true,
        `Light local probe did not report bootstrap-needed: ${JSON.stringify(localProbe.value)}`)
      result.localExecution = {
        localInstallOfferVisible: localOfferVisible === true,
        probe: { bootstrapNeeded: true },
        localInstallNotStarted: true,
        conclusion: 'No bundled local backend was runnable; the first-run local option resolves to bootstrap-needed and was not executed.'
      }

      writeStage('connection-negative-test-start')
      const wrongTest = await bridge(client, 'testConnectionConfig', { ...payload, remoteToken: wrongSecret })
      assert(!wrongTest.ok, 'wrong gateway secret was unexpectedly accepted by the packaged app')
      result.connection.negative = { rejected: true, error: redact(wrongTest.error) }

      writeStage('connection-positive-test-start')
      const positiveTest = await bridge(client, 'testConnectionConfig', payload)
      assert(positiveTest.ok && positiveTest.value?.ok === true,
        `packaged app did not pass authenticated HTTP+WebSocket test: ${redact(positiveTest.error || JSON.stringify(positiveTest.value))}`)
      result.connection.preflight = { ok: true, baseUrl: positiveTest.value.baseUrl, version: positiveTest.value.version || null }

      writeStage('connection-persistence-start')
      const applied = await bridge(client, 'applyConnectionConfig', payload)
      assert(applied.ok, `remote connection apply failed: ${redact(applied.error)}`)
      await sleep(3000)
      const config = await bridge(client, 'getConnectionConfig')
      assert(config.ok && config.value?.mode === 'remote', 'remote mode was not persisted after apply')
      assert(config.value.remoteUrl === gatewayUrl, 'persisted gateway URL does not match the test gateway')
      assert(config.value.remoteTokenSet === true, 'persisted gateway token was not recorded as set')
      result.settings.beforeUpdate = {
        mode: config.value.mode,
        remoteUrl: config.value.remoteUrl,
        remoteTokenSet: config.value.remoteTokenSet === true,
        tokenNotExported: !Object.prototype.hasOwnProperty.call(config.value, 'remoteToken')
      }
      await evaluate(client, `localStorage.setItem('hermes-desktop-light-acceptance-marker', 'retained'); true`, 'acceptance marker persistence')
      writeStage('connection-persistence-complete')
    } else {
      writeStage('connection-persistence-readback-start')
      const config = await bridge(client, 'getConnectionConfig')
      assert(config.ok && config.value?.mode === 'remote', 'remote mode did not survive Scoop update')
      assert(config.value.remoteUrl === gatewayUrl, 'gateway URL did not survive Scoop update')
      assert(config.value.remoteTokenSet === true, 'gateway token did not survive Scoop update')
      result.settings.afterUpdate = {
        mode: config.value.mode,
        remoteUrl: config.value.remoteUrl,
        remoteTokenSet: config.value.remoteTokenSet === true,
        tokenNotExported: !Object.prototype.hasOwnProperty.call(config.value, 'remoteToken')
      }
      const marker = await evaluate(client, `localStorage.getItem('hermes-desktop-light-acceptance-marker')`, 'acceptance marker readback')
      assert(marker === 'retained', 'renderer user data did not survive Scoop update')
      const persistedRpc = await persistedGatewayRpc(client, 'session.list', { limit: 1 })
      assert(persistedRpc && Array.isArray(persistedRpc.sessions),
        `persisted app gateway RPC returned an invalid session.list result: ${redact(JSON.stringify(persistedRpc))}`)
      result.connection.persistedWsRpc = {
        method: 'session.list',
        authenticated: true,
        sessionCount: persistedRpc.sessions.length
      }
      writeStage('connection-persistence-readback-complete')
    }

    writeStage('gateway-round-trip-start')
    const session = await fetchJsonWithRetry(`${gatewayUrl}/api/sessions?limit=1`, secret)
    assert(session && session.status === 200,
      `authenticated /api/sessions round-trip failed with status ${session?.status}: ${redact(JSON.stringify(session?.body))}`)
    const wrongSession = await fetchJson(`${gatewayUrl}/api/sessions?limit=1`, wrongSecret)
    assert(wrongSession.status === 401 || wrongSession.status === 403,
      `wrong secret was not rejected by /api/sessions (status ${wrongSession.status})`)
    result.gateway.authenticated = true
    result.sessionRoundTrip = {
      source: 'direct-node-gateway-probe',
      endpoint: '/api/sessions?limit=1',
      authenticatedStatus: session.status,
      wrongSecretStatus: wrongSession.status,
      bodyShape: Array.isArray(session.body) ? 'array' : typeof session.body
    }
    writeStage('gateway-round-trip-complete')

    writeStage('updater-check-start')
    const beforeTree = appTreeFingerprint(appRoot)
    const check = await bridge(client, 'updates.check', { force: true })
    assert(check.ok && check.value?.mechanism === 'external',
      `in-app updater did not report external ownership: ${redact(check.error || JSON.stringify(check.value))}`)
    assert(check.value.supported === false,
      `in-app updater did not report unsupported external ownership: ${redact(JSON.stringify(check.value))}`)
    if (preview) {
      assert(check.value.reason === 'commit-build',
        `preview external updater reason was not commit-build: ${redact(JSON.stringify(check.value))}`)
    } else {
      assert(check.value.reason === 'bundled-not-appinstaller',
        `stable external updater reason was not bundled-not-appinstaller: ${redact(JSON.stringify(check.value))}`)
    }
    const apply = await bridge(client, 'updates.apply')
    assert(apply.ok && apply.value?.mechanism === 'external',
      `in-app updater apply did not report external ownership: ${redact(apply.error || JSON.stringify(apply.value))}`)
    if (preview) {
      assert(apply.value.ok === false && apply.value.error === 'commit-build',
        `preview updater apply was not refused as commit-build: ${redact(JSON.stringify(apply.value))}`)
    } else {
      assert(apply.value.manual === true,
        `stable updater apply was not manual-only: ${redact(JSON.stringify(apply.value))}`)
    }
    const refused = true
    await sleep(2000)
    const afterTree = appTreeFingerprint(appRoot)
    assert(beforeTree === afterTree, 'in-app updater check/apply changed the Scoop app tree')
    result.updater = {
      check: {
        mechanism: check.value.mechanism,
        supported: check.value.supported === false,
        reason: check.value.reason || null,
        previewCommitBuildMarker: check.value.reason === 'commit-build'
      },
      apply: {
        mechanism: apply.value.mechanism,
        refused,
        supported: apply.value.supported === false
      },
      appTreeUnchanged: true
    }
    writeStage('updater-check-complete')
  } catch (error) {
    writeStage('failure', `error=${redact(error?.message || error)}`)
    await writeDiagnostics(error, { client, target })
    throw error
  } finally {
    if (client) {
      writeStage('electron-shutdown-start')
      try {
        await client.call('Browser.close', {}, 'Electron Browser.close response')
      } catch {
        // The parent process also terminates the Electron process tree.
      }
      client.close()
      writeStage('electron-shutdown-complete')
    }
  }

  fs.writeFileSync(resultPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8')
  writeStage('result-written', `phase=${phase}`)
  process.stdout.write(`${JSON.stringify({ phase, status: result.status, authenticated: result.gateway.authenticated })}\n`)
}

if (isMain) {
  run().catch(error => {
    const failure = {
      schema: 1,
      status: 'failed',
      phase,
      error: redact(error.message || error)
    }
    try { fs.writeFileSync(resultPath, `${JSON.stringify(failure, null, 2)}\n`, 'utf8') } catch { /* report original failure */ }
    process.stderr.write(`${failure.error}\n`)
    process.exitCode = 1
  })
}

module.exports = {
  CdpClient,
  DEFAULT_TIMEOUTS,
  timeoutError,
  withTimeout,
  fetchWithTimeout
}
