from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import Error as DatabaseError
from psycopg.types.json import Jsonb

from . import __version__
from .db import connect, migrate
from .schema import Batch


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(event):
    payload = event.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return payload, digest


def resolve(db, identity, event=None):
    if identity is None:
        return None, 'unknown'
    if identity.account_type == 'local':
        if event is not None:
            rows=db.execute('''SELECT b.employee_id FROM local_employee_bindings b
                WHERE b.device_id=%s AND b.local_user=%s AND b.local_uid=%s
                AND b.valid_from<=%s AND (b.valid_to IS NULL OR b.valid_to>=%s)''',
                (event.device_id,identity.local_user,identity.uid,event.start,event.end)).fetchall()
            if len(rows)==1:return rows[0]['employee_id'],'local_ldap_binding'
        return None, 'local_device_account'
    if identity.domain_uid is None:
        # Early pilot intervals did not contain a domain UID. A login alone is
        # insufficient to distinguish an old account from a recreated one.
        return None, 'missing_domain_uid'
    rows = db.execute('SELECT DISTINCT employee_id FROM account_bindings WHERE realm=%s AND principal=%s AND domain_uid=%s',
                      (identity.realm.upper(), identity.principal, identity.domain_uid)).fetchall()
    if len(rows) == 1:
        return rows[0]['employee_id'], 'ipa_uuid'
    return None, 'ambiguous_domain' if rows else 'unresolved_domain'


@asynccontextmanager
async def lifespan(app):
    migrate()
    yield


app = FastAPI(title='Office Activity ingestion', version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo uploaded identity data or any unrecognised fields into responses/logs.
    return JSONResponse(status_code=422, content={'detail': 'invalid_event_batch',
        'errors': [{'loc': list(e['loc']), 'type': e['type']} for e in exc.errors()[:20]]})


@app.exception_handler(DatabaseError)
async def database_error(request, exc):
    logging.getLogger('activity').error('database_unavailable: %s', type(exc).__name__)
    return JSONResponse(status_code=503, content={'detail': 'database_unavailable'})


@app.get('/healthz')
def health():
    with connect() as db:
        db.execute('SELECT 1').fetchone()
    return {'status': 'ok', 'version': __version__}


@app.post('/api/v1/events')
def ingest(batch: Batch, authorization: str = Header(default='')):
    if not authorization.startswith('Bearer ') or len(authorization) > 256:
        raise HTTPException(401, 'invalid_device_credentials')
    supplied = token_hash(authorization[7:])
    accepted = []
    with connect() as db:
        # Hold the device lock until commit so disable/rotation and ingestion serialize.
        device = db.execute('SELECT token_hash,enabled FROM devices WHERE id=%s FOR UPDATE',
                            (batch.device_id,)).fetchone()
        if not device or not device['enabled'] or not hmac.compare_digest(supplied, device['token_hash']):
            raise HTTPException(401, 'invalid_device_credentials')
        for event in batch.events:
            payload, digest = canonical(event)
            employee_id, resolution = resolve(db, event.identity, event)
            inserted = db.execute('''INSERT INTO events(event_id,device_id,employee_id,resolution,start_at,end_at,
                duration_ms,state,key_presses,boundary_key_drops,payload,payload_hash)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING RETURNING event_id''',
                (event.event_id, batch.device_id, employee_id, resolution, event.start, event.end,
                 event.duration_ms, event.state, event.key_presses, event.boundary_key_drops, Jsonb(payload), digest)).fetchone()
            if inserted is None:
                previous = db.execute('SELECT device_id,payload_hash FROM events WHERE event_id=%s', (event.event_id,)).fetchone()
                if previous['device_id'] != batch.device_id or previous['payload_hash'] != digest:
                    # Atomic failure: even earlier inserts in this batch roll back.
                    raise HTTPException(409, 'event_id_conflict')
            if inserted is not None:
                db.execute('''INSERT INTO report_versions(day)
                    SELECT d::date FROM generate_series(
                        (%s::timestamptz AT TIME ZONE 'Europe/Moscow')::date::timestamp,
                        ((%s::timestamptz-interval '1 microsecond') AT TIME ZONE 'Europe/Moscow')::date::timestamp,
                        interval '1 day') d ON CONFLICT(day) DO UPDATE SET revision=report_versions.revision+1''',
                    (event.start,event.end))
            accepted.append(str(event.event_id))
        db.execute('UPDATE devices SET hostname=%s,agent_version=%s,last_seen=now() WHERE id=%s',
                   (batch.hostname, batch.agent_version, batch.device_id))
    # The context manager commits before any acknowledgement is returned.
    return {'accepted_event_ids': accepted}

from .auth import router as auth_router
from .reports import router as reports_router
app.include_router(auth_router)
app.include_router(reports_router)

@app.middleware('http')
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response

from .structure import router as structure_router
app.include_router(structure_router)

from .local_accounts import router as local_accounts_router
app.include_router(local_accounts_router)

from .enrollment import router as enrollment_router
app.include_router(enrollment_router)
