from pathlib import Path
import hashlib

import pytest

from video_translate.agent.translation_review import TranslationReview,replace_only_cue_text
from video_translate.models import SubtitleCue
from video_translate.subtitle.srt import read_srt,write_srt


def test_span_writer_preserves_unmodified_bytes_headers_and_line_endings():
    raw=b'\xef\xbb\xbf1\r\n00:00:00,000 --> 00:00:01,000\r\nold first\r\n\r\n2\r\n00:00:02,000 --> 00:00:03,000\r\nold\r\nsecond\r\n\r\n3\r\n00:00:04,000 --> 00:00:05,000\r\nlast'
    assert replace_only_cue_text(raw,{1:'new first',2:'new\nsecond'})==raw.replace(b'old first',b'new first').replace(b'old\r\nsecond',b'new\r\nsecond')
    assert replace_only_cue_text(raw,{})==raw


@pytest.mark.parametrize('replacement',['','a\n\nb','a\rb','  '])
def test_span_writer_rejects_srt_block_injection(replacement):
    with pytest.raises(ValueError):replace_only_cue_text(b'1\n00:00:00,000 --> 00:00:01,000\nx\n\n',{1:replacement})


@pytest.mark.parametrize('newline',[b'\n',b'\r\n'])
def test_span_writer_can_fill_one_authorized_empty_block_without_touching_other_bytes(newline):
    before=newline.join([b'1',b'00:00:00,000 --> 00:00:02,000',b'unchanged',b'',b'2',b'00:00:01,000 --> 00:00:02,000',b'',b'',b'3',b'00:00:03,000 --> 00:00:04,000',b'also unchanged'])
    header=newline.join([b'2',b'00:00:01,000 --> 00:00:02,000',b''])
    result=replace_only_cue_text(before,{2:'谢谢'})
    assert result==before.replace(header,header+'谢谢'.encode()+newline)
    assert replace_only_cue_text(before,{})==before


@pytest.mark.parametrize('ending',[b'',b'\n'])
def test_span_writer_can_fill_empty_last_cue_without_existing_body(ending):
    raw=b'1\n00:00:00,000 --> 00:00:01,000'+ending
    assert b'\ntext\n' in replace_only_cue_text(raw,{1:'text'})


@pytest.fixture
def inputs(tmp_path):
    source=tmp_path/'source.srt';zh=tmp_path/'zh.srt'
    write_srt([SubtitleCue(1,0,1,'선물을 사요'),SubtitleCue(2,2,3,'엄마에게 줘요'),SubtitleCue(3,4,5,'레이 같아요'),SubtitleCue(4,6,7,'끝')],source)
    write_srt([SubtitleCue(1,0,1,'买礼物'),SubtitleCue(2,2,3,'送给朋友'),SubtitleCue(3,4,5,'很有레이的风格'),SubtitleCue(4,6,7,'结束')],zh)
    return source,zh,tmp_path/'new-review'


def proposals():
    return [{'id':2,'action':'revise','replacement':'送给妈妈','reason_zh':'原文为妈妈，不是朋友',
        'evidence':[{'id':2,'quote':'엄마에게'},{'id':1,'quote':'선물'}]},
        {'id':3,'action':'keep','replacement':None,'reason_zh':'原译自然，人名保留原文无需猜译名','evidence':[{'id':3,'quote':'레이 같아요'}]}]


def approvals(verdict='approve'):
    return {'checks':[{'id':i,'verdict':verdict,'reason_zh':'原文和上下文支持本判断',
        'evidence':[{'id':i,'quote':quote}],**({'change_basis':{'kind':'fact_conflict','context_supports_disputed_meaning':False}} if i==2 and verdict=='approve' else {})} for i,quote in [(2,'엄마에게'),(3,'레이 같아요')]]}


def test_agent_reads_context_repairs_only_approved_cue_and_exports_new_version(inputs):
    source,zh,out=inputs;original_source=source.read_bytes();original=zh.read_bytes()
    calls=[];actions=iter([{'tool':'read_context','args':{'cue_ids':[2,3],'radius':1}},
        {'tool':'propose','args':{'decisions':proposals()}},{'tool':'check'},{'tool':'finish'}])
    def llm(root,name,task,instruction,data):
        calls.append(name)
        return approvals() if name.startswith('proposal-check') else next(actions)
    result=TranslationReview(source,zh,[],[2,3],out,llm).run()
    assert result['changed_ids']==[2] and result['unresolved_ids']==[]
    assert Path(result['translated_srt']).read_bytes()==original.replace('送给朋友'.encode(),'送给妈妈'.encode())
    assert source.read_bytes()==original_source and zh.read_bytes()==original
    assert [c.text for c in read_srt(Path(result['translated_srt']))]==['买礼物','送给妈妈','很有레이的风格','结束']
    assert len([name for name in calls if name.startswith('proposal-check')])==1


def test_existing_proposal_is_checked_and_exported_without_model_repeating_unavailable_propose(inputs):
    source,zh,out=inputs;planning=[]
    def llm(root,name,task,instruction,data):
        if name.startswith('proposal-check'):return approvals()
        planning.append(name)
        if len(planning)==1:return {'tool':'read_context','args':{'cue_ids':[2,3],'radius':1}}
        if len(planning)==2:return {'tool':'propose','args':{'decisions':proposals()}}
        pytest.fail('After a valid proposal, checking and export should not wait for more planning')
    result=TranslationReview(source,zh,[],[2,3],out,llm).run()
    assert result['changed_ids']==[2] and result['unresolved_ids']==[] and len(planning)==2


def test_uncertain_or_rejected_edits_are_not_applied(inputs):
    source,zh,out=inputs
    review=TranslationReview(source,zh,[],[2,3],out,lambda *a:approvals('uncertain'))
    review.execute('read_context',{'cue_ids':[2,3],'radius':1});review.execute('propose',{'decisions':proposals()})
    review.execute('check',{});result=review.execute('finish',{})
    assert result['changed_ids']==[] and result['unresolved_ids']==[2,3]
    assert Path(result['translated_srt']).read_bytes()==zh.read_bytes()


def test_no_out_of_scope_proposal_fake_evidence_or_shell_tool(inputs):
    source,zh,out=inputs;review=TranslationReview(source,zh,[],[2,3],out,None)
    review.execute('read_context',{'cue_ids':[2,3],'radius':1})
    row=proposals()[0]
    with pytest.raises(ValueError):review.execute('propose',{'decisions':[{**row,'id':4}]})
    with pytest.raises(ValueError):review.execute('propose',{'decisions':[{**row,'evidence':[{'id':2,'quote':'伪造原文'}]}]})
    with pytest.raises(ValueError):review.execute('propose',{'decisions':[{**row,'evidence':[{'id':2,'quote':'엄마'}]}]})
    with pytest.raises(ValueError):review.execute('shell',{'command':'translate whole file'})
    assert not list(out.glob('*.srt'))


def test_checker_must_cover_all_targets_and_has_one_format_retry(inputs):
    source,zh,out=inputs;calls=[]
    def incomplete(*a):calls.append(1);return {'checks':[]}
    review=TranslationReview(source,zh,[],[2,3],out,incomplete)
    review.execute('read_context',{'cue_ids':[2,3],'radius':1});review.execute('propose',{'decisions':proposals()})
    with pytest.raises(ValueError):review.execute('check',{})
    assert len(calls)==2 and not review.reviews
    with pytest.raises(ValueError):review.execute('finish',{})


def test_existing_version_or_changed_input_is_not_overwritten(inputs):
    source,zh,out=inputs;review=TranslationReview(source,zh,[],[2],out,None)
    with pytest.raises(FileExistsError):TranslationReview(source,zh,[],[2],out,None)
    zh.write_bytes(zh.read_bytes()+b'\n')
    with pytest.raises(RuntimeError):review.execute('read_context',{'cue_ids':[2],'radius':1})


def test_controller_budget_stops_without_exporting_unapproved_changes(inputs):
    source,zh,out=inputs;calls=[]
    def bad(*args):calls.append(1);return {'tool':'translate_whole_file','args':{}}
    with pytest.raises(RuntimeError):TranslationReview(source,zh,[],[2],out,bad).run()
    assert len(calls)==16 and not list(out.glob('*.srt'))


def test_rejected_proposal_has_one_more_evidence_round_before_finish(inputs):
    source,zh,out=inputs
    response=approvals();response['checks'][0]['verdict']='reject'
    review=TranslationReview(source,zh,[],[2,3],out,lambda *a:response)
    review.execute('read_context',{'cue_ids':[2,3],'radius':1});review.execute('propose',{'decisions':proposals()});review.execute('check',{})
    available={t['name']:t for t in review.available()}
    assert 'finish' not in available and available['propose']['eligible_ids']==[2]
    retry={**proposals()[0],'action':'uncertain','replacement':None,'reason_zh':'证据有分歧，保留原文待确认'}
    review.execute('propose',{'decisions':[retry]})
    assert review.review_history['2'][0]['verdict']=='reject'
    review.llm=lambda *a:{'checks':[approvals()['checks'][0]]}
    review.execute('check',{})
    assert 'finish' in {t['name'] for t in review.available()}
    result=review.execute('finish',{})
    assert result['changed_ids']==[] and result['unresolved_ids']==[2]


def test_local_review_obeys_human_glossary_and_cannot_erase_confirmed_name(inputs,tmp_path):
    source,zh,out=inputs
    path=tmp_path/'approved.yaml';path.write_text('characters:\n- source: 레이\n  zh: 用户译名\n  reviewed: true\n')
    rows=read_srt(zh);rows[2].text='很有用户译名的风格';write_srt(rows,zh)
    review=TranslationReview(source,zh,[],[3],out,None,glossary_path=path)
    assert review.glossary_context['glossary'][0]['zh']=='用户译名'
    review.execute('read_context',{'cue_ids':[3],'radius':1})
    with pytest.raises(ValueError,match='用户已确认'):
        review.execute('propose',{'decisions':[{'id':3,'action':'revise','replacement':'很有猜测名的风格','reason_zh':'换个名字',
            'evidence':[{'id':3,'quote':'레이 같아요'},{'id':2,'quote':'엄마에게'}]}]})
    path.write_text('characters: []\n')
    with pytest.raises(RuntimeError,match='词表快照'):review.assert_inputs()


@pytest.mark.parametrize('basis',[
    {'kind':'unsupported_addition','context_supports_disputed_meaning':True},
    {'kind':'style','context_supports_disputed_meaning':False},
    {'kind':'uncertain','context_supports_disputed_meaning':False},
])
def test_context_supported_or_stylistic_edits_cannot_be_applied_even_if_checker_approves(inputs,basis):
    source,zh,out=inputs
    response=approvals();response['checks'][0]['change_basis']=basis
    review=TranslationReview(source,zh,[],[2,3],out,lambda *a:response)
    review.execute('read_context',{'cue_ids':[2,3],'radius':1});review.execute('propose',{'decisions':proposals()})
    review.execute('check',{})
    assert review.reviews['2']['verdict']=='reject'
    assert review.execute('finish',{})['changed_ids']==[]


def test_revise_without_material_basis_is_protocol_error_not_approval(inputs):
    source,zh,out=inputs
    response=approvals();response['checks'][0].pop('change_basis')
    review=TranslationReview(source,zh,[],[2,3],out,lambda *a:response)
    review.execute('read_context',{'cue_ids':[2,3],'radius':1});review.execute('propose',{'decisions':proposals()})
    with pytest.raises(ValueError):review.execute('check',{})
    assert not review.reviews
