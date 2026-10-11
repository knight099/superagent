"""Thin intent HTTP adapter. Trusted headers require an authenticating gateway."""
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from .models import StrictModel
from .config import parse_user_id


class ExecuteRequest(StrictModel):
    intent: str = Field(min_length=1, max_length=8000)
    dry_run: bool = False


def create_app(runtime):
    app = FastAPI(title='Superagent', version='0.1.0')

    @app.get('/health')
    def health():
        return {'status':'ok','version':'0.1.0'}

    @app.post('/v1/execute')
    def execute(body: ExecuteRequest, x_user_id: str | None = Header(default=None),
                idempotency_key: str | None = Header(default=None)):
        if runtime.config.auth.mode == 'dev' and x_user_id is None:
            x_user_id = '1'
        if x_user_id is None or not x_user_id.strip() or len(x_user_id) > 128:
            raise HTTPException(status_code=401, detail='Authenticated X-User-ID required')
        try:
            user_id = parse_user_id(x_user_id, runtime.config.auth)
        except ValueError:
            raise HTTPException(status_code=401, detail='Invalid identity format') from None
        result = runtime.execute(body.intent, {'user_id':user_id},idempotency_key,
                                 dry_run=body.dry_run)
        status = 200
        if result['status'] == 'rejected':
            status = 503 if result['error']['code'] == 'audit_unavailable' else 422
            if 'conflicts' in result['error']['message']:
                status = 409
        return JSONResponse(result,status_code=status)

    return app
