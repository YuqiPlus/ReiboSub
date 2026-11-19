import copy
import json

from video_translate.agent import ocr_candidates as candidates
from video_translate.models import OCRBox, TextTrack, TrackKind
from video_translate.pipeline import CueTimingConfig


def track(i, text, bbox):
    return TextTrack(i, text, 0, 2,
        [OCRBox(text=text, bbox=tuple(bbox), confidence=.98, time=t, frame_index=int(t*30), region='bottom') for t in (0, 1)],
        kind=TrackKind.MAIN_SUBTITLE).to_dict()


def fixture():
    return [track(1, '안녕하세요', [20, 70, 80, 80]), track(2, '[Ruler]', [2, 70, 18, 80]),
            track(3, '18', [2, 40, 12, 45]), track(4, '2026', [40, 20, 60, 25]),
            track(5, 'MUSINSA', [40, 92, 60, 98])]


def test_native_subtitles_and_adjacent_speaker_labels_are_never_noise_candidates():
    rows = fixture(); before = copy.deepcopy(rows)
    protected, groups = candidates.candidate_groups(rows, 'korean', 100, 100)
    assert {1, 2} <= protected
    assert not {1, 2} & {i for g in groups for i in g['track_ids']}
    assert rows == before
    # Numeric text is sent for review, not mechanically thrown away.
    assert {3, 4} <= {i for g in groups for i in g['track_ids']}


def test_group_review_requires_real_quotes_and_explicit_high_confidence_noise():
    _, groups = candidates.candidate_groups(fixture(), 'korean', 100, 100)
    group = next(g for g in groups if 3 in g['track_ids'])
    valid = {'id': group['id'], 'kind': 'game_hud', 'certainty': 'high', 'quotes': ['18'], 'reason_zh': '游戏HUD数值'}
    assert 3 in candidates.reviewed_drops(groups, {'groups': [valid]})[0]
    for update in ({'quotes': ['invented']}, {'certainty': 'low'}, {'kind': 'uncertain'}, {'reason_zh': ''}):
        assert not candidates.reviewed_drops(groups, {'groups': [{**valid, **update}]})[0]
    assert not candidates.reviewed_drops(groups, {'groups': [valid, valid]})[0]
    assert not candidates.reviewed_drops(groups, {})[0]


def test_footer_labels_cannot_replace_native_dialogue_in_machine_seed():
    rows = fixture() + [track(6, 'CHOVY RULER', [30, 95, 70, 99])]
    original = copy.deepcopy(rows)
    machine = candidates.machine_tracks(rows, 'korean', 100, 100)
    assert {1, 2} <= {r['id'] for r in machine}
    assert 6 not in {r['id'] for r in machine}
    assert rows == original  # Full evidence still contains the uncertain ID.


def test_standalone_latin_text_is_not_suppressed_when_no_native_caption_is_present():
    rows = [track(1, 'WIN!', [20, 60, 80, 80])]
    assert candidates.machine_tracks(rows, 'korean', 100, 100) == rows


def test_prepare_keeps_editorial_numbers_and_raw_data_and_reuses_v3_inputs(tmp_path):
    raw = tmp_path/'raw'; raw.mkdir(); rows = fixture()
    (raw/'tracks.json').write_text(json.dumps(rows))
    (raw/'run.yaml').write_text('ocr:\n  extraction_mode: region_v3\n')
    before = (raw/'tracks.json').read_bytes()
    calls = []
    def llm(root, name, task, prompt, payload):
        calls.append(payload)
        return {'groups': [
            {'id': g['id'], 'kind': 'object_text' if any(r['text'] == 'MUSINSA' for r in g['examples']) else 'keep',
             'certainty': 'high', 'quotes': [g['examples'][0]['text']], 'reason_zh': '衣物字样，不是字幕'}
            for g in payload['groups']]}
    result = candidates.prepare(raw, tmp_path/'review', language='korean', width=100, height=100,
        vision={}, llm_json=llm, cue_timing=CueTimingConfig(), progress=lambda _: None)
    report = json.loads((tmp_path/'review/candidate-review.json').read_text())
    assert report['quarantined_ids'] == [5]
    assert result['kept_tracks'] == 4 and (raw/'tracks.json').read_bytes() == before
    assert (tmp_path/'review/source.machine.srt').is_file()
    assert 1 <= len(calls) <= 4
    assert {r['text'] for r in json.loads((tmp_path/'review/ocr_boxes.json').read_text())} == {'안녕하세요', '[Ruler]', '18', '2026'}
