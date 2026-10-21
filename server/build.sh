#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p dist
tar --exclude='./dist' --exclude='./.venv' --exclude='./.pytest_cache' \
    --exclude='__pycache__' --exclude='./secrets' --exclude='./backups' \
    --exclude='./frontend/node_modules' --exclude='./pilot-*.json' -czf dist/office-activity-server-0.4.6.tar.gz .
sha256sum dist/office-activity-server-0.4.6.tar.gz > dist/office-activity-server-0.4.6.tar.gz.sha256
