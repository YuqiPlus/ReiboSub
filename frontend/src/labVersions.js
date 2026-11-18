export const OCR_LAB_VERSIONS = Object.freeze([
  { id: 'region_v3', label: 'OCR 3.0', badge: '稳定版', description: '几何提示、文字纠错与画面字 / 对白分层。', detail: '几何判断与成品精修分别保存；默认横向优先是软提示，也可在高级参数中切换形态策略。' },
  { id: 'region', label: 'OCR 2.0', badge: '独立保留', description: '区域识别与专属轨迹精修，便于继续优化和对照。', detail: '保留第二版的区域逻辑和专属精修，使用独立调试目录，不会被 3.0 覆盖。' },
])

export const ASR_LAB_VERSIONS = Object.freeze([
  { id: '2.0', label: 'ASR 2.2', badge: '推荐', description: '双遍高召回识别，对可疑缺口定向增益重听。', detail: '只提取原文，不翻译、不调用 LLM。可选区分说话人；疑似漏听片段仍可试听复核。', experimental: false },
  { id: 'agent-experimental', label: '多模型 Agent', badge: '实验 · 韩语', description: '多模型识别、复核、中文翻译与时间轴校准。', detail: '本机识别后调用模型服务复核与翻译；只处理指定区间，实验产物单独保存，原 ASR 2.2 保留。', experimental: true },
  { id: 'autonomous-experimental', label: '自主字幕 Agent', badge: '独立实验 · 韩语', description: '自主检查疑点、按需局部重听，证据不足时再询问。', detail: '仅韩语区间实验，不是主线整片 Agent。使用复核、翻译和时间轴工具，可能需要你补充线索；会消耗模型额度。', experimental: true },
  { id: '1.0', label: 'ASR 1.0', badge: '历史兼容', description: '保留模型原始分段，用于历史对照与回退。', detail: '不启用 2.2 的定向补漏。只提取原文，不翻译、不调用 LLM；说话人匹配保留旧版行为。', experimental: false },
])
