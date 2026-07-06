import test from "node:test"
import assert from "node:assert/strict"

import { copyText } from "./clipboard.js"

test("uses navigator clipboard when available", async () => {
  const calls = []
  const ok = await copyText("hello", {
    navigator: { clipboard: { writeText: async (value) => calls.push(value) } },
  })

  assert.equal(ok, true)
  assert.deepEqual(calls, ["hello"])
})

test("falls back to textarea copy when clipboard api is unavailable", async () => {
  const appended = []
  const removed = []
  const selected = []
  const element = {
    value: "",
    style: {},
    setAttribute(name, value) { this[name] = value },
    select() { selected.push(this.value) },
  }
  const ok = await copyText("http://example.test:7860/demo", {
    navigator: {},
    document: {
      body: {
        appendChild(node) { appended.push(node) },
        removeChild(node) { removed.push(node) },
      },
      createElement(tag) {
        assert.equal(tag, "textarea")
        return element
      },
      execCommand(command) {
        assert.equal(command, "copy")
        return true
      },
    },
  })

  assert.equal(ok, true)
  assert.deepEqual(selected, ["http://example.test:7860/demo"])
  assert.equal(appended[0], element)
  assert.equal(removed[0], element)
})

test("falls back when navigator clipboard rejects", async () => {
  const ok = await copyText("fallback", {
    navigator: { clipboard: { writeText: async () => { throw new Error("denied") } } },
    document: {
      body: { appendChild() {}, removeChild() {} },
      createElement() { return { style: {}, setAttribute() {}, select() {} } },
      execCommand() { return true },
    },
  })

  assert.equal(ok, true)
})
