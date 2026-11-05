"""User-facing launcher for the isolated Korean multi-ASR experiment."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote


def seconds(value):
    if isinstance(value, bool):raise ValueError('时间格式无效')
    try:
        if isinstance(value, str) and ':' in value:
            parts=value.strip().split(':')
            if len(parts) not in (2,3):raise ValueError()
            numbers=[float(p) for p in parts]
            if any(n<0 for n in numbers) or any(n>=60 for n in numbers[1:]):raise ValueError()
            result=sum(n*60**i for i,n in enumerate(reversed(numbers)))
        else:result=float(value)
    except (ValueError,TypeError):raise ValueError('时间请填写秒数或 时:分:秒 / 分:秒') from None
    if not math.isfinite(result) or result<0:raise ValueError('时间必须是非负有限数值')
    return result


def ranges(raw, duration):
    if not isinstance(raw,list) or not 1<=len(raw)<=3:raise ValueError('请选择1到3个测试区间')
    result=[]
    for row in raw:
        if not isinstance(row,dict):raise ValueError('测试区间格式无效')
        start,end=seconds(row.get('start')),seconds(row.get('end'))
        if not 5<=end-start<=180:raise ValueError('每个测试区间须为5秒到3分钟')
        if end>duration+.001:raise ValueError(f'测试区间超出素材时长（{duration:.1f}秒）')
        if any(start<r['end'] and end>r['start'] for r in result):raise ValueError('测试区间不能重叠')
        result.append({'start':start,'end':end})
    return sorted(result,key=lambda r:r['start'])


def launch(payload, app):
    media=app._resolve_project_path(app._required_str(payload,'input_video'))
    app._ensure_under_root(media)
    if not media.is_file():raise FileNotFoundError('请选择存在的视频或音频文件')
    if str(payload.get('source_language') or 'korean') not in {'auto','korean','ko'}:
        raise ValueError('多模型实验版目前仅支持韩语，其他语言请使用ASR 2.2')
    prefix=Path(app.PYTHON).parent
    qwen=Path(os.environ.get('REIBOSUB_QWEN_PYTHON',str(prefix.parent.parent/'reibosub-asr3/bin/python')))
    if not qwen.is_file():raise ValueError('尚未配置实验版Qwen独立环境')
    for name in ('Qwen3-ASR-1.7B','Qwen3-ForcedAligner-0.6B'):
        if not (app.ROOT/'models/asr3'/name/'config.json').is_file():raise ValueError(f'实验模型尚未准备好：{name}')
    if app._nvidia_gpu_count()<2:raise ValueError('当前实验版需要两张NVIDIA GPU，ASR 2.2仍可照常使用')
    from video_translate.llm_config import load_llm_task_config
    for task in ('asr_correction','subtitle_translation'):
        config=load_llm_task_config(task)
        if not config.api_key or not config.model or not config.base_url:raise ValueError('请先在设置里配置ASR纠错和字幕翻译的模型服务')
    probe=prefix/'ffprobe'
    if not probe.is_file():probe=Path(shutil.which('ffprobe') or '')
    if not probe.is_file():raise ValueError('当前工程环境缺少ffprobe')
    info=subprocess.run([str(probe),'-v','error','-show_entries','format=duration','-of','json',str(media)],
                        capture_output=True,text=True,timeout=15,check=True)
    duration=float(json.loads(info.stdout)['format']['duration'])
    if not math.isfinite(duration) or duration<=0:raise ValueError('无法读取素材时长')
    selected=ranges(payload.get('test_ranges'),duration)

    def target(job_id):
        from scripts.asr3_benchmark import load_json, save_json
        root=app.ROOT/'outputs/asr3_experiments'/f'lab_{job_id}'
        if root.exists():raise FileExistsError('实验目录已存在，不覆盖过往结果')
        baseline=root/'baseline';baseline.mkdir(parents=True)
        save_json(root/'lab-request.json',{'input_video':str(media),'test_ranges':selected,
                  'language':'korean','audio_uploaded':False,'production_asr_changed':False})
        manifest=baseline/'manifest.json'
        save_json(manifest,{'samples':[{'id':f'clip_{i}','label':f'测试片段{i} · 原视频 {r["start"]:g}–{r["end"]:g}秒',
            'input':str(media),'start':r['start'],'duration':r['end']-r['start'],'review_points':[]} for i,r in enumerate(selected,1)]})
        bench=str(app.ROOT/'scripts/asr3_benchmark.py');review=str(app.ROOT/'scripts/asr_review_agent.py')
        path=str(prefix)+os.pathsep+os.environ.get('PATH','')
        env={'PATH':path,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
        stages=[('1/7 截取测试音频',[app.PYTHON,'-u',bench,'prepare','--manifest',str(manifest)],None),
                ('2/7 检测语音和停顿',[app.PYTHON,'-u',bench,'vad','--manifest',str(manifest)],None),
                ('3/7 ASR 2.2识别',[app.PYTHON,'-u',bench,'whisper','--manifest',str(manifest)],'0'),
                ('4/7 Qwen独立识别',[str(qwen),'-u',bench,'qwen','--manifest',str(manifest),'--qwen-dir','qwen_vad'],'1'),
                ('5/7 处理Qwen异常时间',[str(qwen),'-u',str(app.ROOT/'scripts/refine_asr3_alignment.py'),'--manifest',str(manifest)],'1'),
                ('6/7 Agent局部复核与中文翻译',[app.PYTHON,'-u',review,'run','--manifest',str(manifest),'--output',str(root/'review'),
                    '--qwen-python',str(qwen)],None),
                ('7/7 最终文本时间轴校准',[app.PYTHON,'-u',review,'calibrate-timing','--seed-experiment',str(root/'review'),
                    '--output',str(root/'calibrated'),'--qwen-python',str(qwen)],None)]
        for label,command,gpu in stages:
            app._append_log(job_id,'experiment_stage: '+label)
            app._run_command(job_id,command,env_overrides={**env,**({'CUDA_VISIBLE_DEVICES':gpu} if gpu else {})})
        final=root/'calibrated';questions=load_json(final/'human-review-questions.json')
        summary=load_json(final/'timing-summary.json')
        ko=final/'agent.original-timeline.ko.srt';zh=final/'agent.original-timeline.zh.srt'
        result={'kind':'asr_experiment_lab','asr_version':'agent-experimental','pipeline_version':'多模型Agent（实验版）',
                'input_video':str(media),'test_ranges':selected,'output_dir':str(root),
                'source_srt':str(ko),'translated_srt':str(zh),
                'report_url':'/api/file?path='+quote(str((final/'comparison.html').relative_to(app.ROOT))),
                'pending_questions':questions.get('pending_case_count',len(questions['questions'])),
                'human_review_available':questions.get('status')!='unavailable',
                'cue_count':sum(s['total'] for s in summary['samples']),
                'timing_needs_review':sum(s['timing_needs_review'] for s in summary['samples']),
                'notice':'仅包含选定测试区间，SRT使用原视频时间；实验稿不代表人工确认。'+(
                    ' 人名审核卡暂不可用，未确认人名保留韩文。' if questions.get('status')=='unavailable' else '')}
        save_json(root/'lab-result.json',result)
        app._append_log(job_id,'experiment_stage: 完成，可试听或确认人名')
        return result
    return app.start_job('多模型Agent实验 · '+media.stem[:60],target)
