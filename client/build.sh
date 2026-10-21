#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p dist
tar --exclude='./dist' --exclude='*/__pycache__' --exclude='*.pyc' -czf dist/office-activity-0.1.0.tar.gz .
cd dist
sha256sum office-activity-0.1.0.tar.gz > office-activity-0.1.0.tar.gz.sha256
