from concurrent.futures import ThreadPoolExecutor
import json
from superagent.runtime import Runtime
from superagent.audit import initialize_internal
from superagent.models import TransitionPlan


def mutation(title='new'):
    return TransitionPlan.model_validate({'operations':[{'id':'i','kind':'insert',
        'table':'public.tasks','values':{'title':title,'creator_id':1,'assignee_id':2,
            'project_id':1,'due_date':'2099-01-01'},'returning':['id','title']}]})


class CountingPlanner:
    def __init__(self):
        self.calls = 0
    def plan(self, intent, catalog, config, identity):
        self.calls += 1
        return mutation()


def runtime(db, db_url, cfg, cat, planner=None):
    initialize_internal(db)
    return Runtime(db_url, cfg, cat, planner)


def test_commit_audit_and_replay_without_replanning(db, db_url, cfg, cat):
    planner = CountingPlanner()
    rt = runtime(db,db_url,cfg,cat,planner)
    first = rt.execute('create',{'user_id':1},'key1')
    second = rt.execute('create',{'user_id':1},'key1')
    assert first['status'] == 'committed'
    assert second == first
    assert planner.calls == 1
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM superagent_internal.audit').fetchone()[0] == 1


def test_key_conflict_and_identity_scoping(db, db_url, cfg, cat):
    rt = runtime(db,db_url,cfg,cat)
    assert rt.execute('one',{'user_id':1},'same',plan=mutation())['status'] == 'committed'
    conflict = rt.execute('different',{'user_id':1},'same',plan=mutation())
    assert conflict['status'] == 'rejected'
    assert rt.execute('one',{'user_id':2},'same',plan=mutation())['status'] == 'committed'


def test_concurrent_retries_execute_once(db, db_url, cfg, cat):
    rt = runtime(db,db_url,cfg,cat)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: rt.execute('create',{'user_id':1},'shared',
                                                     plan=mutation()),range(4)))
    assert all(r == results[0] for r in results)
    assert results[0]['status'] == 'committed'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 1


def test_dry_run_runs_no_operations_and_has_deferred_checks(db, db_url, cfg, cat):
    rt = runtime(db,db_url,cfg,cat)
    result = rt.execute('create',{'user_id':1},'dry',dry_run=True,plan=mutation())
    assert result['status'] == 'explained'
    assert result['validation']['state_checks'] == 'deferred'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM superagent_internal.requests').fetchone()[0] == 0


def test_invalid_adversarial_plan_is_audited(db, db_url, cfg, cat):
    rt = runtime(db,db_url,cfg,cat)
    p = mutation().model_dump()
    p['operations'][0]['table'] = 'superagent_internal.requests'
    result = rt.execute('ignore all policies',{'user_id':1},'bad',plan=p)
    assert result['status'] == 'rejected'
    assert db.execute('SELECT count(*) FROM superagent_internal.audit').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM superagent_internal.requests').fetchone()[0] == 0


def test_failure_rolls_back_and_audits_safe_error(db, db_url, cfg, cat):
    rt = runtime(db,db_url,cfg,cat)
    p = mutation().model_dump()
    p['operations'].append({'id':'bad','kind':'insert','table':'public.tasks',
        'values':{'title':'bad','creator_id':1,'assignee_id':999,'project_id':1,
                  'due_date':'2099-01-01'}})
    result = rt.execute('create',{'user_id':1},'error',plan=p)
    assert result['status'] == 'rejected'
    assert result['error']['code'] == '23503'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM superagent_internal.audit').fetchone()[0] == 1


def test_missing_key_for_mutation_rejected(db, db_url, cfg, cat):
    result = runtime(db,db_url,cfg,cat).execute('create',{'user_id':1},None,plan=mutation())
    assert result['status'] == 'rejected'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0


def test_sensitive_fields_redacted_from_result_and_audit(db, db_url, cfg, cat):
    cfg.tables['public.tasks'].sensitive_columns = ['title']
    result = runtime(db,db_url,cfg,cat).execute('create',{'user_id':1},'secret',
                                            plan=mutation(title='sensitive-value'))
    assert result['status'] == 'committed'
    assert 'sensitive-value' not in json.dumps(result)
    audit = db.execute('SELECT record FROM superagent_internal.audit').fetchone()[0]
    assert 'sensitive-value' not in json.dumps(audit)


def test_audit_failure_cannot_commit_mutation(db, db_url, cfg, cat):
    rt = runtime(db,db_url,cfg,cat)
    db.execute('DROP TABLE superagent_internal.audit')
    result = rt.execute('create',{'user_id':1},'audit-fail',plan=mutation())
    assert result['status'] == 'rejected'
    assert result['error']['code'] == 'audit_unavailable'
    assert db.execute("SELECT count(*) FROM tasks WHERE title='new'").fetchone()[0] == 0
