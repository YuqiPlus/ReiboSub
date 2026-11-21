export const TOOLBOX_TOOLS = [
  { id: 'translate', icon: 'language', title: '文本翻译', description: '粘贴文字，随手翻译' },
  { id: 'subtitles', icon: 'edit', title: '字幕工具', description: '上传字幕，翻译与转换' },
  { id: 'dialogue', icon: 'audio', title: '提取对话', description: '把音视频变成文字与字幕' },
  { id: 'transcript', icon: 'book', title: '字幕转纯文本', description: '去掉时间码，保留内容' },
]

export function mediaChoices(assets = {}) {
  const paths = new Set()
  return [...(assets.videos || []), ...(assets.audios || [])].filter(item => {
    if (!item.path || paths.has(item.path)) return false
    paths.add(item.path)
    return true
  })
}

export function dialoguePayload({ input, language = 'auto', model = 'large-v3', device = 'cuda', hotwords = '', speakers = false, knownSpeakerCount = 'auto', chineseScript = 'simplified' }) {
  if (!String(input || '').trim()) throw new Error('请先选择或上传视频、音频。')
  if (!['auto', 'korean', 'japanese', 'chinese', 'english'].includes(language)) throw new Error('不支持的音频语言')
  if (!['large-v3', 'medium', 'small'].includes(model)) throw new Error('不支持的识别模型')
  if (!['cuda', 'cpu'].includes(device)) throw new Error('不支持的运行设备')
  if (!['simplified', 'traditional', 'original'].includes(chineseScript)) throw new Error('不支持的中文输出字形')
  const count = speakers && knownSpeakerCount !== 'auto' ? Number(knownSpeakerCount) : 'auto'
  if (count !== 'auto' && (!Number.isInteger(count) || count < 1 || count > 20)) throw new Error('已知说话人数须在 1 到 20 之间，或选择自动判断')
  return {
    input_video: input.trim(), source_language: language, model_size: model,
    chinese_script: chineseScript,
    asr_version: '2.0', high_recall: true, hotwords: hotwords.trim(),
    speaker_diarization: speakers, known_speaker_count: count,
    diarization_device: device, dual_gpu_parallel: false,
    device, compute_type: device === 'cpu' ? 'int8' : 'float16',
  }
}

// Keep cue order, repeated phrases, punctuation and speaker labels. No LLM or network.
export function subtitleTranscript(value, { timestamps = false } = {}) {
  const blocks = String(value || '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').trim().split(/\n[ \t]*\n/)
  const cues = []
  const timing = /^((?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})(?:[ \t].*)?$/
  for (const block of blocks) {
    const lines = block.split('\n')
    if (/^(?:WEBVTT(?:\s|$)|NOTE(?:\s|$)|STYLE\s*$|REGION\s*$)/.test(lines[0])) continue
    const index = lines.findIndex(line => timing.test(line.trim()))
    if (index < 0) continue
    const match = lines[index].trim().match(timing)
    const text = lines.slice(index + 1).join('\n')
      .replace(/<\d{2}:\d{2}(?::\d{2})?[.,]\d{3}>/g, '')
      .replace(/<\/?(?:b|i|u|c|v|lang|ruby|rt)(?:[.\s][^<>]*)?>/g, '')
      .replace(/\{\\[^}]*\}/g, '').trim()
    if (text) cues.push({ start: match[1], end: match[2], text })
  }
  if (!cues.length) throw new Error('没有找到有效字幕，请使用 SRT 或 WebVTT 文件内容。')
  return {
    count: cues.length,
    text: cues.map(cue => timestamps ? `[${cue.start} → ${cue.end}]\n${cue.text}` : cue.text).join('\n\n'),
  }
}

export function toolJobBusy(job) {
  return ['queued', 'running', 'cancel_requested'].includes(job?.status)
}
