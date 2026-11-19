import math

import pytest

from video_translate.agent import autonomous as agent


def state():
    return {'controller_version':2,'counts':{},'events':[],'sources':{},'captions':[],
            'language':'chinese','evidence':{},'user_confirmations':{},'probe':{'duration':337.27},'media':'/owned/video.mp4'}


@pytest.mark.parametrize('times', ['15,100,200,310', '[15,100,200,310]', ['15','100','200','310'], [15,100,200,310]])
def test_unambiguous_frame_numbers_are_normalized_without_changing_points(times):
    call={'tool':'sample_frames','args':{'times':times}}
    normalized=agent.normalize_call(call)
    assert agent.validate_call(normalized,state())==('sample_frames',{'times':[15,100,200,310]})
    assert call['args']['times']==times


@pytest.mark.parametrize('times', ['1:30,2:00','about 30 seconds','15,100;200','1,2,3,4,5',None,{},[True],['hello'],[math.inf],[10**400],[-1],[337.27],[1,1]])
def test_repairs_never_guess_clamp_drop_or_authorize_bad_times(times):
    with pytest.raises(agent.ToolArgumentError):
        agent.validate_call(agent.normalize_call({'tool':'sample_frames','args':{'times':times}}),state())


def test_argument_error_identifies_field_type_and_array_example():
    with pytest.raises(agent.ToolArgumentError) as error:
        agent.validate_call({'tool':'sample_frames','args':{'times':'15,100,200,310'}},state())
    assert error.value.details['code']=='times_type'
    assert error.value.details['field']=='times'
    assert isinstance(error.value.details['example']['args']['times'],list)
    assert 'JSON数字数组' in str(error.value)


def test_format_repair_still_rejects_used_frames_and_other_tool_arguments():
    s=state();s['frame_history']=[{'time_seconds':15}]
    with pytest.raises(agent.ToolArgumentError,match='重复'):
        agent.validate_call(agent.normalize_call({'tool':'sample_frames','args':{'times':'15,100'}}),s)
    with pytest.raises(ValueError,match='授权'):
        agent.validate_call(agent.normalize_call({'tool':'sample_frames','args':{'times':'15,100','url':'https://example.com'}}),state())


def test_frame_schema_explicitly_requires_a_number_array():
    spec=agent.SPEC['sample_frames'].arguments['times']
    assert spec['type']=='array' and spec['items']['type']=='number'
    assert spec['maxItems']==4
