import pytest
from superagent.models import Expression, TransitionPlan
from superagent.policy import evaluate, policy_sql
from superagent.executor import Executor
from superagent.validation import Rejection


def expr(source='row', field='creator_id', claim='user_id'):
    return Expression.model_validate({'op':'eq','left':{'source':source,'field':field},
                                     'right':{'source':'identity','field':claim}})


def change(**values):
    return TransitionPlan.model_validate({'operations':[{'id':'u','kind':'update',
        'table':'public.tasks','values':values,'returning':['id'],
        'where':[{'field':'id','op':'eq','value':1}]}]})


def test_expression_allow_and_deny():
    rule = expr()
    assert evaluate(rule, {'row':{'creator_id':1},'identity':{'user_id':1}}) is True
    assert evaluate(rule, {'row':{'creator_id':1},'identity':{'user_id':2}}) is False


def test_missing_identity_cannot_allow_negation():
    rule = Expression(op='not',args=[expr()])
    with pytest.raises(Rejection, match='missing'):
        evaluate(rule, {'row':{'creator_id':1},'identity':{}})
    with pytest.raises(Rejection, match='missing'):
        policy_sql(rule, {})


def test_null_comparisons_under_negation_fail_closed():
    rule = Expression(op='not',args=[expr()])
    assert evaluate(rule, {'row':{'creator_id':None},'identity':{'user_id':1}}) is None


def test_unauthorized_update_rejected(db, cfg, cat):
    cfg.tables['public.tasks'].permissions['update'] = expr()
    with pytest.raises(Rejection):
        Executor(cfg, cat).execute(db, change(title='stolen'), {'user_id':2})
    assert db.execute('SELECT title FROM tasks WHERE id=1').fetchone()[0] == 'Fix login'


def test_read_policy_filters_rows(db, cfg, cat):
    cfg.tables['public.tasks'].permissions['select'] = expr()
    p = TransitionPlan.model_validate({'operations':[{'id':'r','kind':'select',
        'table':'public.tasks','select':['id']}]})
    result = Executor(cfg, cat).execute(db,p,{'user_id':1})
    assert {r['id'] for r in result[0]['rows']} == {1,2}


def test_null_policy_not_does_not_leak_rows(db, cfg, cat):
    db.execute('ALTER TABLE tasks ADD COLUMN optional_owner integer')
    cfg.tables['public.tasks'].columns.append('optional_owner')
    from superagent.schema import introspect
    cat = introspect(db,cfg)
    cfg.tables['public.tasks'].permissions['select'] = Expression(
        op='not',args=[expr(field='optional_owner')])
    p = TransitionPlan.model_validate({'operations':[{'id':'r','kind':'select',
        'table':'public.tasks','select':['id']}]})
    assert Executor(cfg, cat).execute(db,p,{'user_id':1})[0]['rows'] == []


def test_owner_change_after_rule_rolls_back(db, cfg, cat):
    cfg.tables['public.tasks'].permissions['update'] = expr()
    cfg.tables['public.tasks'].after['update'] = Expression.model_validate({
        'op':'eq','left':{'source':'after','field':'creator_id'},
        'right':{'source':'before','field':'creator_id'}})
    with pytest.raises(Rejection, match='after'):
        Executor(cfg, cat).execute(db, change(creator_id=2), {'user_id':1})
    assert db.execute('SELECT creator_id FROM tasks WHERE id=1').fetchone()[0] == 1


def test_completed_task_cannot_reopen(db, cfg, cat):
    db.execute('UPDATE tasks SET done=true WHERE id=1')
    cfg.tables['public.tasks'].invariants = [Expression.model_validate({'op':'not','args':[
        {'op':'all','args':[
            {'op':'eq','left':{'source':'before','field':'done'},'right':True},
            {'op':'eq','left':{'source':'after','field':'done'},'right':False}]}]})]
    with pytest.raises(Rejection, match='invariant'):
        Executor(cfg, cat).execute(db, change(done=False), {'user_id':1})
    assert db.execute('SELECT done FROM tasks WHERE id=1').fetchone()[0] is True


def test_insert_permission_checks_server_defaults(db, cfg, cat):
    cfg.tables['public.tasks'].permissions['insert'] = Expression.model_validate({
        'op':'eq','left':{'source':'row','field':'priority'},'right':'high'})
    p = TransitionPlan.model_validate({'operations':[{'id':'i','kind':'insert',
        'table':'public.tasks','values':{'title':'new','project_id':1,'creator_id':1,
                                       'assignee_id':2,'due_date':'2099-01-01'}}]})
    with pytest.raises(Rejection):
        Executor(cfg,cat).execute(db,p,{'user_id':1})
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0


def test_uuid_database_identity_matches_canonical_string():
    from uuid import UUID
    user_id='12345678-1234-5678-1234-567812345678'
    assert evaluate(expr(),{'row':{'creator_id':UUID(user_id)},
                            'identity':{'user_id':user_id}}) is True
