import test from "node:test"
import assert from "node:assert/strict"

import {
  detectCuePairSymbolIssues,
  parsePrefixNames,
  stripCueSpeakerPrefixes,
  stripCueTrailingCommas,
} from "./subtitlePrefixTools.js"

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
