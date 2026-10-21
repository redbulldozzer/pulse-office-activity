#!/bin/bash
set -euo pipefail
export ACTIVITY_DB_PASSWORD
ACTIVITY_DB_PASSWORD=$(cat /run/secrets/db_password)
psql -v ON_ERROR_STOP=1 --username postgres --dbname activity <<'SQL'
\getenv app_password ACTIVITY_DB_PASSWORD
SELECT format('CREATE ROLE activity LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_password') \gexec
ALTER DATABASE activity OWNER TO activity;
SQL
unset ACTIVITY_DB_PASSWORD
