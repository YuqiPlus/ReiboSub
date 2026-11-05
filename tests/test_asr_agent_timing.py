import copy
import math

import pytest

from scripts.asr_agent_timing import groups, map_words, settle


def cues():
    return [{'index':1,'start':0.,'end':2.,'text':'여러분들 감기'},
            {'index':2,'start':2.,'end':4.,'text':'조심하세요'}]


def words():
    return [{'text':'여러분들','start':1.,'end':1.7},
            {'text':'감기','start':1.8,'end':2.4},
            {'text':'조심하세요','start':2.5,'end':4.5}]


def test_final_text_alignment_moves_boundaries_and_keeps_text():
    before=cues();p=map_words(before,words(),(0,6));out,audit=settle(before,p,6)
    assert out[0]['start']==1 and out[0]['end']==2.5
    assert out[1]['end']==4.62
    assert [c['text'] for c in out]==[c['text'] for c in before]
    assert all(r['accepted'] for r in audit)
    assert before==cues()


def test_zero_edge_not_invented_or_padded():
    w=words();w[0]['end']=w[0]['start']
    result=map_words(cues(),w,(0,6))
    assert not result[1]['accepted'] and result[1]['reason']=='unresolved_edge_word'


def test_interior_zero_remains_explicitly_flagged():
    c=[{'index':1,'start':0,'end':3,'text':'하나 둘 셋'}]
    w=[{'text':'하나','start':1,'end':1.5},{'text':'둘','start':1.5,'end':1.5},
       {'text':'셋','start':2,'end':2.5}]
    p=map_words(c,w,(0,4));assert p[1]['accepted'] and p[1]['needs_review']


@pytest.mark.parametrize('kind',['nan','outside','reversed','text_changed'])
def test_invalid_alignment_is_rejected(kind):
    w=words()
    if kind=='nan':w[0]['start']=math.nan
    if kind=='outside':w[0]['start']=-1
    if kind=='reversed':w[0]['end']=.5
    if kind=='text_changed':w[0]['text']='invented'
    with pytest.raises(ValueError):map_words(cues(),w,(0,6))


def test_no_uniform_shift_for_different_cue_errors():
    p=map_words(cues(),words(),(0,6));out,_=settle(cues(),p,6)
    assert out[0]['start']-cues()[0]['start']!=out[1]['start']-cues()[1]['start']


def test_conflicts_rollback_not_truncate_speech():
    c=cues();p={1:{'accepted':True,'start':1,'end':3.5},2:{'accepted':True,'start':3,'end':4.5}}
    out,audit=settle(c,p,6)
    assert out==c and all(not r['accepted'] for r in audit)


def test_padding_cannot_cross_next_sentence_or_video_end():
    c=cues();p={1:{'accepted':True,'start':0,'end':1.99},2:{'accepted':True,'start':2,'end':4}}
    out,_=settle(c,p,4)
    assert out[0]['end']==2 and out[-1]['end']==4


def test_large_displacement_requires_manual_review():
    w=words();w[0].update(start=4,end=4.5);w[1].update(start=4.6,end=5)
    w[2].update(start=5,end=6)
    assert not map_words(cues(),w,(0,7))[1]['accepted']


def test_group_bounds_clip_to_media_and_do_not_bridge_long_silence():
    c=cues()+[{'index':3,'start':20,'end':22,'text':'다음'}]
    result=groups(c,22)
    assert len(result)==2 and result[0]['start']==0 and result[-1]['end']==22
    assert result[0]['indexes']==[1,2]
