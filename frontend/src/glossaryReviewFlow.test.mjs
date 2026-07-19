import test from 'node:test'
import assert from 'node:assert/strict'

import {
  canReuseOpenedGlossaryReview,
  effectiveTaskStageStatus,
  findGlossaryReviewSession,
  glossaryReviewKey,
  isGlossaryReviewPathForSession,
  taskGlossaryOpenPayload,
  taskHasCurrentTranslation,
} from './glossaryReviewFlow.js'

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

test('finds the preferred waiting glossary review session', () => {
  const sessions = [
    { id: 'agent-1', status: 'waiting', phase: 'review_glossary', question: { glossary_path: 'a.yaml' } },
    { id: 'agent-2', status: 'waiting', phase: 'review_glossary', question: { glossary_path: 'b.yaml' } },
  ]

  assert.equal(findGlossaryReviewSession(sessions, 'agent-2')?.id, 'agent-2')
  assert.equal(findGlossaryReviewSession(sessions, 'missing')?.id, 'agent-1')
})

test('matches only the glossary path belonging to the waiting session', () => {
  const session = {
    id: 'agent-1',
    status: 'waiting',
    phase: 'review_glossary',
    question: { glossary_path: 'outputs/current/glossary.yaml' },
  }

  assert.equal(isGlossaryReviewPathForSession(session, 'outputs/current/glossary.yaml'), true)
  assert.equal(isGlossaryReviewPathForSession(session, 'outputs/old/glossary.yaml'), false)
})

test('reuses an opened review only while the same glossary is still loaded', () => {
  const session = {
    id: 'agent-1',
    status: 'waiting',
    phase: 'review_glossary',
    question: { glossary_path: 'outputs/current/glossary.yaml' },
  }
  const key = glossaryReviewKey(session)

  assert.equal(canReuseOpenedGlossaryReview(session, key, 'outputs/current/glossary.yaml', 'outputs/current/glossary.yaml'), true)
  assert.equal(canReuseOpenedGlossaryReview(session, key, 'outputs/other/glossary.yaml', 'outputs/other/glossary.yaml'), false)
})

test('task glossary review payload restores the waiting task session', () => {
  const stage = { glossary_path: 'outputs/task/glossary.yaml' }

  assert.deepEqual(taskGlossaryOpenPayload({ id: 'task-1', current_stage: 'glossary_review' }, stage), {
    path: 'outputs/task/glossary.yaml',
    taskId: 'task-1',
  })
  assert.deepEqual(taskGlossaryOpenPayload({ id: 'task-1', current_stage: 'done' }, stage), {
    path: 'outputs/task/glossary.yaml',
  })
})

test('ignores stale translated output while the current run is reviewing glossary', () => {
  const task = {
    current_stage: 'glossary_review',
    stages: { translate: { status: 'done', translated_srt: 'outputs/old.zh.srt' } },
    stage_items: [{ id: 'translate', status: 'done' }],
  }

  assert.equal(taskHasCurrentTranslation(task), false)
  assert.equal(effectiveTaskStageStatus(task.stage_items[0], task), 'pending')
})

test('reports translation output after the task has actually moved past review', () => {
  const task = {
    current_stage: 'done',
    stages: { translate: { status: 'done', translated_srt: 'outputs/current.zh.srt' } },
  }

  assert.equal(taskHasCurrentTranslation(task), true)
})

test('does not treat an invalidated translated path as a current translation', () => {
  const task = {
    current_stage: 'glossary_rerun',
    stages: { translate: { status: 'invalidated', translated_srt: 'outputs/old.zh.srt' } },
  }

  assert.equal(taskHasCurrentTranslation(task), false)
})
