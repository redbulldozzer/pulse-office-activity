"""FreeIPA password bind, opaque sessions and current server-side authorization."""
import hashlib
import hmac
import os
import re
import secrets
import ssl
from uuid import UUID

import ldap3
from ldap3.core.exceptions import LDAPInvalidCredentialsResult, LDAPException
from ldap3.utils.dn import escape_rdn
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ConfigDict
from .db import connect

router = APIRouter(prefix='/api/v1')
COOKIE = '__Host-activity_session'
ADMIN_GROUP = os.getenv('DASHBOARD_ADMIN_GROUP', 'ff729180-8f44-11f1-b48a-bc2411bbfb7d')
ORIGIN = os.getenv('PUBLIC_ORIGIN', 'https://example.invalid')

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def origin(request):
    if request.headers.get('origin') != ORIGIN:
        raise HTTPException(403, 'invalid_origin')

def fresh(db):
    status = db.execute("SELECT last_success > now()-interval '15 minutes' AS fresh FROM directory_sync WHERE id=1").fetchone()
    if not status or not status['fresh']: raise HTTPException(503, 'directory_stale')

def employee_access(db, employee_id):
    user = db.execute('SELECT id,principal,display_name FROM employees WHERE id=%s AND enabled AND present', (employee_id,)).fetchone()
    if not user: raise HTTPException(401, 'session_expired')
    user['is_admin'] = bool(db.execute('''SELECT 1 FROM group_memberships m JOIN directory_groups g ON g.id=m.group_id
        WHERE m.employee_id=%s AND m.group_id=%s AND m.valid_to IS NULL AND g.present''', (employee_id,ADMIN_GROUP)).fetchone())
    return user

def authorize(request, db, write=False, admin=False):
    raw = request.cookies.get(COOKIE, '')
    if not raw or len(raw)>256: raise HTTPException(401, 'session_expired')
    session = db.execute("""SELECT * FROM dashboard_sessions WHERE token_hash=%s
        AND expires_at>now() AND last_seen>now()-interval '30 minutes'""", (digest(raw),)).fetchone()
    if not session: raise HTTPException(401, 'session_expired')
    fresh(db)
    user = employee_access(db, session['employee_id'])
    if admin and not user['is_admin']: raise HTTPException(403, 'access_denied')
    if write:
        origin(request)
        if not hmac.compare_digest(request.headers.get('x-csrf-token',''),session['csrf_token']):
            raise HTTPException(403, 'invalid_csrf')
    db.execute('UPDATE dashboard_sessions SET last_seen=now() WHERE token_hash=%s',(session['token_hash'],))
    user['csrf_token'] = session['csrf_token']
    return user

def departments(db, user):
    return db.execute('''SELECT d.id,d.name,d.ldap_group_id FROM departments d
        LEFT JOIN directory_groups g ON g.id=d.ldap_group_id WHERE d.enabled
        AND (%s OR ((d.ldap_group_id IS NULL OR g.present) AND EXISTS (
            SELECT 1 FROM department_heads h WHERE h.group_id=d.id AND h.employee_id=%s)))
        ORDER BY d.name''',(user['is_admin'],user['id'])).fetchall()

def scope(db, user, group_id):
    allowed=departments(db,user)
    if group_id is None:
        return None if user['is_admin'] else [g['id'] for g in allowed]
    if str(group_id) not in {str(g['id']) for g in allowed}:
        raise HTTPException(403,'access_denied')
    return [group_id]

def ldap_authenticate(login, password):
    host=os.getenv('IPA_HOST','example.invalid'); base=os.getenv('IPA_BASE_DN','dc=example,dc=invalid')
    tls=ldap3.Tls(validate=ssl.CERT_REQUIRED,version=ssl.PROTOCOL_TLS_CLIENT,
        ca_certs_file=os.getenv('IPA_CA_FILE','/run/secrets/ipa_ca'),valid_names=[host])
    server=ldap3.Server(host,port=636,use_ssl=True,tls=tls,connect_timeout=5)
    dn=f'uid={escape_rdn(login)},cn=users,cn=accounts,{base}'
    connection=ldap3.Connection(server,user=dn,password=password,receive_timeout=8,raise_exceptions=True)
    try:
        connection.bind()
        connection.search(dn,'(objectClass=posixAccount)',search_scope=ldap3.BASE,attributes=['ipaUniqueID'])
        if len(connection.entries)!=1: raise HTTPException(401,'invalid_credentials')
        return UUID(str(connection.entries[0].ipaUniqueID.value))
    except LDAPInvalidCredentialsResult:
        raise HTTPException(401,'invalid_credentials') from None
    except LDAPException:
        raise HTTPException(503,'directory_unavailable') from None
    finally:
        connection.unbind()

class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    login: str=Field(min_length=1,max_length=128)
    password: str=Field(min_length=1,max_length=1024)

@router.post('/auth/login')
def login(body: Credentials, request: Request, response: Response):
    origin(request)
    name=body.login.strip().lower()
    suffix='@'+os.getenv('IPA_REALM','example.invalid').lower()
    if name.endswith(suffix): name=name[:-len(suffix)]
    if not re.fullmatch(r'[a-z0-9_.-]{1,64}',name): raise HTTPException(401,'invalid_credentials')
    address=request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    # Commit each attempt BEFORE binding; failed requests cannot roll back throttling.
    with connect() as db:
        fresh(db)
        db.execute("DELETE FROM login_attempts WHERE created_at<now()-interval '15 minutes'")
        db.execute('SELECT pg_advisory_xact_lock(17010203)')
        attempts=db.execute('''SELECT count(*) FILTER(WHERE account_hash=%s) AS account,
            count(*) FILTER(WHERE address=%s) AS address FROM login_attempts''',(digest(name),address)).fetchone()
        if attempts['account']>=10 or attempts['address']>=40: raise HTTPException(429,'login_throttled')
        db.execute('INSERT INTO login_attempts(account_hash,address) VALUES(%s,%s)',(digest(name),address))
    employee_id=ldap_authenticate(name,body.password)
    token=secrets.token_urlsafe(48); csrf=secrets.token_urlsafe(32)
    with connect() as db:
        fresh(db); employee_access(db,employee_id)
        old=request.cookies.get(COOKIE,'')
        db.execute("DELETE FROM dashboard_sessions WHERE expires_at<now() OR last_seen<now()-interval '30 minutes' OR token_hash=%s",(digest(old),))
        db.execute('INSERT INTO dashboard_sessions(token_hash,employee_id,csrf_token) VALUES(%s,%s,%s)',(digest(token),employee_id,csrf))
    response.set_cookie(COOKIE,token,max_age=28800,secure=True,httponly=True,samesite='strict',path='/')
    return {'ok':True}

@router.get('/auth/me')
def me(request: Request):
    with connect() as db:
        user=authorize(request,db)
        return {**user,'departments':departments(db,user)}

@router.post('/auth/logout')
def logout(request: Request, response: Response):
    # Permit logout even when directory sync is unavailable, but still enforce CSRF.
    origin(request)
    with connect() as db:
        key=digest(request.cookies.get(COOKIE,''))
        row=db.execute('SELECT csrf_token FROM dashboard_sessions WHERE token_hash=%s',(key,)).fetchone()
        if row and not hmac.compare_digest(row['csrf_token'],request.headers.get('x-csrf-token','')):
            raise HTTPException(403,'invalid_csrf')
        db.execute('DELETE FROM dashboard_sessions WHERE token_hash=%s',(key,))
    response.delete_cookie(COOKIE,secure=True,httponly=True,samesite='strict',path='/')
    return {'ok':True}
