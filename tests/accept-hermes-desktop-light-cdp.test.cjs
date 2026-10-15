'use strict'

const assert = require('node:assert/strict')
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const {
  CdpClient,
  fetchWithTimeout
} = require('../scripts/accept-hermes-desktop-light.cjs')

class NeverRespondingWebSocket {
  static instances = []

  constructor() {
    this.listeners = new Map()
    this.closed = false
    this.sent = []
    NeverRespondingWebSocket.instances.push(this)
    queueMicrotask(() => this.emit('open'))
  }

  addEventListener(name, listener, options = {}) {
    const listeners = this.listeners.get(name) || []
    listeners.push({ listener, once: options.once === true })
    this.listeners.set(name, listeners)
  }

  emit(name, value = {}) {
    const listeners = this.listeners.get(name) || []
    for (const entry of [...listeners]) {
      entry.listener(value)
      if (entry.once) {
        const current = this.listeners.get(name) || []
        this.listeners.set(name, current.filter(candidate => candidate !== entry))
      }
    }
  }

  send(payload) {
    this.sent.push(JSON.parse(payload))
    // Deliberately never emit a CDP response.
  }

  close() {
    if (this.closed) return
    this.closed = true
    this.emit('close', { code: 1000 })
  }
}

function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error?.code === 'EPERM'
  }
}

async function waitForProcessGone(pid, operation, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (isProcessAlive(pid) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  assert.equal(isProcessAlive(pid), false, `Timed out waiting for ${operation} after ${timeoutMs}ms`)
}

function forceKillProcessTreeForTest(pid) {
  if (!isProcessAlive(pid)) return
  spawnSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', timeout: 5000 })
}


test('CDP response timeout names the operation and closes the socket', async () => {
  const previousWebSocket = global.WebSocket
  NeverRespondingWebSocket.instances = []
  global.WebSocket = NeverRespondingWebSocket
  try {
    const client = new CdpClient('ws://127.0.0.1:1/devtools/page/never', {
      connectTimeoutMs: 100,
      callTimeoutMs: 30
    })
    await assert.rejects(
      client.call('Runtime.evaluate', {}, 'Electron renderer readiness'),
      error => error.message === 'Timed out waiting for Electron renderer readiness after 30ms'
    )
    assert.equal(client.pending.size, 0)
    assert.equal(NeverRespondingWebSocket.instances.length, 1)
    assert.equal(NeverRespondingWebSocket.instances[0].closed, true)
  } finally {
    global.WebSocket = previousWebSocket
  }
})

test('Browser.close is sent without waiting for a response', async () => {
  const previousWebSocket = global.WebSocket
  NeverRespondingWebSocket.instances = []
  global.WebSocket = NeverRespondingWebSocket
  try {
    const client = new CdpClient('ws://127.0.0.1:1/devtools/page/close', {
      connectTimeoutMs: 100,
      callTimeoutMs: 30
    })
    await client.sendWithoutResponse('Browser.close')
    const socket = NeverRespondingWebSocket.instances[0]
    assert.deepEqual(socket.sent[0].method, 'Browser.close')
    assert.equal(client.pending.size, 0)
    client.close()
  } finally {
    global.WebSocket = previousWebSocket
  }
})

test('CDP connection timeout closes an endpoint that never opens', async () => {
  class NeverOpeningWebSocket extends NeverRespondingWebSocket {
    emit(name, value = {}) {
      if (name === 'open') return
      super.emit(name, value)
    }
  }
  const previousWebSocket = global.WebSocket
  global.WebSocket = NeverOpeningWebSocket
  try {
    const client = new CdpClient('ws://127.0.0.1:1/devtools/page/never', {
      connectTimeoutMs: 30,
      callTimeoutMs: 100
    })
    await assert.rejects(
      client.call('Runtime.evaluate'),
      error => error.message === 'Timed out waiting for CDP WebSocket connection after 30ms'
    )
    assert.equal(client.closed, true)
    assert.equal(client.pending.size, 0)
  } finally {
    global.WebSocket = previousWebSocket
  }
})

test('CDP target-list timeout aborts a server that never answers', async () => {
  const previousFetch = global.fetch
  let aborted = false
  global.fetch = (_url, options = {}) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      aborted = true
      const error = new Error('aborted')
      error.name = 'AbortError'
      reject(error)
    }, { once: true })
  })
  try {
    await assert.rejects(
      fetchWithTimeout(
        'http://127.0.0.1:1/json/list',
        undefined,
        30,
        'Electron CDP target-list response'
      ),
      error => error.message === 'Timed out waiting for Electron CDP target-list response after 30ms'
    )
    assert.equal(aborted, true)
  } finally {
    global.fetch = previousFetch
  }
})

test('Windows acceptance timeout cleanup kills a child process tree', {
  skip: process.platform === 'win32'
    ? false
    : 'Windows-only: Stop-ProcessTree uses taskkill.exe /T /F and is exercised in the Windows CI Test jobs',
  timeout: 15000
}, async () => {
  const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-acceptance-tree-'))
  const fixturePath = path.join(temporaryDirectory, 'spawn-tree.cjs')
  const fixture = [
    "const { spawn } = require('node:child_process')",
    "const grandchild = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' })",
    'process.stdout.write(`${grandchild.pid}\\n`)',
    'setInterval(() => {}, 1000)'
  ].join('\n')
  fs.writeFileSync(fixturePath, `${fixture}\n`, 'utf8')
  let parent
  try {
    parent = spawn(process.execPath, [fixturePath], {
      stdio: ['ignore', 'pipe', 'pipe']
    })
    parent.stdout.setEncoding('utf8')
    const grandchildPid = await new Promise((resolve, reject) => {
      let output = ''
      const onData = chunk => {
        output += chunk
        const line = output.split(/\r?\n/, 1)[0]
        const pid = Number.parseInt(line, 10)
        if (Number.isInteger(pid) && pid > 0) {
          parent.stdout.off('data', onData)
          resolve(pid)
        }
      }
      parent.stdout.on('data', onData)
      parent.once('error', reject)
      parent.once('exit', (code, signal) => {
        reject(new Error(`fixture exited before announcing grandchild (${code ?? signal})`))
      })
    })
    assert.equal(isProcessAlive(parent.pid), true)
    assert.equal(isProcessAlive(grandchildPid), true)

    const helpersPath = path.resolve(__dirname, '../scripts/accept-hermes-desktop-light-helpers.ps1')
    const timeoutCommand = [
      '$ErrorActionPreference = "Stop"',
      '. $env:HERMES_ACCEPTANCE_HELPERS',
      '$process = Get-Process -Id ([int]$env:HERMES_ACCEPTANCE_PARENT_PID)',
      'Start-Sleep -Milliseconds 100',
      'if (!$process.HasExited) {',
      '  Stop-ProcessTree -ProcessId $process.Id',
      '  throw "Timed out waiting for Electron acceptance cleanup fixture after 100ms"',
      '}',
      'throw "fixture exited before the named timeout"'
    ].join('; ')
    const cleanup = spawnSync('pwsh', [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      timeoutCommand
    ], {
      env: {
        ...process.env,
        HERMES_ACCEPTANCE_HELPERS: helpersPath,
        HERMES_ACCEPTANCE_PARENT_PID: String(parent.pid)
      },
      encoding: 'utf8',
      timeout: 10000
    })
    assert.ifError(cleanup.error)
    assert.notEqual(cleanup.status, 0)
    assert.match(
      `${cleanup.stdout}\n${cleanup.stderr}`,
      /Timed out waiting for Electron acceptance cleanup fixture after 100ms/
    )
    await waitForProcessGone(parent.pid, 'acceptance child process', 5000)
    await waitForProcessGone(grandchildPid, 'acceptance grandchild process', 5000)
  } finally {
    if (parent && isProcessAlive(parent.pid)) {
      forceKillProcessTreeForTest(parent.pid)
      parent.kill()
    }
    fs.rmSync(temporaryDirectory, { recursive: true, force: true })
  }
})
