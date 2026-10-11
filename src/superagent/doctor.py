"""Read-only local diagnostics; never send inference or reveal credentials."""
import os
import psycopg
from .schema import introspect
from .revisions import schema_revision,policy_revision
from .tools.registry import ToolRegistry


def doctor(config,database_url):
    report={'app':config.app,'ready':False,'blockers':[], 'warnings':[],
            'planner_key_present':bool(os.environ.get(config.planner.key_env)),
            'incompatible_tools':[]}
    try:
        with psycopg.connect(database_url,connect_timeout=5) as conn:
            conn.execute("SELECT set_config('statement_timeout',%s,true)",
                         (str(config.limits.statement_timeout_ms),))
            if int(conn.execute("SELECT current_setting('server_version_num')").fetchone()[0])<160000:
                report['blockers'].append('PostgreSQL 16+ required')
            for table in ('audit','requests','tools','model_attempts'):
                if conn.execute('SELECT to_regclass(%s)',(f'superagent_internal.{table}',)).fetchone()[0] is None:
                    report['blockers'].append('Internal tables missing; run init-db')
                    break
            catalog=introspect(conn,config)
            report['schema_revision']=schema_revision(catalog,config)
            report['policy_revision']=policy_revision(config)
            report['allowed_tables']=len(config.tables)
            if conn.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0]:
                report['warnings'].append('Use a restricted database runtime role before deployment')
        if not report['blockers']:
            registry=ToolRegistry(database_url)
            for entry in registry.list(config.app):
                if entry['status']!='active':
                    continue
                manifest=registry.get(config.app,entry['tool_id'],entry['version'])
                if (manifest.schema_revision!=report['schema_revision']
                        or manifest.policy_revision!=report['policy_revision']):
                    report['incompatible_tools'].append({'tool_id':entry['tool_id'],'version':entry['version']})
            if report['incompatible_tools']:
                report['blockers'].append('Active tools require rebuild after schema or policy change')
        if not report['planner_key_present']:
            report['warnings'].append('AI credential absent; approved tools can run with --tools-only')
        report['ready']=not report['blockers']
    except Exception:
        report['blockers'].append('Database/configuration check failed; inspect local setup')
    return report
