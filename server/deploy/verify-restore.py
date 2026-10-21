#!/usr/bin/python3
"""Operator test: pauses ingestion, restores to a disposable DB, compares every row."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--outage-seconds',type=int,default=0,choices=range(61))
args=parser.parse_args()
os.chdir('/opt/office-activity-server')
compose=['docker','compose']
prefix=compose+['exec','-T','db']


def command(args):
    return subprocess.check_output(prefix+args,stdin=subprocess.DEVNULL)


def inventory(database):
    tables=['schema_migrations','devices','employees','account_bindings','directory_groups',
            'group_memberships','directory_sync','events','dashboard_sessions',
            'department_heads','dashboard_audit','login_attempts','report_versions','report_cache','departments','department_memberships','structure_version','local_employee_bindings']
    result={}
    for table in tables:
        raw=command(['psql','-U','postgres','-d',database,'-At','-c',
                     f'SELECT row_to_json(t)::text FROM {table} t ORDER BY row_to_json(t)::text'])
        result[table]={'rows':len(raw.splitlines()),'sha256':hashlib.sha256(raw).hexdigest()}
    return result


subprocess.run(compose+['stop','api','directory'],check=True,stdin=subprocess.DEVNULL)
print('Ingestion paused for restore/recovery verification',flush=True)
started=time.monotonic()
try:
    dump=Path(subprocess.check_output(['deploy/backup.sh'],stdin=subprocess.DEVNULL,text=True).strip())
    before=inventory('activity')
    command(['psql','-U','postgres','-d','postgres','-c','CREATE DATABASE activity_restore_test OWNER activity'])
    try:
        with dump.open('rb') as stream:
            subprocess.run(prefix+['pg_restore','-U','postgres','-d','activity_restore_test','--exit-on-error'],stdin=stream,check=True)
        restored=inventory('activity_restore_test')
        assert before==restored,'Restored data mismatch'
        report={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'dump':str(dump),
                'tables':restored,'result':'all_rows_and_hashes_match'}
        path=Path('/var/backups/office-activity/restore-verification.json')
        path.write_text(json.dumps(report,indent=2)+'\n');path.chmod(0o600)
        print(json.dumps(report),flush=True)
    finally:
        command(['psql','-U','postgres','-d','postgres','-c','DROP DATABASE activity_restore_test'])
    time.sleep(max(0,args.outage_seconds-(time.monotonic()-started)))
finally:
    subprocess.run(compose+['up','-d','api','directory'],check=True,stdin=subprocess.DEVNULL)
    print('Ingestion restarted',flush=True)
