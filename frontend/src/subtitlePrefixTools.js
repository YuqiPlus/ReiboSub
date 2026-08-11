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

const SPEAKER_PREFIX_BLOCKLIST = new Set([
  '原因', '时间', '地点', '日期', '结果', '答案', '提示', '注意', '字幕', '画面',
  '说明', '标题', '来源', '资料提供', '翻译', '原文', '注', '备注', '问题', '方法',
  '重点', '总结', '例如', '比如', '问', '答', '代码名',
])

export function detectCueSpeakerPrefixCandidates(cues, speakerDictionary = []) {
  const dictionary = normalizeSpeakerDictionary(speakerDictionary)
  const knownNames = [...dictionary.keys()].sort((left, right) => right.length - left.length)
  const candidates = new Map()

  for (const cue of cues || []) {
    const text = String(cue?.text || '')
    const known = findKnownSpeakerOccurrence(cue, text, knownNames, dictionary)
    if (known) {
      addSpeakerOccurrence(candidates, known)
      continue
    }
    const inferred = findRepeatedSpeakerOccurrence(cue, text)
    if (inferred) addSpeakerOccurrence(candidates, inferred)
  }

  return [...candidates.values()]
    .filter((candidate) => candidate.known || candidate.occurrences.length >= 2)
    .map((candidate) => ({
      ...candidate,
      count: candidate.occurrences.length,
      recommended: candidate.known && candidate.trusted,
      confidence: candidate.known && candidate.trusted ? 'high' : 'medium',
      reason: candidate.known
        ? (candidate.trusted ? 'Glossary 已确认人物名 + 冒号' : 'Glossary 人物候选 + 冒号')
        : '重复出现的短冒号标签，需确认是否为说话者',
    }))
    .sort((left, right) => (
      Number(right.recommended) - Number(left.recommended)
      || right.count - left.count
      || left.name.localeCompare(right.name, 'zh-CN')
    ))
}

export function applySpeakerPrefixCandidates(cues, candidates, candidateIds) {
  const selected = new Set((candidateIds || []).map((value) => String(value || '')))
  const occurrences = new Map()
  for (const candidate of candidates || []) {
    if (!selected.has(String(candidate.id || ''))) continue
    for (const occurrence of candidate.occurrences || []) {
      occurrences.set(String(occurrence.uid || ''), occurrence)
    }
  }

  let changedCueCount = 0
  const nextCues = (cues || []).map((cue) => {
    const occurrence = occurrences.get(String(cue?.uid || ''))
    if (!occurrence || String(cue.text || '') !== occurrence.originalText) return cue
    changedCueCount += 1
    return { ...cue, text: occurrence.replacementText }
  })
  return { cues: nextCues, changedCueCount, removedPrefixCount: changedCueCount }
}

function normalizeSpeakerDictionary(values) {
  const result = new Map()
  for (const item of values || []) {
    const entry = typeof item === 'string' ? { name: item, trusted: true } : (item || {})
    const name = normalizeSpeakerName(entry.name)
    if (!isSafeSpeakerName(name)) continue
    const existing = result.get(name)
    result.set(name, {
      name,
      trusted: Boolean(entry.trusted || existing?.trusted),
      canonical: String(entry.canonical || existing?.canonical || name),
    })
  }
  return result
}

function findKnownSpeakerOccurrence(cue, text, knownNames, dictionary) {
  const parts = splitSpeakerPrefixStart(text)
  for (const name of knownNames) {
    if (!parts.remainder.startsWith(name)) continue
    const rest = parts.remainder.slice(name.length)
    const separator = rest.match(/^\s*[:：]\s*/)
    if (!separator) continue
    const dialogue = rest.slice(separator[0].length)
    if (!dialogue.trim()) continue
    const annotationPrefix = parts.annotation ? `${parts.annotation.trimEnd()} ` : ''
    const replacementText = `${parts.leading}${annotationPrefix}${dialogue.replace(/^[ \t　]+/, '')}`
    const metadata = dictionary.get(name)
    return {
      id: `known:${name}`,
      name,
      known: true,
      trusted: Boolean(metadata?.trusted),
      occurrences: [buildSpeakerOccurrence(cue, text, replacementText)],
    }
  }
  return null
}

function findRepeatedSpeakerOccurrence(cue, text) {
  const leading = text.match(/^\s*/)?.[0] || ''
  const body = text.slice(leading.length)
  const match = body.match(/^([^:：\n]{1,18})\s*[:：]\s*(\S[\s\S]*)$/u)
  if (!match) return null
  const name = normalizeSpeakerName(match[1])
  if (!isSafeSpeakerName(name) || SPEAKER_PREFIX_BLOCKLIST.has(name)) return null
  if (/心想$|说道$|表示$|写道$|问道$|回答$|补充$|强调$/u.test(name)) return null
  return {
    id: `inferred:${name}`,
    name,
    known: false,
    trusted: false,
    occurrences: [buildSpeakerOccurrence(cue, text, `${leading}${match[2]}`)],
  }
}

function splitSpeakerPrefixStart(text) {
  const leading = text.match(/^\s*/)?.[0] || ''
  let remainder = text.slice(leading.length)
  let annotation = ''
  const annotationMatch = remainder.match(/^((?:\[[^\]\n]{1,24}\]|【[^】\n]{1,24}】)\s*)/u)
  if (annotationMatch) {
    annotation = annotationMatch[1]
    remainder = remainder.slice(annotation.length)
  }
  return { leading, annotation, remainder }
}

function normalizeSpeakerName(value) {
  return String(value || '').trim().replace(/[ \t　]{2,}/g, ' ')
}

function isSafeSpeakerName(name) {
  if (!name || Array.from(name).length > 18) return false
  if (/^[\d\s.:：/-]+$/u.test(name)) return false
  if (/[，,。！？!?；;…“”‘’《》「」『』()[\]【】<>]/u.test(name)) return false
  if (/^(?:https?|www\.)/iu.test(name)) return false
  return true
}

function buildSpeakerOccurrence(cue, originalText, replacementText) {
  return {
    uid: cue?.uid,
    cueNumber: Number(cue?.index || 0) || undefined,
    start_time: cue?.start_time,
    end_time: cue?.end_time,
    originalText,
    replacementText,
  }
}

function addSpeakerOccurrence(candidates, candidate) {
  const current = candidates.get(candidate.id)
  if (!current) {
    candidates.set(candidate.id, candidate)
    return
  }
  current.occurrences.push(...candidate.occurrences)
  current.trusted = current.trusted || candidate.trusted
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
  { name: '中文双引号', family: 'double_quote', open: '“', close: '”', crossCue: true },
  { name: '中文单引号', family: 'single_quote', open: '‘', close: '’', crossCue: true },
  { name: '中文圆括号', family: 'round', open: '（', close: '）' },
  { name: '英文圆括号', family: 'round', open: '(', close: ')' },
  { name: '方括号', family: 'square', open: '[', close: ']' },
  { name: '中文方括号', family: 'square', open: '【', close: '】' },
  { name: '书名号', family: 'book', open: '《', close: '》', crossCue: true },
  { name: '直角引号', family: 'corner', open: '「', close: '」', crossCue: true },
  { name: '双直角引号', family: 'double_corner', open: '『', close: '』', crossCue: true },
]

export function detectCuePairSymbolIssues(cues, pairs = PAIR_SYMBOLS) {
  const stack = []
  const issues = []
  const openMap = new Map(pairs.map((pair) => [pair.open, pair]))
  const closeMap = new Map(pairs.map((pair) => [pair.close, pair]))

  ;(cues || []).forEach((cue, cueIndex) => {
    const text = String(cue.text || '')
    for (const [charIndex, char] of Array.from(text).entries()) {
      const openPair = openMap.get(char)
      if (openPair) {
        stack.push({ pair: openPair, cue, cueIndex, charIndex })
        continue
      }
      const closePair = closeMap.get(char)
      if (!closePair) continue
      const matchIndex = findLastStackIndex(stack, closePair)
      if (matchIndex >= 0) {
        const matched = stack[matchIndex]
        if (matchIndex !== stack.length - 1) {
          issues.push(buildPairIssue({
            cue,
            cueIndex,
            pair: closePair,
            type: 'crossed_pair',
            charIndex,
            relatedCue: matched.cue,
            relatedCueIndex: matched.cueIndex,
          }))
        } else if (isDistantPair(matched.cueIndex, cueIndex)) {
          issues.push(buildPairIssue({
            cue,
            cueIndex,
            pair: closePair,
            type: 'distant_pair',
            charIndex,
            relatedCue: matched.cue,
            relatedCueIndex: matched.cueIndex,
          }))
        }
        stack.splice(matchIndex, 1)
        continue
      }
      const compatibleIndex = findCompatibleStackIndex(stack, closePair)
      if (compatibleIndex >= 0) {
        const matched = stack.splice(compatibleIndex, 1)[0]
        if (compatibleIndex !== stack.length) {
          issues.push(buildPairIssue({
            cue,
            cueIndex,
            pair: matched.pair,
            type: 'crossed_pair',
            charIndex,
            actualSymbol: char,
            replacementSymbol: matched.pair.close,
            relatedCue: matched.cue,
            relatedCueIndex: matched.cueIndex,
          }))
          continue
        }
        issues.push(buildPairIssue(
          isDistantPair(matched.cueIndex, cueIndex)
            ? {
                cue,
                cueIndex,
                pair: matched.pair,
                type: 'distant_pair',
                charIndex,
                actualSymbol: char,
                replacementSymbol: matched.pair.close,
                relatedCue: matched.cue,
                relatedCueIndex: matched.cueIndex,
              }
            : {
                cue,
                cueIndex,
                pair: matched.pair,
                type: 'mismatched_close',
                charIndex,
                actualSymbol: char,
                replacementSymbol: matched.pair.close,
                relatedCue: matched.cue,
                relatedCueIndex: matched.cueIndex,
              },
        ))
        continue
      }
      issues.push(buildPairIssue({ cue, cueIndex, pair: closePair, type: 'missing_open', charIndex }))
    }

    for (let stackIndex = stack.length - 1; stackIndex >= 0; stackIndex -= 1) {
      const item = stack[stackIndex]
      if (item.pair.crossCue) continue
      issues.push(buildPairIssue({
        cue: item.cue,
        cueIndex: item.cueIndex,
        pair: item.pair,
        type: 'missing_close',
        charIndex: item.charIndex,
      }))
      stack.splice(stackIndex, 1)
    }
  })

  for (const item of [...stack].reverse()) {
    issues.push(buildPairIssue({
      cue: item.cue,
      cueIndex: item.cueIndex,
      pair: item.pair,
      type: 'missing_close',
      charIndex: item.charIndex,
    }))
  }

  return issues
    .sort((left, right) => left.index - right.index || left.charIndex - right.charIndex)
    .map((issue, issueIndex) => ({ ...issue, issueId: `${issue.uid}:${issue.type}:${issue.charIndex}:${issueIndex}` }))
}

function findLastStackIndex(stack, pair) {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (stack[index].pair.open === pair.open && stack[index].pair.close === pair.close) return index
  }
  return -1
}

function findCompatibleStackIndex(stack, pair) {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (stack[index].pair.family === pair.family) return index
  }
  return -1
}

function isDistantPair(openCueIndex, closeCueIndex) {
  return Math.abs(Number(closeCueIndex) - Number(openCueIndex)) > 3
}

function buildPairIssue({
  cue,
  cueIndex,
  pair,
  type,
  charIndex = 0,
  actualSymbol = '',
  replacementSymbol = '',
  relatedCue = null,
  relatedCueIndex = null,
}) {
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
    missingSymbol: type === 'missing_close' ? pair.close : type === 'missing_open' ? pair.open : '',
    actualSymbol,
    replacementSymbol,
    charIndex,
    relatedUid: relatedCue?.uid || '',
    relatedCueNumber: relatedCueIndex === null ? null : relatedCueIndex + 1,
    cueSpan: relatedCueIndex === null ? 0 : Math.abs(cueIndex - relatedCueIndex),
    autoRepairable: type === 'mismatched_close',
    suggestionAvailable: ['mismatched_close', 'missing_open', 'missing_close'].includes(type),
    type,
  }
}

export function applyCuePairIssueRepairs(cues, issues, { includeBoundarySuggestions = false } = {}) {
  const editsByUid = new Map()
  for (const issue of issues || []) {
    if (!issue?.suggestionAvailable) continue
    if (!issue.autoRepairable && !includeBoundarySuggestions) continue
    const uid = String(issue.uid || '')
    if (!uid) continue
    if (!editsByUid.has(uid)) editsByUid.set(uid, [])
    editsByUid.get(uid).push(issue)
  }

  let repairedIssueCount = 0
  const nextCues = (cues || []).map((cue) => {
    const edits = editsByUid.get(String(cue?.uid || ''))
    if (!edits?.length) return cue
    let text = String(cue.text || '')
    const replacements = edits
      .filter((issue) => issue.type === 'mismatched_close')
      .sort((left, right) => right.charIndex - left.charIndex)
    for (const issue of replacements) {
      const chars = Array.from(text)
      if (chars[issue.charIndex] !== issue.actualSymbol) continue
      chars[issue.charIndex] = issue.replacementSymbol
      text = chars.join('')
      repairedIssueCount += 1
    }
    for (const issue of edits.filter((item) => item.type === 'missing_open')) {
      const leading = text.match(/^\s*/)?.[0] || ''
      text = `${leading}${issue.missingSymbol}${text.slice(leading.length)}`
      repairedIssueCount += 1
    }
    for (const issue of edits.filter((item) => item.type === 'missing_close')) {
      const trailing = text.match(/\s*$/)?.[0] || ''
      text = `${text.slice(0, text.length - trailing.length)}${issue.missingSymbol}${trailing}`
      repairedIssueCount += 1
    }
    return text === cue.text ? cue : { ...cue, text }
  })
  return { cues: nextCues, repairedIssueCount }
}
