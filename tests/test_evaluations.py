import pytest
from superagent.config import load_config
from superagent.schema import introspect
from superagent.revisions import schema_revision,policy_revision
from test_tools_binding import manifest_data


def candidate(db):
    from superagent.tools.models import ToolManifest
    cfg=load_config('examples/project_management/config.yaml')
    cat=introspect(db,cfg)
    data=manifest_data()
    data.update(app=cfg.app,schema_revision=schema_revision(cat,cfg),policy_revision=policy_revision(cfg))
    return ToolManifest.model_validate(data),cfg


def cases():
    return [
        {'id':'owned','kind':'functional','identity':{'user_id':1},'arguments':{'title':'evaluated'},
         'expected_status':'committed','expected_rows':{'create':[{'title':'evaluated'}]}},
        {'id':'other_user','kind':'functional','identity':{'user_id':2},'arguments':{'title':'other'},
         'expected_status':'committed','expected_rows':{'create':[{'title':'other'}]}},
        {'id':'override','kind':'authorization','identity':{'user_id':1},
         'arguments':{'title':'attack','user_id':2},'expected_status':'rejected','expected_error':'rejected'}]


def test_evals_roll_back_rows_and_record_revision_bound_evidence(db,db_url):
    from superagent.evaluations import evaluate,verify_report
    tool,cfg=candidate(db)
    before=db.execute('SELECT count(*) FROM tasks').fetchone()[0]
    report=evaluate(tool,cases(),cfg,db_url)
    assert report['passed'] is True
    assert report['case_count']==3
    assert report['authorization_checks']==1
    assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
    verify_report(report,tool)
    altered=tool.model_copy(update={'version':2})
    with pytest.raises(ValueError):
        verify_report(report,altered)
    assert 'evaluated' not in str(report)


def test_eval_expected_result_mismatch_prevents_publish_evidence(db,db_url):
    from superagent.evaluations import evaluate,verify_report
    tool,cfg=candidate(db)
    suite=cases()
    suite[0]['expected_rows']['create'][0]['title']='incorrect'
    report=evaluate(tool,suite,cfg,db_url)
    assert report['passed'] is False
    with pytest.raises(ValueError):
        verify_report(report,tool)


def test_evaluation_refuses_application_database_and_missing_auth_cases(db,db_url):
    from superagent.evaluations import evaluate,verify_report
    tool,cfg=candidate(db)
    with pytest.raises(ValueError):
        evaluate(tool,cases(),cfg,db_url,production_url=db_url)
    report=evaluate(tool,cases()[:2],cfg,db_url)
    with pytest.raises(ValueError):
        verify_report(report,tool)


def test_publication_requires_passing_matching_eval_evidence(db,db_url):
    from superagent.audit import initialize_internal
    from superagent.evaluations import evaluate
    from superagent.tools.registry import ToolRegistry
    tool,cfg=candidate(db)
    initialize_internal(db)
    registry=ToolRegistry(db_url)
    with pytest.raises(ValueError):
        registry.publish(tool)
    evidence=evaluate(tool,cases(),cfg,db_url)
    assert registry.publish(tool,evaluation=evidence)
    changed=tool.model_copy(update={'version':2})
    with pytest.raises(ValueError):
        registry.publish(changed,evaluation=evidence)


def test_unrelated_database_failure_is_not_authorization_evidence(db,db_url):
    from superagent.evaluations import evaluate,verify_report
    tool,cfg=candidate(db)
    data=tool.model_dump()
    data['plan']['operations'][0]['values']['assignee_id']=999
    from superagent.tools.models import ToolManifest
    bad=ToolManifest.model_validate(data)
    suite=[{'id':'invalid_fk','kind':'authorization','identity':{'user_id':1},
        'arguments':{'title':'fails'},'expected_status':'rejected','expected_error':'23503'}]
    report=evaluate(bad,suite,cfg,db_url)
    assert report['authorization_checks']==0
    with pytest.raises(ValueError):
        verify_report(report,bad)


def test_empty_expected_map_does_not_claim_result_assertions(db,db_url):
    from superagent.evaluations import evaluate
    tool,cfg=candidate(db)
    suite=cases()
    suite[0]['expected_rows']={}
    with pytest.raises(ValueError):
        evaluate(tool,suite,cfg,db_url)
