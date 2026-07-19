export function createGlossaryReviewAutosave({
  save,
  onState = () => {},
  delay = 500,
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
} = {}) {
  if (typeof save !== 'function') throw new TypeError('save must be a function')

  let timerId = null
  let revision = 0
  let savedRevision = 0
  let latestPayload = null
  let activePromise = null
  let lastResult = null
  let destroyed = false

  function publish(state, error = '') {
    onState({ state, dirty: savedRevision < revision, error })
  }

  function cancelTimer() {
    if (timerId === null) return
    clearTimer(timerId)
    timerId = null
  }

  function schedule(wait = delay) {
    cancelTimer()
    timerId = setTimer(() => {
      timerId = null
      void persistPending().catch(() => {})
    }, wait)
  }

  function markDirty(payload) {
    if (destroyed) return
    revision += 1
    latestPayload = payload
    publish('dirty')
    schedule()
  }

  async function persistPending() {
    if (destroyed) return lastResult
    cancelTimer()

    if (activePromise) {
      try {
        await activePromise
      } catch {
        // The next explicit edit or retry will attempt the latest revision again.
      }
      if (savedRevision >= revision) return lastResult
    }

    if (savedRevision >= revision || !latestPayload) return lastResult

    const targetRevision = revision
    const targetPayload = latestPayload
    publish('saving')
    const request = Promise.resolve().then(() => save(targetPayload))
    activePromise = request
    try {
      lastResult = await request
      savedRevision = Math.max(savedRevision, targetRevision)
      if (savedRevision < revision) {
        publish('dirty')
        schedule(0)
      } else {
        publish('saved')
      }
      return lastResult
    } catch (error) {
      publish('error', error?.message || String(error))
      throw error
    } finally {
      if (activePromise === request) activePromise = null
    }
  }

  async function flush() {
    cancelTimer()
    while (!destroyed && savedRevision < revision) {
      await persistPending()
    }
    return lastResult
  }

  function retry() {
    if (!destroyed && savedRevision < revision) schedule(0)
  }

  function reset(state = 'saved') {
    cancelTimer()
    revision = 0
    savedRevision = 0
    latestPayload = null
    lastResult = null
    publish(state)
  }

  function destroy() {
    destroyed = true
    cancelTimer()
  }

  return { markDirty, flush, retry, reset, destroy }
}
