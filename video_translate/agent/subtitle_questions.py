"""Control-action labels are not subtitle translations or approval evidence."""

ACTION_LABELS=frozenset({'删除该条','删除这条字幕','作为噪声删除该条','保留现有译文','保留当前译文','保留原文'})


def clean(question, verification=None):
    if question.get('question_type')!='translation' or not any(c in ACTION_LABELS for c in question.get('candidates',[])):
        return question
    cue_id=question.get('cue_id')
    issue=next((row for row in (verification or {}).get('issues',[]) if row.get('id')==cue_id),{})
    source=issue.get('source_quote','')
    message=f'第{cue_id}条仍无法确认原文含义。'
    if source:message+=f'当前识别原文为“{source}”。'
    message+='请播放下面的原画面或原音，补充你看到的文字、听到的内容或意思线索。已有译稿保留；不会把“删除/保留”等动作标签写进字幕，也不会自动删除原文。'
    return {**question,'message':message,'candidates':[],'candidate_details':[]}
