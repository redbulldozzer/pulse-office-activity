#!/bin/bash
set -euo pipefail
cd /opt/office-activity-server
if [ -n "$(docker compose ps --status running -q proxy)" ]; then
    docker compose exec -T proxy nginx -t </dev/null
    docker compose exec -T proxy nginx -s reload </dev/null
fi
