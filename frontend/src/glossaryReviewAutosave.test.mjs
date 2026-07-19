import test from 'node:test'
import assert from 'node:assert/strict'

import { createGlossaryReviewAutosave } from './glossaryReviewAutosave.js'

test('coalesces rapid edits and persists the newest glossary snapshot', async () => {
  const writes = []
  const states = []
  const autosave = createGlossaryReviewAutosave({
    save: async (payload) => {
      writes.push(payload)
      return { ok: true }
    },
    onState: ({ state }) => states.push(state),
    delay: 60_000,
  })

  autosave.markDirty({ items: [{ reviewed: false }] })
  autosave.markDirty({ items: [{ reviewed: true }] })
  await autosave.flush()

  assert.deepEqual(writes, [{ items: [{ reviewed: true }] }])
  assert.deepEqual(states.slice(-2), ['saving', 'saved'])
  autosave.destroy()
})

test('keeps an edit made during a request and saves it in a trailing request', async () => {
  let releaseFirst
  const writes = []
  const autosave = createGlossaryReviewAutosave({
    save: async (payload) => {
      writes.push(payload)
      if (writes.length === 1) await new Promise((resolve) => { releaseFirst = resolve })
      return { ok: true }
    },
    delay: 60_000,
  })

  autosave.markDirty({ version: 1 })
  const flushing = autosave.flush()
  await Promise.resolve()
  autosave.markDirty({ version: 2 })
  releaseFirst()
  await flushing

  assert.deepEqual(writes, [{ version: 1 }, { version: 2 }])
  autosave.destroy()
})

test('reports save errors without treating the revision as saved', async () => {
  const states = []
  const autosave = createGlossaryReviewAutosave({
    save: async () => { throw new Error('offline') },
    onState: (state) => states.push(state),
    delay: 60_000,
  })

  autosave.markDirty({ items: [] })
  await assert.rejects(autosave.flush(), /offline/)
  assert.deepEqual(states.at(-1), { state: 'error', dirty: true, error: 'offline' })
  autosave.destroy()
})
