"""The closed, versioned planner contract. No SQL or executable code fields."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


Scalar = str | int | float | bool | None
Name = Annotated[str, Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]*$', max_length=63)]
TableName = Annotated[str, Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$', max_length=127)]


class Reference(StrictModel):
    ref: Name
    column: Name


class Calculation(StrictModel):
    calc: Literal['add', 'date_add_days']
    left: Scalar | Reference
    right: int | float | Reference


Value = Scalar | Reference | Calculation


class Operand(StrictModel):
    source: Literal['row', 'before', 'after', 'identity']
    field: Name


class Expression(StrictModel):
    op: Literal['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'is_null', 'all', 'any', 'not']
    left: Scalar | Operand = None
    right: Scalar | Operand = None
    args: list['Expression | bool'] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def arity(self):
        if self.op in ('all', 'any', 'not'):
            if not self.args or (self.op == 'not' and len(self.args) != 1):
                raise ValueError('invalid expression arity')
            if 'left' in self.model_fields_set or 'right' in self.model_fields_set:
                raise ValueError('logical expressions only accept args')
        elif self.args or 'left' not in self.model_fields_set:
            raise ValueError('comparison requires left operand and no args')
        elif self.op != 'is_null' and 'right' not in self.model_fields_set:
            raise ValueError('comparison requires right operand')
        return self


class Predicate(StrictModel):
    field: Name
    op: Literal['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'is_null']
    value: Value | list[Scalar] = None

    @model_validator(mode='after')
    def value_shape(self):
        if self.op == 'in':
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 100:
                raise ValueError('in requires 1..100 literal values')
        elif isinstance(self.value, list):
            raise ValueError('only in accepts lists')
        elif self.op == 'is_null':
            if not isinstance(self.value, bool):
                raise ValueError('is_null requires boolean')
        elif self.value is None:
            raise ValueError('use is_null for null predicates')
        return self


class Operation(StrictModel):
    id: Name
    table: TableName


class Select(Operation):
    kind: Literal['select']
    select: list[Name] = Field(min_length=1, max_length=100)
    where: list[Predicate] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=100, ge=1, le=1000)


class Insert(Operation):
    kind: Literal['insert']
    values: dict[Name, Value] = Field(min_length=1, max_length=100)
    returning: list[Name] = Field(default_factory=list, max_length=100)


class Update(Operation):
    kind: Literal['update']
    values: dict[Name, Value] = Field(min_length=1, max_length=100)
    where: list[Predicate] = Field(min_length=1, max_length=30)
    returning: list[Name] = Field(default_factory=list, max_length=100)


class Delete(Operation):
    kind: Literal['delete']
    where: list[Predicate] = Field(min_length=1, max_length=30)
    returning: list[Name] = Field(default_factory=list, max_length=100)


PlanOperation = Annotated[Select | Insert | Update | Delete, Field(discriminator='kind')]


class TransitionPlan(StrictModel):
    version: Literal[1] = 1
    operations: list[PlanOperation] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def bounded(self):
        if len({op.id for op in self.operations}) != len(self.operations):
            raise ValueError('operation IDs must be unique')
        if len(self.model_dump_json()) > 65536:
            raise ValueError('plan exceeds 64 KiB')
        return self
