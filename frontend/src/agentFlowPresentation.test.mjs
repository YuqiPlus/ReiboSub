import test from 'node:test'
import assert from 'node:assert/strict'

import {
  AGENT_FLOW_STAGES,
  AGENT_PHASE_PRESENTATIONS,
  agentOperationPresentation,
  buildAgentFlowSteps,
  getAgentPhasePresentation,
  presentAgentQuestionOptions,
  routeLabel,
  sessionPhaseLabel,
  shouldShowAgentOcrWorkbench,
} from './agentFlowPresentation.js'

test('uses six stable user-facing Agent stages', () => {
  assert.deepEqual(
    AGENT_FLOW_STAGES.map(({ id, label }) => [id, label]),
    [
      ['analyze', '分析素材'],
      ['decide', '确定路线'],
      ['source', '取得原文'],
      ['glossary', 'Glossary 审核'],
      ['translate', '翻译字幕'],
      ['deliver', '交付结果'],
    ],
  )
})

test('maps every current backend phase to a stable stage', () => {
  const expected = {
    created: 'analyze',
    probe: 'analyze',
    download_video_for_audio_probe: 'analyze',
    probe_audio_language: 'analyze',
    confirm_subtitle: 'decide',
    diagnose_ocr_asr: 'decide',
    download_video_for_preview: 'decide',
    confirm_hybrid_ocr_settings: 'decide',
    confirm_ocr_reuse: 'decide',
    download_subtitle: 'source',
    download_reference_subtitle: 'source',
    dual_subtitle_reference: 'source',
    download_anchor_subtitle: 'source',
    download_video_for_hybrid: 'source',
    hybrid_anchor_ocr: 'source',
    ocr_full: 'source',
    download_video_for_asr: 'source',
    audio_asr: 'source',
    ocr_reference: 'source',
    asr_ocr_refine: 'source',
    generate_glossary: 'glossary',
    review_glossary: 'glossary',
    translate: 'translate',
    done: 'deliver',
  }

  assert.deepEqual(
    Object.fromEntries(Object.keys(expected).map((phase) => [phase, getAgentPhasePresentation(phase).stageId])),
    expected,
  )
  assert.equal(Object.keys(AGENT_PHASE_PRESENTATIONS).length, Object.keys(expected).length + 1)
})

test('labels phases that were missing from the old progress rail', () => {
  assert.equal(sessionPhaseLabel('created'), '等待启动')
  assert.equal(sessionPhaseLabel('download_video_for_preview'), '下载视频用于 OCR 预览')
  assert.equal(sessionPhaseLabel('download_video_for_asr'), '下载视频用于 ASR')
  assert.equal(sessionPhaseLabel('diagnose_ocr_asr'), '等待选择 OCR / ASR 路线')
  assert.equal(sessionPhaseLabel('review_glossary'), '等待 Glossary 审核')
  assert.equal(sessionPhaseLabel('done'), '已完成')
})

test('marks only coarse stages before the current phase as done', () => {
  assert.deepEqual(
    buildAgentFlowSteps('review_glossary', 'waiting').map(({ state }) => state),
    ['done', 'done', 'done', 'active', 'upcoming', 'upcoming'],
  )
  assert.deepEqual(
    buildAgentFlowSteps('asr_ocr_refine', 'running').map(({ state }) => state),
    ['done', 'done', 'active', 'upcoming', 'upcoming', 'upcoming'],
  )
})

test('represents failed and completed sessions without branch-specific steps', () => {
  assert.deepEqual(
    buildAgentFlowSteps('translate', 'failed').map(({ state }) => state),
    ['done', 'done', 'done', 'done', 'failed', 'upcoming'],
  )
  assert.ok(buildAgentFlowSteps('done', 'done').every(({ state }) => state === 'done'))
})

test('surfaces an unknown phase without inventing progress', () => {
  assert.deepEqual(getAgentPhasePresentation('future_phase'), {
    phase: 'future_phase',
    stageId: null,
    label: 'future_phase',
    known: false,
  })
  assert.equal(sessionPhaseLabel(''), '未开始')
  assert.ok(buildAgentFlowSteps('future_phase', 'running').every(({ state }) => state === 'upcoming'))
})

test('labels every current route and preserves unknown route names', () => {
  assert.equal(routeLabel('download_target_subtitle'), '直接下载中文字幕')
  assert.equal(routeLabel('dual_subtitle_reference'), '原声主字幕 + 英文参考')
  assert.equal(routeLabel('hybrid_anchor_ocr'), '英文定轴 + 原声 OCR')
  assert.equal(routeLabel('asr_ocr_reference'), 'ASR 主导 + OCR 参考')
  assert.equal(routeLabel('future_route'), 'future_route')
  assert.equal(routeLabel(''), '等待检测')
})

test('presents preview actions without mutating backend question options', () => {
  const options = [
    { action: 'download_video_for_preview', label: '旧预览文案', primary: true },
    { action: 'run_ocr', label: '使用 OCR' },
    { action: 'run_asr', label: '使用 ASR' },
  ]
  const original = structuredClone(options)
  const presented = presentAgentQuestionOptions({
    status: 'waiting',
    phase: 'diagnose_ocr_asr',
    question: { kind: 'diagnose_ocr_asr', options },
    result: {},
  })

  assert.deepEqual(presented, [
    { action: 'download_video_for_preview', label: '下载视频并打开裁框预览', primary: true },
    { action: 'run_ocr', label: '使用 OCR' },
    { action: 'run_asr', label: '使用 ASR' },
  ])
  assert.deepEqual(options, original)
  assert.notEqual(presented[0], options[0])
})

test('removes the redundant preview action and names OCR against the selected area once video is ready', () => {
  const options = [
    { action: 'download_video_for_preview', label: '下载预览' },
    { action: 'run_ocr', label: '使用 OCR' },
    { action: 'run_asr', label: '使用 ASR' },
  ]
  const presented = presentAgentQuestionOptions({
    question: { kind: 'diagnose_ocr_asr', options },
    result: { input_video: '/private/video.mp4' },
  })

  assert.deepEqual(presented, [
    { action: 'run_ocr', label: '按当前字幕区域开始 OCR' },
    { action: 'run_asr', label: '使用 ASR' },
  ])
  assert.equal(options[1].label, '使用 OCR')
})

test('keeps glossary filtering and tolerates missing question options', () => {
  assert.deepEqual(presentAgentQuestionOptions({}), [])
  assert.deepEqual(presentAgentQuestionOptions({
    phase: 'review_glossary',
    question: {
      kind: 'review_glossary',
      options: [
        { action: 'continue_after_glossary', label: '继续' },
        { action: 'skip_glossary', label: '跳过' },
      ],
    },
  }), [{ action: 'skip_glossary', label: '跳过' }])
})

test('shows the OCR workbench only for waiting OCR decisions with a local video', () => {
  for (const kind of ['diagnose_ocr_asr', 'confirm_hybrid_ocr_settings', 'confirm_ocr_settings']) {
    assert.equal(shouldShowAgentOcrWorkbench({ status: 'waiting', question: { kind } }, '/tmp/video.mp4'), true)
  }
  assert.equal(shouldShowAgentOcrWorkbench({ status: 'running', question: { kind: 'diagnose_ocr_asr' } }, '/tmp/video.mp4'), false)
  assert.equal(shouldShowAgentOcrWorkbench({ status: 'waiting', question: { kind: 'review_glossary' } }, '/tmp/video.mp4'), false)
  assert.equal(shouldShowAgentOcrWorkbench({ status: 'waiting', question: { kind: 'diagnose_ocr_asr' } }, ''), false)
  assert.equal(shouldShowAgentOcrWorkbench({
    status: 'waiting',
    question: { kind: 'diagnose_ocr_asr' },
    result: { input_video: '/tmp/restored.mp4' },
  }), true)
})

test('describes running probe and OCR operations in user-facing language', () => {
  assert.deepEqual(agentOperationPresentation({ status: 'running', phase: 'probe' }), {
    title: '正在检测素材',
    message: '正在读取视频信息和可用字幕。',
  })
  assert.deepEqual(agentOperationPresentation({ status: 'running', phase: 'ocr_full' }), {
    title: '正在提取画面字幕',
    message: 'OCR 正在逐帧识别，耗时取决于视频长度。',
  })
  assert.equal(agentOperationPresentation({ status: 'waiting', phase: 'probe' }), null)
})

test('extracts only safe download progress and never exposes raw logs or paths', () => {
  const operation = agentOperationPresentation({
    status: 'running',
    phase: 'download_video_for_preview',
    result: {
      current_job_status: 'running',
      current_job_logs: [
        'exec: yt-dlp --token SECRET /data/private/video.mp4',
        '[download]  42.37% of 98.00MiB at /data/private/video.mp4',
      ],
    },
  })

  assert.equal(operation.title, '正在下载 OCR 预览视频')
  assert.match(operation.message, /42\.4%/)
  assert.match(operation.message, /自动抽帧/)
  assert.doesNotMatch(operation.message, /SECRET|\/data\/|yt-dlp/)
})

test('translates already-downloaded logs without exposing the local filename', () => {
  const operation = agentOperationPresentation({
    status: 'running',
    phase: 'download_video_for_preview',
    result: {
      current_job_logs: ['[download] /data/private/secret-name.mp4 has already been downloaded'],
    },
  })

  assert.equal(operation.message, '检测到视频已在本地，正在直接使用。')
  assert.doesNotMatch(operation.message, /secret-name|\/data\//)
})

test('uses safe operation fallbacks for unknown phases and malformed progress', () => {
  assert.deepEqual(agentOperationPresentation({ status: 'running', phase: '/bin/sh --secret' }), {
    title: 'Agent 正在处理',
    message: '正在执行当前任务，请稍候。',
  })
  const operation = agentOperationPresentation({
    status: 'running',
    phase: 'download_video_for_preview',
    result: { current_job_logs: ['[download] 999% /private/file.mp4'] },
  })
  assert.doesNotMatch(operation.message, /999|private/)
  assert.match(operation.message, /正在下载视频/)
})
