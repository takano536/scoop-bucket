'use strict'

const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  CdpClient,
  fetchWithTimeout,
  timeoutError
} = require('../scripts/accept-hermes-desktop-light.cjs')

class NeverRespondingWebSocket {
  static instances = []

  constructor() {
    this.listeners = new Map()
    this.closed = false
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

  send() {
    // Deliberately never emit a CDP response.
  }

  close() {
    if (this.closed) return
    this.closed = true
    this.emit('close', { code: 1000 })
  }
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

test('timeoutError keeps operation names stable for diagnostics', () => {
  assert.equal(timeoutError('diagnostic operation', 7).message, 'Timed out waiting for diagnostic operation after 7ms')
})
