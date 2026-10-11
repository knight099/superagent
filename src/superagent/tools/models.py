"""Closed template contract. Slots can only replace data, never SQL structure."""
import math
from typing import Annotated, Literal
from pydantic import Field, model_validator
from ..models import (StrictModel, Name, Scalar, Reference, Select, Insert, Update,
                      Delete, Predicate, TransitionPlan)

Revision = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


class ArgumentSlot(StrictModel):
    argument: Name


class IdentitySlot(StrictModel):
    identity: Literal['user_id']


class TemplateCalculation(StrictModel):
    calc: Literal['add', 'date_add_days']
    left: Scalar | Reference | ArgumentSlot | IdentitySlot
    right: int | float | Reference | ArgumentSlot | IdentitySlot


TemplateValue = Scalar | Reference | TemplateCalculation | ArgumentSlot | IdentitySlot


class TemplatePredicate(Predicate):
    value: TemplateValue | list[Scalar | ArgumentSlot | IdentitySlot] = None


class TemplateSelect(Select):
    where: list[TemplatePredicate] = Field(default_factory=list, max_length=30)


class TemplateInsert(Insert):
    values: dict[Name, TemplateValue] = Field(min_length=1, max_length=100)


class TemplateUpdate(Update):
    values: dict[Name, TemplateValue] = Field(min_length=1, max_length=100)
    where: list[TemplatePredicate] = Field(min_length=1, max_length=30)


class TemplateDelete(Delete):
    where: list[TemplatePredicate] = Field(min_length=1, max_length=30)


TemplateOperation = Annotated[
    TemplateSelect | TemplateInsert | TemplateUpdate | TemplateDelete, Field(discriminator='kind')]


class TemplatePlan(TransitionPlan):
    operations: list[TemplateOperation] = Field(min_length=1, max_length=100)


class InputSpec(StrictModel):
    type: Literal['string', 'integer', 'number', 'boolean']
    required: bool = True
    nullable: bool = False
    default: Scalar = None
    max_length: int | None = Field(default=None, ge=1, le=8000)
    minimum: float | None = None
    maximum: float | None = None

    def check(self, value):
        if value is None and self.nullable:
            return value
        expected = {'string':(str,), 'integer':(int,), 'number':(int,float), 'boolean':(bool,)}
        if type(value) not in expected[self.type]:
            raise ValueError('input type does not match contract')
        if isinstance(value,str) and self.max_length is not None and len(value)>self.max_length:
            raise ValueError('input exceeds max length')
        if type(value) in (int,float):
            if not math.isfinite(value) or abs(value)>1e12:
                raise ValueError('input numeric bound exceeded')
            if self.minimum is not None and value<self.minimum:
                raise ValueError('input is below minimum')
            if self.maximum is not None and value>self.maximum:
                raise ValueError('input exceeds maximum')
        return value

    @model_validator(mode='after')
    def contract(self):
        if self.max_length is not None and self.type!='string':
            raise ValueError('length applies only to strings')
        if any(v is not None and not math.isfinite(v) for v in (self.minimum,self.maximum)):
            raise ValueError('input bounds must be finite')
        if (self.minimum is not None or self.maximum is not None) and self.type not in ('integer','number'):
            raise ValueError('numeric bounds require numeric input')
        if self.minimum is not None and self.maximum is not None and self.minimum>self.maximum:
            raise ValueError('invalid input range')
        if not self.required:
            if 'default' not in self.model_fields_set:
                raise ValueError('optional input requires an explicit default')
            self.check(self.default)
        elif 'default' in self.model_fields_set and self.default is not None:
            raise ValueError('required input cannot have a default')
        return self


class ToolManifest(StrictModel):
    format_version: Literal[1] = 1
    app: Name
    tool_id: Name
    version: int = Field(ge=1)
    description: str = Field(min_length=1,max_length=2000)
    schema_revision: Revision
    policy_revision: Revision
    runtime_contract: Literal[1] = 1
    output_contract: Literal['runtime_result_v1'] = 'runtime_result_v1'
    inputs: dict[Name, InputSpec] = Field(default_factory=dict, max_length=100)
    plan: TemplatePlan

    @model_validator(mode='after')
    def slots(self):
        if set(self.inputs) & {'identity','user_id','tenant_id'}:
            raise ValueError('authenticated context cannot be a caller argument')
        used=set()
        def walk(value):
            if isinstance(value,dict):
                if set(value)=={'argument'}:
                    used.add(value['argument'])
                for child in value.values():
                    walk(child)
            elif isinstance(value,list):
                for child in value:
                    walk(child)
        walk(self.plan.model_dump())
        if used != set(self.inputs):
            raise ValueError('declared inputs must match argument slots')
        if len(self.model_dump_json())>131072:
            raise ValueError('tool manifest exceeds size bound')
        return self


class ToolExecutionContext(StrictModel):
    app: Name
    tool_id: Name
    version: int = Field(ge=1)
    digest: Revision
    schema_revision: Revision
    policy_revision: Revision


class ToolInvocation(StrictModel):
    tool_id: Name
    version: int = Field(ge=1)
    arguments: dict[Name, Scalar] = Field(default_factory=dict, max_length=100)
