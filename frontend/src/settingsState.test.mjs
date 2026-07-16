import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SETTINGS_TASKS,
  buildProviderConnectionPayload,
  buildCreateProviderPayload,
  buildUpdateProviderPayload,
  buildSettingsPayload,
  createProviderDraft,
  createProviderMetadataDraft,
  createProviderConnectionDraft,
  mergeProviderModelMaps,
  normalizeSettings,
  normalizeProviderConnection,
  providerCredentialState,
  providerConnectionHasChanges,
  providerConnectionEndpointChangeRequiresLocal,
  providerConnectionSourceLabel,
  providerIdIsValid,
  providerMetadataMatches,
  providerModels,
  replacementProviderId,
  resolvedProviderId,
  shouldFetchProviderModelsOnSelection,
} from './settingsState.js'

test('defines every configurable LLM task once', () => {
  assert.deepEqual(
    SETTINGS_TASKS.map((item) => item.key),
    [
      'title_translation',
      'glossary',
      'subtitle_translation',
      'asr_correction',
      'hybrid_source_reconstruction',
      'ocr_source_refinement',
      'ocr_geometry_refinement',
      'ocr_source_cleanup',
    ],
  )
})

test('normalizes empty settings to Korean defaults and all task bindings', () => {
  const result = normalizeSettings({}, [{ id: 'volcano' }])

  assert.deepEqual(result.defaults, {
    source_language: 'korean',
    ocr_language: 'auto',
    target_language: 'zh',
    provider_profile: 'volcano',
  })
  assert.equal(Object.keys(result.tasks).length, 8)
  assert.deepEqual(result.tasks.subtitle_translation, { provider_profile: '', model: '' })
})

test('keeps explicit provider and model bindings while dropping unknown tasks from payload', () => {
  const payload = buildSettingsPayload({
    defaults: {
      source_language: 'japanese',
      ocr_language: 'japanese',
      target_language: 'zh',
      provider_profile: 'qianwen',
    },
    tasks: {
      subtitle_translation: { provider_profile: 'volcano', model: 'doubao-seed-2-0-lite' },
      glossary: 'qwen3.6-flash',
      unsupported_task: { model: 'must-not-leak' },
    },
  })

  assert.deepEqual(payload.tasks.subtitle_translation, {
    provider_profile: 'volcano',
    model: 'doubao-seed-2-0-lite',
  })
  assert.deepEqual(payload.tasks.glossary, { provider_profile: '', model: 'qwen3.6-flash' })
  assert.equal(payload.tasks.unsupported_task, undefined)
})

test('merges profile and remote model lists without preventing manual values', () => {
  const providers = [{
    id: 'volcano',
    model_name: 'doubao-seed-2-0-lite',
    models: ['doubao-seed-2-0-pro', { id: 'deepseek-v4-pro' }],
  }]
  const remoteModels = {
    volcano: {
      models: [
        { id: 'doubao-seed-2-0-lite' },
        { id: 'kimi-k2.6' },
      ],
    },
  }

  assert.deepEqual(providerModels('volcano', providers, remoteModels), [
    'doubao-seed-2-0-pro',
    'deepseek-v4-pro',
    'doubao-seed-2-0-lite',
    'kimi-k2.6',
  ])
})

test('reconciles saved provider profiles with already fetched model lists', () => {
  const providers = [
    { id: 'volcano', models: ['doubao-seed-2-0-lite'] },
    { id: 'qianwen', models: [] },
  ]
  const result = mergeProviderModelMaps(providers, {
    volcano: ['doubao-seed-2-0-pro'],
    qianwen: ['qwen-plus'],
    removed: ['stale-model'],
  })

  assert.deepEqual(result, {
    volcano: ['doubao-seed-2-0-lite', 'doubao-seed-2-0-pro'],
    qianwen: ['qwen-plus'],
  })
})

test('auto-fetches a newly selected provider once even when its profile has static models', () => {
  assert.equal(shouldFetchProviderModelsOnSelection('', [], {}), false)
  assert.equal(
    shouldFetchProviderModelsOnSelection('volcano', [{ id: 'volcano', models: ['doubao-lite'] }], {}),
    true,
  )
  assert.equal(
    shouldFetchProviderModelsOnSelection(
      'volcano',
      [{ id: 'volcano', models: ['doubao-lite'] }],
      { volcano: ['doubao-lite', 'doubao-pro'] },
    ),
    false,
  )
  assert.equal(shouldFetchProviderModelsOnSelection('missing', [{ id: 'volcano' }], {}), false)
})

test('resolves inherited providers and reports credential state without exposing a key', () => {
  assert.equal(resolvedProviderId({ provider_profile: '' }, 'volcano'), 'volcano')
  assert.equal(resolvedProviderId({ provider_profile: 'openai' }, 'volcano'), 'openai')
  assert.deepEqual(providerCredentialState({ id: 'volcano', key_configured: true }), {
    state: 'configured',
    label: '连接凭据已配置',
  })
  assert.deepEqual(providerCredentialState({ id: 'openai', api_key_configured: false }), {
    state: 'missing',
    label: '缺少连接凭据',
  })
})

test('normalizes provider connection metadata without ever retaining a returned secret', () => {
  const result = normalizeProviderConnection({
    provider_id: 'volcano',
    label: '火山方舟',
    api_key: 'must-not-reach-the-password-field',
    key_configured: true,
    local_key_configured: true,
    key_source: 'local',
    base_url: 'https://ark.example/api/v3',
    base_url_source: 'env',
    storage_path: 'configs/provider_connections.local.yaml',
    key_write_allowed: true,
    endpoint_origin_change_allowed: false,
  })
  const draft = createProviderConnectionDraft(result)

  assert.equal(result.api_key, undefined)
  assert.equal(draft.api_key, '')
  assert.equal(draft.base_url, 'https://ark.example/api/v3')
  assert.equal(result.local_key_configured, true)
  assert.equal(result.key_write_allowed, true)
  assert.equal(result.endpoint_origin_change_allowed, false)
})

test('connection payload omits blank passwords and includes only changed connection fields', () => {
  const current = {
    provider_id: 'volcano',
    base_url: 'https://ark.example/api/v3',
    models_url: 'https://ark.example/api/v3/models',
  }

  assert.deepEqual(buildProviderConnectionPayload({
    api_key: '   ',
    base_url: current.base_url,
    models_url: current.models_url,
  }, current), {})
  assert.deepEqual(buildProviderConnectionPayload({
    api_key: 'new-secret',
    base_url: 'https://proxy.example/v1',
    models_url: '',
  }, current), {
    api_key: 'new-secret',
    base_url: 'https://proxy.example/v1',
    clear_models_url: true,
  })
  assert.equal(providerConnectionHasChanges({ api_key: 'new-secret' }, current), true)
})

test('clearing an inherited base URL uses the explicit clear flag', () => {
  assert.deepEqual(buildProviderConnectionPayload(
    { api_key: '', base_url: '', models_url: '' },
    { base_url: 'https://configured.example/v1' },
  ), { clear_base_url: true })
})

test('formats connection source values for the settings UI', () => {
  assert.equal(providerConnectionSourceLabel('local'), '本地私密配置')
  assert.equal(providerConnectionSourceLabel('env'), '进程环境变量（兼容旧配置）')
  assert.equal(providerConnectionSourceLabel('unconfigured'), '未配置')
  assert.equal(providerConnectionSourceLabel('', { configured: false }), '未配置')
})

test('remote capability permits same-origin endpoint paths but requires local access for origin changes', () => {
  const remoteConnection = {
    base_url: 'https://api.example.com/v1',
    models_url: 'https://api.example.com/v1/models',
    endpoint_origin_change_allowed: false,
  }

  assert.equal(providerConnectionEndpointChangeRequiresLocal({
    base_url: 'https://api.example.com/v2',
    models_url: 'https://api.example.com/models',
  }, remoteConnection), false)
  assert.equal(providerConnectionEndpointChangeRequiresLocal({
    api_key: 'write-only-key',
    base_url: remoteConnection.base_url,
    models_url: remoteConnection.models_url,
  }, remoteConnection), false)
  assert.equal(providerConnectionEndpointChangeRequiresLocal({
    base_url: 'https://other.example.com/v1',
    models_url: remoteConnection.models_url,
  }, remoteConnection), true)
  assert.equal(providerConnectionEndpointChangeRequiresLocal({
    base_url: '',
    models_url: remoteConnection.models_url,
  }, remoteConnection), true)
})

test('local endpoint capability allows cross-origin connection edits', () => {
  assert.equal(providerConnectionEndpointChangeRequiresLocal(
    { base_url: 'https://other.example.com/v1' },
    { base_url: 'https://api.example.com/v1', endpoint_origin_change_allowed: true },
  ), false)
})

test('builds a write-only new provider payload and validates provider ids', () => {
  assert.deepEqual(createProviderDraft(), {
    id: '',
    label: '',
    base_url: '',
    api_key: '',
    default_model: '',
    models_url: '',
    models_text: '',
  })
  assert.equal(providerIdIsValid('custom-gateway'), true)
  assert.equal(providerIdIsValid('Custom-Gateway'), true)
  assert.equal(providerIdIsValid('../../escape'), false)
  assert.equal(providerIdIsValid('custom.yml'), false)
  assert.deepEqual(buildCreateProviderPayload({
    id: ' Custom-Gateway ',
    label: ' 自定义网关 ',
    base_url: ' https://gateway.example/v1 ',
    api_key: ' write-only-key ',
    default_model: ' model-a ',
    models_url: ' ',
    models_text: 'model-b\nmodel-c, model-b',
  }), {
    id: 'custom-gateway',
    label: '自定义网关',
    base_url: 'https://gateway.example/v1',
    api_key: 'write-only-key',
    default_model: 'model-a',
    models: ['model-b', 'model-c'],
  })
})

test('chooses a safe replacement provider without selecting the deleted id', () => {
  const providers = [{ id: 'volcano' }, { id: 'qianwen' }, { id: 'openai' }]
  assert.equal(replacementProviderId('qianwen', providers, 'volcano'), 'volcano')
  assert.equal(replacementProviderId('volcano', providers, 'volcano'), 'qianwen')
  assert.equal(replacementProviderId('only', [{ id: 'only' }], 'only'), '')
})

test('builds and recognizes editable provider metadata without connection fields', () => {
  const provider = {
    id: 'custom',
    label: 'Custom Provider',
    default_model: 'model-a',
    models: ['model-a', 'model-b'],
    static_models: ['model-b'],
    key_configured: true,
  }
  const draft = createProviderMetadataDraft(provider)
  assert.deepEqual(draft, {
    id: 'custom',
    label: 'Custom Provider',
    default_model: 'model-a',
    models_text: 'model-b',
  })
  const payload = buildUpdateProviderPayload({
    ...draft,
    label: ' Updated ',
    models_text: 'model-new\nmodel-extra, model-new',
  })
  assert.deepEqual(payload, {
    label: 'Updated',
    default_model: 'model-a',
    models: ['model-new', 'model-extra'],
  })
  assert.equal(providerMetadataMatches({
    ...provider,
    label: 'Updated',
    models: ['model-a', 'model-extra', 'model-new'],
    static_models: ['model-extra', 'model-new'],
  }, payload), true)
  assert.equal(Object.hasOwn(payload, 'api_key'), false)
  assert.equal(Object.hasOwn(payload, 'base_url'), false)
})
