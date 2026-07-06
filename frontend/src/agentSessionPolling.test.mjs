import test from "node:test"
import assert from "node:assert/strict"

import { createAgentSessionPoller } from "./agentSessionPolling.js"

test("schedules independent timers for multiple agent sessions", () => {
  let nextTimerId = 1
  const timers = new Map()
  const pollCalls = []
  const poller = createAgentSessionPoller({
    setTimeout(fn, delay) {
      const id = nextTimerId++
      timers.set(id, { fn, delay })
      return id
    },
    clearTimeout(id) {
      timers.delete(id)
    },
    poll(sessionId) {
      pollCalls.push(sessionId)
    },
  })

  poller.schedule("agent-a", 100)
  poller.schedule("agent-b", 200)

  assert.equal(poller.has("agent-a"), true)
  assert.equal(poller.has("agent-b"), true)
  assert.equal(timers.size, 2)
  assert.deepEqual([...timers.values()].map((item) => item.delay), [100, 200])

  timers.get(1).fn()
  timers.get(2).fn()

  assert.deepEqual(pollCalls, ["agent-a", "agent-b"])
  assert.equal(poller.has("agent-a"), false)
  assert.equal(poller.has("agent-b"), false)
})

test("rescheduling one agent session does not clear another session timer", () => {
  let nextTimerId = 1
  const cleared = []
  const timers = new Map()
  const poller = createAgentSessionPoller({
    setTimeout(fn, delay) {
      const id = nextTimerId++
      timers.set(id, { fn, delay })
      return id
    },
    clearTimeout(id) {
      cleared.push(id)
      timers.delete(id)
    },
    poll() {},
  })

  poller.schedule("agent-a", 100)
  poller.schedule("agent-b", 200)
  poller.schedule("agent-a", 300)

  assert.deepEqual(cleared, [1])
  assert.equal(poller.has("agent-a"), true)
  assert.equal(poller.has("agent-b"), true)
  assert.equal(timers.has(2), true)
  assert.equal(timers.has(3), true)
})

test("cancelAll clears every active agent session timer", () => {
  let nextTimerId = 1
  const cleared = []
  const poller = createAgentSessionPoller({
    setTimeout() {
      return nextTimerId++
    },
    clearTimeout(id) {
      cleared.push(id)
    },
    poll() {},
  })

  poller.schedule("agent-a", 100)
  poller.schedule("agent-b", 200)
  poller.cancelAll()

  assert.deepEqual(cleared, [1, 2])
  assert.equal(poller.has("agent-a"), false)
  assert.equal(poller.has("agent-b"), false)
})
