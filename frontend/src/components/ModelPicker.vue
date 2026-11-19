<template>
  <div ref="root" class="model-picker" @focusout="onFocusOut">
    <button :id="id" ref="trigger" class="model-picker-trigger secondary" type="button" role="combobox"
      :aria-label="label" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="listId"
      :disabled="disabled" @click="toggle" @keydown.down.prevent="show" @keydown.up.prevent="show" @keydown.esc="close">
      <span class="model-picker-value" :class="{ placeholder: !modelValue }">{{ modelValue || emptyLabel }}</span>
      <AppIcon name="chevron" :size="15" />
    </button>
    <div v-if="open" class="model-picker-popover" :class="{ above }" :style="{ '--model-options-height': `${optionsHeight}px` }" @keydown.esc.stop.prevent="close">
      <label class="model-picker-search"><AppIcon name="search" :size="16" />
        <input ref="search" v-model="query" type="text" autocomplete="off" spellcheck="false" :aria-label="`搜索${label}`"
          role="combobox" aria-autocomplete="list" aria-expanded="true" :aria-controls="listId" :aria-activedescendant="`${listId}-${active}`"
          :placeholder="models.length ? '搜索模型名称' : '输入完整模型 ID'" @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)" @keydown.enter.prevent="choose(options[active]?.value)" />
      </label>
      <p v-if="loading" class="model-picker-notice" role="status">正在获取模型…</p>
      <p v-else-if="error" class="model-picker-notice">暂时无法获取列表，可使用已有模型或手动输入 ID。</p>
      <ul :id="listId" ref="list" role="listbox" :aria-label="label" class="model-picker-options">
        <li v-for="(option, index) in options" :id="`${listId}-${index}`" :key="option.value" role="option"
          :aria-selected="modelValue === option.value" :class="{ focused: active === index, chosen: modelValue === option.value }">
          <button type="button" tabindex="-1" @mousedown.prevent @click="choose(option.value)" @mousemove="active = index">
            <span><b>{{ option.label }}</b><small v-if="option.manual">手动指定，不保证服务商支持</small></span>
            <AppIcon v-if="modelValue === option.value" name="check" :size="16" />
          </button>
        </li>
      </ul>
      <p v-if="query && options.length === 1" class="model-picker-notice">没有匹配的模型。</p>
      <div class="model-picker-footer"><span>{{ models.length ? `${models.length} 个候选` : '暂无候选 · 可手填 ID' }}</span><button class="ghost mini" type="button" :disabled="loading" @click="$emit('refresh')">{{ loading ? '获取中' : '刷新列表' }}</button></div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
const props = defineProps({
  id: { type: String, default: undefined }, label: { type: String, default: '模型' }, modelValue: { type: String, default: '' },
  models: { type: Array, default: () => [] }, emptyLabel: { type: String, default: '跟随通用模型' },
  disabled: Boolean, loading: Boolean, error: { type: [String, Boolean], default: '' },
})
const emit = defineEmits(['update:modelValue', 'open', 'refresh'])
const root = ref(null), trigger = ref(null), search = ref(null), list = ref(null)
const open = ref(false), query = ref(''), active = ref(0), above = ref(false)
const optionsHeight = ref(270)
const listId = `model-list-${useId()}`
const options = computed(() => {
  const value = query.value.trim(), needle = value.toLocaleLowerCase()
  const candidates = [...new Set(props.models.filter(model => typeof model === 'string' && model.trim()))]
  const result = [{ value: '', label: props.emptyLabel }, ...candidates.filter(model => !needle || model.toLocaleLowerCase().includes(needle)).map(model => ({ value: model, label: model }))]
  if (!candidates.length && value && value.length <= 256 && !/[\x00-\x1f\x7f]/.test(value)) result.push({ value, label: `使用「${value}」`, manual: true })
  return result
})
watch([query, options], () => { active.value = query.value.trim() && options.value.length > 1 ? 1 : 0 })
watch(() => props.disabled, value => { if (value) open.value = false })
async function show() {
  if (props.disabled || open.value) return
  query.value = ''; active.value = 0
  const bounds = trigger.value?.getBoundingClientRect()
  const below = bounds ? window.innerHeight - bounds.bottom : 400
  above.value = Boolean(bounds && below < 330 && bounds.top > below)
  optionsHeight.value = Math.max(80, Math.min(270, (above.value ? bounds.top : below) - 130))
  open.value = true; emit('open')
  await nextTick(); search.value?.focus()
}
function toggle() { if (open.value) close(); else show() }
function close() { open.value = false; trigger.value?.focus() }
function choose(value) { if (typeof value !== 'string') return; emit('update:modelValue', value); close() }
async function move(direction) {
  active.value = (active.value + direction + options.value.length) % options.value.length
  await nextTick(); list.value?.children[active.value]?.scrollIntoView({ block: 'nearest' })
}
function onFocusOut(event) { if (!root.value?.contains(event.relatedTarget)) open.value = false }
function outside(event) { if (!root.value?.contains(event.target)) open.value = false }
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>
