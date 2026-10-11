import pytest
from pydantic import ValidationError
from superagent.models import TransitionPlan
from superagent.config import Config
from superagent.schema import Catalog, Column, Table
from superagent.validation import validate, Rejection
from superagent.compiler import compile_operation


def config():
    return Config.model_validate({'app': 'test', 'tables': {'public.tasks': {
        'columns': ['id', 'title', 'creator_id', 'done'],
        'permissions': {'select': True, 'insert': True, 'update': True, 'delete': True}
    }}})


def catalog():
    return Catalog(tables={'public.tasks': Table(schema='public', name='tasks', columns={
        'id': Column(name='id', type='integer', nullable=False, default=True, generated=True),
        'title': Column(name='title', type='text', nullable=False),
        'creator_id': Column(name='creator_id', type='integer', nullable=False),
        'done': Column(name='done', type='boolean', nullable=False, default=True),
    }, primary_key=['id'])})


def plan(op):
    return TransitionPlan.model_validate({'version': 1, 'operations': [op]})


def insert(**kw):
    return {'id': 'create', 'kind': 'insert', 'table': 'public.tasks',
            'values': {'title': 'hello', 'creator_id': 1}, 'returning': ['id'], **kw}


@pytest.mark.parametrize('op', [insert(sql='DROP TABLE tasks'),
    {'id':'read','kind':'sql','table':'public.tasks'},
    {'id':'change','kind':'update','table':'public.tasks','values':{'done':True}},
    {'id':'read','kind':'select','table':'public.tasks','select':['id'],'limit':'10'}])
def test_strict_plan_rejects_unknown_unbounded_or_coerced_input(op):
    with pytest.raises(ValidationError):
        plan(op)


@pytest.mark.parametrize('op', [insert(table='private.tasks'),
    insert(values={'title':'x', 'creator_id':1, 'secret':'hidden'}),
    insert(values={'title':'x'}), insert(values={'title':'x','creator_id':1,'id':9}),
    {'id':'read','kind':'select','table':'superagent_internal.audit','select':['id']},
    {'id':'read','kind':'select','table':'public.tasks','select':['*']}])
def test_unknown_disallowed_missing_and_generated_fields_fail(op):
    with pytest.raises((Rejection, ValidationError)):
        validate(plan(op), catalog(), config())


def test_values_are_parameters_not_sql():
    value = "'); DROP TABLE tasks; --"
    op = plan(insert(values={'title':value,'creator_id':1})).operations[0]
    validate(plan(insert(values={'title':value,'creator_id':1})), catalog(), config())
    statement = compile_operation(op)
    assert value not in statement.sql.as_string()
    assert statement.params == [value, 1]
    assert '"public"."tasks"' in statement.sql.as_string()
    assert '%s' in statement.sql.as_string()


def test_where_and_limits_are_bound():
    op = plan({'id':'change','kind':'update','table':'public.tasks','values':{'done':True},
               'where':[{'field':'creator_id','op':'eq','value':7}]}).operations[0]
    s = compile_operation(op)
    assert s.params == [True, 7]
    assert '"creator_id" = %s' in s.sql.as_string()


def test_limits_and_denied_permissions():
    cfg = config()
    cfg.limits.max_operations = 1
    p = TransitionPlan.model_validate({'operations':[insert(), insert(id='second')]})
    with pytest.raises(Rejection):
        validate(p, catalog(), cfg)
    cfg.tables['public.tasks'].permissions = {}
    with pytest.raises(Rejection):
        validate(plan(insert()), catalog(), cfg)


def test_references_must_be_prior_and_returned():
    p = plan(insert(values={'title':'x','creator_id':{'ref':'future','column':'id'}}))
    with pytest.raises(Rejection):
        validate(p, catalog(), config())


def test_predicate_null_and_in_contract():
    with pytest.raises(ValidationError):
        plan({'id':'r','kind':'select','table':'public.tasks','select':['id'],
              'where':[{'field':'id','op':'in','value':[]}]})


def test_reserved_schema_config_and_empty_allowlist_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate({'app':'bad','tables':{'superagent_internal.audit':{
            'columns':['id'],'permissions':{'select':True}}}})


@pytest.mark.parametrize('value', ['1', True, 1.5])
def test_integer_columns_reject_incompatible_literals(value):
    with pytest.raises(Rejection, match='type'):
        validate(plan(insert(values={'title':'x','creator_id':value})),catalog(),config())


def test_reference_types_must_be_compatible():
    p = TransitionPlan.model_validate({'operations':[
        {'id':'r','kind':'select','table':'public.tasks','select':['title']},
        insert(values={'title':'x','creator_id':{'ref':'r','column':'title'}})]})
    with pytest.raises(Rejection, match='type'):
        validate(p,catalog(),config())


def test_application_policy_config_roundtrips_without_relaxing_arity():
    from superagent.config import Config,load_config
    from superagent.models import Expression
    cfg=load_config('examples/project_management/config.yaml')
    assert Config.model_validate(cfg.model_dump()).model_dump()==cfg.model_dump()
    with pytest.raises(ValueError):
        Expression.model_validate({'op':'any','args':[True],'left':None})
