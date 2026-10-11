"""Application-independent intent coordination, dry-run, audit, and replay."""
import json
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlsplit
import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from .models import TransitionPlan
from .compiler import compile_operation
from .executor import Executor
from .policy import policy_sql
from .validation import validate, Rejection
from .audit import write_audit, redact, json_safe
from .schema import introspect
from .revisions import schema_revision, policy_revision, digest


class Runtime:
    def __init__(self, database_url, config, catalog, planner=None):
        self.database_url = database_url
        self.config, self.catalog, self.planner = config, catalog, planner

    def _plan(self, intent, identity, supplied):
        if supplied is not None:
            data = supplied.model_dump() if isinstance(supplied, TransitionPlan) else supplied
            return TransitionPlan.model_validate(data)
        if self.planner is None:
            raise Rejection('no planner configured')
        from .usage import UsageLedger
        ledger = UsageLedger(self.database_url)
        provider_config = getattr(self.planner,'config',self.config.planner)
        attempt = ledger.begin(self.config.app,'intent_plan',
            urlsplit(provider_config.url).hostname or 'custom',provider_config.model)
        try:
            output = self.planner.plan(intent, self.catalog, self.config, identity)
            result = TransitionPlan.model_validate(output.model_dump() if isinstance(
                output, TransitionPlan) else output)
        except Exception:
            ledger.finish(attempt,'failed',getattr(self.planner,'usage',None),None)
            raise
        ledger.finish(attempt,'succeeded',getattr(self.planner,'usage',None),None)
        return result

    def explain(self, plan, identity, *, catalog=None):
        validate(plan, catalog or self.catalog, self.config)
        statements = []
        for op in plan.operations:
            statement = compile_operation(op).explain()
            rule = self.config.tables[op.table].permissions[op.kind]
            if op.kind != 'insert':
                policy = policy_sql(rule, identity)
                statement['row_policy'] = policy.explain()
            if any(t.sensitive_columns for t in self.config.tables.values()):
                statement['parameters'] = ['[REDACTED]'] * len(statement['parameters'])
                if 'row_policy' in statement:
                    statement['row_policy']['parameters'] = ['[REDACTED]'] * len(
                        statement['row_policy']['parameters'])
            statements.append(statement)
        return {'status':'explained','plan':redact(plan.model_dump(), self.config),
                'validation':{'static':'accepted','state_checks':'deferred'},
                'statements':statements,'limits':self.config.limits.model_dump(),
                'notice':'No plan statements executed. Row authorization, references, constraints '
                         'and invariants require execution-time checks.'}

    def execute(self, intent, identity, key=None, *, dry_run=False, plan=None,
                tool_request=None, registry=None):
        audit_id = str(uuid4())
        proposed = None
        started = datetime.now(timezone.utc).isoformat()
        record = {'audit_id':audit_id, 'app':self.config.app, 'identity':identity, 'intent':intent,
                  'started_at':started, 'dry_run':dry_run}
        try:
            if not isinstance(intent, str) or not intent.strip() or len(intent) > 8000:
                raise Rejection('intent must contain 1..8000 characters')
            if not isinstance(identity, dict) or type(identity.get('user_id')) not in (str,int):
                raise Rejection('stable authenticated user_id required')
            if type(identity['user_id']) is not (int if self.config.auth.user_id_type == 'integer' else str):
                raise Rejection('identity user_id type does not match auth configuration')
            if not str(identity['user_id']).strip() or len(json.dumps(identity)) > 4096:
                raise Rejection('invalid identity context')
            if key is not None and (not isinstance(key,str) or not 1 <= len(key) <= 128):
                raise Rejection('idempotency key must contain 1..128 characters')
            supplied = plan.model_dump() if isinstance(plan, TransitionPlan) else plan
            request_data = {'intent':intent, 'identity':identity, 'plan':supplied}
            if tool_request is not None:
                from .tools.models import ToolInvocation
                if plan is not None:
                    raise Rejection('tool requests cannot supply a separate plan')
                invocation = ToolInvocation.model_validate(tool_request)
                request_data['tool_request'] = invocation.model_dump()
                record['tool'] = {'tool_id':invocation.tool_id,'version':invocation.version}
            scope = json.dumps(identity['user_id'], sort_keys=True)
            catalog = self.catalog
            with psycopg.connect(self.database_url, autocommit=True) as conn:
                with conn.transaction():
                    conn.execute("SELECT set_config('statement_timeout', %s, true)",
                                 (str(self.config.limits.statement_timeout_ms),))
                    if tool_request is not None:
                        from .tools.registry import ToolRegistry, artifact_digest
                        from .tools.binding import bind
                        source = registry or ToolRegistry(self.database_url)
                        tool = source.load_for_execution(conn,self.config.app,
                                                         invocation.tool_id,invocation.version)
                        content = artifact_digest(tool)
                        record['tool'].update({'digest':content,'schema_revision':tool.schema_revision,
                                              'policy_revision':tool.policy_revision})
                        catalog = introspect(conn,self.config)
                        if (tool.schema_revision != schema_revision(catalog,self.config)
                                or tool.policy_revision != policy_revision(self.config)):
                            raise Rejection('tool schema or policy revision is incompatible; rebuild required')
                        plan = bind(tool,invocation.arguments,identity)
                        request_data['tool'] = record['tool']
                    fingerprint = digest(request_data)
                    if key is not None and not dry_run:
                        conn.execute('''INSERT INTO superagent_internal.requests
                            (app, identity, key, fingerprint) VALUES (%s,%s,%s,%s)
                            ON CONFLICT DO NOTHING''', (self.config.app, scope, key, fingerprint))
                        existing = conn.execute('''SELECT fingerprint, response
                            FROM superagent_internal.requests WHERE app=%s AND identity=%s AND key=%s
                            FOR UPDATE''', (self.config.app, scope, key)).fetchone()
                        if existing[0] != fingerprint:
                            raise Rejection('idempotency key conflicts with a different request')
                        if existing[1] is not None:
                            return existing[1]
                    proposed = self._plan(intent, identity, plan)
                    record['plan'] = proposed.model_dump()
                    if self.planner is not None and plan is None:
                        record['planner_usage'] = getattr(self.planner, 'usage', {})
                    validate(proposed, catalog, self.config)
                    if dry_run:
                        result = self.explain(proposed, identity, catalog=catalog)
                        result['audit_id'] = audit_id
                    else:
                        if key is None and any(o.kind != 'select' for o in proposed.operations):
                            raise Rejection('mutations require an idempotency key')
                        changes = Executor(self.config, catalog).execute(conn, proposed, identity)
                        result = {'status':'committed', 'summary':'Validated transition completed',
                                  'changes':redact([{k:v for k,v in change.items() if k != 'effects'}
                                                    for change in changes], self.config), 'audit_id':audit_id}
                        record['executed_operations'] = changes
                    result = json_safe(result)
                    record.update({'status':result['status'], 'validation':'accepted',
                                   'result':result, 'finished_at':datetime.now(timezone.utc).isoformat()})
                    write_audit(conn, audit_id, record, self.config)
                    if key is not None and not dry_run:
                        conn.execute('''UPDATE superagent_internal.requests SET response=%s
                            WHERE app=%s AND identity=%s AND key=%s''',
                            (Jsonb(result),self.config.app,scope,key))
                return result
        except Exception as exc:
            if isinstance(exc, Rejection):
                error = {'code':'rejected', 'message':str(exc)}
            elif isinstance(exc, ValidationError):
                error = {'code':'invalid_plan','message':'Plan does not match the strict schema'}
            elif isinstance(exc, psycopg.Error):
                error = {'code':exc.sqlstate or 'database_error',
                         'message':'Database rejected or interrupted the transition'}
            else:
                error = {'code':'planning_or_runtime_error','message':'Planning or execution failed'}
            result = {'status':'rejected','audit_id':audit_id,'error':error}
            if proposed is not None:
                record['plan'] = proposed.model_dump()
            record.update({'status':'rejected','validation':'rejected', 'error':error,
                           'finished_at':datetime.now(timezone.utc).isoformat()})
            try:
                with psycopg.connect(self.database_url, autocommit=True) as conn:
                    with conn.transaction():
                        conn.execute("SELECT set_config('statement_timeout', %s, true)",
                                     (str(self.config.limits.statement_timeout_ms),))
                        write_audit(conn, audit_id, record, self.config)
            except Exception:
                result['error'] = {'code':'audit_unavailable',
                                  'message':'Required audit storage is unavailable; no success reported'}
            return result
