"""Read-only FreeIPA sync. Membership dates are observation dates, not HR dates."""
import logging
import hashlib
import json
import os
from pathlib import Path
import ssl
import signal
import threading
from uuid import UUID

import ldap3

from .db import connect, migrate
from .structure import sync_departments


def expand_members(users_by_dn, groups_by_dn):
    result = {}
    for dn, group in groups_by_dn.items():
        found, visited, pending = set(), set(), list(group['members'])
        while pending:
            member = pending.pop().lower()
            if member in visited:
                continue
            visited.add(member)
            if member in users_by_dn:
                found.add(users_by_dn[member]['id'])
            elif member in groups_by_dn:
                pending.extend(groups_by_dn[member]['members'])
        result[group['id']] = found
    return result


def read_directory():
    host = os.environ['IPA_HOST']
    base = os.environ.get('IPA_BASE_DN', 'dc=example,dc=invalid')
    realm = os.environ.get('IPA_REALM', 'example.invalid')
    password = Path(os.getenv('IPA_PASSWORD_FILE', '/run/secrets/ipa_password')).read_text().strip()
    tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT,
                   ca_certs_file=os.getenv('IPA_CA_FILE', '/run/secrets/ipa_ca'), valid_names=[host])
    server = ldap3.Server(host, port=636, use_ssl=True, tls=tls, connect_timeout=10)
    connection = ldap3.Connection(server, user=os.environ['IPA_BIND_DN'], password=password,
        auto_bind=True, receive_timeout=20, raise_exceptions=True)
    try:
        def search(branch, filter_text, attrs):
            return [e for e in connection.extend.standard.paged_search(
                branch+','+base, filter_text, attributes=attrs, paged_size=500, generator=False)
                if e['type'] == 'searchResEntry']

        users = {}
        for entry in search('cn=users,cn=accounts', '(objectClass=posixAccount)',
                            ['uid', 'uidNumber', 'ipaUniqueID', 'displayName', 'cn', 'nsAccountLock']):
            a = entry['attributes']
            def scalar(key, default=''):
                value = a.get(key, default)
                return value[0] if isinstance(value, list) and value else value or default
            employee = {'id': str(UUID(str(scalar('ipaUniqueID')))), 'realm': realm,
                'principal': str(scalar('uid')), 'domain_uid': int(scalar('uidNumber')),
                'display_name': str(scalar('displayName') or scalar('cn') or scalar('uid')),
                'enabled': str(scalar('nsAccountLock', 'false')).lower() != 'true'}
            users[entry['dn'].lower()] = employee
        if not users:
            raise RuntimeError('empty_directory_snapshot_refused')
        groups = {}
        for entry in search('cn=groups,cn=accounts', '(objectClass=ipausergroup)', ['cn', 'ipaUniqueID', 'member']):
            a = entry['attributes']
            uid = a['ipaUniqueID']; name = a['cn']; members = a.get('member', [])
            groups[entry['dn'].lower()] = {'id': str(UUID(uid[0] if isinstance(uid, list) else uid)),
                'name': name[0] if isinstance(name, list) else name,
                'members': members if isinstance(members, list) else [members]}
        if not groups:
            raise RuntimeError('empty_group_snapshot_refused')
        return users, groups
    finally:
        connection.unbind()


def apply_snapshot(users, groups):
    memberships = expand_members(users, groups)
    snapshot_hash = hashlib.sha256(json.dumps([users,groups],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    with connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(17010202)')
        db.execute('UPDATE employees SET present=false')
        db.execute('UPDATE directory_groups SET present=false')
        for u in users.values():
            db.execute('''INSERT INTO employees(id,realm,principal,domain_uid,display_name,enabled)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET realm=excluded.realm,
                principal=excluded.principal,domain_uid=excluded.domain_uid,display_name=excluded.display_name,
                enabled=excluded.enabled,present=true,last_seen=now()''',
                (u['id'],u['realm'],u['principal'],u['domain_uid'],u['display_name'],u['enabled']))
            db.execute('''INSERT INTO account_bindings(employee_id,realm,principal,domain_uid) VALUES(%s,%s,%s,%s)
                ON CONFLICT(employee_id,realm,principal,domain_uid) DO UPDATE SET last_seen=now()''',
                (u['id'],u['realm'],u['principal'],u['domain_uid']))
        for g in groups.values():
            db.execute('''INSERT INTO directory_groups(id,name) VALUES(%s,%s) ON CONFLICT(id)
                DO UPDATE SET name=excluded.name,present=true,last_seen=now()''', (g['id'],g['name']))
        wanted = {(str(g), str(u)) for g, members in memberships.items() for u in members}
        current = {(str(r['group_id']), str(r['employee_id'])) for r in db.execute(
            'SELECT group_id,employee_id FROM group_memberships WHERE valid_to IS NULL')}
        for g,u in current - wanted:
            db.execute('UPDATE group_memberships SET valid_to=now() WHERE group_id=%s AND employee_id=%s AND valid_to IS NULL', (g,u))
        for g,u in wanted - current:
            db.execute('INSERT INTO group_memberships(group_id,employee_id) VALUES(%s,%s)', (g,u))
        sync_departments(db)
        # A new UUID with the same login/UID never silently takes an older UUID's events.
        db.execute('''WITH unambiguous AS (
              SELECT realm,principal,domain_uid,min(employee_id::text)::uuid employee_id
              FROM account_bindings GROUP BY realm,principal,domain_uid HAVING count(*)=1
            ) UPDATE events e SET employee_id=b.employee_id,resolution='ipa_uuid' FROM unambiguous b
            WHERE e.resolution='unresolved_domain' AND upper(e.payload->'identity'->>'realm')=b.realm
            AND e.payload->'identity'->>'principal'=b.principal
            AND (e.payload->'identity'->>'domain_uid')::bigint=b.domain_uid''')
        db.execute('''INSERT INTO directory_sync(id,last_success,last_attempt,error,users_count,groups_count)
            VALUES(1,now(),now(),NULL,%s,%s) ON CONFLICT(id) DO UPDATE SET last_success=now(),
            last_attempt=now(),error=NULL,users_count=excluded.users_count,groups_count=excluded.groups_count''',
            (len(users),len(groups)))
        db.execute('UPDATE directory_sync SET snapshot_hash=%s WHERE id=1',(snapshot_hash,))
    return {'users': len(users), 'groups': len(groups), 'memberships': len(wanted)}


def sync_once():
    try:
        return apply_snapshot(*read_directory())
    except Exception as exc:
        # Keep the previous complete snapshot and never log bind credentials.
        with connect() as db:
            db.execute('''INSERT INTO directory_sync(id,last_attempt,error) VALUES(1,now(),%s)
                ON CONFLICT(id) DO UPDATE SET last_attempt=now(),error=excluded.error''', (type(exc).__name__,))
        raise


def main():
    migrate()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            logging.warning('directory_sync_ok %s', sync_once())
        except Exception as exc:
            logging.error('directory_sync_failed %s', type(exc).__name__)
        stop.wait(300)


if __name__ == '__main__':
    main()
