#!/bin/bash
set -euo pipefail
umask 077
cd /opt/office-activity-server
mkdir -p /var/backups/office-activity
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target=/var/backups/office-activity/activity-$stamp.dump
docker compose exec -T db pg_dump -U activity -d activity -Fc </dev/null > "$target.partial"
test -s "$target.partial"
mv "$target.partial" "$target"
sha256sum "$target" > "$target.sha256"
# Expire only dumps created by this job, after a new backup succeeds.
find /var/backups/office-activity -maxdepth 1 -type f -name 'activity-*.dump*' -mtime +14 -delete
printf '%s\n' "$target"
