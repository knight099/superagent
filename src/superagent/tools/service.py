"""Direct tool invocation. Resolution, binding and audit share one transaction."""
from .registry import ToolRegistry


class ToolService:
    def __init__(self,runtime,registry=None):
        self.runtime=runtime
        self.registry=registry or ToolRegistry(runtime.database_url)

    def execute(self,tool_id,version,arguments,identity,key=None,*,dry_run=False):
        return self.runtime.execute('Execute approved backend tool',identity,key,
            dry_run=dry_run,tool_request={'tool_id':tool_id,'version':version,'arguments':arguments},
            registry=self.registry)
