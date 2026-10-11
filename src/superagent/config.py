"""Developer-owned configuration; untrusted requests cannot change it."""
from pathlib import Path
from typing import Literal
import re
import yaml
from pydantic import Field, model_validator
from .models import StrictModel, Name, TableName, Expression, Operand


class Limits(StrictModel):
    max_operations: int = Field(default=20, ge=1, le=100)
    max_rows: int = Field(default=100, ge=1, le=1000)
    max_read_rows: int = Field(default=100, ge=1, le=1000)
    statement_timeout_ms: int = Field(default=2000, ge=1, le=60000)


class TableConfig(StrictModel):
    columns: list[Name] = Field(min_length=1, max_length=100)
    permissions: dict[str, Expression | bool] = Field(default_factory=dict)
    after: dict[str, Expression | bool] = Field(default_factory=dict)
    invariants: list[Expression | bool] = Field(default_factory=list, max_length=20)
    sensitive_columns: list[Name] = Field(default_factory=list)

    @model_validator(mode='after')
    def rules(self):
        if set(self.permissions) - {'select', 'insert', 'update', 'delete'}:
            raise ValueError('unknown permission kind')
        if set(self.after) - {'insert', 'update'}:
            raise ValueError('after rules only apply to insert/update')
        if set(self.sensitive_columns) - set(self.columns):
            raise ValueError('sensitive columns must be allowlisted')
        def walk(expr, depth=0):
            if depth > 10:
                raise ValueError('policy nesting exceeds 10')
            if isinstance(expr, Expression):
                for value in (expr.left, expr.right):
                    if isinstance(value, Operand) and value.source != 'identity':
                        if value.field not in self.columns:
                            raise ValueError('policy references unexposed column')
                for arg in expr.args:
                    walk(arg, depth + 1)
        for expr in [*self.permissions.values(), *self.after.values(), *self.invariants]:
            walk(expr)
        return self


class DatabaseConfig(StrictModel):
    url_env: Name = 'DATABASE_URL'


class PlannerConfig(StrictModel):
    url: str = 'https://api.openai.com/v1/chat/completions'
    model: str = 'gpt-4.1-mini'
    key_env: Name = 'OPENAI_API_KEY'
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class AuthConfig(StrictModel):
    user_id_type: Literal['integer', 'string'] = 'integer'
    mode: str = 'trusted_header'

    @model_validator(mode='after')
    def mode_check(self):
        if self.mode not in ('trusted_header', 'dev'):
            raise ValueError('unsupported auth mode')
        return self


class Config(StrictModel):
    app: Name
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    limits: Limits = Field(default_factory=Limits)
    tables: dict[TableName, TableConfig] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def schemas(self):
        for table in self.tables:
            if table.split('.')[0] in ('superagent_internal', 'pg_catalog', 'information_schema'):
                raise ValueError('reserved schema cannot be exposed')
        return self


def load_config(path: str | Path) -> Config:
    return Config.model_validate(yaml.safe_load(Path(path).read_text()))


def parse_user_id(text, auth):
    if not isinstance(text, str) or not text.strip() or len(text) > 128:
        raise ValueError('invalid identity')
    if auth.user_id_type == 'string':
        return text
    if not re.fullmatch(r'(0|-?[1-9][0-9]*)', text):
        raise ValueError('integer identity must use canonical decimal form')
    return int(text)
