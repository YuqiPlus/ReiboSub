<template>
  <section class="panel subtitle-editor">
    <div class="panel-head">
      <div>
        <h2>字幕精修</h2>
        <p class="panel-subtitle">修改文字、删除条目、合并碎片，保存为新的 edited.srt 或覆盖原字幕。</p>
      </div>
      <span class="badge" :class="dirty ? 'pending' : 'done'">{{ dirty ? '未保存' : '已同步' }}</span>
    </div>

    <div class="path-row subtitle-editor-path-row">
      <div>
        <label for="subtitleEditorPath">字幕文件</label>
        <input
          id="subtitleEditorPath"
          :value="subtitlePath"
          placeholder="/path/to/Video_Translate/YoutubeDownloads/.../xxx.zh.srt"
          @input="$emit('update:subtitlePath', $event.target.value)"
          @keydown.enter.prevent="$emit('load-subtitle')"
        />
      </div>
      <div class="toolbar editor-toolbar">
        <button class="secondary" :disabled="loading" @click="$emit('load-subtitle')">加载</button>
        <button class="warning" :disabled="loading || !cues.length" @click="$emit('save-subtitle')">覆盖保存</button>
        <button :disabled="loading || !cues.length" @click="$emit('save-subtitle-as')">另存 edited</button>
      </div>
    </div>

    <div class="toolbar editor-tools">
      <button class="secondary mini" :disabled="!cues.length" @click="$emit('strip-all-breaks')">全部去异常换行</button>
      <button class="secondary mini" :disabled="!cues.length" @click="$emit('strip-trailing-commas')">删除结尾逗号</button>
      <button class="secondary mini" :disabled="!cues.length" @click="$emit('detect-pair-issues')">检测半边符号</button>
      <button class="ghost mini" :disabled="!cues.length" @click="$emit('remove-empty')">删除空字幕</button>
      <button class="ghost mini" :disabled="!canUndo" @click="$emit('undo')">撤销上一步</button>
      <span class="muted">{{ cues.length }} 条字幕</span>
    </div>

    <div class="prefix-tool">
      <label for="subtitlePrefixNames">名前缀处理</label>
      <div class="prefix-tool-row">
        <input
          id="subtitlePrefixNames"
          :value="prefixNames"
          placeholder="朴宝英, 禧主, 小昱"
          @input="$emit('update:prefixNames', $event.target.value)"
          @keydown.enter.prevent="$emit('strip-prefixes')"
        />
        <button class="secondary mini" :disabled="!cues.length || !prefixNames.trim()" @click="$emit('strip-prefixes')">删除名前缀</button>
      </div>
      <p class="muted">只删除“名字 + 空格 / 冒号”的开头前缀，不删除“名字作为句子主语”的内容。</p>
    </div>

    <div v-if="pairIssues.length" class="pair-issue-panel">
      <div class="pair-issue-head">
        <b>半边符号待检查</b>
        <span>{{ pairIssues.length }} 处</span>
      </div>
      <div class="pair-issue-list">
        <article
          v-for="issue in pairIssues"
          :key="`${issue.uid}-${issue.missingSymbol}-${issue.type}`"
          class="pair-issue-item"
          :class="{ active: focusedCueUid === issue.uid }"
        >
          <div>
            <b>#{{ issue.cueNumber }} · {{ issue.start_time || '--' }} → {{ issue.end_time || '--' }}</b>
            <span>{{ issue.type === 'missing_close' ? '缺右符号' : '缺左符号' }}：{{ issue.missingSymbol }} · {{ issue.pairName }}</span>
            <p>{{ issue.text }}</p>
          </div>
          <div class="pair-issue-actions">
            <button class="secondary mini" type="button" @click="$emit('focus-pair-issue', issue.uid)">定位</button>
            <button class="ghost mini" type="button" @click="$emit('copy-pair-symbol', issue.missingSymbol)">复制 {{ issue.missingSymbol }}</button>
            <button class="ghost mini" type="button" @click="$emit('resolve-pair-issue', issue)">标记已处理</button>
          </div>
        </article>
      </div>
    </div>

    <div v-if="!cues.length" class="asset-list empty">还没有加载字幕。</div>
    <div v-else class="subtitle-edit-list">
      <article
        v-for="(cue, index) in cues"
        :key="cue.uid"
        class="subtitle-edit-item"
        :class="{ focused: focusedCueUid === cue.uid }"
        :data-subtitle-cue="cue.uid"
      >
        <div class="subtitle-edit-index">
          <b>{{ index + 1 }}</b>
          <span>{{ cue.start_time }} → {{ cue.end_time }}</span>
        </div>
        <div class="subtitle-edit-fields">
          <div class="time-grid">
            <div>
              <label>开始</label>
              <input
                :value="cue.start_time"
                @input="$emit('update-cue', { uid: cue.uid, patch: { start_time: $event.target.value } })"
              />
            </div>
            <div>
              <label>结束</label>
              <input
                :value="cue.end_time"
                @input="$emit('update-cue', { uid: cue.uid, patch: { end_time: $event.target.value } })"
              />
            </div>
          </div>
          <textarea
            rows="3"
            :data-subtitle-textarea="cue.uid"
            :value="cue.text"
            @input="$emit('update-cue', { uid: cue.uid, patch: { text: $event.target.value } })"
          />
        </div>
        <div class="subtitle-edit-actions">
          <button class="ghost mini" :disabled="index === 0" @click="$emit('merge-prev', cue.uid)">并上</button>
          <button class="ghost mini" :disabled="index === cues.length - 1" @click="$emit('merge-next', cue.uid)">并下</button>
          <button class="secondary mini" @click="$emit('strip-breaks', cue.uid)">去换行</button>
          <button class="danger secondary mini" @click="$emit('delete-cue', cue.uid)">删除</button>
        </div>
      </article>
    </div>

    <div class="status" :class="statusClass">{{ status }}</div>
  </section>
</template>

<script setup>
defineProps({
  subtitlePath: { type: String, default: '' },
  cues: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  dirty: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  prefixNames: { type: String, default: '' },
  canUndo: { type: Boolean, default: false },
  pairIssues: { type: Array, default: () => [] },
  focusedCueUid: { type: String, default: '' },
})

defineEmits([
  'update:subtitlePath',
  'update:prefixNames',
  'load-subtitle',
  'save-subtitle',
  'save-subtitle-as',
  'update-cue',
  'delete-cue',
  'merge-prev',
  'merge-next',
  'strip-breaks',
  'strip-all-breaks',
  'strip-trailing-commas',
  'detect-pair-issues',
  'focus-pair-issue',
  'copy-pair-symbol',
  'resolve-pair-issue',
  'remove-empty',
  'strip-prefixes',
  'undo',
])
</script>
