"""Bind validated values and verified identity without changing plan structure."""
from ..models import TransitionPlan
from .models import ToolManifest


def bind(manifest, arguments, identity):
    manifest=ToolManifest.model_validate(manifest.model_dump())
    if not isinstance(arguments,dict) or set(arguments)-set(manifest.inputs):
        raise ValueError('unknown tool argument')
    if not isinstance(identity,dict) or type(identity.get('user_id')) not in (str,int):
        raise ValueError('verified identity is required')
    values={}
    for name,spec in manifest.inputs.items():
        if name not in arguments and spec.required:
            raise ValueError('required argument is missing')
        values[name]=spec.check(arguments[name] if name in arguments else spec.default)
    def walk(value):
        if isinstance(value,dict):
            if set(value)=={'argument'}:
                return values[value['argument']]
            if set(value)=={'identity'}:
                return identity[value['identity']]
            return {key:walk(child) for key,child in value.items()}
        if isinstance(value,list):
            return [walk(child) for child in value]
        return value
    return TransitionPlan.model_validate(walk(manifest.plan.model_dump()))
