<template>
  <section class="panel settings-panel">
    <div class="panel-head settings-head">
      <div>
        <h2>默认值与模型</h2>
        <p class="panel-subtitle">这些设置用于之后新建的任务，不会改写已经运行或等待审核的 Agent 任务。</p>
      </div>
      <span class="badge" :class="{ pending: dirty, done: !dirty }">{{ dirty ? '有未保存修改' : '已与保存配置同步' }}</span>
    </div>

    <div v-if="loading" class="empty loading-box">正在读取设置和服务配置…</div>

    <template v-else>
      <section class="settings-section settings-language-section">
        <div class="settings-section-head">
          <div>
            <span class="eyebrow">01 · 新任务</span>
            <h3>默认语言</h3>
          </div>
          <span class="muted">Agent 首页和字幕工具会以此作为初始值</span>
        </div>

        <div class="grid2 settings-language-grid">
          <div>
            <label for="settingsSourceLanguage">默认音源 / 原文语言</label>
            <select id="settingsSourceLanguage" v-model="draft.defaults.source_language">
              <option v-for="option in SOURCE_LANGUAGE_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <p class="muted settings-field-help">连续处理韩语或日语视频时，固定语言可以减少每次手动选择。</p>
          </div>
          <div>
            <label for="settingsOcrLanguage">默认 OCR 语言</label>
            <select id="settingsOcrLanguage" v-model="draft.defaults.ocr_language">
              <option value="auto">跟随音源语言</option>
              <option value="korean">韩语</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
              <option value="chinese">中文</option>
            </select>
            <p class="muted settings-field-help">保持“跟随”时，Agent 会把上方语言传给 OCR。</p>
          </div>
        </div>

        <div class="settings-readonly-row">
          <span>默认目标语言</span>
          <b>{{ targetLanguageLabel }}</b>
          <small>当前成品流程固定输出简体中文。</small>
        </div>
      </section>

      <section class="settings-section settings-provider-section">
        <div class="settings-section-head">
          <div>
            <span class="eyebrow">02 · 连接</span>
            <h3>默认服务配置</h3>
          </div>
          <span class="muted">连接信息可保存到服务器本地私密配置；本页永远不会回显密钥</span>
        </div>

        <div v-if="providers.length" class="settings-provider-grid">
          <div>
            <label for="settingsDefaultProvider">默认服务商</label>
            <select
              id="settingsDefaultProvider"
              :value="draft.defaults.provider_profile"
              @change="handleDefaultProviderChange"
            >
              <option
                v-if="draft.defaults.provider_profile && !providerById.has(draft.defaults.provider_profile)"
                :value="draft.defaults.provider_profile"
              >
                {{ draft.defaults.provider_profile }}（配置未加载）
              </option>
              <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                {{ providerDisplayName(provider) }}
              </option>
            </select>
          </div>

          <div class="settings-provider-connection">
            <label>连接状态</label>
            <div class="settings-connection-line">
              <span class="badge" :class="credentialBadgeClass">{{ credential.label }}</span>
              <span class="muted settings-provider-endpoint">连接信息在下方“管理服务商”中维护</span>
            </div>
          </div>

          <div class="settings-provider-actions">
            <label>模型列表</label>
            <button
              type="button"
              class="secondary"
              :disabled="!defaultProviderId || defaultProviderFetching"
              @click="requestModels(defaultProviderId)"
            >
              {{ defaultProviderFetching ? '正在请求…' : '获取远程模型' }}
            </button>
            <span class="muted">{{ defaultProviderModels.length ? `已可用 ${defaultProviderModels.length} 个模型` : '暂无列表，下方仍可手动填写' }}</span>
          </div>
        </div>

        <div v-else class="empty settings-provider-empty">
          还没有服务商。请在下方新增一个 OpenAI-compatible 服务商。
        </div>

        <div class="settings-provider-manager">
          <div class="settings-provider-manager-select">
            <label for="settingsManagedProvider">管理服务商</label>
            <select
              id="settingsManagedProvider"
              :value="selectedProviderId"
              :disabled="!providers.length || providerManaging"
              @change="handleManagedProviderChange"
            >
              <option v-if="!providers.length" value="">暂无服务商</option>
              <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                {{ providerDisplayName(provider) }} · {{ provider.id }}
              </option>
            </select>
            <p class="muted settings-field-help">这里只切换正在编辑的连接，不会修改默认服务商。</p>
          </div>
          <div class="settings-provider-manager-actions">
            <label>服务商结构</label>
            <div>
              <button
                type="button"
                class="secondary"
                :disabled="!providerManagementAllowed || providerManaging"
                @click="openCreateProvider"
              >
                新增服务商
              </button>
              <button
                type="button"
                class="secondary"
                :disabled="!providerManagementAllowed || providerManaging || !selectedProvider"
                @click="openEditProvider"
              >
                编辑当前
              </button>
              <button
                type="button"
                class="secondary settings-delete-provider"
                :disabled="!canDeleteSelectedProvider"
                @click="deleteSelectedProvider"
              >
                删除当前
              </button>
            </div>
            <p v-if="!providerManagementAllowed" class="settings-inline-warning">
              当前服务未开放 Provider 结构管理。
            </p>
            <p v-else-if="providers.length === 1" class="muted settings-field-help">至少保留一个服务商；请先新增再删除。</p>
          </div>
        </div>

        <div v-if="showCreateProvider" class="settings-provider-create" role="region" aria-label="新增服务商">
          <div class="settings-provider-create-head">
            <div>
              <b>新增 OpenAI-compatible 服务商</b>
              <p>先保存名称和连接；创建成功后会自动拉取模型，并留在这里选择默认模型。</p>
            </div>
            <button type="button" class="secondary mini" :disabled="providerManaging" @click="cancelCreateProvider">
              {{ createdProviderId ? '完成' : '取消' }}
            </button>
          </div>
          <div class="settings-provider-create-grid">
            <div>
              <label for="settingsNewProviderId">Provider ID</label>
              <input
                id="settingsNewProviderId"
                v-model.trim="newProviderDraft.id"
                autocomplete="off"
                spellcheck="false"
                placeholder="例如 siliconflow"
                :disabled="providerManaging || Boolean(createdProviderId)"
              />
              <p class="muted settings-field-help">仅限小写字母、数字、点、下划线和连字符。</p>
            </div>
            <div>
              <label for="settingsNewProviderLabel">显示名称</label>
              <input
                id="settingsNewProviderLabel"
                v-model.trim="newProviderDraft.label"
                autocomplete="off"
                placeholder="例如 SiliconFlow"
                :disabled="providerManaging || Boolean(createdProviderId)"
              />
            </div>
            <div>
              <label for="settingsNewProviderBaseUrl">API Base URL</label>
              <input
                id="settingsNewProviderBaseUrl"
                v-model.trim="newProviderDraft.base_url"
                type="url"
                inputmode="url"
                autocomplete="off"
                spellcheck="false"
                placeholder="https://api.example.com/v1"
                :disabled="providerManaging || Boolean(createdProviderId)"
              />
            </div>
            <div>
              <label for="settingsNewProviderApiKey">API Key <span class="muted">（可稍后填写）</span></label>
              <input
                id="settingsNewProviderApiKey"
                v-model="newProviderDraft.api_key"
                type="password"
                name="new-provider-api-key"
                autocomplete="new-password"
                spellcheck="false"
                placeholder="只写，不回显"
                :disabled="providerManaging || Boolean(createdProviderId)"
              />
            </div>
            <div>
              <label for="settingsNewProviderModelsUrl">模型列表 URL <span class="muted">（可选）</span></label>
              <input
                id="settingsNewProviderModelsUrl"
                v-model.trim="newProviderDraft.models_url"
                type="url"
                inputmode="url"
                autocomplete="off"
                spellcheck="false"
                placeholder="默认使用 Base URL + /models"
                :disabled="providerManaging || Boolean(createdProviderId)"
              />
              <p class="muted settings-field-help">通常留空，默认请求 Base URL 下的模型列表接口。</p>
            </div>
          </div>
          <div v-if="!createdProviderId" class="settings-provider-create-actions">
            <button type="button" :disabled="!canCreateProvider" @click="submitCreateProvider">
              {{ providerManaging ? '正在创建…' : '创建并获取模型' }}
            </button>
            <span v-if="newProviderDraft.id && !providerIdIsValid(newProviderDraft.id)" class="settings-inline-error">
              Provider ID 格式不正确。
            </span>
          </div>

          <div v-else class="settings-provider-default-model">
            <div class="settings-provider-create-head">
              <div>
                <b>服务商已创建，选择默认模型</b>
                <p>后续模块留空模型 ID 时，会使用这里保存的默认模型。</p>
              </div>
              <span class="badge done">连接已保存</span>
            </div>
            <div class="settings-model-input-row">
              <select
                v-if="createdProviderModels.length"
                id="settingsNewProviderModel"
                v-model="newProviderDraft.default_model"
                :disabled="providerManaging"
              >
                <option value="" disabled>请选择默认模型</option>
                <option v-for="model in createdProviderModels" :key="model" :value="model">{{ model }}</option>
              </select>
              <input
                v-else
                id="settingsNewProviderModel"
                v-model.trim="newProviderDraft.default_model"
                autocomplete="off"
                spellcheck="false"
                :placeholder="createdProviderFetching ? '正在获取模型…' : '获取失败时可手动填写模型 ID'"
                :disabled="providerManaging || createdProviderFetching"
              />
              <button
                type="button"
                class="secondary"
                :disabled="providerManaging || createdProviderFetching"
                @click="requestModels(createdProviderId)"
              >
                {{ createdProviderFetching ? '正在获取…' : (createdProviderModelError ? '重试获取' : '刷新模型') }}
              </button>
            </div>
            <p v-if="createdProviderModelError" class="settings-inline-error">
              模型列表获取失败：{{ createdProviderModelError }}。可以重试，也可以手动填写模型 ID。
            </p>
            <p v-else class="muted settings-field-help">
              {{ createdProviderModels.length ? `已获取 ${createdProviderModels.length} 个模型，请从列表中选择。` : '模型列表为空，可以手动填写。' }}
            </p>
            <div class="settings-provider-create-actions">
              <button
                type="button"
                :disabled="providerManaging || !createdProviderDefaultModelDirty"
                @click="submitCreatedProviderDefaultModel"
              >
                {{ providerManaging && pendingCreatedDefaultModel ? '正在保存…' : '保存默认模型' }}
              </button>
              <span v-if="pendingCreatedDefaultModel" class="muted">等待服务端保存…</span>
              <span v-else-if="createdProviderSavedModel" class="badge done">默认模型已保存</span>
            </div>
          </div>
        </div>

        <div v-if="showEditProvider && selectedProvider" class="settings-provider-create settings-provider-edit" role="region" aria-label="编辑服务商">
          <div class="settings-provider-create-head">
            <div>
              <b>编辑服务商资料</b>
              <p>修改名称、默认模型和静态模型列表。Provider ID 用于配置引用，保持不变；密钥和 API 地址继续在下方连接管理中修改。</p>
            </div>
            <span class="badge" :class="{ pending: editProviderDirty, done: !editProviderDirty }">
              {{ editProviderDirty ? '有未保存修改' : '已与服务配置同步' }}
            </span>
          </div>
          <div class="settings-provider-create-grid settings-provider-edit-grid">
            <div>
              <label for="settingsEditProviderId">Provider ID</label>
              <input
                id="settingsEditProviderId"
                :value="editProviderDraft.id"
                readonly
                spellcheck="false"
              />
              <p class="muted settings-field-help">ID 不可直接修改；如需更换 ID，请新增新服务商后迁移并删除旧项。</p>
            </div>
            <div>
              <label for="settingsEditProviderLabel">显示名称</label>
              <input
                id="settingsEditProviderLabel"
                v-model.trim="editProviderDraft.label"
                autocomplete="off"
                :disabled="providerManaging"
              />
            </div>
            <div>
              <label for="settingsEditProviderDefaultModel">默认模型 ID <span class="muted">（可留空）</span></label>
              <div class="settings-model-input-row">
                <select
                  v-if="selectedProviderModels.length"
                  id="settingsEditProviderDefaultModel"
                  v-model="editProviderDraft.default_model"
                  :disabled="providerManaging"
                >
                  <option value="">不设置默认模型</option>
                  <option v-for="model in selectedProviderModels" :key="model" :value="model">{{ model }}</option>
                </select>
                <input
                  v-else
                  id="settingsEditProviderDefaultModel"
                  v-model.trim="editProviderDraft.default_model"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="暂无候选，请手动填写模型 ID"
                  :disabled="providerManaging || selectedProviderFetching"
                />
                <button
                  type="button"
                  class="secondary mini"
                  :disabled="providerManaging || selectedProviderFetching"
                  @click="requestModels(selectedProviderId)"
                >
                  {{ selectedProviderFetching ? '获取中' : '刷新' }}
                </button>
              </div>
            </div>
            <div class="settings-provider-models-field">
              <label for="settingsEditProviderStaticModels">静态模型列表 <span class="muted">（可留空）</span></label>
              <textarea
                id="settingsEditProviderStaticModels"
                v-model="editProviderDraft.models_text"
                rows="5"
                spellcheck="false"
                placeholder="每行一个模型 ID，也可以用逗号分隔"
                :disabled="providerManaging"
              />
              <p class="muted settings-field-help">这里只维护手工模型候选；远程获取到的模型不会写回 Provider YAML。</p>
            </div>
          </div>
          <div class="settings-provider-create-actions">
            <button type="button" :disabled="providerManaging || !editProviderDirty" @click="submitEditProvider">
              {{ providerManaging ? '正在保存…' : '保存服务商资料' }}
            </button>
            <button type="button" class="secondary" :disabled="providerManaging" @click="cancelEditProvider">关闭</button>
          </div>
        </div>

        <div v-if="selectedProviderModelError" class="status bad settings-model-error">
          远程模型获取失败：{{ selectedProviderModelError }}。可以继续使用已保存的模型，或在下方直接填写模型 ID。
        </div>

        <div v-if="selectedProviderId" class="settings-connection-editor">
          <div class="settings-connection-editor-head">
            <div>
              <b>服务连接管理</b>
              <p>管理 {{ managedProviderName }} 在这台服务器上的密钥和 API 地址。</p>
            </div>
            <span v-if="connectionLoading" class="badge pending">正在读取</span>
            <div v-else class="settings-connection-badges">
              <span class="badge" :class="connectionCapabilityBadgeClass">{{ connectionCapabilityLabel }}</span>
              <span class="badge" :class="connectionCredentialBadgeClass">{{ connectionCredentialLabel }}</span>
            </div>
          </div>

          <div v-if="connectionError" class="status bad settings-connection-error">
            连接配置读取失败：{{ connectionError }}
          </div>

          <template v-else>
            <div class="settings-connection-summary">
              <div>
                <span>密钥状态</span>
                <b>{{ activeConnection.key_configured ? '已配置' : '未配置' }}</b>
                <small>来源：{{ keySourceLabel }}</small>
              </div>
              <div>
                <span>API 地址</span>
                <b>{{ activeConnection.base_url ? '已配置' : '未配置' }}</b>
                <small>来源：{{ baseUrlSourceLabel }}</small>
              </div>
              <div v-if="activeConnection.storage_path">
                <span>本地保存文件</span>
                <code>{{ activeConnection.storage_path }}</code>
                <small>已设为 Git 忽略</small>
              </div>
            </div>

            <div class="settings-connection-fields">
              <div>
                <label :for="`settingsApiKey-${selectedProviderId}`">API Key</label>
                <input
                  :id="`settingsApiKey-${selectedProviderId}`"
                  v-model="connectionDraft.api_key"
                  type="password"
                  :name="`provider-api-key-${selectedProviderId}`"
                  autocomplete="new-password"
                  spellcheck="false"
                  placeholder="留空表示不修改现有密钥"
                  :disabled="connectionLoading || connectionSaving || !activeConnection.key_write_allowed"
                />
                <p class="muted settings-field-help">为了安全，已保存的密钥不会返回浏览器；远程页面也只能写入新值。</p>
              </div>
              <div>
                <label :for="`settingsBaseUrl-${selectedProviderId}`">API Base URL</label>
                <input
                  :id="`settingsBaseUrl-${selectedProviderId}`"
                  v-model.trim="connectionDraft.base_url"
                  type="url"
                  inputmode="url"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="https://api.example.com/v1"
                  :disabled="connectionLoading || connectionSaving"
                />
                <p class="muted settings-field-help">
                  {{ activeConnection.endpoint_origin_change_allowed
                    ? '地址会保存在 provider_secrets.yaml；通常不需要手工编辑文件。'
                    : '远程页面可修改同一服务的路径；切换服务来源或清空 Base URL 需要本机 / SSH。' }}
                </p>
              </div>
              <div>
                <label :for="`settingsModelsUrl-${selectedProviderId}`">模型列表 URL <span class="muted">（可选）</span></label>
                <input
                  :id="`settingsModelsUrl-${selectedProviderId}`"
                  v-model.trim="connectionDraft.models_url"
                  type="url"
                  inputmode="url"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="默认使用 API Base URL + /models"
                  :disabled="connectionLoading || connectionSaving"
                />
                <p class="muted settings-field-help">只在服务商的模型列表端点不同时填写。</p>
              </div>
            </div>

            <div v-if="connectionEndpointChangeBlocked" class="settings-endpoint-local-warning" role="status">
              当前 URL 修改会切换服务来源，为避免把密钥发往错误地址，请在服务器本机页面或 SSH 端口转发中保存。密钥输入仍可保留，恢复原 URL 后即可单独保存密钥。
            </div>

            <div class="settings-connection-actions">
              <button
                type="button"
                :disabled="connectionLoading || connectionSaving || !connectionDirty || connectionEndpointChangeBlocked"
                @click="saveLocalConnection"
              >
                {{ connectionSaving ? '正在保存…' : (connectionEndpointChangeBlocked ? '跨来源地址需本机保存' : '保存连接') }}
              </button>
              <button
                type="button"
                class="secondary settings-clear-credential"
                :disabled="connectionLoading || connectionSaving || !activeConnection.key_write_allowed || !activeConnection.local_key_configured"
                @click="clearLocalApiKey"
              >
                清除密钥
              </button>
            </div>

          </template>

          <div class="settings-security-note">
            <b>安全提醒</b>
            <p>密钥会以明文保存在本机 Git 忽略文件中，请只在受信任的服务器上使用。远程打开本页时，请先通过 HTTPS 或 SSH 隧道访问，不要在明文 HTTP 连接中输入密钥。</p>
          </div>
        </div>
      </section>

      <section class="settings-section settings-model-section">
        <div class="settings-section-head">
          <div>
            <span class="eyebrow">03 · 模块</span>
            <h3>模型绑定</h3>
          </div>
          <span class="muted">有远程候选时直接选择；列表为空时才需要手动填写</span>
        </div>

        <div class="settings-model-list">
          <div v-for="task in SETTINGS_TASKS" :key="task.key" class="settings-model-row">
            <div class="settings-model-copy">
              <b>{{ task.label }}</b>
              <p>{{ task.description }}</p>
              <code>{{ task.key }}</code>
            </div>

            <div class="settings-model-provider">
              <label :for="`settingsProvider-${task.key}`">服务配置</label>
              <select
                :id="`settingsProvider-${task.key}`"
                :value="draft.tasks[task.key].provider_profile"
                @change="handleTaskProviderChange(task.key, $event)"
              >
                <option value="">跟随默认（{{ defaultProviderName }}）</option>
                <option
                  v-if="draft.tasks[task.key].provider_profile && !providerById.has(draft.tasks[task.key].provider_profile)"
                  :value="draft.tasks[task.key].provider_profile"
                >
                  {{ draft.tasks[task.key].provider_profile }}（配置未加载）
                </option>
                <option v-for="provider in providers" :key="provider.id" :value="provider.id">
                  {{ providerDisplayName(provider) }}
                </option>
              </select>
            </div>

            <div class="settings-model-input">
              <label :for="`settingsModel-${task.key}`">模型 ID</label>
              <div class="settings-model-input-row">
                <select
                  v-if="modelsForTask(task.key).length"
                  :id="`settingsModel-${task.key}`"
                  v-model="draft.tasks[task.key].model"
                  @focus="ensureTaskModelCatalog(task.key)"
                >
                  <option value="">使用服务商默认模型{{ defaultModelForTask(task.key) ? `（${defaultModelForTask(task.key)}）` : '' }}</option>
                  <option
                    v-if="taskModelAwaitingValidation(task.key)"
                    :value="draft.tasks[task.key].model"
                  >
                    {{ draft.tasks[task.key].model }}（等待刷新验证）
                  </option>
                  <option v-for="model in modelsForTask(task.key)" :key="model" :value="model">{{ model }}</option>
                </select>
                <input
                  v-else
                  :id="`settingsModel-${task.key}`"
                  v-model.trim="draft.tasks[task.key].model"
                  autocomplete="off"
                  placeholder="暂无候选，请手动填写模型 ID"
                  :disabled="isProviderFetching(providerIdForTask(task.key))"
                />
                <button
                  type="button"
                  class="secondary mini"
                  :disabled="!providerIdForTask(task.key) || isProviderFetching(providerIdForTask(task.key))"
                  @click="requestModels(providerIdForTask(task.key))"
                >
                  {{ isProviderFetching(providerIdForTask(task.key)) ? '获取中' : '刷新' }}
                </button>
              </div>
              <p v-if="modelErrorFor(providerIdForTask(task.key))" class="settings-inline-error">
                列表获取失败；没有本地候选时可手填，或点击“刷新”重试。
              </p>
              <p v-else class="muted settings-field-help">
                {{ modelsForTask(task.key).length ? `${modelsForTask(task.key).length} 个可选模型` : '无可选列表，请手动填写' }}
              </p>
            </div>
          </div>
        </div>
      </section>

      <div class="settings-save-bar">
        <div>
          <b>{{ dirty ? '修改尚未生效' : '当前配置已保存' }}</b>
          <p class="muted">保存后，新启动的 Agent、OCR 精修和字幕翻译任务会使用新配置。</p>
        </div>
        <button type="button" :disabled="saving || !dirty" @click="saveSettings">
          {{ saving ? '正在保存…' : '保存设置' }}
        </button>
      </div>

      <div v-if="status" class="status settings-status" :class="statusClass" aria-live="polite">{{ status }}</div>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import {
  SETTINGS_TASKS,
  SOURCE_LANGUAGE_OPTIONS,
  applyDefaultProviderChange,
  applyTaskProviderChange,
  buildSettingsPayload,
  normalizeSettings,
  providerCredentialState,
  providerDisplayName,
  providerModels,
  buildProviderConnectionPayload,
  buildCreateProviderPayload,
  buildUpdateProviderPayload,
  createProviderDraft,
  createProviderMetadataDraft,
  createProviderConnectionDraft,
  normalizeProviderConnection,
  providerConnectionHasChanges,
  providerConnectionEndpointChangeRequiresLocal,
  providerConnectionSourceLabel,
  providerIdIsValid,
  providerMetadataMatches,
  replacementProviderId,
  reconcileTaskModelBindings,
  resolvedProviderId,
  shouldFetchProviderModelsOnSelection,
} from '../settingsState.js'

const props = defineProps({
  settings: { type: Object, default: () => ({}) },
  providers: { type: Array, default: () => [] },
  modelsByProvider: { type: Object, default: () => ({}) },
  modelErrors: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  fetchingProviderId: { type: String, default: '' },
  selectedProviderId: { type: String, default: '' },
  providerManagementAllowed: { type: Boolean, default: false },
  providerManaging: { type: Boolean, default: false },
  connection: { type: Object, default: null },
  connectionLoading: { type: Boolean, default: false },
  connectionSaving: { type: Boolean, default: false },
  connectionError: { type: String, default: '' },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits([
  'save-settings',
  'fetch-models',
  'select-provider',
  'save-connection',
  'create-provider',
  'update-provider',
  'delete-provider',
])
const initialSettings = normalizeSettings(props.settings, props.providers)
const draft = ref(reconcileTaskModelBindings(initialSettings, props.providers, props.modelsByProvider))
const savedPayload = ref(JSON.stringify(buildSettingsPayload(initialSettings)))
const connectionDraft = ref(createProviderConnectionDraft())
const showCreateProvider = ref(false)
const newProviderDraft = ref(createProviderDraft())
const pendingCreatedProviderId = ref('')
const createdProviderId = ref('')
const pendingCreatedDefaultModel = ref('')
const showEditProvider = ref(false)
const editProviderDraft = ref(createProviderMetadataDraft())
const editProviderSavedPayload = ref('')
const pendingUpdatedProvider = ref(null)

watch(
  () => props.settings,
  (settings) => {
    const normalized = normalizeSettings(settings, props.providers)
    draft.value = reconcileTaskModelBindings(normalized, props.providers, props.modelsByProvider)
    savedPayload.value = JSON.stringify(buildSettingsPayload(normalized))
  },
  { deep: true },
)

watch(
  [() => props.providers, () => props.modelsByProvider],
  ([providers, modelsByProvider]) => {
    draft.value = reconcileTaskModelBindings(draft.value, providers, modelsByProvider)
  },
  { deep: true },
)

const providerById = computed(() => new Map(props.providers.map((provider) => [String(provider?.id || ''), provider])))
const defaultProviderId = computed(() => draft.value.defaults.provider_profile)
const defaultProvider = computed(() => providerById.value.get(defaultProviderId.value) || null)
const selectedProviderId = computed(() => String(props.selectedProviderId || '').trim() || defaultProviderId.value)
const selectedProvider = computed(() => providerById.value.get(selectedProviderId.value) || null)
const connectionMatchesSelection = computed(() => (
  String(props.connection?.provider_id || '') === selectedProviderId.value
))
const activeConnection = computed(() => normalizeProviderConnection(
  connectionMatchesSelection.value ? props.connection : {},
  selectedProvider.value || {},
))
const selectedProviderModels = computed(() => providerModels(selectedProviderId.value, props.providers, props.modelsByProvider))
const selectedProviderFetching = computed(() => isProviderFetching(selectedProviderId.value))
const selectedProviderModelError = computed(() => modelErrorFor(selectedProviderId.value))
const defaultProviderModels = computed(() => providerModels(defaultProviderId.value, props.providers, props.modelsByProvider))
const defaultProviderFetching = computed(() => isProviderFetching(defaultProviderId.value))
const createdProvider = computed(() => providerById.value.get(createdProviderId.value) || null)
const createdProviderModels = computed(() => providerModels(createdProviderId.value, props.providers, props.modelsByProvider))
const createdProviderFetching = computed(() => isProviderFetching(createdProviderId.value))
const createdProviderModelError = computed(() => modelErrorFor(createdProviderId.value))
const createdProviderSavedModel = computed(() => String(createdProvider.value?.default_model || '').trim())
const createdProviderDefaultModelDirty = computed(() => (
  Boolean(String(newProviderDraft.value.default_model || '').trim())
  && String(newProviderDraft.value.default_model || '').trim() !== createdProviderSavedModel.value
))
const credential = computed(() => providerCredentialState(defaultProvider.value))
const credentialBadgeClass = computed(() => ({
  done: credential.value.state === 'configured',
  pending: credential.value.state === 'unknown',
  bad: credential.value.state === 'missing',
}))
const defaultProviderName = computed(() => providerDisplayName(defaultProvider.value))
const managedProviderName = computed(() => providerDisplayName(selectedProvider.value))
const deleteReplacementId = computed(() => replacementProviderId(
  selectedProviderId.value,
  props.providers,
  defaultProviderId.value,
))
const canDeleteSelectedProvider = computed(() => (
  props.providerManagementAllowed
  && !props.providerManaging
  && Boolean(selectedProviderId.value)
  && Boolean(deleteReplacementId.value)
  && !selectedProviderFetching.value
))
const canCreateProvider = computed(() => (
  props.providerManagementAllowed
  && !props.providerManaging
  && !createdProviderId.value
  && providerIdIsValid(newProviderDraft.value.id)
  && Boolean(String(newProviderDraft.value.base_url || '').trim())
))
const editProviderPayload = computed(() => buildUpdateProviderPayload(editProviderDraft.value))
const editProviderDirty = computed(() => (
  JSON.stringify(editProviderPayload.value) !== editProviderSavedPayload.value
))
const targetLanguageLabel = computed(() => draft.value.defaults.target_language === 'zh' ? '简体中文' : draft.value.defaults.target_language)
const currentPayload = computed(() => buildSettingsPayload(draft.value))
const dirty = computed(() => JSON.stringify(currentPayload.value) !== savedPayload.value)
const connectionDirty = computed(() => providerConnectionHasChanges(connectionDraft.value, activeConnection.value))
const connectionEndpointChangeBlocked = computed(() => providerConnectionEndpointChangeRequiresLocal(
  connectionDraft.value,
  activeConnection.value,
))
const connectionCredentialLabel = computed(() => {
  if (props.connectionError) return '连接状态不可用'
  return activeConnection.value.key_configured ? '连接密钥已配置' : '缺少连接密钥'
})
const connectionCredentialBadgeClass = computed(() => ({
  done: !props.connectionError && activeConnection.value.key_configured,
  pending: Boolean(props.connectionError),
  bad: !props.connectionError && !activeConnection.value.key_configured,
}))
const connectionCapabilityLabel = computed(() => {
  if (!activeConnection.value.key_write_allowed) return '连接能力未加载'
  return activeConnection.value.endpoint_origin_change_allowed ? '本机完整管理' : '远程 Key 只写模式'
})
const connectionCapabilityBadgeClass = computed(() => ({
  done: activeConnection.value.key_write_allowed && activeConnection.value.endpoint_origin_change_allowed,
  pending: !activeConnection.value.key_write_allowed || !activeConnection.value.endpoint_origin_change_allowed,
}))
const keySourceLabel = computed(() => providerConnectionSourceLabel(
  activeConnection.value.key_source,
  { configured: activeConnection.value.key_configured },
))
const baseUrlSourceLabel = computed(() => providerConnectionSourceLabel(
  activeConnection.value.base_url_source,
  { configured: Boolean(activeConnection.value.base_url) },
))

watch(
  [() => props.connection, selectedProvider, () => props.connectionLoading],
  ([connection, provider, loading]) => {
    if (loading) {
      connectionDraft.value = createProviderConnectionDraft({}, provider || {})
      return
    }
    const matches = String(connection?.provider_id || '') === String(provider?.id || '')
    connectionDraft.value = createProviderConnectionDraft(matches ? connection : {}, provider || {})
  },
  { deep: true, immediate: true },
)

watch(
  () => props.providers,
  (providers) => {
    const pendingId = pendingCreatedProviderId.value
    if (pendingId && (providers || []).some((provider) => String(provider?.id || '') === pendingId)) {
      pendingCreatedProviderId.value = ''
      createdProviderId.value = pendingId
      const created = (providers || []).find((provider) => String(provider?.id || '') === pendingId)
      newProviderDraft.value.default_model = String(created?.default_model || '').trim()
    }

    const pendingModel = pendingCreatedDefaultModel.value
    if (pendingModel && createdProviderId.value) {
      const created = (providers || []).find((provider) => String(provider?.id || '') === createdProviderId.value)
      if (String(created?.default_model || '').trim() === pendingModel) {
        pendingCreatedDefaultModel.value = ''
      }
    }

    const pendingUpdate = pendingUpdatedProvider.value
    if (!pendingUpdate) return
    const updatedProvider = (providers || []).find((provider) => String(provider?.id || '') === pendingUpdate.id)
    if (!updatedProvider || !providerMetadataMatches(updatedProvider, pendingUpdate.payload)) return
    pendingUpdatedProvider.value = null
    editProviderDraft.value = createProviderMetadataDraft(updatedProvider)
    editProviderSavedPayload.value = JSON.stringify(buildUpdateProviderPayload(editProviderDraft.value))
  },
  { deep: true },
)

watch(selectedProviderId, (providerId, previousId) => {
  if (providerId === previousId) return
  pendingUpdatedProvider.value = null
  if (!showEditProvider.value) return
  const provider = providerById.value.get(providerId)
  editProviderDraft.value = createProviderMetadataDraft(provider || {})
  editProviderSavedPayload.value = JSON.stringify(buildUpdateProviderPayload(editProviderDraft.value))
})

function providerIdForTask(taskKey) {
  return resolvedProviderId(draft.value.tasks[taskKey], defaultProviderId.value)
}

function modelsForTask(taskKey) {
  return providerModels(providerIdForTask(taskKey), props.providers, props.modelsByProvider)
}

function defaultModelForTask(taskKey) {
  const provider = providerById.value.get(providerIdForTask(taskKey))
  return String(provider?.default_model || provider?.model_name || '').trim()
}

function providerCatalogLoaded(providerId) {
  return Object.prototype.hasOwnProperty.call(props.modelsByProvider || {}, providerId)
}

function taskModelAwaitingValidation(taskKey) {
  const model = String(draft.value.tasks[taskKey]?.model || '').trim()
  const providerId = providerIdForTask(taskKey)
  return Boolean(
    model
    && !providerCatalogLoaded(providerId)
    && !modelsForTask(taskKey).includes(model)
  )
}

function ensureTaskModelCatalog(taskKey) {
  const providerId = providerIdForTask(taskKey)
  if (!shouldFetchProviderModelsOnSelection(providerId, props.providers, props.modelsByProvider)) return
  requestModels(providerId)
}

function isProviderFetching(providerId) {
  return Boolean(providerId) && props.fetchingProviderId === providerId
}

function modelErrorFor(providerId) {
  if (!providerId) return ''
  const explicit = props.modelErrors?.[providerId]
  const embedded = props.modelsByProvider?.[providerId]?.error
  const value = explicit || embedded
  return typeof value === 'string' ? value : String(value?.error || value?.message || '')
}

function requestModels(providerId) {
  if (!providerId || isProviderFetching(providerId)) return
  emit('fetch-models', providerId)
}

function handleDefaultProviderChange(event) {
  const providerId = String(event?.target?.value || '').trim()
  draft.value = applyDefaultProviderChange(draft.value, providerId)
  emit('select-provider', providerId)
  if (!shouldFetchProviderModelsOnSelection(providerId, props.providers, props.modelsByProvider)) return
  requestModels(providerId)
}

function handleManagedProviderChange(event) {
  const providerId = String(event?.target?.value || '').trim()
  emit('select-provider', providerId)
  if (shouldFetchProviderModelsOnSelection(providerId, props.providers, props.modelsByProvider)) {
    requestModels(providerId)
  }
}

function handleTaskProviderChange(taskKey, event) {
  const selectedId = String(event?.target?.value || '').trim()
  draft.value = applyTaskProviderChange(draft.value, taskKey, selectedId)
  const providerId = selectedId || defaultProviderId.value
  if (!taskKey || !shouldFetchProviderModelsOnSelection(providerId, props.providers, props.modelsByProvider)) return
  requestModels(providerId)
}

function saveSettings() {
  if (props.saving || !dirty.value) return
  emit('save-settings', currentPayload.value)
}

function saveLocalConnection() {
  if (!selectedProviderId.value || props.connectionSaving || !connectionDirty.value || connectionEndpointChangeBlocked.value) return
  const payload = buildProviderConnectionPayload(connectionDraft.value, activeConnection.value)
  connectionDraft.value.api_key = ''
  emit('save-connection', { providerId: selectedProviderId.value, payload })
}

function clearLocalApiKey() {
  if (!selectedProviderId.value || props.connectionSaving || !activeConnection.value.key_write_allowed || !activeConnection.value.local_key_configured) return
  if (typeof window !== 'undefined' && !window.confirm('确定清除这个服务的密钥吗？清除后需要重新填写，才能获取模型或发起请求。')) return
  connectionDraft.value.api_key = ''
  emit('save-connection', {
    providerId: selectedProviderId.value,
    payload: { clear_api_key: true },
  })
}

function openCreateProvider() {
  if (!props.providerManagementAllowed || props.providerManaging) return
  showEditProvider.value = false
  pendingUpdatedProvider.value = null
  pendingCreatedProviderId.value = ''
  createdProviderId.value = ''
  pendingCreatedDefaultModel.value = ''
  newProviderDraft.value = createProviderDraft()
  showCreateProvider.value = true
}

function cancelCreateProvider() {
  if (props.providerManaging) return
  showCreateProvider.value = false
  pendingCreatedProviderId.value = ''
  createdProviderId.value = ''
  pendingCreatedDefaultModel.value = ''
  newProviderDraft.value = createProviderDraft()
}

function submitCreateProvider() {
  if (!canCreateProvider.value) return
  const payload = buildCreateProviderPayload(newProviderDraft.value)
  pendingCreatedProviderId.value = payload.id
  newProviderDraft.value.api_key = ''
  emit('create-provider', payload)
}

function submitCreatedProviderDefaultModel() {
  const providerId = createdProviderId.value
  const defaultModel = String(newProviderDraft.value.default_model || '').trim()
  if (!providerId || !defaultModel || props.providerManaging || !createdProviderDefaultModelDirty.value) return
  pendingCreatedDefaultModel.value = defaultModel
  emit('update-provider', {
    providerId,
    payload: { default_model: defaultModel },
  })
}

function openEditProvider() {
  if (!props.providerManagementAllowed || props.providerManaging || !selectedProvider.value) return
  showCreateProvider.value = false
  pendingCreatedProviderId.value = ''
  showEditProvider.value = true
  editProviderDraft.value = createProviderMetadataDraft(selectedProvider.value)
  editProviderSavedPayload.value = JSON.stringify(buildUpdateProviderPayload(editProviderDraft.value))
  pendingUpdatedProvider.value = null
}

function cancelEditProvider() {
  if (props.providerManaging) return
  showEditProvider.value = false
  pendingUpdatedProvider.value = null
  editProviderDraft.value = createProviderMetadataDraft()
  editProviderSavedPayload.value = ''
}

function submitEditProvider() {
  if (!selectedProviderId.value || props.providerManaging || !editProviderDirty.value) return
  const payload = editProviderPayload.value
  pendingUpdatedProvider.value = { id: selectedProviderId.value, payload }
  emit('update-provider', {
    providerId: selectedProviderId.value,
    payload,
  })
}

function deleteSelectedProvider() {
  if (!canDeleteSelectedProvider.value) return
  const providerId = selectedProviderId.value
  const replacementId = deleteReplacementId.value
  const replacement = providerById.value.get(replacementId)
  const message = `确定删除“${managedProviderName.value}”吗？\n\n本地 Provider 文件和对应私密密钥都会删除；正在使用它的默认值或模块会切换到“${providerDisplayName(replacement)}”。这不会撤销服务商后台的 API Key。`
  if (typeof window !== 'undefined' && !window.confirm(message)) return
  showEditProvider.value = false
  pendingUpdatedProvider.value = null
  emit('delete-provider', {
    providerId,
    replacementProviderId: replacementId,
  })
}
</script>
