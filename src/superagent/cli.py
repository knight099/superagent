"""Bootstrap, explain, execute and host the same application-independent runtime."""
import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
import psycopg
import yaml
from .config import load_config, parse_user_id
from .schema import introspect
from .models import TransitionPlan
from .runtime import Runtime
from .audit import initialize_internal
from .setup import discover_config, save_schema


def main(argv=None):
    parser = argparse.ArgumentParser(prog='superagent')
    sub = parser.add_subparsers(dest='command',required=True)
    init = sub.add_parser('init',help='Generate config from your database or the sample app')
    init.add_argument('--config',default='superagent.yaml')
    init.add_argument('--from-db',action='store_true',help='Discover tables in your PostgreSQL schema')
    init.add_argument('--schema',default='public')
    init.add_argument('--schema-file',default='.superagent/schema.json')
    for name in ('init-db','schema','explain','execute','run'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--config',default='superagent.yaml')
        if name in ('schema','run'):
            cmd.add_argument('--schema-file',default='.superagent/schema.json')
        if name in ('explain','execute'):
            cmd.add_argument('--user-id',required=True)
            cmd.add_argument('--plan')
            cmd.add_argument('--intent',default='Explain supplied plan' if name == 'explain' else None)
            if name == 'execute':
                cmd.add_argument('--key')
        if name == 'run':
            cmd.add_argument('--host',default='127.0.0.1')
            cmd.add_argument('--port',type=int,default=8000)
    args = parser.parse_args(argv)
    try:
        if hasattr(args,'schema_file') and (args.command != 'init' or args.from_db):
            config_path = Path(args.config).resolve()
            schema_path = Path(args.schema_file).resolve()
            if config_path == schema_path or (
                    config_path.exists() and schema_path.exists()
                    and config_path.samefile(schema_path)):
                raise ValueError('Config and schema snapshot require separate files')
        if args.command == 'init':
            if Path(args.config).exists():
                raise FileExistsError(args.config)
            if args.from_db:
                url = os.environ.get('DATABASE_URL')
                if not url:
                    raise ValueError('DATABASE_URL is required')
                with psycopg.connect(url,autocommit=True) as conn:
                    cfg = discover_config(conn,args.schema)
                    catalog = introspect(conn,cfg)
                data = yaml.safe_dump(cfg.model_dump(),sort_keys=False)
            else:
                data = files('superagent').joinpath('templates/project_management.yaml').read_text()
            created = False
            try:
                with Path(args.config).open('x') as handle:
                    created = True
                    handle.write(data)
                if args.from_db:
                    save_schema(catalog,cfg,args.schema_file)
            except Exception:
                if created:
                    Path(args.config).unlink(missing_ok=True)
                raise
            print(f'Created {args.config}. Configure table allowlists, permissions, and DATABASE_URL.')
            if args.from_db:
                print(f'Saved schema to {args.schema_file}. All permissions start denied.')
            return 0
        cfg = load_config(args.config)
        url = os.environ.get(cfg.database.url_env)
        if not url:
            raise ValueError(f'{cfg.database.url_env} is required')
        with psycopg.connect(url,autocommit=True) as conn:
            if args.command == 'init-db':
                initialize_internal(conn)
                print('Initialized internal audit and idempotency tables.')
                return 0
            catalog = introspect(conn,cfg)
        if args.command in ('schema','run'):
            save_schema(catalog,cfg,args.schema_file)
            if args.command == 'schema':
                print(f'Saved allowed PostgreSQL metadata to {args.schema_file}.')
                return 0
        if args.command == 'run' or not getattr(args,'plan',None):
            from .planner import OpenAIPlanner
            planner = OpenAIPlanner(cfg.planner)
        else:
            planner = None
        runtime = Runtime(url,cfg,catalog,planner)
        if args.command == 'run':
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(runtime),host=args.host,port=args.port)
            return 0
        identity = {'user_id':parse_user_id(args.user_id, cfg.auth)}
        supplied = TransitionPlan.model_validate_json(Path(args.plan).read_text()) if args.plan else None
        if args.command == 'explain' and supplied:
            result = runtime.explain(supplied,identity)
        else:
            if not args.intent:
                raise ValueError('--intent is required')
            result = runtime.execute(args.intent,identity,getattr(args,'key',None),
                                     dry_run=args.command == 'explain',plan=supplied)
        print(json.dumps(result,indent=2,default=str))
        return 1 if result['status'] == 'rejected' else 0
    except FileExistsError:
        print('Config already exists; refusing to overwrite.',file=sys.stderr)
    except Exception:
        # Do not emit connection strings, provider response bodies or SQL error values.
        print('Command failed. Check configuration, credentials, database and plan.',file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
