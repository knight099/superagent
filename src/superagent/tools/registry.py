"""Immutable version publication and revocation using PostgreSQL row locks."""
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from ..revisions import digest
from ..validation import Rejection
from .models import ToolManifest


def artifact_digest(manifest):
    return digest(ToolManifest.model_validate(manifest.model_dump()).model_dump())


class ToolRegistry:
    def __init__(self,database_url):
        self.database_url=database_url

    def publish(self,manifest):
        manifest=ToolManifest.model_validate(manifest.model_dump())
        content=artifact_digest(manifest)
        with psycopg.connect(self.database_url) as conn:
            conn.execute('''INSERT INTO superagent_internal.tools
                (app,tool_id,version,digest,manifest,status) VALUES (%s,%s,%s,%s,%s,'active')
                ON CONFLICT DO NOTHING''', (manifest.app,manifest.tool_id,manifest.version,
                                           content,Jsonb(manifest.model_dump())))
            existing=conn.execute('''SELECT digest FROM superagent_internal.tools
                WHERE app=%s AND tool_id=%s AND version=%s FOR UPDATE''',
                (manifest.app,manifest.tool_id,manifest.version)).fetchone()
            if existing[0]!=content:
                raise Rejection('tool version is immutable; publish a new version')
        return content

    def load_for_execution(self,conn,app,tool_id,version):
        row=conn.execute('''SELECT manifest,digest,status FROM superagent_internal.tools
            WHERE app=%s AND tool_id=%s AND version=%s FOR SHARE''',
            (app,tool_id,version)).fetchone()
        if row is None or row[2]!='active':
            raise Rejection('tool is unknown or revoked')
        manifest=ToolManifest.model_validate(row[0])
        if (manifest.app,manifest.tool_id,manifest.version)!=(app,tool_id,version) or artifact_digest(manifest)!=row[1]:
            raise Rejection('tool artifact integrity check failed')
        return manifest

    def get(self,app,tool_id,version):
        with psycopg.connect(self.database_url) as conn:
            return self.load_for_execution(conn,app,tool_id,version)

    def revoke(self,app,tool_id,version,reason):
        if not isinstance(reason,str) or not 1<=len(reason)<=2000:
            raise Rejection('revocation reason is required')
        with psycopg.connect(self.database_url) as conn:
            result=conn.execute('''UPDATE superagent_internal.tools
                SET status='revoked', revoked_at=clock_timestamp(), reason=%s
                WHERE app=%s AND tool_id=%s AND version=%s''',(reason,app,tool_id,version))
            if result.rowcount!=1:
                raise Rejection('unknown tool version')

    def list(self,app):
        with psycopg.connect(self.database_url,row_factory=dict_row) as conn:
            return conn.execute('''SELECT tool_id,version,digest,status,created_at,revoked_at
                FROM superagent_internal.tools WHERE app=%s ORDER BY tool_id,version''',(app,)).fetchall()
