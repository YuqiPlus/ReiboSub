from video_translate.agent.structure import inspect_pairs
from video_translate.models import SubtitleCue


def test_exact_empty_translation_is_identified_not_blame_timing_or_truncation():
    source=[SubtitleCue(327,765.519,770,'다들 너무 감사합니다.'),SubtitleCue(328,767,770,'니다.')]
    target=[SubtitleCue(327,765.519,770,'谢谢大家'),SubtitleCue(328,767,770,'')]
    result=inspect_pairs(source,target)
    assert result['source_count']==result['target_count']==2
    assert result['issue_count']==1
    issue=result['issues'][0]
    assert issue['id']==328 and issue['kind']=='empty_translation'
    assert issue['recommended_tool']=='review_translation'
    assert issue['context'][0]['source']=='다들 너무 감사합니다.'
    assert '时轴' in issue['reason_zh']


def test_rolling_source_overlap_is_not_a_pair_mismatch():
    source=[SubtitleCue(1,0,4,'첫째'),SubtitleCue(2,2,6,'둘째')]
    target=[SubtitleCue(1,0,4,'第一'),SubtitleCue(2,2,6,'第二')]
    assert inspect_pairs(source,target)['acceptable']


def test_count_timing_and_invalid_interval_have_separate_diagnostics():
    source=[SubtitleCue(1,0,1,'a'),SubtitleCue(2,1,2,'b')]
    target=[SubtitleCue(1,0,0,'a')]
    kinds={i['kind'] for i in inspect_pairs(source,target)['issues']}
    assert kinds=={'cue_count_mismatch','invalid_translation_time','timing_mismatch'}
