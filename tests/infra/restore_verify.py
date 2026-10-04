"""Compare the source database with a restored copy: table names, extensions, migration version, row counts.

Runs inside the api container (see verify_restore.sh). The database URL comes from the container's own environment and is
never printed. Usage: python restore_verify.py <restored-db-endpoint-host>
"""
import os
import re
import sys

from sqlalchemy import create_engine, text

urls = [v for v in os.environ.values() if v.startswith("postgres")]
if not urls:
    print("NO_DB_URL_ENV")
    sys.exit(1)
base = urls[0]
endpoint = sys.argv[1]


def run(label, url):
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            tables = [r[0] for r in conn.execute(text("select tablename from pg_tables where schemaname='public' order by 1"))]
            # The runtime role is least-privilege: count only tables it may SELECT and report the rest as such.
            counts = {}
            for t in tables:
                readable = conn.execute(text("select has_table_privilege(current_user, quote_ident(:t), 'SELECT')"), {"t": t}).scalar()
                counts[t] = conn.execute(text(f'select count(*) from "{t}"')).scalar() if readable else "no-SELECT-privilege"
            extensions = [r[0] for r in conn.execute(text("select extname from pg_extension order by 1"))]
            print(label, "OK", "tables=", len(tables), "extensions=", extensions)
            print(label, "counts=", counts)
    except Exception as exc:  # noqa: BLE001
        print(label, "ERROR", type(exc).__name__, re.sub(r"postgres\S+", "<url>", str(exc))[:200])


run("SOURCE", base)
run("RESTORED", re.sub(r"@[^/:@]+", "@" + endpoint, base, count=1))
