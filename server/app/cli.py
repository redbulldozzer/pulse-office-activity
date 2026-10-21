"""Administration is available only to operators with VM/Compose access."""
import argparse
import json
import secrets
from uuid import UUID

from .db import connect, migrate
from .main import token_hash
from .structure import DepartmentBody,save_department


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    register = sub.add_parser('register-device')
    register.add_argument('device_id', type=UUID)
    register.add_argument('--label', required=True)
    disable = sub.add_parser('disable-device')
    disable.add_argument('device_id', type=UUID)
    rotate = sub.add_parser('rotate-token')
    rotate.add_argument('device_id', type=UUID)
    sub.add_parser('status')
    sub.add_parser('sync-directory')
    department = sub.add_parser('department')
    department.add_argument('group_name')
    department.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    if args.command == 'sync-directory':
        from .directory import sync_once
        print(json.dumps(sync_once()))
        return
    migrate()
    with connect() as db:
        if args.command == 'register-device':
            token = secrets.token_urlsafe(48)
            db.execute('INSERT INTO devices(id,label,token_hash) VALUES(%s,%s,%s)',
                       (args.device_id,args.label,token_hash(token)))
            # Output exactly once; caller must store privately, never in a report.
            result = {'device_id': str(args.device_id), 'token': token}
        elif args.command == 'rotate-token':
            token = secrets.token_urlsafe(48)
            row = db.execute('UPDATE devices SET token_hash=%s WHERE id=%s RETURNING id',
                             (token_hash(token), args.device_id)).fetchone()
            if not row:
                raise SystemExit('device_not_found')
            result = {'device_id':str(args.device_id),'token':token}
        elif args.command == 'disable-device':
            row = db.execute('UPDATE devices SET enabled=false WHERE id=%s RETURNING id', (args.device_id,)).fetchone()
            if not row:
                raise SystemExit('device_not_found')
            result = {'disabled':str(args.device_id)}
        elif args.command == 'department':
            rows = db.execute('SELECT id FROM directory_groups WHERE name=%s AND present', (args.group_name,)).fetchall()
            if len(rows) != 1:
                raise SystemExit('group_not_found_or_ambiguous')
            existing=db.execute('SELECT * FROM departments WHERE ldap_group_id=%s',(rows[0]['id'],)).fetchone()
            if not args.disable or existing:
                heads=[r['employee_id'] for r in db.execute('SELECT employee_id FROM department_heads WHERE group_id=%s',(existing['id'],))] if existing else []
                save_department(db,DepartmentBody(name=args.group_name,ldap_group_id=rows[0]['id'],enabled=not args.disable,
                    heads=heads,revision=existing['revision'] if existing else None),None,existing['id'] if existing else None)
            result = {'department':args.group_name,'enabled':not args.disable}
        else:
            result = {'devices':db.execute('SELECT id,label,hostname,enabled,last_seen,agent_version FROM devices ORDER BY label').fetchall(),
                'directory':db.execute('SELECT * FROM directory_sync').fetchone(),
                'groups':db.execute('SELECT id,name,present FROM directory_groups ORDER BY name').fetchall(),
                'departments':db.execute('SELECT id,name,ldap_group_id,enabled FROM departments ORDER BY name').fetchall(),
                'events':db.execute('SELECT count(*) AS count,coalesce(sum(key_presses),0) AS keys,min(start_at) AS first,max(end_at) AS last FROM events').fetchone(),
                'resolution':db.execute('SELECT resolution,count(*) FROM events GROUP BY resolution').fetchall()}
    print(json.dumps(result,default=str,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
