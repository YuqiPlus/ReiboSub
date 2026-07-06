export function parsePrefixNames(value) {
  const seen = new Set()
  return String(value || '')
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      if (seen.has(item)) return false
      seen.add(item)
      return true
    })
}

export function stripCueSpeakerPrefixes(cues, names) {
  const prefixes = [...(names || [])]
    .map((name) => String(name || '').trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length)
  let changedCueCount = 0
  let removedPrefixCount = 0

  const nextCues = (cues || []).map((cue) => {
    const result = stripSpeakerPrefix(String(cue.text || ''), prefixes)
    if (!result.changed) return cue
    changedCueCount += 1
    removedPrefixCount += result.removedCount
    return { ...cue, text: result.text }
  })

  return { cues: nextCues, changedCueCount, removedPrefixCount }
}

export function stripSpeakerPrefix(text, names) {
  if (!text || !names?.length) return { text, changed: false, removedCount: 0 }
  const leading = text.match(/^\s*/)?.[0] || ''
  const body = text.slice(leading.length)
  for (const name of names) {
    if (!body.startsWith(name)) continue
    const rest = body.slice(name.length)
    const separator = rest.match(/^([:：]|[ \t　]+)/)
    if (!separator) continue
    const next = rest.slice(separator[0].length).replace(/^[ \t　]+/, '')
    return { text: leading + next, changed: true, removedCount: 1 }
  }
  return { text, changed: false, removedCount: 0 }
}

export function stripCueTrailingCommas(cues) {
  let changedCueCount = 0
  let removedCommaCount = 0
  const nextCues = (cues || []).map((cue) => {
    const result = stripTrailingComma(String(cue.text || ''))
    if (!result.changed) return cue
    changedCueCount += 1
    removedCommaCount += result.removedCount
    return { ...cue, text: result.text }
  })
  return { cues: nextCues, changedCueCount, removedCommaCount }
}

export function stripTrailingComma(text) {
  const match = String(text || '').match(/[，,]+\s*$/)
  if (!match) return { text, changed: false, removedCount: 0 }
  const removed = match[0].replace(/\s/g, '').length
  return {
    text: text.slice(0, match.index).replace(/[ \t　]+$/g, ''),
    changed: true,
    removedCount: removed,
  }
}

export const PAIR_SYMBOLS = [
  { name: '中文双引号', open: '“', close: '”' },
  { name: '中文单引号', open: '‘', close: '’' },
  { name: '中文圆括号', open: '（', close: '）' },
  { name: '英文圆括号', open: '(', close: ')' },
  { name: '方括号', open: '[', close: ']' },
  { name: '中文方括号', open: '【', close: '】' },
  { name: '书名号', open: '《', close: '》' },
  { name: '直角引号', open: '「', close: '」' },
  { name: '双直角引号', open: '『', close: '』' },
]

export function detectCuePairSymbolIssues(cues, pairs = PAIR_SYMBOLS) {
  const stack = []
  const issues = []
  const openMap = new Map(pairs.map((pair) => [pair.open, pair]))
  const closeMap = new Map(pairs.map((pair) => [pair.close, pair]))

  ;(cues || []).forEach((cue, cueIndex) => {
    const text = String(cue.text || '')
    for (const char of text) {
      const openPair = openMap.get(char)
      if (openPair) {
        stack.push({ pair: openPair, cue, cueIndex })
        continue
      }
      const closePair = closeMap.get(char)
      if (!closePair) continue
      const matchIndex = findLastStackIndex(stack, closePair)
      if (matchIndex >= 0) {
        stack.splice(matchIndex, 1)
      } else {
        issues.push(buildPairIssue({ cue, cueIndex, pair: closePair, type: 'missing_open' }))
      }
    }
  })

  for (const item of stack) {
    issues.push(buildPairIssue({ cue: item.cue, cueIndex: item.cueIndex, pair: item.pair, type: 'missing_close' }))
  }

  return issues.sort((left, right) => left.index - right.index)
}

function findLastStackIndex(stack, pair) {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (stack[index].pair.open === pair.open && stack[index].pair.close === pair.close) return index
  }
  return -1
}

function buildPairIssue({ cue, cueIndex, pair, type }) {
  return {
    uid: cue.uid,
    index: cueIndex,
    cueNumber: cueIndex + 1,
    start_time: cue.start_time,
    end_time: cue.end_time,
    text: cue.text || '',
    pairName: pair.name,
    openSymbol: pair.open,
    closeSymbol: pair.close,
    missingSymbol: type === 'missing_close' ? pair.close : pair.open,
    type,
  }
}
