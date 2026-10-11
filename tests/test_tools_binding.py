import pytest
from pydantic import ValidationError


def manifest_data():
    return {'app':'test','tool_id':'create_task','version':1,'description':'Create an owned task',
        'schema_revision':'a'*64,'policy_revision':'b'*64,
        'inputs':{'title':{'type':'string','max_length':80}},
        'plan':{'operations':[{'id':'create','kind':'insert','table':'public.tasks',
            'values':{'title':{'argument':'title'},'creator_id':{'identity':'user_id'},
                      'assignee_id':2,'project_id':1,'due_date':'2099-01-01'},
            'returning':['id','title']}]}}


def test_same_tool_binds_distinct_caller_identity():
    from superagent.tools.models import ToolManifest
    from superagent.tools.binding import bind
    tool=ToolManifest.model_validate(manifest_data())
    for identity in (1,2):
        plan=bind(tool,{'title':'task'},{'user_id':identity})
        assert plan.operations[0].values['creator_id']==identity
        assert plan.operations[0].values['title']=='task'
    assert manifest_data()['plan']['operations'][0]['values']['creator_id']=={'identity':'user_id'}


@pytest.mark.parametrize('arguments',[{'title':'x','user_id':2},{}, {'title':80},
    {'title':'x'*81}, {'title':'x','unexpected':1}])
def test_typed_inputs_and_identity_overrides_rejected(arguments):
    from superagent.tools.models import ToolManifest
    from superagent.tools.binding import bind
    with pytest.raises(ValueError):
        bind(ToolManifest.model_validate(manifest_data()),arguments,{'user_id':1})


@pytest.mark.parametrize('field,value',[('table',{'argument':'title'}),
    ('kind',{'argument':'title'}),('sql','DROP TABLE tasks'),('code','exec("bad")')])
def test_structure_slots_and_code_rejected(field,value):
    from superagent.tools.models import ToolManifest
    data=manifest_data()
    data['plan']['operations'][0][field]=value
    with pytest.raises(ValidationError):
        ToolManifest.model_validate(data)


def test_undeclared_slot_rejected():
    from superagent.tools.models import ToolManifest
    data=manifest_data()
    data['inputs']={}
    with pytest.raises(ValueError):
        ToolManifest.model_validate(data)


def test_defaults_and_numeric_constraints():
    from superagent.tools.models import ToolManifest
    from superagent.tools.binding import bind
    data=manifest_data()
    data['inputs']['project']={'type':'integer','required':False,'default':1,'minimum':1,'maximum':3}
    data['plan']['operations'][0]['values']['project_id']={'argument':'project'}
    tool=ToolManifest.model_validate(data)
    assert bind(tool,{'title':'task'},{'user_id':1}).operations[0].values['project_id']==1
    for value in (True,0,4,1.5,None):
        with pytest.raises(ValueError):
            bind(tool,{'title':'task','project':value},{'user_id':1})


def test_predicate_list_and_calculation_slots_preserve_reference_structure():
    from superagent.tools.models import ToolManifest
    from superagent.tools.binding import bind
    data=manifest_data()
    data['inputs']={'increment':{'type':'integer'},'id':{'type':'integer'}}
    data['plan']={'operations':[
        {'id':'get','kind':'select','table':'public.tasks','select':['id'],
         'where':[{'field':'id','op':'in','value':[{'argument':'id'}]}]},
        {'id':'set','kind':'update','table':'public.tasks','values':{
          'project_id':{'calc':'add','left':{'ref':'get','column':'id'},'right':{'argument':'increment'}}},
         'where':[{'field':'id','op':'eq','value':{'ref':'get','column':'id'}}]}]}
    tool=ToolManifest.model_validate(data)
    bound=bind(tool,{'increment':2,'id':1},{'user_id':1})
    assert bound.operations[0].where[0].value==[1]
    assert bound.operations[1].values['project_id'].right==2
