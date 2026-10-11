from copy import deepcopy
from superagent.config import Config
from superagent.schema import Catalog, Table, Column


def fixture():
    cfg=Config.model_validate({'app':'app','tables':{'public.items':{
        'columns':['id','owner_id','title'],'permissions':{'select':True}}}})
    cat=Catalog({'public.items':Table('public','items',{
        'id':Column('id','integer',False), 'owner_id':Column('owner_id','integer',False),
        'title':Column('title','text',False), 'secret':Column('secret','text',True)},['id'])})
    return cfg,cat


def test_revisions_stable_under_order_and_provider_changes():
    from superagent.revisions import schema_revision,policy_revision
    cfg,cat=fixture()
    changed=cfg.model_copy(deep=True)
    changed.tables['public.items'].columns.reverse()
    changed.planner.model='other'
    changed.app='another'
    reordered=deepcopy(cat)
    reordered.tables['public.items'].columns=dict(reversed(list(cat.tables['public.items'].columns.items())))
    assert schema_revision(cat,cfg)==schema_revision(reordered,changed)
    assert policy_revision(cfg)==policy_revision(changed)


def test_revisions_change_on_column_permission_or_limit_changes():
    from superagent.revisions import schema_revision,policy_revision
    cfg,cat=fixture()
    before=schema_revision(cat,cfg)
    cat.tables['public.items'].columns['title'].nullable=True
    assert schema_revision(cat,cfg)!=before
    before=policy_revision(cfg)
    cfg.tables['public.items'].permissions['select']=False
    assert policy_revision(cfg)!=before
    before=policy_revision(cfg)
    cfg.limits.max_rows=3
    assert policy_revision(cfg)!=before


def test_hidden_column_does_not_change_visible_revision():
    from superagent.revisions import schema_revision
    cfg,cat=fixture()
    before=schema_revision(cat,cfg)
    cat.tables['public.items'].columns['secret'].type='integer'
    assert schema_revision(cat,cfg)==before
