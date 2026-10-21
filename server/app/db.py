import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def connect():
    password = Path(os.environ.get('DB_PASSWORD_FILE', '/run/secrets/db_password')).read_text().strip()
    return psycopg.connect(host=os.getenv('DB_HOST', 'db'), dbname=os.getenv('DB_NAME', 'activity'),
                          user=os.getenv('DB_USER', 'activity'), password=password,
                          connect_timeout=5, row_factory=dict_row,
                          options='-c statement_timeout=15000 -c lock_timeout=5000 -c jit=off')


def migrate():
    with connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(17010201)')
        db.execute(Path(__file__).with_name('schema.sql').read_text())

        for path in sorted(Path(__file__).with_name('migrations').glob('*.sql')):
            version = int(path.name.split('_')[0])
            if not db.execute('SELECT 1 FROM schema_migrations WHERE version=%s', (version,)).fetchone():
                db.execute(path.read_text())
                db.execute('INSERT INTO schema_migrations(version) VALUES(%s)', (version,))
