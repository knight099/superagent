from datetime import date, timedelta
import pytest
from psycopg.errors import ForeignKeyViolation, QueryCanceled
from superagent.models import TransitionPlan
from superagent.executor import Executor
from superagent.validation import Rejection


def plan(*ops):
    return TransitionPlan.model_validate({'operations':list(ops)})


def update(id='u', **values):
    return {'id':id,'kind':'update','table':'public.tasks','values':values,
            'where':[{'field':'id','op':'eq','value':1}], 'returning':['id','title','due_date']}


def test_introspection_metadata(db, cfg, cat):
    task = cat.tables['public.tasks']
    assert task.primary_key == ['id']
    assert task.columns['id'].generated
    assert task.columns['done'].default
    assert not task.columns['title'].nullable
    assert {'p','f','c'} <= {c['kind'] for c in task.constraints}
    assert cat.tables['public.project_members'].primary_key == ['project_id','user_id']


def test_atomic_commit(db, cfg, cat):
    result = Executor(cfg, cat).execute(db, plan(update(title='Changed')), {'user_id':1})
    assert result[0]['rows'][0]['title'] == 'Changed'
    assert db.execute('SELECT title FROM tasks WHERE id=1').fetchone()[0] == 'Changed'


def test_late_failure_rolls_back(db, cfg, cat):
    with pytest.raises(ForeignKeyViolation):
        Executor(cfg, cat).execute(db, plan(update(title='Changed'),
            update(id='bad',assignee_id=999)), {'user_id':1})
    assert db.execute('SELECT title FROM tasks WHERE id=1').fetchone()[0] == 'Fix login'


def test_references_resolve_one_row(db, cfg, cat):
    lookup = {'id':'who','kind':'select','table':'public.users','select':['id'],
              'where':[{'field':'name','op':'eq','value':'Rahul'}]}
    result = Executor(cfg, cat).execute(db, plan(lookup, update(
        assignee_id={'ref':'who','column':'id'})), {'user_id':1})
    assert result[1]['affected'] == 1
    assert db.execute('SELECT assignee_id FROM tasks WHERE id=1').fetchone()[0] == 2


def test_ambiguous_references_abort(db, cfg, cat):
    lookup = {'id':'who','kind':'select','table':'public.users','select':['id']}
    with pytest.raises(Rejection, match='exactly one'):
        Executor(cfg, cat).execute(db, plan(update(title='Nope'), lookup,
            update(id='last',assignee_id={'ref':'who','column':'id'})), {'user_id':1})
    assert db.execute('SELECT title FROM tasks WHERE id=1').fetchone()[0] == 'Fix login'


def test_row_bound_rolls_back_instead_of_truncating(db, cfg, cat):
    cfg.limits.max_rows = 1
    op = update(title='Nope')
    op['where'] = [{'field':'creator_id','op':'eq','value':1}]
    with pytest.raises(Rejection, match='row limit'):
        Executor(cfg, cat).execute(db, plan(op), {'user_id':1})
    assert db.execute("SELECT count(*) FROM tasks WHERE title='Nope'").fetchone()[0] == 0


def test_calculation_is_bounded_and_parameters(db, cfg, cat):
    lookup = {'id':'task','kind':'select','table':'public.tasks','select':['due_date'],
              'where':[{'field':'id','op':'eq','value':1}]}
    old = db.execute('SELECT due_date FROM tasks WHERE id=1').fetchone()[0]
    result = Executor(cfg, cat).execute(db, plan(lookup, update(due_date={
        'calc':'date_add_days','left':{'ref':'task','column':'due_date'},'right':3})), {})
    assert result[1]['rows'][0]['due_date'] == old + timedelta(days=3)
    assert old >= date.today()


def test_read_limit(db, cfg, cat):
    result = Executor(cfg, cat).execute(db, plan({'id':'r','kind':'select',
        'table':'public.users','select':['id'],'limit':1}), {})
    assert len(result[0]['rows']) == 1


def test_timeout_is_local_and_rolls_back(db, cfg, cat):
    db.execute('''CREATE FUNCTION slow_task() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN PERFORM pg_sleep(0.1); RETURN NEW; END $$;
        CREATE TRIGGER slow BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION slow_task()''')
    cfg.limits.statement_timeout_ms = 10
    with pytest.raises(QueryCanceled):
        Executor(cfg, cat).execute(db, plan(update(title='Nope')), {})
    assert db.execute('SHOW statement_timeout').fetchone()[0] == '0'
    assert db.execute('SELECT title FROM tasks WHERE id=1').fetchone()[0] == 'Fix login'


def test_numeric_reference_addition_preserves_postgres_decimal(db,cfg):
    from decimal import Decimal
    from superagent.schema import introspect
    db.execute('ALTER TABLE tasks ADD COLUMN estimate numeric(12,2) NOT NULL DEFAULT 10.25')
    cfg.tables['public.tasks'].columns.append('estimate')
    cat=introspect(db,cfg)
    lookup={'id':'cost','kind':'select','table':'public.tasks','select':['estimate'],
            'where':[{'field':'id','op':'eq','value':1}]}
    op=update(estimate={'calc':'add','left':{'ref':'cost','column':'estimate'},'right':0.1})
    op['returning']=['estimate']
    result=Executor(cfg,cat).execute(db,plan(lookup,op),{})
    assert result[1]['rows'][0]['estimate'] == Decimal('10.35')


def test_uuid_creator_insert_permission_works_for_string_identity(db,cfg):
    from superagent.schema import introspect
    from superagent.models import Expression
    user='12345678-1234-5678-1234-567812345678'
    db.execute('ALTER TABLE tasks ADD COLUMN owner_uuid uuid')
    cfg.tables['public.tasks'].columns.append('owner_uuid')
    cfg.tables['public.tasks'].permissions['insert']=Expression.model_validate({
        'op':'eq','left':{'source':'row','field':'owner_uuid'},
        'right':{'source':'identity','field':'user_id'}})
    cat=introspect(db,cfg)
    p=plan({'id':'i','kind':'insert','table':'public.tasks','values':{
        'title':'UUID owned','creator_id':1,'assignee_id':2,'project_id':1,
        'due_date':'2099-01-01','owner_uuid':user},'returning':['owner_uuid']})
    result=Executor(cfg,cat).execute(db,p,{'user_id':user})
    assert str(result[0]['rows'][0]['owner_uuid']) == user
