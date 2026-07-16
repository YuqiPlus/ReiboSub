export const SETTINGS_TASKS = Object.freeze([
  {
    key: 'title_translation',
    label: '标题翻译',
    description: '视频标题盲翻和 Glossary 审核里的单句候选。',
  },
  {
    key: 'glossary',
    label: 'Glossary 生成',
    description: '从原字幕提取人名、节目名和固定术语。',
  },
  {
    key: 'subtitle_translation',
    label: '字幕翻译',
    description: '将原字幕翻译为中文，包含批量重试与译后清理。',
  },
  {
    key: 'asr_correction',
    label: 'ASR 原文纠错',
    description: '纠正语音识别结果，保留原语言文本。',
  },
  {
    key: 'hybrid_source_reconstruction',
    label: 'Hybrid 原文重建',
    description: '结合 OCR 文本和参考字幕重建原语言字幕。',
  },
  {
    key: 'ocr_source_refinement',
    label: 'OCR 文字与分层精修',
    description: 'OCR V2 / V3 的文字精修与画中字分层目前共用此配置。',
  },
  {
    key: 'ocr_geometry_refinement',
    label: 'OCR V3 几何判断',
    description: '利用位置、角度和轨迹特征过滤倾斜画面字。',
  },
  {
    key: 'ocr_source_cleanup',
    label: 'OCR 旧版去噪',
    description: '用于仍启用上下文去噪的旧 OCR 流程。',
  },
])

export const SOURCE_LANGUAGE_OPTIONS = Object.freeze([
  { value: 'auto', label: '自动判断' },
  { value: 'korean', label: '韩语' },
  { value: 'japanese', label: '日语' },
  { value: 'english', label: '英语' },
  { value: 'chinese', label: '中文' },
])

const SOURCE_LANGUAGES = new Set(SOURCE_LANGUAGE_OPTIONS.map((item) => item.value))
const OCR_LANGUAGES = new Set(['auto', 'korean', 'japanese', 'english', 'chinese'])
const PROVIDER_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{0,127}$/

export function normalizeSettings(settings = {}, providers = []) {
  const source = asObject(settings)
  const defaults = asObject(source.defaults)
  const tasks = asObject(source.tasks)
  const firstProviderId = cleanText(providers?.[0]?.id)
  const normalizedTasks = {}

  for (const task of SETTINGS_TASKS) {
    const rawBinding = tasks[task.key]
    const binding = typeof rawBinding === 'string'
      ? { model: rawBinding }
      : asObject(rawBinding)
    normalizedTasks[task.key] = {
      provider_profile: cleanText(binding.provider_profile),
      model: cleanText(binding.model),
    }
  }

  return {
    version: 1,
    defaults: {
      source_language: validChoice(defaults.source_language, SOURCE_LANGUAGES, 'korean'),
      ocr_language: validChoice(defaults.ocr_language, OCR_LANGUAGES, 'auto'),
      target_language: cleanText(defaults.target_language) || 'zh',
      provider_profile: cleanText(defaults.provider_profile) || firstProviderId,
    },
    tasks: normalizedTasks,
  }
}

export function buildSettingsPayload(settings = {}) {
  const normalized = normalizeSettings(settings)
  const tasks = {}

  for (const task of SETTINGS_TASKS) {
    const binding = normalized.tasks[task.key]
    tasks[task.key] = {
      provider_profile: cleanText(binding.provider_profile),
      model: cleanText(binding.model),
    }
  }

  return {
    version: 1,
    defaults: { ...normalized.defaults },
    tasks,
  }
}

export function resolvedProviderId(binding, defaultProviderId = '') {
  return cleanText(binding?.provider_profile) || cleanText(defaultProviderId)
}

export function providerModels(providerId, providers = [], modelsByProvider = {}) {
  const id = cleanText(providerId)
  if (!id) return []
  const provider = (providers || []).find((item) => cleanText(item?.id) === id) || {}
  const remote = asObject(modelsByProvider)[id]
  const candidates = [
    provider.models,
    provider.model_names,
    provider.model_name,
    provider.default_model,
    remote,
  ]
  const result = []
  const seen = new Set()

  for (const candidate of candidates) {
    for (const model of extractModels(candidate)) {
      if (!seen.has(model)) {
        seen.add(model)
        result.push(model)
      }
    }
  }
  return result
}

export function mergeProviderModelMaps(providers = [], current = {}) {
  const result = {}
  for (const provider of providers || []) {
    const providerId = cleanText(provider?.id)
    if (!providerId) continue
    result[providerId] = providerModels(providerId, providers, current)
  }
  return result
}

export function shouldFetchProviderModelsOnSelection(providerId, providers = [], modelsByProvider = {}) {
  const id = cleanText(providerId)
  if (!id || !(providers || []).some((provider) => cleanText(provider?.id) === id)) return false
  return !Object.prototype.hasOwnProperty.call(asObject(modelsByProvider), id)
}

export function providerCredentialState(provider) {
  if (!provider || !Object.keys(provider).length) {
    return { state: 'unknown', label: '未选择服务配置' }
  }
  const configured = provider.key_configured ?? provider.api_key_configured ?? provider.configured
  if (configured === true) return { state: 'configured', label: '连接凭据已配置' }
  if (configured === false) return { state: 'missing', label: '缺少连接凭据' }
  return { state: 'unknown', label: '尚未检查连接凭据' }
}

export function providerDisplayName(provider) {
  return cleanText(provider?.label) || cleanText(provider?.name) || cleanText(provider?.id) || '未知服务'
}

export function createProviderDraft() {
  return {
    id: '',
    label: '',
    base_url: '',
    api_key: '',
    default_model: '',
    models_url: '',
    models_text: '',
  }
}

export function providerIdIsValid(value) {
  const id = cleanText(value).toLowerCase()
  return PROVIDER_ID_PATTERN.test(id) && !id.endsWith('.yml') && !id.endsWith('.yaml')
}

export function buildCreateProviderPayload(draft = {}) {
  const source = asObject(draft)
  const payload = {
    id: cleanText(source.id).toLowerCase(),
    label: cleanText(source.label),
    base_url: cleanText(source.base_url),
    default_model: cleanText(source.default_model),
  }
  const apiKey = cleanText(source.api_key)
  const modelsUrl = cleanText(source.models_url)
  const models = String(source.models_text || '')
    .split(/[\n,]/)
    .map((model) => model.trim())
    .filter((model, index, values) => Boolean(model) && values.indexOf(model) === index)
  if (apiKey) payload.api_key = apiKey
  if (modelsUrl) payload.models_url = modelsUrl
  if (models.length) payload.models = models
  return payload
}

export function createProviderMetadataDraft(provider = {}) {
  const source = asObject(provider)
  const defaultModel = cleanText(source.default_model) || cleanText(source.model_name)
  const staticModels = Array.isArray(source.static_models)
    ? extractModels(source.static_models)
    : providerModels(cleanText(source.id), [source], {}).filter((model) => model !== defaultModel)
  return {
    id: cleanText(source.id),
    label: cleanText(source.label) || cleanText(source.name) || cleanText(source.id),
    default_model: defaultModel,
    models_text: staticModels.join('\n'),
  }
}

export function buildUpdateProviderPayload(draft = {}) {
  const source = asObject(draft)
  const models = String(source.models_text || '')
    .split(/[\n,]/)
    .map((model) => model.trim())
    .filter((model, index, values) => Boolean(model) && values.indexOf(model) === index)
  return {
    label: cleanText(source.label),
    default_model: cleanText(source.default_model),
    models,
  }
}

export function providerMetadataMatches(provider = {}, payload = {}) {
  const source = asObject(provider)
  const expected = asObject(payload)
  const expectedLabel = cleanText(expected.label) || cleanText(source.id)
  const actualModels = (Array.isArray(source.static_models)
    ? extractModels(source.static_models)
    : providerModels(cleanText(source.id), [source], {}).filter((model) => model !== cleanText(source.default_model)))
    .sort((a, b) => a.localeCompare(b))
  const expectedModels = (Array.isArray(expected.models) ? expected.models.map(cleanText).filter(Boolean) : [])
    .sort((a, b) => a.localeCompare(b))
  return providerDisplayName(source) === expectedLabel
    && cleanText(source.default_model) === cleanText(expected.default_model)
    && actualModels.length === expectedModels.length
    && actualModels.every((model, index) => model === expectedModels[index])
}

export function replacementProviderId(providerId, providers = [], defaultProviderId = '') {
  const removedId = cleanText(providerId)
  const candidates = (providers || []).map((provider) => cleanText(provider?.id)).filter(Boolean)
  const preferred = cleanText(defaultProviderId)
  if (preferred && preferred !== removedId && candidates.includes(preferred)) return preferred
  return candidates.find((candidate) => candidate !== removedId) || ''
}

export function normalizeProviderConnection(connection = {}, provider = {}) {
  const source = asObject(connection)
  const profile = asObject(provider)
  return {
    provider_id: cleanText(source.provider_id) || cleanText(profile.id),
    label: cleanText(source.label) || providerDisplayName(profile),
    key_configured: source.key_configured === true,
    local_key_configured: source.local_key_configured === true,
    key_source: cleanText(source.key_source) || (source.key_configured === true ? 'configured' : 'missing'),
    base_url: cleanText(source.base_url),
    base_url_source: cleanText(source.base_url_source) || (source.base_url ? 'configured' : 'missing'),
    local_base_url_configured: source.local_base_url_configured === true,
    models_url: cleanText(source.models_url) || cleanText(profile.models_url),
    storage_path: cleanText(source.storage_path),
    key_write_allowed: source.key_write_allowed === true,
    endpoint_origin_change_allowed: source.endpoint_origin_change_allowed === true,
  }
}

export function createProviderConnectionDraft(connection = {}, provider = {}) {
  const normalized = normalizeProviderConnection(connection, provider)
  return {
    // Password values are deliberately never copied from an API response.
    api_key: '',
    base_url: normalized.base_url,
    models_url: normalized.models_url,
  }
}

export function buildProviderConnectionPayload(draft = {}, connection = {}) {
  const normalized = normalizeProviderConnection(connection)
  const source = asObject(draft)
  const apiKey = cleanText(source.api_key)
  const baseUrl = cleanText(source.base_url)
  const modelsUrl = cleanText(source.models_url)
  const payload = {}

  if (apiKey) payload.api_key = apiKey
  if (baseUrl !== normalized.base_url) {
    if (baseUrl) payload.base_url = baseUrl
    else if (normalized.base_url) payload.clear_base_url = true
  }
  if (modelsUrl !== normalized.models_url) {
    if (modelsUrl) payload.models_url = modelsUrl
    else if (normalized.models_url) payload.clear_models_url = true
  }
  return payload
}

export function providerConnectionHasChanges(draft = {}, connection = {}) {
  return Object.keys(buildProviderConnectionPayload(draft, connection)).length > 0
}

export function providerConnectionEndpointChangeRequiresLocal(draft = {}, connection = {}) {
  const normalized = normalizeProviderConnection(connection)
  if (normalized.endpoint_origin_change_allowed) return false

  const payload = buildProviderConnectionPayload(draft, normalized)
  if (payload.clear_base_url) return true

  const currentOrigin = urlOrigin(normalized.base_url)
  if (payload.base_url && urlOrigin(payload.base_url) !== currentOrigin) return true
  if (payload.models_url && urlOrigin(payload.models_url) !== currentOrigin) return true
  return false
}

export function providerConnectionSourceLabel(source, { configured = false } = {}) {
  const value = cleanText(source).toLowerCase()
  const labels = {
    local: '本地私密配置',
    local_config: '本地私密配置',
    env: '进程环境变量（兼容旧配置）',
    environment: '进程环境变量（兼容旧配置）',
    profile: '服务配置文件',
    configured: '已配置',
    missing: '未配置',
    unconfigured: '未配置',
    default: '程序默认值',
  }
  return labels[value] || (value ? source : (configured ? '已配置' : '未配置'))
}

function extractModels(value) {
  if (!value) return []
  if (typeof value === 'string') return splitModelText(value)
  if (Array.isArray(value)) return value.flatMap((item) => extractModels(item))
  if (typeof value !== 'object') return []

  if (Array.isArray(value.models)) return extractModels(value.models)
  if (Array.isArray(value.data)) return extractModels(value.data)
  if (Array.isArray(value.items)) return extractModels(value.items)
  const model = cleanText(value.id) || cleanText(value.model) || cleanText(value.model_name) || cleanText(value.name)
  return model ? [model] : []
}

function splitModelText(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function validChoice(value, choices, fallback) {
  const cleaned = cleanText(value)
  return choices.has(cleaned) ? cleaned : fallback
}

function urlOrigin(value) {
  try {
    const parsed = new URL(cleanText(value))
    if (!['http:', 'https:'].includes(parsed.protocol)) return ''
    return parsed.origin.toLowerCase()
  } catch {
    return ''
  }
}

function cleanText(value) {
  return String(value ?? '').trim()
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}
