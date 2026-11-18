<template>
  <section class="agent-cockpit" :class="{ 'agent-home': !session }">
    <div v-if="!session" class="agent-welcome">
      <span class="welcome-mark"><AppIcon name="language" :size="30" /></span>
      <h2>把视频交给我，<br />把理解留给你。</h2>
      <p>从一个链接开始，得到一份看得懂的字幕。</p>
    </div>

    <div v-if="session" class="agent-current-panel">
      <div class="agent-hero">
        <div class="agent-hero-copy">
          <div class="eyebrow">你的字幕任务</div>
          <h2>{{ itemLabel(session) }}</h2>
          <a v-if="sourceLink" class="agent-source-link" :href="sourceLink" target="_blank" rel="noreferrer"><AppIcon name="link" :size="14" />查看原视频</a>
        </div>
        <div class="agent-live-chip" :class="session?.status || 'idle'">
          <span></span>
          <b>{{ session ? statusLabel : '无当前任务' }}</b>
        </div>
      </div>

      <div class="toolbar agent-current-actions">
        <button class="secondary mini" type="button" @click="$emit('new-task')"><AppIcon name="compose" :size="15" />新建任务</button>
        <button v-if="session?.retryable" class="secondary mini" type="button" @click="$emit('retry-agent')">重试当前阶段</button>
        <button v-if="session?.cancellable" class="danger secondary mini" type="button" @click="$emit('cancel-agent')">中断</button>
      </div>

      <div class="agent-response-heading"><span class="assistant-avatar"><AppIcon name="language" :size="20" /></span><b>ReiboSub</b><span v-if="!operationStatus">{{ phaseLabel }}</span></div>

      <div v-if="operationStatus" class="agent-operation-status" role="status" aria-live="polite">
        <span class="agent-operation-spinner" aria-hidden="true"></span>
        <div>
          <b>{{ operationStatus.title }}</b>
          <p>{{ operationStatus.message }}</p>
          <details v-if="operationStatus.detail"><summary>进度详情</summary><small>{{ operationStatus.detail }}</small></details>
        </div>
      </div>

      <div v-if="session?.question?.kind" class="agent-question">
        <div class="question-pulse">待你处理</div>
        <h3>{{ session.question.title || '需要确认' }}</h3>
        <p>{{ session.question.message }}</p>
        <div v-if="session.question.kind === 'autonomous_verification_review'" class="autonomous-question">
          <details v-for="(issue, i) in session.question.verification_issues || []" :key="i">
            <summary>{{ issue.id ? `第 ${issue.id} 条` : '结构检查' }}<span v-if="issue.source_quote" class="issue-preview">{{ issue.source_quote.slice(0, 60) }}</span><span v-else>查看待核查问题</span></summary>
            <p>{{ issue.reason_zh }}</p>
            <p v-if="issue.source_quote">原文：{{ issue.source_quote }}</p>
            <p v-if="issue.translation_quote">译文：{{ issue.translation_quote }}</p>
          </details>
        </div>
        <div v-if="session.question.kind === 'autonomous_question'" class="autonomous-question">
          <p v-if="session.question.question_type === 'translation'">这是中文含义/译法的求证，不是重新识别原文。选择后只对这条继续复核，不会重翻整片。</p>
          <audio v-if="session.question.audio_path" controls preload="none" :src="`/api/file?path=${encodeURIComponent(session.question.audio_path)}`" aria-label="疑句原音" />
          <button v-for="candidate in session.question.candidate_details || []" :key="candidate.text" class="secondary" type="button"
            @click="$emit('answer-agent', { action: 'autonomous_reply', confirmed_text: candidate.text })">
            <b>{{ candidate.text }}</b><br /><small>{{ candidate.romanization }}</small><br /><span>{{ candidate.meaning_zh }}</span><br />确认采用
          </button>
          <input v-model="autonomousClue" placeholder="补一句线索，或说明你的字幕要求" aria-label="给自主Agent的线索" />
        </div>
        <div v-if="session.question.selected_subtitle" class="agent-selected">
          <span>字幕</span>
          <b>{{ session.question.selected_subtitle.label || session.question.selected_subtitle.lang }}</b>
        </div>
        <div v-if="session.question.candidate_subtitles?.length" class="agent-candidates">
          <span>可选字幕</span>
          <div class="candidate-list">
            <b v-for="item in session.question.candidate_subtitles" :key="`${item.kind}-${item.lang}`">
              {{ item.label || `${item.lang} · ${item.kind}` }}
            </b>
          </div>
        </div>
        <div v-if="session.question.glossary_path" class="agent-selected">
          <span>Glossary</span>
          <b>{{ session.question.glossary_path }}</b>
        </div>
        <div v-if="session.question.reusable_ocr" class="agent-selected">
          <span>可复用 OCR</span>
          <b>{{ session.question.reusable_ocr.source_srt }}</b>
          <small>{{ reuseLabel(session.question.reusable_ocr) }}</small>
        </div>
        <div v-if="showOcrWorkbench" class="agent-inline-ocr-workbench">
          <div class="agent-inline-ocr-head">
            <div>
              <span>位置操作</span>
              <b>视频已下载，调整 OCR 字幕区域</b>
              <p>首帧会自动加载。直接拖动绿色字幕框，或拖右下角改变大小；调整会自动带入下一步 OCR。</p>
            </div>
            <span class="badge done">视频已就绪 · {{ currentSessionOcrPipeline.label }}</span>
          </div>
          <OcrCropControls
            title="OCR 字幕位置预览"
            :input-video="inputVideo"
            :ocr-scope="currentSessionOcrScope"
            :ocr-extraction-mode="currentSessionOcrPipeline.ocrExtractionMode"
            :ocr-shape-mode="currentSessionOcrPipeline.ocrShapeMode"
            :source-language="sourceLanguage"
            :ocr-language="ocrLanguage"
            :ocr-crop-top-ratio="ocrCropTopRatio"
            :ocr-crop-bottom-ratio="ocrCropBottomRatio"
            :ocr-crop-left-ratio="ocrCropLeftRatio"
            :ocr-crop-right-ratio="ocrCropRightRatio"
            :ocr-exclude-enabled="ocrExcludeEnabled"
            :ocr-exclude-top-ratio="ocrExcludeTopRatio"
            :ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
            :ocr-exclude-left-ratio="ocrExcludeLeftRatio"
            :ocr-exclude-right-ratio="ocrExcludeRightRatio"
            auto-load-preview
            @update:ocr-crop-top-ratio="$emit('update:ocrCropTopRatio', $event)"
            @update:ocr-crop-bottom-ratio="$emit('update:ocrCropBottomRatio', $event)"
            @update:ocr-crop-left-ratio="$emit('update:ocrCropLeftRatio', $event)"
            @update:ocr-crop-right-ratio="$emit('update:ocrCropRightRatio', $event)"
            @update:ocr-exclude-enabled="$emit('update:ocrExcludeEnabled', $event)"
            @update:ocr-exclude-top-ratio="$emit('update:ocrExcludeTopRatio', $event)"
            @update:ocr-exclude-bottom-ratio="$emit('update:ocrExcludeBottomRatio', $event)"
            @update:ocr-exclude-left-ratio="$emit('update:ocrExcludeLeftRatio', $event)"
            @update:ocr-exclude-right-ratio="$emit('update:ocrExcludeRightRatio', $event)"
          />
        </div>
        <div class="toolbar">
          <button
            v-if="isGlossaryQuestion"
            type="button"
            @click="$emit('open-glossary', { path: session.question.glossary_path, sessionId: session.id })"
          >
            打开 Glossary 审核
          </button>
          <button
            v-for="option in questionOptions"
            :key="option.action"
            type="button"
            :disabled="option.action === 'autonomous_reply' && !autonomousClue.trim()"
            :class="{ secondary: !primaryActions.includes(option.action) }"
            @click="$emit('answer-agent', option.action === 'autonomous_reply' ? { action: option.action, clue: autonomousClue } : option.action)"
          >
            {{ option.label }}
          </button>
          <button
            v-if="!isGlossaryQuestion && session.question.glossary_path"
            class="secondary"
            type="button"
            @click="$emit('open-glossary', { path: session.question.glossary_path, sessionId: session.id })"
          >
            打开 Glossary 审核
          </button>
        </div>
      </div>

      <div v-if="session && session.payload?.agent_mode !== 'autonomous'" class="agent-stage-card">
        <div class="agent-stage-head">
          <span>六阶段流程</span>
          <b>{{ phaseLabel }}</b>
        </div>
        <div class="agent-rail">
          <div v-for="step in steps" :key="step.id" class="agent-step" :class="step.state">
            <span>{{ step.index }}</span>
            <b>{{ step.label }}</b>
          </div>
        </div>
      </div>

      <div v-if="agentDecision || session?.result?.autonomous_actions?.length" class="agent-decision-card">
        <template v-if="agentDecision">
          <p>{{ agentDecision.summary }}</p>
          <details>
            <summary>计划与判断依据</summary>
            <p><b>{{ session.status === 'running' ? '当前行动' : '最近行动' }}：</b>{{ agentDecision.reason }}</p>
            <p v-if="agentDecision.nextCheck"><b>核对目标：</b>{{ agentDecision.nextCheck }}</p>
            <p>计划会随工具结果调整，不是固定执行流程。</p>
            <ol><li v-for="(item, i) in agentDecision.plan" :key="`plan-${i}`">{{ item }}</li></ol>
            <p v-for="(item, i) in agentDecision.unknowns" :key="`unknown-${i}`">待核查：{{ item }}</p>
            <small>依据记录：{{ agentDecision.evidenceRefs.join('、') }}</small>
          </details>
        </template>
        <p v-else>{{ session.result.autonomous_actions.at(-1)?.reason }}</p>
        <details><summary>已执行 {{ session.result.autonomous_actions?.length || 0 }} 项操作</summary>
          <ol><li v-for="(event, i) in session.result.autonomous_actions" :key="i">{{ autonomousToolLabels[event.tool] || event.tool }} · {{ event.reason }} · {{ event.status === 'done' ? '完成' : '未采用或未完成' }}</li></ol>
          <details v-for="(decision, i) in session.result.autonomous_decisions || []" :key="`decision-${i}`">
            <summary>{{ autonomousToolLabels[decision.tool] || decision.tool }} · {{ decision.status === 'done' ? '已执行' : '未完成' }}</summary>
            <p>{{ friendlyAgentText(decision.summary) }}</p>
            <p>预期核对：{{ friendlyAgentText(decision.next_check) }}</p>
            <small>依据：{{ decision.evidence_refs.map(evidenceRefLabel).join('、') }}</small>
          </details>
        </details>
      </div>
      <div v-if="session?.payload?.agent_mode === 'autonomous' && session?.result?.translated_srt" class="agent-decision-card agent-delivery-card">
        <div class="delivery-file-icon"><AppIcon name="log" :size="25" /></div>
        <h3>{{ session.status === 'done' ? (session.result.delivery_mode === 'existing_target_subtitle' ? '中文字幕已就绪（沿用现成字幕）' : '中文字幕已生成') : '已有字幕草稿' }}</h3>
        <p>{{ autonomousDraftMessage(session) }}</p>
        <p v-if="session.result.suppressed_cue_ids?.length">当前副本 {{ session.result.delivery_cue_count }} 条；已合并 {{ session.result.suppressed_cue_ids.length }} 条经独立复核确认的重复词尾空块，原稿和编号映射保留。检查记录沿用原稿编号。</p>
        <p v-if="session.result.input_video">视频已保存到本地素材库。</p>
        <div class="toolbar">
          <a class="button-link" :href="`/api/file?path=${encodeURIComponent(session.result.translated_srt)}`" download>下载中文字幕</a>
          <a v-if="session.result.source_srt" class="button-link secondary" :href="`/api/file?path=${encodeURIComponent(session.result.source_srt)}`" download>下载原文字幕</a>
          <a v-if="session.result.input_video" class="button-link secondary" :href="`/api/file?path=${encodeURIComponent(session.result.input_video)}`" download>下载视频</a>
        </div>
      </div>
      <details v-if="localReview" class="agent-decision-card agent-review-details">
        <summary>局部复核记录 · {{ localReview.decisions.length }} 条</summary>
        <p>只复核已授权条目，未重翻整片；未通过检查的修改不会写入。</p>
        <details v-for="row in localReview.decisions" :key="row.id">
          <summary>{{ row.suppressed_in_delivery ? '原字幕' : '字幕' }} {{ row.id }} · {{ row.suppressed_in_delivery ? '重复词尾已并入前句（仅交付副本）' : row.action === 'revise' ? '已局部修改' : row.action === 'keep' ? '保留当前译文' : '仍待确认，未修改' }}</summary>
          <p>原译：{{ row.before || '（空）' }}</p><p v-if="row.after !== row.before">修订：{{ row.after }}</p>
          <p>{{ row.reason_zh }}</p>
        </details>
      </details>
      <details v-if="session?.question?.kind !== 'autonomous_verification_review' && session?.result?.autonomous_verification?.status === 'complete' && session.result.autonomous_verification.issues?.length" class="agent-decision-card agent-review-details">
        <summary>检查结果 · {{ session.result.autonomous_verification.issues.length }} 处待复核</summary>
        <p v-if="session.result.autonomous_verification.structure">原文 {{ session.result.autonomous_verification.structure.source_count }} 条 · 中文 {{ session.result.autonomous_verification.structure.target_count }} 条</p>
        <details v-for="(issue, i) in session.result.autonomous_verification.issues.slice(0, 12)" :key="i">
          <summary>{{ issue.id ? `第 ${issue.id} 条：` : '' }}{{ issue.reason_zh }}</summary>
          <p v-if="issue.source_quote">原文：{{ issue.source_quote }}</p>
          <p v-if="issue.kind === 'empty_translation'">中文：当前为空，需要局部复核，不会因此重翻整片或重新对齐。</p>
          <p v-else-if="issue.translation_quote">中文：{{ issue.translation_quote }}</p>
        </details>
      </details>

      <div v-if="agentPlan && session?.payload?.agent_mode !== 'autonomous'" class="agent-decision-card">
        <div>
          <span>Agent 判断</span>
          <h3>{{ routeLabel }}</h3>
        </div>
        <p v-if="agentPlan.reasons?.length">{{ agentPlan.reasons[0] }}</p>
        <div v-if="detectedLanguage" class="agent-selected">
          <span>音源语言</span>
          <b>{{ detectedLanguage }}</b>
        </div>
        <div v-if="agentPlan.selected_subtitle" class="agent-selected">
          <span>推荐字幕</span>
          <b>{{ agentPlan.selected_subtitle.label || agentPlan.selected_subtitle.lang }}</b>
        </div>
        <div v-if="agentPlan.reference_subtitle" class="agent-selected">
          <span>参考字幕</span>
          <b>{{ agentPlan.reference_subtitle.label || agentPlan.reference_subtitle.lang }}</b>
        </div>
        <div v-if="candidateSubtitles.length" class="agent-candidates">
          <span>人工字幕候选</span>
          <div class="candidate-list">
            <b v-for="item in candidateSubtitles" :key="`${item.kind}-${item.lang}`">
              {{ item.label || `${item.lang} · ${item.kind}` }}
            </b>
          </div>
        </div>
      </div>

      <div v-if="status && statusClass === 'bad'" class="status agent-status" :class="statusClass" role="alert">{{ status }}</div>
    </div>

    <section v-if="!session" class="agent-launchpad agent-new-task" aria-label="新建字幕任务">
      <form class="agent-command" @submit.prevent="submitTask">
        <div class="agent-url-field">
          <label class="sr-only" for="agentUrl">YouTube 链接或视频 ID</label>
          <input id="agentUrl" :value="url" autocomplete="off" placeholder="粘贴 YouTube 链接，开始制作中文字幕…" @input="$emit('update:url', $event.target.value)" />
        </div>
        <div class="composer-controls">
          <label class="composer-select"><AppIcon name="spark" :size="16" /><span class="sr-only">处理模式</span><select aria-label="处理模式" :value="agentMode" @change="$emit('update:agentMode', $event.target.value)"><option value="autonomous">自主 Agent · 实验</option><option value="workflow">经典工作流</option></select></label>
          <label class="composer-select"><AppIcon name="language" :size="16" /><span class="sr-only">音源语言</span><select aria-label="音源语言" :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)"><option value="auto">自动识别语言</option><option value="korean">韩语</option><option value="japanese">日语</option><option value="english">英语</option><option value="chinese">中文</option></select></label>
        </div>
        <div class="agent-submit">
          <button type="submit" :disabled="starting || !url.trim()" :aria-label="starting ? '正在启动任务' : '开始制作字幕'" :title="starting ? '正在启动' : '开始制作字幕'">
            <span v-if="starting" class="agent-operation-spinner"></span><AppIcon v-else name="arrow" :size="23" />
          </button>
        </div>
      </form>

      <div v-if="agentMode !== 'autonomous'" class="agent-context-strip agent-basic-settings">
        <div class="agent-setting">
          <span>字幕目标</span>
          <div class="segmented">
            <button type="button" :class="{ active: embeddedSubtitleGoal === 'screen_subtitle' }" @click="$emit('update:embeddedSubtitleGoal', 'screen_subtitle')">复刻画面</button>
            <button type="button" :class="{ active: embeddedSubtitleGoal === 'full_speech' }" @click="$emit('update:embeddedSubtitleGoal', 'full_speech')">完整听译</button>
          </div>
        </div>
        <div class="agent-setting agent-pipeline-setting">
          <span>需要 OCR 时使用</span>
          <div class="segmented">
            <button type="button" :class="{ active: ocrPipelineVersion === 'v1' }" @click="$emit('update:ocrPipelineVersion', 'v1')">OCR 1.0（旧版）</button>
            <button type="button" :class="{ active: ocrPipelineVersion === 'v2' }" @click="$emit('update:ocrPipelineVersion', 'v2')">OCR 2.0（稳定）</button>
            <button type="button" :class="{ active: ocrPipelineVersion === 'v3' }" @click="$emit('update:ocrPipelineVersion', 'v3')">OCR 3.0（稳定）</button>
          </div>
          <p class="agent-pipeline-note">{{ activeOcrPipeline.description }}</p>
          <p class="agent-pipeline-note">用于整片 OCR 与 ASR + OCR 参考路线；“英文定轴 + 原声 OCR”保留独立流程，直接采用人工字幕时不会运行 OCR。</p>
        </div>
      </div>

      <details v-if="agentMode === 'autonomous'" class="agent-advanced-settings">
        <summary>补充要求与能力说明 <span v-if="extraHint.trim()" class="composer-hint-set">已填写</span></summary>
        <label>补充要求<input :value="extraHint" placeholder="例如：对白和画面配字都保留，不要节目水印" @input="$emit('update:extraHint', $event.target.value)" /></label>
        <p>无需选择测试区间；按整片处理。首版视频下载与重识别工具限1小时以内，较长素材可先尝试已有外挂字幕。</p>
        <p>Agent 会先检查现成中文字幕，按需使用 OCR 或 ASR。翻译前仍由你确认术语；视觉分析需要支持图片的模型。</p>
      </details>
      <details v-else class="agent-advanced-settings">
        <summary>高级设置：语言、内嵌字幕、任务提示与 OCR 裁框</summary>
        <div class="agent-context-strip">
          <div class="agent-setting">
            <span>内嵌字幕提示</span>
            <div class="segmented">
              <button type="button" :class="{ active: embeddedSubtitleHint === 'unknown' }" @click="$emit('update:embeddedSubtitleHint', 'unknown')">不清楚</button>
              <button type="button" :class="{ active: embeddedSubtitleHint === 'yes' }" @click="$emit('update:embeddedSubtitleHint', 'yes')">有</button>
              <button type="button" :class="{ active: embeddedSubtitleHint === 'no' }" @click="$emit('update:embeddedSubtitleHint', 'no')">没有</button>
            </div>
          </div>
          <div class="agent-setting">
            <span>音源语言</span>
            <select :value="sourceLanguage" @change="$emit('update:sourceLanguage', $event.target.value)">
              <option value="auto">自动</option>
              <option value="korean">韩语</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
              <option value="chinese">中文</option>
            </select>
          </div>
          <div class="agent-setting">
            <span>OCR 字幕语言</span>
            <select :value="ocrLanguage" @change="$emit('update:ocrLanguage', $event.target.value)">
              <option value="auto">跟随音源</option>
              <option value="korean">韩语</option>
              <option value="japanese">日语</option>
              <option value="english">英语</option>
              <option value="chinese">中文：只提取</option>
            </select>
          </div>
          <div v-if="ocrPipelineVersion === 'v1'" class="agent-setting">
            <span>OCR 模式</span>
            <div class="segmented">
              <button type="button" :class="{ active: ocrScope !== 'smart_full' }" @click="setOcrMode('limited')">限定区域</button>
              <button type="button" :class="{ active: ocrScope === 'smart_full' }" @click="setOcrMode('smart_full')">全屏辅助</button>
            </div>
          </div>
          <div v-if="inputVideo" class="agent-setting">
            <span>裁剪预设</span>
            <div class="segmented">
              <button type="button" :class="{ active: isCropPreset(0.58) }" @click="applyCropPreset(0.58)">底部</button>
              <button type="button" :class="{ active: isCropPreset(0.38) }" @click="applyCropPreset(0.38)">中下</button>
            </div>
          </div>
          <div class="agent-hint-field">
            <label for="agentHint">任务提示</label>
            <textarea id="agentHint" class="compact-textarea" :value="extraHint" placeholder="人名、节目名、固定译法" @input="$emit('update:extraHint', $event.target.value)" />
          </div>
        </div>

        <div v-if="inputVideo && !showOcrWorkbench" class="agent-ocr-workbench">
          <OcrCropControls
            title="OCR 裁剪预览"
            :input-video="inputVideo"
            :ocr-scope="effectiveOcrScope"
            :ocr-extraction-mode="activeOcrPipeline.ocrExtractionMode"
            :ocr-shape-mode="activeOcrPipeline.ocrShapeMode"
            :source-language="sourceLanguage"
            :ocr-language="ocrLanguage"
            :ocr-crop-top-ratio="ocrCropTopRatio"
            :ocr-crop-bottom-ratio="ocrCropBottomRatio"
            :ocr-crop-left-ratio="ocrCropLeftRatio"
            :ocr-crop-right-ratio="ocrCropRightRatio"
            :ocr-exclude-enabled="ocrExcludeEnabled"
            :ocr-exclude-top-ratio="ocrExcludeTopRatio"
            :ocr-exclude-bottom-ratio="ocrExcludeBottomRatio"
            :ocr-exclude-left-ratio="ocrExcludeLeftRatio"
            :ocr-exclude-right-ratio="ocrExcludeRightRatio"
            @update:ocr-crop-top-ratio="$emit('update:ocrCropTopRatio', $event)"
            @update:ocr-crop-bottom-ratio="$emit('update:ocrCropBottomRatio', $event)"
            @update:ocr-crop-left-ratio="$emit('update:ocrCropLeftRatio', $event)"
            @update:ocr-crop-right-ratio="$emit('update:ocrCropRightRatio', $event)"
            @update:ocr-exclude-enabled="$emit('update:ocrExcludeEnabled', $event)"
            @update:ocr-exclude-top-ratio="$emit('update:ocrExcludeTopRatio', $event)"
            @update:ocr-exclude-bottom-ratio="$emit('update:ocrExcludeBottomRatio', $event)"
            @update:ocr-exclude-left-ratio="$emit('update:ocrExcludeLeftRatio', $event)"
            @update:ocr-exclude-right-ratio="$emit('update:ocrExcludeRightRatio', $event)"
          />
        </div>
        <div v-else class="empty">Agent 下载视频后，这里会显示抽帧裁框预览。</div>
      </details>
      <p v-if="status" class="status" :class="statusClass" role="status">{{ status }}</p>
    </section>

    <div v-if="!session" class="agent-home-shortcuts">
      <button type="button" @click="$emit('open-view', 'new-task')"><AppIcon name="download" :size="17" />我只想下载视频</button>
      <button type="button" @click="$emit('open-view', 'assets')"><AppIcon name="folder" :size="17" />使用本地素材</button>
    </div>
    <p v-if="!session" class="agent-home-note">视频会保存到素材库。人名和专名，仍由你来决定。</p>

    <details v-if="session" class="agent-session-strip agent-technical-details">
      <summary class="section-title">
        <h3>文件与运行详情</h3>
      </summary>
      <div class="agent-technical-stack">
        <div v-if="currentJobLabel" class="agent-monitor">
          <span>底层任务</span>
          <b>{{ currentJobLabel }}</b>
          <pre v-if="currentJobLogs.length">{{ currentJobLogs.join('\n') }}</pre>
        </div>

        <div v-if="resultItems.length" class="agent-outputs">
          <h3>产物</h3>
          <div v-for="item in resultItems" :key="item.label" class="path-row">
            <span>{{ item.label }}</span>
            <code>{{ item.value }}</code>
          </div>
        </div>

        <div class="agent-log">
          <h3>时间线</h3>
          <ol>
            <li v-for="(line, index) in sessionLogs" :key="`${index}-${line}`">{{ line }}</li>
          </ol>
        </div>
      </div>
    </details>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { currentLocalReview, autonomousDraftMessage, publicAgentDecision, friendlyAgentText, evidenceRefLabel } from '../autonomousPresentation.js'
import OcrCropControls from './OcrCropControls.vue'
import { getAgentOcrPipeline, inferAgentOcrPipelineVersion } from '../agentOcrPipeline.js'
import {
  agentOperationPresentation,
  buildAgentFlowSteps,
  presentAgentQuestionOptions,
  routeLabel as formatRouteLabel,
  sessionPhaseLabel,
  shouldShowAgentOcrWorkbench,
} from '../agentFlowPresentation.js'

const props = defineProps({
  agentMode: { type: String, default: 'workflow' },
  url: { type: String, default: '' },
  embeddedSubtitleHint: { type: String, default: 'unknown' },
  embeddedSubtitleGoal: { type: String, default: 'screen_subtitle' },
  sourceLanguage: { type: String, default: 'auto' },
  ocrLanguage: { type: String, default: 'auto' },
  ocrScope: { type: String, default: 'bottom' },
  ocrPipelineVersion: { type: String, default: 'v3' },
  inputVideo: { type: String, default: '' },
  ocrCropTopRatio: { type: Number, default: 0.58 },
  ocrCropBottomRatio: { type: Number, default: 0 },
  ocrCropLeftRatio: { type: Number, default: 0 },
  ocrCropRightRatio: { type: Number, default: 0 },
  ocrExcludeEnabled: { type: Boolean, default: false },
  ocrExcludeTopRatio: { type: Number, default: 0.04 },
  ocrExcludeBottomRatio: { type: Number, default: 0.82 },
  ocrExcludeLeftRatio: { type: Number, default: 0.76 },
  ocrExcludeRightRatio: { type: Number, default: 0.02 },
  extraHint: { type: String, default: '' },
  session: { type: Object, default: null },
  sessions: { type: Array, default: () => [] },
  starting: { type: Boolean, default: false },
  status: { type: String, default: '' },
  statusClass: { type: String, default: '' },
})

const emit = defineEmits([
  'update:agentMode',
  'update:url',
  'update:embeddedSubtitleHint',
  'update:embeddedSubtitleGoal',
  'update:sourceLanguage',
  'update:ocrLanguage',
  'update:ocrScope',
  'update:ocrPipelineVersion',
  'update:ocrCropTopRatio',
  'update:ocrCropBottomRatio',
  'update:ocrCropLeftRatio',
  'update:ocrCropRightRatio',
  'update:ocrExcludeEnabled',
  'update:ocrExcludeTopRatio',
  'update:ocrExcludeBottomRatio',
  'update:ocrExcludeLeftRatio',
  'update:ocrExcludeRightRatio',
  'update:extraHint',
  'start-agent',
  'answer-agent',
  'cancel-agent',
  'retry-agent',
  'select-agent',
  'open-task-history',
  'open-glossary',
  'new-task',
  'open-view',
])
function submitTask() {
  if (!props.starting && props.url.trim()) emit('start-agent')
}
const sourceLink = computed(() => {
  const value = props.session?.result?.probe?.webpage_url || props.session?.payload?.url || ''
  try { const parsed = new URL(value); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : '' } catch { return '' }
})
const autonomousClue = ref('')
const localReview = computed(() => currentLocalReview(props.session?.result))
const agentDecision = computed(() => publicAgentDecision(props.session?.result))
watch(() => [props.session?.id, props.session?.question?.message], () => { autonomousClue.value = '' })

function setOcrMode(mode) {
  emit('update:ocrScope', mode === 'smart_full' ? 'smart_full' : 'bottom')
}

function applyCropPreset(topRatio) {
  emit('update:ocrCropTopRatio', topRatio)
  emit('update:ocrCropBottomRatio', 0)
}

function isCropPreset(topRatio) {
  return Math.abs(Number(props.ocrCropTopRatio || 0) - topRatio) < 0.005
}

const activeOcrPipeline = computed(() => getAgentOcrPipeline(props.ocrPipelineVersion))
const effectiveOcrScope = computed(() => ['v2', 'v3'].includes(props.ocrPipelineVersion) ? 'bottom' : props.ocrScope)
const currentSessionOcrPipelineVersion = computed(() => inferAgentOcrPipelineVersion(props.session?.payload || {}))
const currentSessionOcrPipeline = computed(() => getAgentOcrPipeline(currentSessionOcrPipelineVersion.value))
const currentSessionOcrScope = computed(() => (
  ['v2', 'v3'].includes(currentSessionOcrPipelineVersion.value)
    ? 'bottom'
    : (props.session?.payload?.ocr_scope || props.ocrScope)
))

const statusLabel = computed(() => {
  if (!props.session) return ''
  if (props.session.status === 'running') return '运行中'
  if (props.session.status === 'waiting') return '等待确认'
  if (props.session.status === 'done') return '完成'
  if (props.session.status === 'failed') return '失败'
  if (props.session.status === 'cancelled') return '已取消'
  return props.session.status
})

const phaseLabel = computed(() => {
  const phase = props.session?.phase || ''
  if (phase.startsWith('autonomous_')) return autonomousToolLabels[phase.slice(11)] || '自主检查与工具执行'
  return sessionPhaseLabel(phase)
})
const autonomousToolLabels = { decide: '判断下一步', planner: '检查下一步决策', probe: '检查链接', download: '下载视频', captions: '取得外挂字幕', sample_frames: '抽帧观察',
  analyze_frames: '分析画面', ocr_trial: '试跑OCR与遮罩', ocr: '提取画面字幕', asr: '听取音频', detect_language: '判断音源语言',
  select_source: '选择原文', inspect: '检查原文', review_audio: '局部重听', patch: '修正原文', translate: '翻译字幕',
  verify: '检查译文', align: '校准时间', question: '需要一点线索', finish: '交付字幕',
  inspect_target: '检查现成中文字幕', deliver_target: '直接交付现成中文', ask_target: '确认现成字幕疑点', read_subtitles: '查看字幕上下文', review_target: '对照原文抽查现成中文', transcribe_clip: '局部音频取证', target_review: '确认现成字幕覆盖', target_caption_choice: '选择现成字幕处理方式',
  internal_recovery: '恢复验收状态', format_recovery: '恢复已确认的格式清理', review_scope: '暂停于局部复核边界', internal_error: '内部错误（字幕已保留）', verification_review: '已有具体疑点，未改稿',
  review_translation: '局部复核译文（不重翻整片）', ask_user: '询问具体字幕疑点', reuse_source: '复用既有原字幕', reuse_translation: '复用既有中文字幕',
  glossary: '准备Glossary，等待人工审核', human_glossary_review: '用户已审核Glossary' }

const primaryActions = ['use_recommended', 'start_hybrid_anchor_ocr', 'use_cached_ocr', 'download_video_for_preview', 'run_ocr', 'run_asr', 'run_asr_with_ocr', 'probe_audio_language']
const isGlossaryQuestion = computed(() => props.session?.phase === 'review_glossary' || props.session?.question?.kind === 'review_glossary')
const questionOptions = computed(() => presentAgentQuestionOptions(props.session))
const operationStatus = computed(() => agentOperationPresentation(props.session))
const showOcrWorkbench = computed(() => shouldShowAgentOcrWorkbench(props.session, props.inputVideo))

function sessionStatusLabel(status) {
  const labels = {
    running: '运行中',
    waiting: '等待审核/确认',
    done: '完成',
    failed: '失败',
    cancelled: '已中断',
  }
  return labels[status] || status || '未知'
}

function sessionGlossaryActionLabel(item) {
  return item?.status === 'done' ? '查看 Glossary' : '审核 Glossary'
}

function itemLabel(item) {
  const title = item.result?.probe?.title || item.payload?.url || 'Agent 任务'
  return String(title)
}

function reuseLabel(item) {
  const matchedBy = item.matched_by === 'url' ? '标准链接匹配' : '标题兼容匹配'
  return `${matchedBy} · ${item.job_id || '历史任务'}`
}

const agentPlan = computed(() => props.session?.result?.agent_plan || null)
const candidateSubtitles = computed(() => agentPlan.value?.candidate_subtitles || props.session?.question?.candidate_subtitles || [])
const detectedLanguage = computed(() => {
  const result = props.session?.result || {}
  if (!result.detected_source_language) return ''
  const confidence = result.detected_source_language_confidence
  if (confidence === undefined || confidence === null || confidence === '') return result.detected_source_language
  return `${result.detected_source_language} · ${(Number(confidence) * 100).toFixed(0)}%`
})

const routeLabel = computed(() => {
  const route = agentPlan.value?.route || ''
  return formatRouteLabel(route)
})

const steps = computed(() => buildAgentFlowSteps(props.session?.phase || 'created', props.session?.status || ''))

const resultItems = computed(() => {
  const result = props.session?.result || {}
  return [
    ['源字幕', result.source_srt],
    ['Glossary', result.glossary_path],
    ['中文字幕', result.translated_srt],
    ['视频', result.input_video],
    ['标准链接', result.normalized_url],
  ]
    .filter(([, value]) => value)
    .map(([label, value]) => ({ label, value }))
})

const currentJobLabel = computed(() => {
  const result = props.session?.result || {}
  if (!result.current_job_name) return ''
  return `${result.current_job_name} · ${result.current_job_status || 'running'}`
})

const currentJobLogs = computed(() => props.session?.result?.current_job_logs || [])
const sessionLogs = computed(() => props.session?.logs || ['等待任务启动'])
</script>
