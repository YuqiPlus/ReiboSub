const PIPELINES = Object.freeze({
  v1: Object.freeze({
    version: 'v1',
    label: 'OCR 1.0（旧版）',
    description: '自动主字幕 OCR → 旧文本清理 → 旧翻译流程',
    ocrExtractionMode: 'auto',
    ocrRefinementMode: 'none',
    ocrTranslationMode: 'standard_cleanup',
    ocrShapeMode: 'unrestricted',
  }),
  v2: Object.freeze({
    version: 'v2',
    label: 'OCR 2.0（稳定版）',
    description: '区域 OCR → 专属框/轨迹去噪 → 锁定原时间轴翻译',
    ocrExtractionMode: 'region',
    ocrRefinementMode: 'llm_boxes',
    ocrTranslationMode: 'translate_only',
    ocrShapeMode: 'unrestricted',
  }),
  v3: Object.freeze({
    version: 'v3',
    label: 'OCR 3.0（稳定版）',
    description: '区域 OCR → 几何软提示 → V3 文字纠错 → 画面字/对白分层 → 锁定原时间轴翻译',
    ocrExtractionMode: 'region_v3',
    ocrRefinementMode: 'llm_geometry',
    sourceCleanupMode: 'none',
    ocrTranslationMode: 'translate_only',
    ocrShapeMode: 'horizontal_preferred',
  }),
})

export const DEFAULT_AGENT_OCR_PIPELINE_VERSION = 'v3'

export function normalizeAgentOcrPipelineVersion(value) {
  const normalized = String(value || '').trim().toLowerCase().replace(/[\s._-]+/g, '')
  if (['v3', '3', '30', 'ocr3', 'ocr30'].includes(normalized)) return 'v3'
  if (['v2', '2', '20', 'ocr2', 'ocr20'].includes(normalized)) return 'v2'
  return 'v1'
}

export function getAgentOcrPipeline(version) {
  return PIPELINES[normalizeAgentOcrPipelineVersion(version)]
}

export function inferAgentOcrPipelineVersion(payload) {
  const settings = payload && typeof payload === 'object' ? payload : {}
  if (settings.ocr_pipeline_version) {
    return normalizeAgentOcrPipelineVersion(settings.ocr_pipeline_version)
  }

  const extractionMode = String(settings.ocr_extraction_mode || '').trim().toLowerCase()
  if (extractionMode === 'region_v3') return 'v3'
  if (extractionMode === 'region') return 'v2'
  if (extractionMode === 'auto') return 'v1'
  const refinementMode = String(settings.ocr_refinement_mode || '').trim().toLowerCase()
  if (refinementMode === 'llm_geometry') return 'v3'
  if (refinementMode === 'llm_boxes') return 'v2'
  if (String(settings.ocr_translation_mode || '').trim().toLowerCase() === 'translate_only') return 'v2'
  return 'v1'
}

export function buildAgentOcrPipelinePayload(version, { ocrScope = 'bottom', restoredSettings = null } = {}) {
  const pipeline = getAgentOcrPipeline(version)
  const restored = restoredSettings && typeof restoredSettings === 'object' ? restoredSettings : {}
  if (pipeline.version === 'v3') {
    return {
      ocr_pipeline_version: 'v3',
      ocr_scope: restored.ocr_scope || 'bottom',
      ocr_extraction_mode: 'region_v3',
      ocr_shape_mode: restored.ocr_shape_mode || pipeline.ocrShapeMode,
      ocr_refinement_mode: restored.ocr_refinement_mode || pipeline.ocrRefinementMode,
      ocr_translation_mode: restored.ocr_translation_mode || pipeline.ocrTranslationMode,
    }
  }
  return {
    ocr_pipeline_version: pipeline.version,
    ocr_scope: pipeline.version === 'v2' ? 'bottom' : ocrScope,
    ocr_extraction_mode: pipeline.ocrExtractionMode,
    ocr_shape_mode: pipeline.ocrShapeMode,
    ocr_refinement_mode: pipeline.ocrRefinementMode,
    ocr_translation_mode: pipeline.ocrTranslationMode,
  }
}
