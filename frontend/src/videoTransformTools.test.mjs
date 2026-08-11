import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildVideoTransformPayload,
  createDefaultVideoTransform,
  hasVideoTransform,
  inspectVideoTransform,
  videoCropFrameStyle,
} from './videoTransformTools.js'

test('default video transform is inactive', () => {
  const settings = createDefaultVideoTransform()
  assert.equal(hasVideoTransform(settings), false)
  assert.deepEqual(buildVideoTransformPayload(settings), {
    horizontal_flip: false,
    crop_top_ratio: 0,
    crop_right_ratio: 0,
    crop_bottom_ratio: 0,
    crop_left_ratio: 0,
    output_width: 0,
    output_height: 0,
  })
})

test('horizontal mirror alone enables video processing', () => {
  const settings = { ...createDefaultVideoTransform(), horizontal_flip: true }
  assert.equal(hasVideoTransform(settings), true)
  assert.equal(inspectVideoTransform(settings, 1920, 1080).error, '')
})

test('converts four crop percentages into a retained frame', () => {
  const settings = {
    ...createDefaultVideoTransform(),
    crop_enabled: true,
    crop_top_percent: 10,
    crop_right_percent: 10,
    crop_bottom_percent: 10,
    crop_left_percent: 10,
  }
  const inspected = inspectVideoTransform(settings, 1920, 1080)

  assert.deepEqual(inspected.crop_pixels, { top: 108, right: 192, bottom: 108, left: 192 })
  assert.deepEqual([inspected.cropped_width, inspected.cropped_height], [1536, 864])
  assert.deepEqual([inspected.output_width, inspected.output_height], [1536, 864])
  assert.deepEqual(videoCropFrameStyle(settings), {
    left: '10.000%', top: '10.000%', width: '80.000%', height: '80.000%',
  })
})

test('rejects crop percentages that remove nearly the whole frame', () => {
  const settings = {
    ...createDefaultVideoTransform(),
    crop_enabled: true,
    crop_left_percent: 55,
    crop_right_percent: 45,
  }
  assert.match(inspectVideoTransform(settings, 1920, 1080).error, /左右裁剪合计/)
})

test('rejects out-of-range crop and malformed output dimensions instead of clamping silently', () => {
  const invalidCrop = {
    ...createDefaultVideoTransform(),
    crop_enabled: true,
    crop_left_percent: 96,
  }
  assert.match(inspectVideoTransform(invalidCrop, 1920, 1080).error, /0 到 95/)

  const invalidOutput = {
    ...createDefaultVideoTransform(),
    resize_enabled: true,
    output_width: 1280.5,
  }
  assert.match(inspectVideoTransform(invalidOutput, 1920, 1080).error, /输出宽度/)
})

test('derives the other even output dimension when only width is supplied', () => {
  const settings = {
    ...createDefaultVideoTransform(),
    resize_enabled: true,
    output_width: 1280,
  }
  const inspected = inspectVideoTransform(settings, 1920, 1080)
  assert.deepEqual([inspected.output_width, inspected.output_height], [1280, 720])
  assert.equal(inspected.stretches, false)
})

test('rejects a one-sided resize that derives an unusably small second edge', () => {
  const settings = {
    ...createDefaultVideoTransform(),
    resize_enabled: true,
    output_width: 2,
  }
  assert.match(inspectVideoTransform(settings, 1920, 1080).error, /小于 2 像素/)
})

test('rejects two-sided output dimensions that would stretch the preview', () => {
  const settings = {
    ...createDefaultVideoTransform(),
    resize_enabled: true,
    output_width: 1001,
    output_height: 1001,
  }
  const inspected = inspectVideoTransform(settings, 1920, 1080)
  assert.deepEqual([inspected.output_width, inspected.output_height], [1000, 1000])
  assert.equal(inspected.stretches, true)
  assert.match(inspected.error, /宽高比/)
})

test('accepts two-sided output dimensions when their aspect ratio matches', () => {
  const settings = {
    ...createDefaultVideoTransform(),
    resize_enabled: true,
    output_width: 1280,
    output_height: 720,
  }
  assert.equal(inspectVideoTransform(settings, 1920, 1080).error, '')
})
