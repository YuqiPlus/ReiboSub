<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>字幕处理</h2>
        <p class="panel-subtitle">选择源字幕，决定是否生成 glossary，然后执行翻译。时间轴模式在这里统一控制。</p>
      </div>
      <span class="badge">SRT -> 中文 SRT</span>
    </div>

    <div class="grid2">
      <div>
        <label for="sourceSrt">源字幕路径</label>
        <input id="sourceSrt" :value="sourceSrt" placeholder="/path/to/Video_Translate/YoutubeDownloads/xxx.source.srt" @input="$emit('update:sourceSrt', $event.target.value)" />
      </div>
      <div>
        <label for="glossaryPath">Glossary 路径</label>
        <input id="glossaryPath" :value="glossaryPath" placeholder="configs/glossaries/xxx.draft.yaml" @input="$emit('update:glossaryPath', $event.target.value)" />
      </div>
    </div>

    <div class="mode-row">
      <label for="subtitleSourceLanguage">源字幕语言</label>
      <select id="subtitleSourceLanguage" :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)">
        <option value="auto">自动</option>
        <option value="korean">韩语</option>
        <option value="japanese">日语</option>
        <option value="english">英语</option>
        <option value="chinese">中文</option>
      </select>
      <span class="muted">影响 glossary 生成和 ASR 原文纠错；普通翻译会保留原时间轴。</span>
    </div>

    <div class="mode-row">
      <label for="subtitleTranslationMode">翻译处理模式</label>
      <select id="subtitleTranslationMode" :value="subtitleTranslationMode" @change="$emit('update:subtitleTranslationMode', $event.target.value)">
        <option value="translate_only">锁定时间轴：只翻译文本</option>
        <option value="standard_cleanup">标准清理：修明显重复/残片</option>
        <option value="readability_retime">强力精修：必要时优化阅读时长</option>
      </select>
      <span class="muted">作者上传字幕一般选锁定时间轴；OCR/ASR 字幕再考虑清理</span>
    </div>

    <div class="mode-row">
      <label for="subtitleConvertFormat">字幕格式转换</label>
      <select id="subtitleConvertFormat" :value="subtitleConvertFormat" @change="$emit('update:subtitleConvertFormat', $event.target.value)">
        <option value="srt">SRT</option>
        <option value="vtt">WebVTT</option>
        <option value="ass">ASS</option>
        <option value="ssa">SSA</option>
        <option value="bcc">Bilibili BCC</option>
        <option value="json">JSON</option>
        <option value="lrc">LRC</option>
        <option value="txt">TXT</option>
      </select>
      <span class="muted">BCC 是 B 站字幕格式；常规播放器优先用 SRT/VTT/ASS</span>
    </div>

    <div>
      <label for="extraHint">任务提示</label>
      <textarea id="extraHint" class="hint-box" :value="extraHint" placeholder="例如：视频里的人是朴宝英（박보영），节目名统一翻译为《黄金乐园》。" @input="$emit('update:extraHint', $event.target.value)" />
    </div>

    <div class="action-row">
      <button class="secondary" @click="$emit('correct-asr')">ASR 原文纠错</button>
      <button @click="$emit('generate-glossary')">生成 glossary 草稿</button>
      <button class="secondary" @click="$emit('load-glossary')">加载 glossary</button>
      <button class="warning" @click="$emit('translate-subtitle')">翻译字幕</button>
      <button class="secondary" @click="$emit('convert-subtitle')">转换格式</button>
    </div>
    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
defineProps({
  sourceSrt: { type: String, default: '' },
  glossaryPath: { type: String, default: '' },
  extraHint: { type: String, default: '' },
  subtitleTranslationMode: { type: String, default: 'translate_only' },
  sourceLanguage: { type: String, default: 'auto' },
  subtitleConvertFormat: { type: String, default: 'vtt' },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

defineEmits([
  'update:sourceSrt', 'update:glossaryPath', 'update:extraHint', 'update:subtitleTranslationMode', 'update:subtitleConvertFormat', 'update:sourceLanguage',
  'correct-asr', 'generate-glossary', 'load-glossary', 'translate-subtitle', 'convert-subtitle',
])
</script>
