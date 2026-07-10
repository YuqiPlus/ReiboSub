import test from 'node:test'
import assert from 'node:assert/strict'

import { glossaryReviewKey } from './glossaryReviewFlow.js'

test('returns a stable key for a glossary review waiting state', () => {
  const session = {
    id: 'agent-1',
    status: 'waiting',
    phase: 'review_glossary',
    question: { glossary_path: 'outputs/agent_tasks/agent-1/glossary.yaml' },
  }

  assert.equal(glossaryReviewKey(session), 'agent-1:outputs/agent_tasks/agent-1/glossary.yaml')
})

test('does not auto-open glossary for other agent states', () => {
  assert.equal(glossaryReviewKey({ id: 'agent-1', status: 'running', phase: 'review_glossary', question: { glossary_path: 'a.yaml' } }), '')
  assert.equal(glossaryReviewKey({ id: 'agent-1', status: 'waiting', phase: 'translate', question: { glossary_path: 'a.yaml' } }), '')
  assert.equal(glossaryReviewKey({ id: 'agent-1', status: 'waiting', phase: 'review_glossary', question: {} }), '')
})
