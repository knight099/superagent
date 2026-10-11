"""Deterministic candidate-tool evaluations on owner-selected disposable databases."""
from datetime import datetime,timezone
import json
from typing import Literal
import psycopg
from pydantic import Field
from .models import StrictModel,Name,Scalar
from .schema import introspect
from .executor import Executor
from .config import parse_user_id
from .revisions import schema_revision,policy_revision,digest
from .audit import json_safe
from .tools.models import ToolManifest
from .tools.models import Revision
from .tools.registry import artifact_digest
from .tools.binding import bind
from .validation import Rejection


class EvaluationCase(StrictModel):
    id: Name
    kind: Literal['functional','authorization','invariant'] = 'functional'
    identity: dict[Literal['user_id'],str | int]
    arguments: dict[Name,Scalar]
    expected_status: Literal['committed','rejected']
    expected_error: str | None = Field(default=None,max_length=100)
    expected_rows: dict[Name,list[dict[Name,Scalar]]] | None = Field(default=None,min_length=1)


def database_identity(url):
    with psycopg.connect(url,connect_timeout=5) as conn:
        return conn.execute('''SELECT current_database(),
            (SELECT oid FROM pg_database WHERE datname=current_database()),
            pg_postmaster_start_time()''').fetchone()


class EvaluationResult(StrictModel):
    id: Name
    kind: Literal['functional','authorization','invariant']
    expected_status: Literal['committed','rejected']
    actual_status: Literal['committed','rejected']
    passed: bool
    error_code: str | None = Field(default=None,max_length=100)
    asserted_result: bool
    authorization_guard: bool = False


class EvaluationReport(StrictModel):
    format_version: Literal[1]
    app: Name
    tool_id: Name
    version: int = Field(ge=1)
    digest: Revision
    schema_revision: Revision
    policy_revision: Revision
    suite_revision: Revision
    created_at: str = Field(max_length=64)
    passed: bool
    case_count: int = Field(ge=1,le=100)
    functional_checks: int = Field(ge=0,le=100)
    authorization_checks: int = Field(ge=0,le=100)
    results: list[EvaluationResult] = Field(min_length=1,max_length=100)


def evaluate(manifest,cases,config,database_url,*,production_url=None):
    manifest=ToolManifest.model_validate(manifest.model_dump())
    if production_url is not None and database_identity(database_url)==database_identity(production_url):
        raise Rejection('evaluations require a separate disposable database')
    if manifest.app!=config.app:
        raise Rejection('evaluation application mismatch')
    if not isinstance(cases,list) or not 1<=len(cases)<=100:
        raise Rejection('evaluation requires 1..100 explicit cases')
    suite=[EvaluationCase.model_validate(case) for case in cases]
    if len({case.id for case in suite})!=len(suite) or len(json.dumps(cases))>131072:
        raise Rejection('evaluation suite is invalid or exceeds bounds')
    results=[]
    with psycopg.connect(database_url,autocommit=True) as conn:
        catalog=introspect(conn,config)
        if (schema_revision(catalog,config)!=manifest.schema_revision
                or policy_revision(config)!=manifest.policy_revision):
            raise Rejection('evaluation schema/policy does not match candidate')
        for case in suite:
            status='committed'
            code=None
            checks=True
            try:
                with conn.transaction(force_rollback=True):
                    user=parse_user_id(str(case.identity.get('user_id')),config.auth)
                    # Reject JSON boolean/string coercion mismatches in the identity contract.
                    if type(case.identity.get('user_id')) is not type(user):
                        raise Rejection('evaluation identity type mismatch')
                    plan=bind(manifest,case.arguments,{'user_id':user})
                    changes=Executor(config,catalog).execute(conn,plan,{'user_id':user})
                    if case.expected_rows is not None:
                        by_id={change['id']:json_safe(change['rows']) for change in changes}
                        for op,expected in case.expected_rows.items():
                            actual=by_id.get(op)
                            if actual is None or len(actual)!=len(expected):
                                checks=False
                                continue
                            for row,wanted in zip(actual,expected):
                                if any(key not in row or row[key]!=value for key,value in wanted.items()):
                                    checks=False
            except Exception as exc:
                status='rejected'
                code=exc.sqlstate if isinstance(exc,psycopg.Error) else (
                    'rejected' if isinstance(exc,ValueError) else 'evaluation_error')
            passed=(status==case.expected_status and checks
                    and (case.expected_error is None or case.expected_error==code))
            authorization_guard=(case.kind=='authorization' and passed and (
                (status=='rejected' and case.expected_error=='rejected') or
                (status=='committed' and case.expected_rows is not None
                 and all(not rows for rows in case.expected_rows.values()))))
            results.append({'id':case.id,'kind':case.kind,'expected_status':case.expected_status,
                'actual_status':status,'passed':passed,'error_code':code,
                'authorization_guard':authorization_guard,
                'asserted_result':case.expected_rows is not None or case.expected_error is not None})
    passed=(all(case['passed'] for case in results)
            and any(c['kind']=='functional' and c['actual_status']=='committed'
                    and c['asserted_result'] for c in results)
            and any(c['authorization_guard'] for c in results))
    return {'format_version':1,'app':manifest.app,'tool_id':manifest.tool_id,'version':manifest.version,
        'digest':artifact_digest(manifest),'schema_revision':manifest.schema_revision,
        'policy_revision':manifest.policy_revision,'suite_revision':digest(cases),
        'created_at':datetime.now(timezone.utc).isoformat(),'passed':passed,
        'case_count':len(results),'functional_checks':sum(c['kind']=='functional' and c['passed'] for c in results),
        'authorization_checks':sum(c['authorization_guard'] for c in results),
        'results':results}


def verify_report(report,manifest):
    report=EvaluationReport.model_validate(report).model_dump()
    if (not isinstance(report,dict) or report.get('format_version')!=1 or report.get('passed') is not True
            or report.get('digest')!=artifact_digest(manifest)
            or report.get('app')!=manifest.app or report.get('tool_id')!=manifest.tool_id
            or report.get('version')!=manifest.version
            or report.get('schema_revision')!=manifest.schema_revision
            or report.get('policy_revision')!=manifest.policy_revision):
        raise Rejection('passing evaluation evidence must match this tool and revisions')
    results=report.get('results',[])
    if (not isinstance(results,list) or not 2<=len(results)<=100
            or report.get('case_count')!=len(results)
            or len({case['id'] for case in results})!=len(results)
            or any(case.get('passed') is not True for case in results)
            or any(c['actual_status']!=c['expected_status'] for c in results)
            or not any(c.get('kind')=='functional' and c.get('actual_status')=='committed'
                       and c.get('asserted_result') is True for c in results)
            or report['functional_checks']!=sum(c['kind']=='functional' and c['passed'] for c in results)
            or report['authorization_checks']!=sum(c['authorization_guard'] for c in results)
            or not any(c.get('kind')=='authorization' and c.get('asserted_result') is True
                       and c['authorization_guard'] for c in results)):
        raise Rejection('evaluation needs passing functional and asserted authorization cases')
    return report
