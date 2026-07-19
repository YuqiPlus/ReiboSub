export function glossaryReviewKey(session) {
  const glossaryPath = session?.question?.glossary_path || session?.result?.glossary_path || ''
  if (session?.status !== 'waiting' || session?.phase !== 'review_glossary' || !session?.id || !glossaryPath) return ''
  return `${session.id}:${glossaryPath}`
}

export function findGlossaryReviewSession(sessions, preferredSessionId = '') {
  const reviewSessions = (sessions || []).filter((session) => glossaryReviewKey(session))
  if (!reviewSessions.length) return null
  return reviewSessions.find((session) => session.id === preferredSessionId) || reviewSessions[0]
}

export function isGlossaryReviewPathForSession(session, glossaryPath) {
  const expectedPath = session?.question?.glossary_path || session?.result?.glossary_path || ''
  return Boolean(glossaryReviewKey(session) && expectedPath && expectedPath === String(glossaryPath || '').trim())
}

export function canReuseOpenedGlossaryReview(session, openedKey, loadedPath, requestedPath) {
  const expectedPath = session?.question?.glossary_path || session?.result?.glossary_path || ''
  return Boolean(
    expectedPath
      && glossaryReviewKey(session) === openedKey
      && String(loadedPath || '').trim() === expectedPath
      && String(requestedPath || '').trim() === expectedPath,
  )
}

export function isCurrentGlossaryReviewTask(task) {
  return task?.current_stage === 'glossary_review'
}

export function taskHasCurrentTranslation(task) {
  if (isCurrentGlossaryReviewTask(task)) return false
  const stages = task?.stages || {}
  if (stages.translate?.status === 'done') return true
  return (task?.stage_items || []).some((stage) => stage.id === 'translate' && stage.status === 'done')
}

export function effectiveTaskStageStatus(stage, task) {
  if (isCurrentGlossaryReviewTask(task) && stage?.id === 'translate' && stage?.status === 'done') {
    return 'pending'
  }
  return stage?.status
}

export function taskGlossaryOpenPayload(task, stage) {
  return {
    path: stage?.glossary_path || '',
    ...(task?.current_stage === 'glossary_review' && task?.id ? { taskId: task.id } : {}),
  }
}
