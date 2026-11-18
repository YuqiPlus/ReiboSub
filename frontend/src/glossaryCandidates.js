// Candidate arrival must never replace edits or human confirmation state.
export function mergeGlossaryCandidates(current, incoming) {
  const byKey = new Map((incoming || []).map(item => [JSON.stringify([item.section, item.index, item.source, item.context_text || '']), item]))
  return (current || []).map(item => {
    const row = byKey.get(JSON.stringify([item.section, item.index, item.source, item.context_text || '']))
    if (!row) return item
    const result = { ...item }
    for (const field of ['blind_candidate_zh', 'blind_candidate_error', 'blind_candidate_pending']) {
      if (Object.hasOwn(row, field)) result[field] = row[field]
      else delete result[field]
    }
    return result
  })
}
