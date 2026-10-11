"""Allowlisted PostgreSQL catalog metadata; contains no row data or secrets."""
from dataclasses import dataclass, field, asdict
from psycopg.rows import dict_row


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    default: bool = False
    generated: bool = False


@dataclass
class Table:
    schema: str
    name: str
    columns: dict[str, Column]
    primary_key: list[str] = field(default_factory=list)
    constraints: list[dict] = field(default_factory=list)


@dataclass
class Catalog:
    tables: dict[str, Table]

    def context(self):
        return asdict(self)


def introspect(conn, config) -> Catalog:
    tables = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for qualified, cfg in config.tables.items():
            schema, name = qualified.split('.')
            cur.execute('''SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
                NOT a.attnotnull AS nullable, a.atthasdef AS default,
                (a.attgenerated <> '' OR a.attidentity <> '') AS generated
                FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'r'
                AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum''', (schema, name))
            columns = {r['name']: Column(**r) for r in cur.fetchall()}
            if not columns or set(cfg.columns) - columns.keys():
                raise ValueError(f'configured table/columns not found: {qualified}')
            cur.execute('''SELECT con.contype AS kind, pg_get_constraintdef(con.oid) AS definition,
                ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(num, ord)
                    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.num
                    ORDER BY k.ord) AS columns,
                rn.nspname || '.' || rc.relname AS foreign_table,
                ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(num, ord)
                    JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.num
                    ORDER BY k.ord) AS foreign_columns
                FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_class rc ON rc.oid = con.confrelid
                LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
                WHERE n.nspname = %s AND c.relname = %s''', (schema, name))
            constraints = cur.fetchall()
            # Do not expose definitions mentioning hidden columns to the planner.
            visible = [c for c in constraints if set(c['columns']) <= set(cfg.columns)
                       and (c['kind'] != 'f' or (c['foreign_table'] in config.tables
                            and set(c['foreign_columns']) <=
                                set(config.tables[c['foreign_table']].columns)))]
            primary = next((c['columns'] for c in constraints if c['kind'] == 'p'), [])
            tables[qualified] = Table(schema, name, columns, primary, visible)
    return Catalog(tables)
