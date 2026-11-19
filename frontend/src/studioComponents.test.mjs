import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'

let server
before(async () => {
  server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [vue()], server: { middlewareMode: true, watch: null }, appType: 'custom' })
})
after(async () => { await server?.close() })

async function render(name, props) {
  const { default: component } = await server.ssrLoadModule(`/src/components/${name}.vue`)
  return renderToString(createSSRApp({ render: () => h(component, props) }))
}

test('quiet header retains an accessible sidebar toggle without global counters', async () => {
  const html = await render('HeaderBar', { title: '字幕助手', sidebarOpen: true })
  assert.match(html, /字幕助手/)
  assert.match(html, /aria-controls="main-sidebar"/)
  assert.match(html, /aria-expanded="true"/)
  assert.doesNotMatch(html, /topbar-metrics|metric-chip/)
})

test('new task is a real link composer with optional settings, not a fake chat', async () => {
  const html = await render('AgentSessionPanel', { agentMode: 'autonomous', url: '', status: '请输入链接', statusClass: 'bad' })
  assert.match(html, /把视频交给我/)
  assert.match(html, /<form/)
  assert.match(html, /id="agentUrl"/)
  assert.match(html, /type="submit" disabled/)
  assert.match(html, /我只想下载视频/)
  assert.match(html, /请输入链接/)
  assert.doesNotMatch(html, /暂无运行中|六阶段流程|本次服务运行记录/)
})

test('active task preserves question, draft links and diagnostics without a second composer', async () => {
  const html = await render('AgentSessionPanel', { session: {
    id: 'safe-fixture', status: 'waiting', phase: 'autonomous_verification_review', payload: { agent_mode: 'autonomous', url: 'javascript:alert(1)' },
    question: { kind: 'autonomous_verification_review', title: '尚有疑点', message: '尚未验收', verification_issues: [{ id: 7, source_quote: '원문', reason_zh: '局部核查' }] },
    result: { translated_srt: '/example/zh.srt', source_srt: '/example/source.srt' },
  } })
  assert.match(html, /尚有疑点/)
  assert.match(html, /第 7 条/)
  assert.match(html, /下载中文字幕/)
  assert.match(html, /文件与运行详情/)
  assert.doesNotMatch(html, /id="agentUrl"|href="javascript:/)
})

test('classic workflow controls remain available', async () => {
  const html = await render('AgentSessionPanel', { agentMode: 'workflow', url: 'example', ocrPipelineVersion: 'v3' })
  assert.match(html, /OCR 3.0（稳定）/)
  assert.match(html, /复刻画面/)
  assert.match(html, /高级设置/)
})

test('completed agent puts downloads before closed process and review disclosures', async () => {
  const html = await render('AgentSessionPanel', { session: {
    id: 'complete', status: 'done', phase: 'done', payload: { agent_mode: 'autonomous' },
    result: {
      probe: { title: '已经完成的视频' }, source_kind: 'ocr', translated_srt: '/sample/zh.srt', source_srt: '/sample/ko.srt', input_video: '/sample/video.mp4',
      autonomous_controller_version: 2, autonomous_decision: { summary: '冗长的最终决策', reason: '&#x5C40;部复核已完成' },
      autonomous_actions: [{ tool: 'finalize_screen_ocr', status: 'done', reason: '整理保存的原文' }],
      autonomous_verification: { structure: { target_count: 303 } },
      local_translation_review_current: true,
      local_translation_review: { decisions: [{ id: 136, action: 'keep', before: '保留字幕', after: '保留字幕', reason_zh: '核查依据' }] },
    },
  } })
  assert.ok(html.indexOf('下载中文字幕') < html.indexOf('处理过程'))
  assert.match(html, /303 条 · SRT/)
  assert.match(html, /原文字幕<\/a>/)
  assert.match(html, /核查依据/)
  assert.match(html, /整理内嵌字幕/)
  assert.doesNotMatch(html, /agent-current-summary|已执行 1 项操作|<h3>文件与运行详情/)
  assert.doesNotMatch(html, /<details[^>]*class="[^"]*(?:agent-activity-details|agent-review-details)[^"]*"[^>]*\bopen/)
  assert.match(html, /局部复核已完成/)
})

test('running task keeps its immediate decision visible above the closed history', async () => {
  const html = await render('AgentSessionPanel', { session: {
    id: 'running', status: 'running', phase: 'autonomous_decide', payload: { agent_mode: 'autonomous' },
    result: { autonomous_controller_version: 2, autonomous_decision: { summary: '正在检查画面中的字幕' } },
  } })
  assert.match(html, /class="agent-current-summary">正在检查画面中的字幕/)
  assert.match(html, /处理过程/)
  assert.doesNotMatch(html, /中文字幕已生成/)
})

test('navigation retains tools, settings and recent tasks with full accessible titles', async () => {
  const html = await render('SideNav', {
    activeView: 'glossary', items: [
      { id: 'agent', label: '字幕助手', group: '日常流程' },
      { id: 'glossary', label: '术语审核', group: '字幕工具' },
      { id: 'settings', label: '设置', group: '系统' },
    ], sessions: [{ id: 'one', status: 'waiting', result: { probe: { title: '<a>很长的标题</a>' } } }],
  })
  assert.match(html, /新建字幕任务/)
  assert.match(html, /<details open/)
  assert.match(html, /nav-footer/)
  assert.match(html, /aria-current="page"/)
  assert.match(html, /&lt;a&gt;很长的标题&lt;\/a&gt;/)
  assert.match(html, /待你确认/)
})

test('glossary keeps evidence playback and explicit approval while folding file metadata', async () => {
  const html = await render('GlossaryReviewPanel', {
    glossaryPath: '/example/glossary.yaml', reviewReady: true, agentReview: true,
    glossaryItems: [{ section: 'characters', index: 0, source: '이름', romanized: 'ireum', zh: '', reviewed: false, note: '保留的识别说明' }],
  })
  assert.match(html, /一起确认这些名字/)
  assert.match(html, /<details class="glossary-file-details studio-disclosure">/)
  assert.match(html, /播放证据片段/)
  assert.match(html, /保留的识别说明/)
  assert.match(html, /还有 1 条待确认/)
})

test('editor expands only one cue and keeps batch controls folded', async () => {
  const cues = [1, 2, 3].map(index => ({ uid: `cue-${index}`, text: `字幕 ${index}`, start_time: '00:00:01,000', end_time: '00:00:02,000' }))
  const html = await render('SubtitleEditorPanel', { cues, subtitlePath: '/sample/zh.srt', saveReady: true, canUndo: true })
  assert.equal((html.match(/data-subtitle-textarea=/g) || []).length, 1)
  assert.equal((html.match(/class="cue-summary"/g) || []).length, 3)
  assert.match(html, /后面新增/)
  assert.match(html, /另存副本/)
  assert.match(html, /覆盖原字幕/)
  assert.match(html, /<details class="editor-batch studio-disclosure">/)
  assert.doesNotMatch(html, /editor-batch[^>]*open/)
})

test('external cue focus opens the requested row rather than the first row', async () => {
  const cues = [1, 2].map(index => ({ uid: `cue-${index}`, text: `字幕 ${index}`, start_time: '00:00:01,000', end_time: '00:00:02,000' }))
  const html = await render('SubtitleEditorPanel', { cues, focusedCueUid: 'cue-2', saveReady: true })
  assert.match(html, /data-subtitle-textarea="cue-2"/)
  assert.doesNotMatch(html, /data-subtitle-textarea="cue-1"/)
})

test('library opens on searchable visual cards, not upload forms and file paths', async () => {
  const html = await render('AssetLibrary', { assets: { projects: [{ name: '示例视频', path: '/sample', videos: [{ path: '/sample/video.mp4' }], modified_at: 10 }], ocr_jobs: [] } })
  assert.match(html, /搜索素材/)
  assert.match(html, /打开素材：示例视频/)
  assert.match(html, /导入素材/)
  assert.doesNotMatch(html, /id="localVideo"|删除素材目录|library-import"/)
})

test('term context and romanization remain visible even when a recommendation exists', async () => {
  const html = await render('GlossaryReviewPanel', { reviewReady: true, glossaryItems: [{ section: 'characters', index: 0, source: '이름', romanized: 'ireum', suggested_zh: '名字', context_text: '证据原句', blind_candidate_zh: '原句参考译文' }] })
  assert.match(html, /ireum/)
  assert.match(html, /证据原句/)
  assert.match(html, /采用推荐：名字/)
  assert.doesNotMatch(html, /无推荐|原句参考译文已就绪/)
})

test('links provide direct download and preserve every OCR/cover option behind disclosures', async () => {
  const html = await render('VideoInputPanel', { url: 'https://youtube.com/watch?v=example', availableVideoFormats: [{ id: 'video-1', label: '2160p · WebM · AV1' }] })
  assert.match(html, /<form class="links-composer"/)
  assert.match(html, /type="submit"/)
  assert.match(html, /2160p · WebM · AV1/)
  assert.match(html, /查看字幕与视频信息/)
  assert.match(html, /封面与下载说明/)
  assert.match(html, /OCR 3.0 几何精修/)
  assert.match(html, /下载视频并运行 OCR/)
  assert.match(html, /<details class="link-tool-section link-tool-ocr-section"[^>]*>/)
  assert.doesNotMatch(html, /<details class="link-tool-section link-tool-ocr-section"[^>]*\bopen/)
})

test('probe result retains subtitles, title tools and source details without metric cards', async () => {
  const html = await render('VideoInfoPanel', { probe: { title: '示例视频', webpage_url: 'https://youtube.com/watch?v=example', subtitles: [{ lang: 'zh', kind: 'manual' }], agent_plan: { route: 'download_target_subtitle', selected_subtitle: { lang: 'zh', kind: 'manual' }, reasons: ['检测依据'] } } })
  assert.match(html, /下载推荐字幕/)
  assert.match(html, /下载字幕/)
  assert.match(html, /填入任务提示/)
  assert.match(html, /检测依据/)
  assert.doesNotMatch(html, /summary-grid|class="metric"/)
})

test('task cards surface stage status, artifacts and deletion while folding reruns and archives', async () => {
  const html = await render('TaskHistoryPanel', { tasks: [{ id: 'fixture', title: '历史任务', status: 'waiting', current_stage: 'glossary_review', run_generation: 2, stage_items: [{ id: 'glossary', status: 'waiting_review', glossary_path: '/sample/glossary.yaml' }, { id: 'translate', status: 'done', translated_srt: '/sample/zh.srt', can_rerun: true }], archived_runs: [{ generation: 1, artifacts: [{ kind: 'translated_srt', path: '/sample/old.srt' }] }] }] })
  assert.match(html, /继续任务/)
  assert.match(html, /打开中文字幕/)
  assert.match(html, /查看术语表/)
  assert.match(html, /<details class="history-task-details">/)
  assert.match(html, /从头重跑…/)
  assert.match(html, /重跑此阶段/)
  assert.match(html, /旧版中文字幕/)
  assert.match(html, /删除任务…/)
  assert.ok(html.indexOf('删除任务…') < html.indexOf('class="history-task-details"'))
  assert.match(html, /aria-label="各阶段状态"/)
  assert.match(html, /第 2 轮/)
})

test('media rows expose useful actions without needing to open the detail inspector', async () => {
  const html = await render('AssetLibrary', { assets: { projects: [
    { name: '带字幕的视频', path: '/one', source_type: 'youtube', videos: [{ path: '/one.mp4' }], subtitles: [{ path: '/one.zh.srt', role: 'translated' }] },
    { name: '尚未识别的视频', path: '/two', videos: [{ path: '/two.mp4' }] },
    { name: '音频素材', path: '/three', audios: [{ path: '/three.wav' }] },
  ] } })
  assert.equal((html.match(/class="library-card-actions"/g) || []).length, 3)
  assert.match(html, /载入项目/)
  assert.match(html, /精修字幕/)
  assert.match(html, /提取画面字幕/)
  assert.match(html, /语音识别/)
  assert.match(html, /文件与更多/)
  assert.match(html, /1 视频 · 1 字幕/)
  assert.doesNotMatch(html, /aria-label="所选素材详情"/)
})

test('running task deletion is visible but disabled, with real errors kept on failed cards', async () => {
  const html = await render('TaskHistoryPanel', { tasks: [
    { id: 'running', title: '正在处理', status: 'running', current_stage: 'autonomous_running', stage_items: [] },
    { id: 'failed', title: '失败任务', status: 'failed', current_stage: 'ocr_failed', stage_items: [{ id: 'ocr', status: 'failed', error: '具体失败原因' }] },
  ] })
  assert.match(html, /history-delete-task"[^>]*disabled[^>]*title="请先中断正在运行的任务"/)
  assert.match(html, /class="history-card-error"/)
  assert.match(html, /具体失败原因/)
})

test('settings keep four main model bindings and every extra module without exposing stored keys', async () => {
  const html = await render('SettingsPanel', { settings: { defaults: { provider_profile: 'sample' } }, providers: [{ id: 'sample', label: '示例服务', models: ['example-model'], key_configured: true }], selectedProviderId: 'sample', connection: { provider_id: 'sample', key_configured: true, api_key: 'must-not-be-rendered', key_write_allowed: true }, providerManagementAllowed: true })
  assert.match(html, /常用设置/)
  assert.match(html, /服务商管理/)
  assert.equal((html.match(/class="settings-model-row"/g) || []).length, 9)
  assert.match(html, /<details class="studio-disclosure settings-extra-models">/)
  assert.match(html, /名称与默认模型/)
  assert.match(html, /新增服务商/)
  assert.match(html, /删除当前服务商…/)
  assert.match(html, /type="password"/)
  assert.doesNotMatch(html, /must-not-be-rendered/)
})

test('failed task does not offer viewing a stale running stage as its main action', async () => {
  const html = await render('TaskHistoryPanel', { tasks: [{ id: 'failed', status: 'failed', current_stage: 'autonomous_failed', stage_items: [{ id: 'translate', status: 'running' }] }] })
  assert.match(html, /继续任务/)
  assert.match(html, /Agent 处理失败/)
  assert.doesNotMatch(html, /查看运行/)
})

test('a task awaiting user review offers continuation despite a stale running stage', async () => {
  const html = await render('TaskHistoryPanel', { tasks: [{ id: 'waiting', status: 'waiting', current_stage: 'autonomous_review_required', stage_items: [{ id: 'translate', status: 'running' }] }] })
  assert.match(html, /继续任务/)
  assert.match(html, /字幕疑点待复核/)
  assert.doesNotMatch(html, /查看运行/)
})

test('translation separates operations and retains all eight conversion formats and timing modes', async () => {
  const html = await render('TranslationFlow', { sourceSrt: '/sample/source.srt', glossaryPath: '/sample/terms.yaml', extraHint: '固定译法' })
  for (const text of ['翻译为中文', '原文纠错', '格式转换', '生成术语表', '打开术语审核', 'readability_retime', 'standard_cleanup', 'translate_only', 'WebVTT', 'Bilibili BCC', 'SSA', 'JSON', 'LRC', 'TXT', 'ASS', 'SRT']) assert(html.includes(text), text)
  assert.match(html, /translation-timing/)
  assert.match(html, /固定译法/)
})

test('video processing keeps transforms and both overlay layers without a duplicate page header', async () => {
  const html = await render('VideoOverlayPanel', { inputVideo: '/sample/video.mp4' })
  for (const text of ['调整画面，保留原片', '水平镜像翻转', '裁掉画面边缘', '设置最终输出尺寸', '水印', '遮 Logo', '重置贴图位置', '生成处理后视频']) assert(html.includes(text), text)
  assert.match(html, /<details class="studio-disclosure overlay-stickers">/)
  assert.doesNotMatch(html, /type="file"/)
})

test('OCR version and reuse tools remain separate, including every V2/V3 refinement action', async () => {
  const common = { has_ocr_boxes: true, has_tracks: true, has_machine_source: true, source_srt: '/sample/source.srt', v3_refined_srt: '/sample/refined.srt' }
  const html = await render('OcrDevPanel', { ocrExtractionMode: 'region_v3', debugFolders: [{ ...common, path: '/sample/v2', name: 'V2', ocr_lab_version: 'v2' }, { ...common, path: '/sample/v3', name: 'V3', ocr_lab_version: 'v3' }] })
  assert.equal((html.match(/class="[^"]*\blab-version-card\b[^"]*"/g) || []).length, 2)
  for (const text of ['2.0 从 JSON 重建', '3.0 几何精修', '3.0 文字 + 分层精修', '3.0 仅重跑分层', '2.0 分层精修', '直接 LLM 去噪', '采样帧率', '短闪段平滑', '精确时间轴']) assert(html.includes(text), text)
  assert.match(html, /<details class="studio-disclosure lab-advanced">/)
})

test('compact crop controls fold numeric adjustments without removing any drag or nudge tools', async () => {
  const compact = await render('OcrCropControls', { compact: true, ocrExcludeEnabled: true })
  assert.match(compact, /<details class="crop-tune-panel crop-tune-compact">/)
  for (const text of ['上移亮区', '缩小亮区', '减少排除框上边界', '关闭排除框']) {
    assert(compact.includes(text), text)
  }
  const original = await render('OcrCropControls', {})
  assert.doesNotMatch(original, /<details class="crop-tune-panel/)
})

test('ASR Lab exposes all four versions and experiments retain their bounded ranges', async () => {
  const html = await render('AsrLabPanel', { asrVersion: 'autonomous-experimental', inputVideo: '/sample/video.mp4' })
  assert.equal((html.match(/class="[^"]*\blab-version-card\b[^"]*"/g) || []).length, 4)
  for (const text of ['ASR 2.2', 'ASR 1.0', '多模型 Agent', '自主字幕 Agent', '每段5秒到3分钟', '最多3段', '添加测试区间']) assert(html.includes(text), text)
  assert.match(html, /片段1开始/)
})

test('ASR previous results keep their own version and every diagnostic download', async () => {
  const result = { asr_version: '2.0', source_srt: '/sample/source.srt', speaker_srt: '/sample/speaker.srt', raw_source_srt: '/sample/raw.srt', recovery_raw_source_srt: '/sample/recovery.srt', words_path: '/sample/words.json', recovery_words_path: '/sample/recovery-words.json', focused_words_path: '/sample/focused-words.json', segments_path: '/sample/segments.json', recovery_segments_path: '/sample/recovery-segments.json', focused_segments_path: '/sample/focused-segments.json', quality_path: '/sample/quality.json', transcript_text: '识别全文内容', suspected_missing_regions: [{ review_id: 'one', text: '候选', start: 1, end: 2 }] }
  const html = await render('AsrLabPanel', { asrVersion: '1.0', result })
  assert.match(html, /本次结果 · ASR 2.2/)
  for (const text of ['采纳', '忽略', '试听', '识别全文内容', 'Words JSON', '定向重听 Segments', '补漏 SRT', '带说话人 SRT', '全部产物、原始数据与路径']) assert(html.includes(text), text)
})
