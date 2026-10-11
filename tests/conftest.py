import os
from pathlib import Path
import pytest
import psycopg
from superagent.config import Config
from superagent.schema import introspect


@pytest.fixture
def db_url():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('set TEST_DATABASE_URL to a disposable real PostgreSQL database')
    return url


@pytest.fixture
def db(db_url):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute('DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public')
        conn.execute('DROP SCHEMA IF EXISTS superagent_internal CASCADE')
        conn.execute('DROP SCHEMA IF EXISTS hidden CASCADE')
        conn.execute(Path('examples/project_management/schema.sql').read_text())
        yield conn


@pytest.fixture
def cfg():
    columns = ['id','title','project_id','creator_id','assignee_id','priority','done',
               'created_at','due_date']
    return Config.model_validate({'app':'test','tables':{
        'public.tasks':{'columns':columns,'permissions':{
            'select':True,'insert':True,'update':True,'delete':True}},
        'public.users':{'columns':['id','name'],'permissions':{'select':True}},
        'public.projects':{'columns':['id','name','owner_id','due_date'],
                           'permissions':{'select':True}},
        'public.project_members':{'columns':['project_id','user_id'],
                                 'permissions':{'select':True}},
    }})


@pytest.fixture
def cat(db, cfg):
    return introspect(db, cfg)
