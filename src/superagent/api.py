"""Thin HTTP adapters. Trusted identity headers require an authenticating gateway."""
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from .models import StrictModel, Name, Scalar
from .config import parse_user_id
from .tools.service import ToolService
from .guardrails import BodyLimit
from . import __version__


class ExecuteRequest(StrictModel):
    intent: str = Field(min_length=1, max_length=8000)
    dry_run: bool = False


class ToolExecuteRequest(StrictModel):
    version: int = Field(ge=1)
    arguments: dict[Name, Scalar] = Field(default_factory=dict,max_length=100)
    dry_run: bool = False


def create_app(runtime):
    app = FastAPI(title='Superagent', version=__version__)
    app.add_middleware(BodyLimit)
    tools = ToolService(runtime)

    def identity(x_user_id):
        if runtime.config.auth.mode == 'dev' and x_user_id is None:
            x_user_id = '1'
        if x_user_id is None or not x_user_id.strip() or len(x_user_id) > 128:
            raise HTTPException(status_code=401, detail='Authenticated X-User-ID required')
        try:
            return {'user_id':parse_user_id(x_user_id, runtime.config.auth)}
        except ValueError:
            raise HTTPException(status_code=401, detail='Invalid identity format') from None

    def response(result):
        status = 200
        if result['status'] == 'rejected':
            status = 503 if result['error']['code'] == 'audit_unavailable' else 422
            if 'conflicts' in result['error']['message']:
                status = 409
        return JSONResponse(result,status_code=status)

    @app.get('/health')
    def health():
        return {'status':'ok','version':__version__}

    @app.post('/v1/execute')
    def execute(body: ExecuteRequest, x_user_id: str | None = Header(default=None),
                idempotency_key: str | None = Header(default=None)):
        return response(runtime.execute(body.intent,identity(x_user_id),idempotency_key,
                                        dry_run=body.dry_run))

    @app.post('/v1/tools/{tool_id}/execute')
    def execute_tool(tool_id: str, body: ToolExecuteRequest,
                     x_user_id: str | None = Header(default=None),
                     idempotency_key: str | None = Header(default=None)):
        return response(tools.execute(tool_id,body.version,body.arguments,
                                      identity(x_user_id),idempotency_key,dry_run=body.dry_run))

    return app
