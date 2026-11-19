"""Isolated, bounded request policy around unchanged OCR V3 final refiners."""
from __future__ import annotations

import argparse
from pathlib import Path


def bounded_payload(payload):
    value = {**payload, 'max_tokens': 8192}
    if str(value.get('model', '')).startswith('doubao-seed-2-1-'):
        value['thinking'] = {'type': 'disabled'}
    return value


def run(debug_dir, output_dir):
    # These bindings are replaced only inside this dedicated subprocess; the
    # web service, OCR Lab and their stable defaults are never monkey-patched.
    from video_translate.ocr import llm_refine, layered_refine
    from video_translate.translate.volcengine import _request_translation
    debug_dir, output_dir = Path(debug_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.glob('*.srt')):
        raise FileExistsError('成品目录已有字幕，拒绝覆盖')
    count = 0
    def request(endpoint, key, payload, **kwargs):
        nonlocal count
        count += 1
        if count > 160:
            raise RuntimeError('实验版OCR精修达到160次请求预算；原始OCR和已生成文件保留')
        print(f'agent_ocr_request: {count}/160; bounded non-thinking generation', flush=True)
        return _request_translation(endpoint, key, bounded_payload(payload), max_attempts=1, timeout_seconds=90)
    llm_refine._request_translation = request
    layered_refine._request_translation = request
    refined = output_dir/'source.v3.refined.srt'
    machine = debug_dir/'source.machine.srt'
    boxes = debug_dir/'ocr_boxes.json'
    llm_refine.refine_ocr_source_with_llm(machine, boxes, refined,
        config=llm_refine.OCRRefinementConfig(batch_size=12, window_padding_seconds=.5, max_boxes_per_frame=16))
    layered_refine.refine_ocr_layers_with_llm(refined, boxes, output_dir/'source.v3.layered.srt',
        output_dir/'ocr_v3_layers.json', recovery_srt=machine,
        config=layered_refine.LayeredOCRRefinementConfig(pipeline_version='v3'),
        progress_callback=lambda message: print(message, flush=True))


def launch(app, candidate):
    debug_dir = Path(candidate['debug_dir']).resolve(); app._ensure_under_root(debug_dir)
    if not (debug_dir/'source.machine.srt').is_file() or not (debug_dir/'ocr_boxes.json').is_file():
        raise ValueError('候选OCR尚未核查完整，不能启动成品精修')
    def target(job_id):
        output = app.JOB_DIR/job_id
        app._run_command(job_id, [app.PYTHON, '-u', '-m', 'video_translate.agent.ocr_finalize',
            '--debug-dir', str(debug_dir), '--output-dir', str(output)])
        layered = output/'source.v3.layered.srt'
        if not layered.is_file():
            raise RuntimeError('V3成品精修未生成字幕，不能把原始OCR冒充成品')
        return {'v3_layered_srt': str(layered), 'v3_refined_srt': str(output/'source.v3.refined.srt'),
                'ocr_v3_layers': str(output/'ocr_v3_layers.json'), 'debug_dir': str(debug_dir)}
    return app.start_job('Agent · OCR 3.0 成品精修', target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.debug_dir, args.output_dir)
