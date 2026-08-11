import test from "node:test"
import assert from "node:assert/strict"

import {
  applyCuePairIssueRepairs,
  applySpeakerPrefixCandidates,
  detectCuePairSymbolIssues,
  detectCueSpeakerPrefixCandidates,
  parsePrefixNames,
  stripCueSpeakerPrefixes,
  stripCueTrailingCommas,
} from "./subtitlePrefixTools.js"

test("detects reviewed glossary speakers and preserves a leading visual annotation", () => {
  const cues = [
    { uid: "1", index: 1, text: "朴宝英：今天很开心" },
    { uid: "2", index: 2, text: "[河豚] 车太贤: 你好" },
    { uid: "3", index: 3, text: "朴宝英 今天很开心" },
    { uid: "4", index: 4, text: "[脸红]我有点害羞" },
    { uid: "5", index: 5, text: "资料提供：MBC" },
    { uid: "6", index: 6, text: "[虾] 装作不知情的黄光熙：别装了" },
  ]
  const candidates = detectCueSpeakerPrefixCandidates(cues, [
    { name: "朴宝英", trusted: true },
    { name: "车太贤", trusted: true },
    { name: "黄光熙", trusted: true },
  ])

  assert.deepEqual(
    Object.fromEntries(candidates.map((item) => [item.name, { count: item.count, recommended: item.recommended }])),
    {
      朴宝英: { count: 1, recommended: true },
      车太贤: { count: 1, recommended: true },
    },
  )

  const result = applySpeakerPrefixCandidates(cues, candidates, candidates.map((item) => item.id))
  assert.equal(result.changedCueCount, 2)
  assert.deepEqual(result.cues.map((cue) => cue.text), [
    "今天很开心",
    "[河豚] 你好",
    "朴宝英 今天很开心",
    "[脸红]我有点害羞",
    "资料提供：MBC",
    "[虾] 装作不知情的黄光熙：别装了",
  ])
})

test("lists repeated unknown labels for confirmation without recommending them", () => {
  const candidates = detectCueSpeakerPrefixCandidates([
    { uid: "1", text: "本部职员：请进" },
    { uid: "2", text: "本部职员: 请坐" },
    { uid: "3", text: "濬荣心想：糟糕" },
    { uid: "4", text: "濬荣心想：怎么办" },
    { uid: "5", text: "问：今天开心吗" },
    { uid: "6", text: "问：真的吗" },
    { uid: "7", text: "资料提供：MBC" },
    { uid: "8", text: "资料提供：制作组" },
  ])

  assert.deepEqual(candidates.map((item) => ({ name: item.name, recommended: item.recommended })), [
    { name: "本部职员", recommended: false },
  ])
})

test("skips a stale speaker occurrence after the cue text changed", () => {
  const original = [{ uid: "1", text: "朴宝英：你好" }]
  const candidates = detectCueSpeakerPrefixCandidates(original, [{ name: "朴宝英", trusted: true }])
  const result = applySpeakerPrefixCandidates([{ uid: "1", text: "朴宝英：已经手动改过" }], candidates, [candidates[0].id])

  assert.equal(result.changedCueCount, 0)
  assert.equal(result.cues[0].text, "朴宝英：已经手动改过")
})

test("parses comma and newline separated prefix names", () => {
  assert.deepEqual(parsePrefixNames("朴宝英, 禧主\n小昱，金成哲"), ["朴宝英", "禧主", "小昱", "金成哲"])
})

test("removes only configured name prefixes followed by colon or whitespace", () => {
  const cues = [
    { uid: "1", text: "朴宝英：今天很开心" },
    { uid: "2", text: "禧主 今天来了" },
    { uid: "3", text: "小昱\t没关系" },
    { uid: "4", text: "朴宝英今天很开心" },
    { uid: "5", text: "朴宝英是主演" },
    { uid: "6", text: "金成哲: 你好" },
  ]

  const result = stripCueSpeakerPrefixes(cues, ["朴宝英", "禧主", "小昱", "金成哲"])

  assert.equal(result.changedCueCount, 4)
  assert.equal(result.removedPrefixCount, 4)
  assert.deepEqual(result.cues.map((cue) => cue.text), [
    "今天很开心",
    "今天来了",
    "没关系",
    "朴宝英今天很开心",
    "朴宝英是主演",
    "你好",
  ])
})

test("uses the longest configured prefix first", () => {
  const result = stripCueSpeakerPrefixes([{ uid: "1", text: "朴宝英：开始" }], ["朴", "朴宝英"])

  assert.equal(result.cues[0].text, "开始")
  assert.equal(result.removedPrefixCount, 1)
})

test("removes only trailing Chinese or English commas", () => {
  const result = stripCueTrailingCommas([
    { uid: "1", text: "你好，" },
    { uid: "2", text: "hello," },
    { uid: "3", text: "我说，是真的" },
    { uid: "4", text: "换行结尾，\n" },
    { uid: "5", text: "已经结束。" },
  ])

  assert.equal(result.changedCueCount, 3)
  assert.equal(result.removedCommaCount, 3)
  assert.deepEqual(result.cues.map((cue) => cue.text), [
    "你好",
    "hello",
    "我说，是真的",
    "换行结尾",
    "已经结束。",
  ])
})

test("detects unpaired quote and bracket issues with missing symbol hints", () => {
  const issues = detectCuePairSymbolIssues([
    { uid: "1", text: "他说“今天很开心" },
    { uid: "2", text: "这是《黄金乐园的花絮" },
    { uid: "3", text: "已经正常（没问题）" },
    { uid: "4", text: "只剩右括号）" },
  ])

  assert.deepEqual(issues.map((issue) => ({ uid: issue.uid, missing: issue.missingSymbol, type: issue.type })), [
    { uid: "1", missing: "”", type: "missing_close" },
    { uid: "2", missing: "》", type: "missing_close" },
    { uid: "4", missing: "（", type: "missing_open" },
  ])
})

test("does not report a pair that opens in one cue and closes in the next", () => {
  const issues = detectCuePairSymbolIssues([
    { uid: "1", text: "他说“今天" },
    { uid: "2", text: "真的很开心”" },
  ])

  assert.deepEqual(issues, [])
})

test("does not auto-pair brackets across separate subtitle cues", () => {
  const issues = detectCuePairSymbolIssues([
    { uid: "1", text: "（上条忘了关" },
    { uid: "2", text: "下条是独立内容)" },
  ])

  assert.deepEqual(issues.map((issue) => issue.type), ["missing_close", "missing_open"])
  assert.ok(issues.every((issue) => issue.autoRepairable === false))
})

test("reports a pair spanning too many cues for human review", () => {
  const issues = detectCuePairSymbolIssues([
    { uid: "1", text: "他说“今天" },
    { uid: "2", text: "第一段" },
    { uid: "3", text: "第二段" },
    { uid: "4", text: "第三段" },
    { uid: "5", text: "终于说完了”" },
  ])

  assert.equal(issues.length, 1)
  assert.equal(issues[0].type, "distant_pair")
  assert.equal(issues[0].cueSpan, 4)
  assert.equal(issues[0].autoRepairable, false)
  assert.equal(issues[0].suggestionAvailable, false)
})

test("recognizes mixed full-width parentheses as one mechanically repairable mismatch", () => {
  const cues = [{ uid: "1", text: "（内容)" }]
  const issues = detectCuePairSymbolIssues(cues)

  assert.equal(issues.length, 1)
  assert.equal(issues[0].type, "mismatched_close")
  assert.equal(issues[0].actualSymbol, ")")
  assert.equal(issues[0].replacementSymbol, "）")
  assert.equal(issues[0].autoRepairable, true)

  const repaired = applyCuePairIssueRepairs(cues, issues)
  assert.equal(repaired.repairedIssueCount, 1)
  assert.equal(repaired.cues[0].text, "（内容）")
  assert.deepEqual(detectCuePairSymbolIssues(repaired.cues), [])
})

test("reports crossed nesting without offering an automatic rewrite", () => {
  const issues = detectCuePairSymbolIssues([{ uid: "1", text: "[“内容]”" }])

  assert.equal(issues.length, 1)
  assert.equal(issues[0].type, "crossed_pair")
  assert.equal(issues[0].autoRepairable, false)
  assert.equal(issues[0].suggestionAvailable, false)

  const mixedIssues = detectCuePairSymbolIssues([{ uid: "2", text: "[(内容】)" }])
  assert.equal(mixedIssues[0].type, "crossed_pair")
  assert.equal(mixedIssues[0].autoRepairable, false)
})

test("applies an explicitly confirmed boundary-symbol suggestion", () => {
  const cues = [{ uid: "1", text: "他说“今天很开心" }]
  const issues = detectCuePairSymbolIssues(cues)
  const repaired = applyCuePairIssueRepairs(cues, issues, { includeBoundarySuggestions: true })

  assert.equal(repaired.repairedIssueCount, 1)
  assert.equal(repaired.cues[0].text, "他说“今天很开心”")
})
