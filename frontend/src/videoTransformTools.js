const MAX_OUTPUT_EDGE = 8192
const MAX_OUTPUT_PIXELS = 33_177_600

export function createDefaultVideoTransform() {
  return {
    horizontal_flip: false,
    crop_enabled: false,
    crop_top_percent: 0,
    crop_right_percent: 0,
    crop_bottom_percent: 0,
    crop_left_percent: 0,
    resize_enabled: false,
    output_width: '',
    output_height: '',
  }
}

export function buildVideoTransformPayload(settings = {}) {
  return {
    horizontal_flip: Boolean(settings.horizontal_flip),
    crop_top_ratio: settings.crop_enabled ? percentRatio(settings.crop_top_percent) : 0,
    crop_right_ratio: settings.crop_enabled ? percentRatio(settings.crop_right_percent) : 0,
    crop_bottom_ratio: settings.crop_enabled ? percentRatio(settings.crop_bottom_percent) : 0,
    crop_left_ratio: settings.crop_enabled ? percentRatio(settings.crop_left_percent) : 0,
    output_width: settings.resize_enabled ? optionalInteger(settings.output_width) : 0,
    output_height: settings.resize_enabled ? optionalInteger(settings.output_height) : 0,
  }
}

export function hasVideoTransform(settings = {}) {
  const payload = buildVideoTransformPayload(settings)
  return Boolean(
    payload.horizontal_flip
    || payload.crop_top_ratio
    || payload.crop_right_ratio
    || payload.crop_bottom_ratio
    || payload.crop_left_ratio
    || payload.output_width
    || payload.output_height
  )
}

export function inspectVideoTransform(settings = {}, sourceWidth = 0, sourceHeight = 0) {
  const rawCropValues = [
    settings.crop_top_percent,
    settings.crop_right_percent,
    settings.crop_bottom_percent,
    settings.crop_left_percent,
  ]
  const payload = buildVideoTransformPayload(settings)
  const horizontalCrop = payload.crop_left_ratio + payload.crop_right_ratio
  const verticalCrop = payload.crop_top_ratio + payload.crop_bottom_ratio
  let error = ''
  if (settings.crop_enabled && rawCropValues.some((value) => !validCropPercent(value))) {
    error = '四边裁剪百分比必须是 0 到 95 之间的数字。'
  }
  if (settings.crop_enabled && horizontalCrop >= 0.98) error = '左右裁剪合计必须小于 98%。'
  if (!error && settings.crop_enabled && verticalCrop >= 0.98) error = '上下裁剪合计必须小于 98%。'
  if (!error && settings.resize_enabled && !payload.output_width && !payload.output_height) {
    error = '启用自定义尺寸后，至少填写宽度或高度。'
  }
  if (!error && settings.resize_enabled && !validOptionalDimension(settings.output_width)) {
    error = `输出宽度必须留空，或填写 2 到 ${MAX_OUTPUT_EDGE} 之间的整数。`
  }
  if (!error && settings.resize_enabled && !validOptionalDimension(settings.output_height)) {
    error = `输出高度必须留空，或填写 2 到 ${MAX_OUTPUT_EDGE} 之间的整数。`
  }

  const width = positiveInteger(sourceWidth)
  const height = positiveInteger(sourceHeight)
  const cropLeft = width ? Math.round(width * payload.crop_left_ratio) : 0
  const cropRight = width ? Math.round(width * payload.crop_right_ratio) : 0
  const cropTop = height ? Math.round(height * payload.crop_top_ratio) : 0
  const cropBottom = height ? Math.round(height * payload.crop_bottom_ratio) : 0
  const croppedWidth = width ? width - cropLeft - cropRight : 0
  const croppedHeight = height ? height - cropTop - cropBottom : 0
  if (!error && width && croppedWidth < 2) error = '左右裁剪后没有足够的画面宽度。'
  if (!error && height && croppedHeight < 2) error = '上下裁剪后没有足够的画面高度。'

  let outputWidth = croppedWidth ? evenFloor(croppedWidth) : 0
  let outputHeight = croppedHeight ? evenFloor(croppedHeight) : 0
  if (settings.resize_enabled && !error) {
    if (payload.output_width && payload.output_height) {
      outputWidth = evenFloor(payload.output_width)
      outputHeight = evenFloor(payload.output_height)
    } else if (payload.output_width) {
      outputWidth = evenFloor(payload.output_width)
      outputHeight = croppedWidth && croppedHeight
        ? evenFloor(outputWidth * croppedHeight / croppedWidth)
        : 0
    } else if (payload.output_height) {
      outputHeight = evenFloor(payload.output_height)
      outputWidth = croppedWidth && croppedHeight
        ? evenFloor(outputHeight * croppedWidth / croppedHeight)
        : 0
    }
  }
  if (!error && (outputWidth > MAX_OUTPUT_EDGE || outputHeight > MAX_OUTPUT_EDGE)) {
    error = `输出尺寸单边不能超过 ${MAX_OUTPUT_EDGE} 像素。`
  }
  if (!error && outputWidth && outputHeight && outputWidth * outputHeight > MAX_OUTPUT_PIXELS) {
    error = '输出总像素过大，请降低宽度或高度。'
  }
  if (!error && width && height && (outputWidth < 2 || outputHeight < 2)) {
    error = '当前比例计算出的输出尺寸小于 2 像素，请增大宽度或高度。'
  }

  const sourceAspect = croppedWidth && croppedHeight ? croppedWidth / croppedHeight : 0
  const outputAspect = outputWidth && outputHeight ? outputWidth / outputHeight : 0
  const stretches = Boolean(
    settings.resize_enabled
    && payload.output_width
    && payload.output_height
    && sourceAspect
    && outputAspect
    && Math.abs(sourceAspect - outputAspect) / sourceAspect > 0.01
  )
  if (!error && stretches) {
    error = '输出宽高比与裁剪后画面不一致；请只填一边自动等比，或先调整四边裁剪。'
  }

  return {
    active: hasVideoTransform(settings),
    error,
    payload,
    crop_pixels: { top: cropTop, right: cropRight, bottom: cropBottom, left: cropLeft },
    cropped_width: Math.max(0, croppedWidth),
    cropped_height: Math.max(0, croppedHeight),
    output_width: outputWidth,
    output_height: outputHeight,
    stretches,
  }
}

export function videoCropFrameStyle(settings = {}) {
  const payload = buildVideoTransformPayload(settings)
  const left = payload.crop_left_ratio * 100
  const right = payload.crop_right_ratio * 100
  const top = payload.crop_top_ratio * 100
  const bottom = payload.crop_bottom_ratio * 100
  return {
    left: `${left.toFixed(3)}%`,
    top: `${top.toFixed(3)}%`,
    width: `${Math.max(0.1, 100 - left - right).toFixed(3)}%`,
    height: `${Math.max(0.1, 100 - top - bottom).toFixed(3)}%`,
  }
}

function percentRatio(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(95, number)) / 100
}

function validCropPercent(value) {
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 && number <= 95
}

function validOptionalDimension(value) {
  if (value === '' || value === null || value === undefined) return true
  const number = Number(value)
  return Number.isInteger(number) && number >= 2 && number <= MAX_OUTPUT_EDGE
}

function optionalInteger(value) {
  if (value === '' || value === null || value === undefined) return 0
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return 0
  return Math.floor(number)
}

function positiveInteger(value) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0
}

function evenFloor(value) {
  const number = Math.floor(Number(value) || 0)
  if (number < 2) return number
  return number - (number % 2)
}
