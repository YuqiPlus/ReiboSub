import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_translate.agent.ocr_finalize import bounded_payload, launch, run


def test_bounded_options_do_not_mutate_inputs_or_add_vendor_fields_to_other_models():
    payload = {'model': 'doubao-seed-2-1-lite-example', 'messages': [{'role': 'user', 'content': 'data'}]}
    before = copy.deepcopy(payload)
    bounded = bounded_payload(payload)
    assert bounded['thinking'] == {'type': 'disabled'} and bounded['max_tokens'] == 8192
    assert payload == before
    assert 'thinking' not in bounded_payload({'model': 'another-provider-model'})


def test_finalizer_is_a_subprocess_using_existing_candidates_not_video_decoding(tmp_path):
    debug = tmp_path/'candidate'; debug.mkdir()
    machine = debug/'source.machine.srt'; machine.write_text('original candidate')
    (debug/'ocr_boxes.json').write_text('[]')
    commands = []
    def command(job, args):
        commands.append(args)
        out = Path(args[args.index('--output-dir')+1]); out.mkdir(parents=True)
        (out/'source.v3.layered.srt').write_text('finalized source')
    app = SimpleNamespace(JOB_DIR=tmp_path/'jobs', PYTHON='/project/python',
        _ensure_under_root=lambda p: p.relative_to(tmp_path), _run_command=command,
        start_job=lambda name, target: target('test'))
    result = launch(app, {'debug_dir': str(debug)})
    assert 'video_translate.agent.ocr_finalize' in commands[0]
    assert str(debug) in commands[0] and not any('transcribe' in str(a) or 'extract_video' in str(a) for a in commands[0])
    assert machine.read_text() == 'original candidate'
    assert Path(result['v3_layered_srt']).is_file()


def test_finalizer_rejects_missing_evidence_and_existing_subtitle_outputs(tmp_path):
    app = SimpleNamespace(_ensure_under_root=lambda _: None)
    with pytest.raises(ValueError, match='尚未核查完整'):
        launch(app, {'debug_dir': str(tmp_path)})
    out = tmp_path/'existing'; out.mkdir(); original = out/'saved.srt'; original.write_text('keep me')
    with pytest.raises(FileExistsError, match='拒绝覆盖'):
        run(tmp_path, out)
    assert original.read_text() == 'keep me'
