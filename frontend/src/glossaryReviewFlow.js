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
