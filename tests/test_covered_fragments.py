import copy

from video_translate.agent.covered_fragments import covered_tails


def sample():
    rows=[{'id':327,'start':765.519,'end':770,'source':'다들 너무 감사합니다.','zh':'各位真的非常感谢'},
          {'id':328,'start':767,'end':770,'source':'니다.','zh':''}]
    evidence=[{'id':327,'quote':'감사합니다.'},{'id':328,'quote':'니다.'}]
    return rows,{'328':{'action':'keep','replacement':None,'evidence':evidence}},{'328':{'verdict':'approve','evidence':copy.deepcopy(evidence)}}


def test_only_independently_approved_overlapping_empty_ending_is_covered():
    rows,p,r=sample();result=covered_tails(rows,p,r)
    assert len(result)==1 and result[0]['id']==328 and result[0]['covered_by']==327
    assert rows[1]['zh']==''  # No input mutation or fake filler.


def test_no_coverage_for_nonempty_text_or_unrelated_words_or_separate_speech():
    rows,p,r=sample();rows[1]['zh']='谢谢'
    assert not covered_tails(rows,p,r)
    rows,p,r=sample();rows[1]['source']='아니요'
    assert not covered_tails(rows,p,r)
    rows,p,r=sample();rows[1]['end']=771
    assert not covered_tails(rows,p,r)


def test_model_agreement_without_both_real_context_citations_is_not_enough():
    for side in ('proposer','checker'):
        rows,p,r=sample();obj=p['328'] if side=='proposer' else r['328']
        obj['evidence']=[{'id':328,'quote':'니다.'}]
        assert not covered_tails(rows,p,r)
    rows,p,r=sample();r['328']['verdict']='uncertain'
    assert not covered_tails(rows,p,r)
    rows,p,r=sample();p['328']['evidence'][0]['quote']='不存在的句子'
    assert not covered_tails(rows,p,r)
