<template>
  <section class="panel translation-studio">
    <header class="studio-page-head"><div><span class="studio-kicker">翻译与转换</span><h2>让字幕更进一步</h2><p>翻译成中文、纠正原文，或换一种字幕格式。</p></div></header>
    <div class="studio-source-picker"><label for="sourceSrt">字幕文件<input id="sourceSrt" :value="sourceSrt" placeholder="选择或填写字幕文件路径" @input="$emit('update:sourceSrt', $event.target.value)" /></label><button class="secondary" @click="$emit('open-assets')"><AppIcon name="folder" :size="16" />从素材库选择</button></div>
    <nav class="studio-tabs operation-tabs" aria-label="字幕操作"><button v-for="operation in operations" :key="operation.id" type="button" :class="{ active: activeOperation === operation.id }" :aria-pressed="activeOperation === operation.id" @click="activeOperation = operation.id">{{ operation.label }}</button></nav>
    <div v-show="activeOperation !== 'convert'" class="translation-language-row"><label for="subtitleSourceLanguage">原文语言<select id="subtitleSourceLanguage" :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)"><option value="auto">自动识别</option><option value="korean">韩语</option><option value="japanese">日语</option><option value="english">英语</option><option value="chinese">中文</option></select></label><span>{{ activeOperation === 'correct' ? '纠正识别文本，保留原语言。' : '输出中文字幕。' }}</span></div>
    <div v-show="activeOperation === 'translate'" class="translation-operation-body">
      <div class="operation-intro"><AppIcon name="language" :size="24" /><div><h3>翻译为中文</h3><p>可先确认人名和固定译法，再开始翻译。</p></div></div>
      <details class="studio-disclosure translation-glossary"><summary>术语表（可选）<span>{{ glossaryPath.trim() ? '已选择文件' : '未选择' }}</span></summary><label for="glossaryPath">术语表文件<input id="glossaryPath" :value="glossaryPath" placeholder="填写已有术语表路径，或先生成草稿" @input="$emit('update:glossaryPath', $event.target.value)" /></label><div class="toolbar"><button class="secondary" :disabled="!sourceSrt.trim()" @click="$emit('generate-glossary')">从字幕生成术语表</button><button class="secondary" :disabled="!glossaryPath.trim()" @click="$emit('load-glossary')">打开术语审核</button></div></details>
      <details class="studio-disclosure translation-timing"><summary>翻译与时间轴<span>{{ timingLabel }}</span></summary><label for="subtitleTranslationMode">处理方式<select id="subtitleTranslationMode" :value="subtitleTranslationMode" @change="$emit('update:subtitleTranslationMode', $event.target.value)"><option value="translate_only">锁定时间轴：只翻译文本</option><option value="standard_cleanup">标准清理：修明显重复 / 残片</option><option value="readability_retime">强力精修：必要时优化阅读时长</option></select></label><p>作者字幕通常保留时间轴；OCR / ASR 字幕有残片或重复时，再选择清理。强力精修可能改变时间。</p></details>
    </div>
    <div v-show="activeOperation === 'correct'" class="translation-operation-body"><div class="operation-intro"><AppIcon name="audio" :size="24" /><div><h3>ASR 原文纠错</h3><p>纠正语音识别产生的错字，不会把原文翻译成中文。</p></div></div><p class="operation-notice">会使用所选语言、术语表和补充要求。请核对原文语言。</p><details class="studio-disclosure"><summary>纠错使用的术语表</summary><label for="correctionGlossaryPath">术语表文件<input id="correctionGlossaryPath" :value="glossaryPath" @input="$emit('update:glossaryPath', $event.target.value)" /></label><button class="secondary" :disabled="!glossaryPath.trim()" @click="$emit('load-glossary')">打开术语审核</button></details></div>
    <div v-show="activeOperation === 'convert'" class="translation-operation-body"><div class="operation-intro"><AppIcon name="log" :size="24" /><div><h3>转换字幕格式</h3><p>只转换格式，不调用翻译模型。</p></div></div><label class="conversion-format" for="subtitleConvertFormat">目标格式<select id="subtitleConvertFormat" :value="subtitleConvertFormat" @change="$emit('update:subtitleConvertFormat', $event.target.value)"><option value="srt">SRT</option><option value="vtt">WebVTT</option><option value="ass">ASS</option><option value="ssa">SSA</option><option value="bcc">Bilibili BCC</option><option value="json">JSON</option><option value="lrc">LRC</option><option value="txt">TXT</option></select></label><p class="operation-notice">常规播放器可选 SRT / VTT / ASS；BCC 用于 B 站字幕。</p></div>
    <details v-show="activeOperation !== 'convert'" class="studio-disclosure translation-hint"><summary>补充要求<span v-if="extraHint.trim()">已填写</span></summary><label for="extraHint">人名、术语或原文纠错要求<textarea id="extraHint" :value="extraHint" placeholder="例如：人名和节目名的固定译法。" @input="$emit('update:extraHint', $event.target.value)" /></label></details>
    <footer class="studio-save-bar operation-run-bar"><span>{{ activeOperation === 'convert' ? '格式转换不消耗模型额度。' : '使用设置页对应模块的模型服务。' }}</span><button :disabled="!sourceSrt.trim()" @click="runOperation">{{ activeOperation === 'convert' ? '转换格式' : activeOperation === 'correct' ? '纠正原文' : '开始翻译' }}</button></footer>
    <p v-if="status" class="operation-status" :class="statusClass" role="status">{{ status }}</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
const props = defineProps({
  sourceSrt: { type: String, default: '' },
  glossaryPath: { type: String, default: '' },
  extraHint: { type: String, default: '' },
  subtitleTranslationMode: { type: String, default: 'translate_only' },
  sourceLanguage: { type: String, default: 'auto' },
  subtitleConvertFormat: { type: String, default: 'vtt' },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits([
  'update:sourceSrt', 'update:glossaryPath', 'update:extraHint', 'update:subtitleTranslationMode', 'update:subtitleConvertFormat', 'update:sourceLanguage',
  'correct-asr', 'generate-glossary', 'load-glossary', 'translate-subtitle', 'convert-subtitle', 'open-assets',
])
const activeOperation = ref('translate')
const operations = [{ id: 'translate', label: '翻译为中文' }, { id: 'correct', label: '原文纠错' }, { id: 'convert', label: '格式转换' }]
const timingLabel = computed(() => ({ translate_only: '锁定时间轴', standard_cleanup: '标准清理', readability_retime: '优化阅读时长' }[props.subtitleTranslationMode] || props.subtitleTranslationMode))
function runOperation() {
  if (!props.sourceSrt.trim()) return
  emit({ translate: 'translate-subtitle', correct: 'correct-asr', convert: 'convert-subtitle' }[activeOperation.value])
}
</script>
