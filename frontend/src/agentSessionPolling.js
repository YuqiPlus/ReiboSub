export function createAgentSessionPoller({ setTimeout, clearTimeout, poll }) {
  const timers = new Map()

  function cancel(sessionId) {
    if (!timers.has(sessionId)) return
    clearTimeout(timers.get(sessionId))
    timers.delete(sessionId)
  }

  function schedule(sessionId, delay = 1000) {
    if (!sessionId) return
    cancel(sessionId)
    const timerId = setTimeout(() => {
      timers.delete(sessionId)
      poll(sessionId)
    }, delay)
    timers.set(sessionId, timerId)
  }

  function cancelAll() {
    for (const sessionId of [...timers.keys()]) cancel(sessionId)
  }

  return {
    schedule,
    cancel,
    cancelAll,
    has(sessionId) {
      return timers.has(sessionId)
    },
  }
}
