export function glossaryReviewKey(session) {
  const glossaryPath = session?.question?.glossary_path || session?.result?.glossary_path || ''
  if (session?.status !== 'waiting' || session?.phase !== 'review_glossary' || !session?.id || !glossaryPath) return ''
  return `${session.id}:${glossaryPath}`
}
