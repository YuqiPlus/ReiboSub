from video_translate.agent.subtitle_questions import clean


def test_action_choices_are_not_treated_as_translation_text_or_deletion_authority():
    question={'kind':'autonomous_question','question_type':'translation','cue_id':83,
              'message':'请选择删除或保留','candidates':['删除该条','保留现有译文'],
              'candidate_details':[{'text':'删除该条'}],'audio_path':'/clip.wav','video_path':'/video.mp4'}
    result=clean(question,{'issues':[{'id':83,'source_quote':'원더'}]})
    assert result['candidates']==[] and result['candidate_details']==[]
    assert '원더' in result['message'] and '不会自动删除原文' in result['message']
    assert result['video_path']=='/video.mp4' and result['audio_path']=='/clip.wav'
    assert question['candidates']==['删除该条','保留现有译文']


def test_actual_translation_candidates_remain_unchanged():
    question={'question_type':'translation','candidates':['您是真的很喜欢这些动物对吧？']}
    assert clean(question) is question
