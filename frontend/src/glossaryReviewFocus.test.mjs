import test from 'node:test'
import assert from 'node:assert/strict'

import { nextPendingReviewIndex, shouldConfirmReviewEnter } from './glossaryReviewFocus.js'

test('returns the next pending glossary item after the confirmed row', () => {
  const items = [
    { reviewed: false },
    { reviewed: false },
    { reviewed: true },
    { reviewed: false },
  ]

  assert.equal(nextPendingReviewIndex(items, 1), 3)
})

test('wraps to the first pending glossary item when there is no later pending row', () => {
  const items = [
    { reviewed: false },
    { reviewed: true },
    { reviewed: false },
  ]

  assert.equal(nextPendingReviewIndex(items, 2), 0)
})

test('returns -1 when every other glossary item is already reviewed', () => {
  const items = [
    { reviewed: true },
    { reviewed: false },
    { reviewed: true },
  ]

  assert.equal(nextPendingReviewIndex(items, 1), -1)
})

test('does not confirm enter while IME composition is active', () => {
  assert.equal(shouldConfirmReviewEnter({ isComposing: true, keyCode: 13 }, false), false)
  assert.equal(shouldConfirmReviewEnter({ isComposing: false, keyCode: 229 }, false), false)
  assert.equal(shouldConfirmReviewEnter({ isComposing: false, keyCode: 13 }, true), false)
})

test('confirms enter when IME composition is not active', () => {
  assert.equal(shouldConfirmReviewEnter({ isComposing: false, keyCode: 13 }, false), true)
})
