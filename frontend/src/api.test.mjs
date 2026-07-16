import test from "node:test"
import assert from "node:assert/strict"
import { deleteJson, patchJson, uploadProjectCover, uploadVideoFile } from "./api.js"

test("deleteJson sends a JSON DELETE request and surfaces API errors", async () => {
  const previousFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    return new Response(JSON.stringify({ deleted_provider_id: "old" }), { status: 200 })
  }

  try {
    const result = await deleteJson('/api/settings/providers/old', { replacement_provider_id: 'new' })
    assert.equal(result.deleted_provider_id, 'old')
    assert.equal(calls[0].options.method, 'DELETE')
    assert.equal(calls[0].options.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(calls[0].options.body), { replacement_provider_id: 'new' })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test("patchJson sends provider metadata without changing the request shape", async () => {
  const previousFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    return new Response(JSON.stringify({ provider: { id: 'existing', label: 'Updated' } }), { status: 200 })
  }

  try {
    const result = await patchJson('/api/settings/providers/existing', {
      label: 'Updated',
      default_model: 'model-new',
      models: ['model-extra'],
    })
    assert.equal(result.provider.label, 'Updated')
    assert.equal(calls[0].options.method, 'PATCH')
    assert.deepEqual(JSON.parse(calls[0].options.body), {
      label: 'Updated',
      default_model: 'model-new',
      models: ['model-extra'],
    })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test("uploadVideoFile posts multipart form data without json content type", async () => {
  const calls = []
  const file = new File(["demo"], "demo.mp4", { type: "video/mp4" })
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    assert.equal(path, "/api/upload-video")
    assert.equal(options.method, "POST")
    assert.ok(options.body instanceof FormData)
    assert.equal(options.body.get("file"), file)
    assert.equal(options.body.get("title"), "手机视频")
    assert.equal(options.headers, undefined)
    return new Response(JSON.stringify({ input_video: "/tmp/demo.mp4" }), { status: 200 })
  }

  try {
    const result = await uploadVideoFile(file, { title: "手机视频" })
    assert.equal(result.input_video, "/tmp/demo.mp4")
    assert.equal(calls.length, 1)
  } finally {
    globalThis.fetch = previousFetch
  }
})


test("uploadProjectCover posts project path and cover file", async () => {
  const calls = []
  const file = new File(["cover"], "cover.png", { type: "image/png" })
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    assert.equal(path, "/api/upload-project-cover")
    assert.equal(options.method, "POST")
    assert.ok(options.body instanceof FormData)
    assert.equal(options.body.get("file"), file)
    assert.equal(options.body.get("project_path"), "/projects/demo")
    assert.equal(options.headers, undefined)
    return new Response(JSON.stringify({ thumbnail_path: "/projects/demo/cover.png" }), { status: 200 })
  }

  try {
    const result = await uploadProjectCover(file, { projectPath: "/projects/demo" })
    assert.equal(result.thumbnail_path, "/projects/demo/cover.png")
    assert.equal(calls.length, 1)
  } finally {
    globalThis.fetch = previousFetch
  }
})
