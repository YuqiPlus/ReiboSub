import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SETTINGS_TASKS,
  applyDefaultProviderChange,
  applyTaskProviderChange,
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
  reconcileTaskModelBindings,
  replacementProviderId,
  resolvedProviderId,
  shouldFetchProviderModelsOnSelection,
  useSharedTextModel,
} from './settingsState.js'

test('defines every configurable LLM task once', () => {
  assert.deepEqual(
    SETTINGS_TASKS.map((item) => item.key),
    [
      'video_analysis',
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
    model: '',
  })
  assert.equal(Object.keys(result.tasks).length, 9)
  assert.deepEqual(result.tasks.subtitle_translation, { provider_profile: '', model: '' })
})

test('shared model survives saves, clears across providers and keeps vision separate on text unification', () => {
  const settings = normalizeSettings({ defaults: { provider_profile: 'one', model: 'main-model' }, tasks: {
    video_analysis: { provider_profile: 'vision', model: 'image-model' }, glossary: { model: 'custom' }, subtitle_translation: { provider_profile: 'two', model: 'other' },
  } })
  assert.equal(buildSettingsPayload(settings).defaults.model, 'main-model')
  const unified = useSharedTextModel(settings)
  assert.equal(unified.defaults.model, 'main-model')
  assert.deepEqual(unified.tasks.video_analysis, settings.tasks.video_analysis)
  assert.deepEqual(unified.tasks.subtitle_translation, { provider_profile: '', model: '' })
  assert.equal(settings.tasks.glossary.model, 'custom')
  assert.equal(applyDefaultProviderChange(settings, 'two').defaults.model, '')
  assert.equal(applyDefaultProviderChange(settings, 'one').defaults.model, 'main-model')
})

test('shared model follows fetched catalog validation without guessing model prefixes', () => {
  const settings = { defaults: { provider_profile: 'one', model: 'previous-vendor-model' } }
  assert.equal(reconcileTaskModelBindings(settings, [], {}).defaults.model, 'previous-vendor-model')
  assert.equal(reconcileTaskModelBindings(settings, [], { one: [] }).defaults.model, 'previous-vendor-model')
  assert.equal(reconcileTaskModelBindings(settings, [], { one: ['valid-model'] }).defaults.model, '')
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

test('changing the default provider clears only models inherited from the old default', () => {
  const settings = normalizeSettings({
    defaults: { provider_profile: 'volcano' },
    tasks: {
      glossary: { provider_profile: '', model: 'doubao-glossary' },
      subtitle_translation: { provider_profile: 'qianwen', model: 'qwen-plus' },
      title_translation: { provider_profile: '', model: 'doubao-title' },
    },
  })

  const changed = applyDefaultProviderChange(settings, 'openai')

  assert.equal(changed.defaults.provider_profile, 'openai')
  assert.deepEqual(changed.tasks.glossary, { provider_profile: '', model: '' })
  assert.deepEqual(changed.tasks.title_translation, { provider_profile: '', model: '' })
  assert.deepEqual(changed.tasks.subtitle_translation, {
    provider_profile: 'qianwen',
    model: 'qwen-plus',
  })
  assert.equal(settings.tasks.glossary.model, 'doubao-glossary')
})

test('changing a task provider clears its stale model, including when switching back to inherit', () => {
  const settings = normalizeSettings({
    defaults: { provider_profile: 'volcano' },
    tasks: {
      subtitle_translation: { provider_profile: 'qianwen', model: 'qwen-plus' },
    },
  })

  const explicit = applyTaskProviderChange(settings, 'subtitle_translation', 'openai')
  assert.deepEqual(explicit.tasks.subtitle_translation, {
    provider_profile: 'openai',
    model: '',
  })

  const inherited = applyTaskProviderChange(settings, 'subtitle_translation', '')
  assert.deepEqual(inherited.tasks.subtitle_translation, {
    provider_profile: '',
    model: '',
  })
  assert.equal(settings.tasks.subtitle_translation.model, 'qwen-plus')
})

test('keeps the model when toggling inherit versus the same effective provider', () => {
  const inherited = normalizeSettings({
    defaults: { provider_profile: 'volcano' },
    tasks: { glossary: { provider_profile: '', model: 'doubao-lite' } },
  })
  const explicit = applyTaskProviderChange(inherited, 'glossary', 'volcano')
  const backToInherited = applyTaskProviderChange(explicit, 'glossary', '')

  assert.deepEqual(explicit.tasks.glossary, {
    provider_profile: 'volcano',
    model: 'doubao-lite',
  })
  assert.deepEqual(backToInherited.tasks.glossary, {
    provider_profile: '',
    model: 'doubao-lite',
  })
})

test('reconciles stale task models by exact provider catalog membership', () => {
  const providers = [
    { id: 'volcano', default_model: 'doubao-pro', models: ['doubao-pro', 'doubao-lite'] },
    { id: 'openai', default_model: 'gpt-5.6-sol', models: ['gpt-5.6-sol'] },
    { id: 'manual', models: [] },
  ]
  const settings = {
    defaults: { provider_profile: 'volcano' },
    tasks: {
      glossary: { provider_profile: 'openai', model: 'doubao-lite' },
      subtitle_translation: { provider_profile: 'openai', model: 'gpt-5.6-sol' },
      asr_correction: { provider_profile: 'manual', model: 'private-model' },
    },
  }

  const reconciled = reconcileTaskModelBindings(settings, providers, {
    openai: ['gpt-5.4', 'gpt-5.6-sol'],
  })

  assert.equal(reconciled.tasks.glossary.model, '')
  assert.equal(reconciled.tasks.subtitle_translation.model, 'gpt-5.6-sol')
  assert.equal(reconciled.tasks.asr_correction.model, 'private-model')
  assert.equal(settings.tasks.glossary.model, 'doubao-lite')
})

test('preserves a remote model until its provider catalog has actually loaded', () => {
  const providers = [{
    id: 'openai',
    default_model: 'gpt-5.6-sol',
    models: ['gpt-5.6-sol'],
  }]
  const settings = {
    defaults: { provider_profile: 'openai' },
    tasks: { glossary: { provider_profile: 'openai', model: 'gpt-5.4' } },
  }

  assert.equal(reconcileTaskModelBindings(settings, providers, {}).tasks.glossary.model, 'gpt-5.4')
  assert.equal(
    reconcileTaskModelBindings(settings, providers, { openai: ['gpt-5.4', 'gpt-5.6-sol'] }).tasks.glossary.model,
    'gpt-5.4',
  )
  assert.equal(
    reconcileTaskModelBindings(settings, providers, { openai: ['gpt-5.6-sol'] }).tasks.glossary.model,
    '',
  )
})

test('reselecting the same provider keeps the selected model', () => {
  const settings = normalizeSettings({
    defaults: { provider_profile: 'volcano' },
    tasks: {
      glossary: { provider_profile: '', model: 'doubao-glossary' },
      subtitle_translation: { provider_profile: 'qianwen', model: 'qwen-plus' },
    },
  })

  assert.equal(applyDefaultProviderChange(settings, 'volcano').tasks.glossary.model, 'doubao-glossary')
  assert.equal(
    applyTaskProviderChange(settings, 'subtitle_translation', 'qianwen').tasks.subtitle_translation.model,
    'qwen-plus',
  )
})

test('uses a fetched remote catalog instead of mixing in stale profile fallbacks', () => {
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
    'doubao-seed-2-0-lite',
    'kimi-k2.6',
  ])
})

test('drops removed providers and keeps fetched catalogs authoritative', () => {
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
    volcano: ['doubao-seed-2-0-pro'],
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
  assert.equal(providerConnectionSourceLabel('local'), '网页保存')
  assert.equal(providerConnectionSourceLabel('env'), '旧环境变量（建议重新保存）')
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
