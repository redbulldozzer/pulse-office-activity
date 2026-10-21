"""Administrator-approved device enrollment, retryable without credential rotation."""
import hashlib
import hmac
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from .auth import authorize
from .db import connect

router = APIRouter(prefix='/api/v1/admin')

class Enrollment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_id: UUID
    label: str = Field(min_length=1, max_length=120, pattern=r'^[^\x00-\x1f\x7f]+$')
    token: str = Field(min_length=48, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')

@router.post('/devices/enroll')
def enroll(body: Enrollment, request: Request):
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    with connect() as db:
        user = authorize(request, db, admin=True, write=True)
        inserted = db.execute('''INSERT INTO devices(id,label,token_hash) VALUES(%s,%s,%s)
            ON CONFLICT(id) DO NOTHING RETURNING id''', (body.device_id,body.label,digest)).fetchone()
        row = db.execute('SELECT token_hash,enabled FROM devices WHERE id=%s FOR UPDATE',
                         (body.device_id,)).fetchone()
        if not row['enabled']:
            raise HTTPException(409, 'device_disabled')
        if not hmac.compare_digest(row['token_hash'], digest):
            raise HTTPException(409, 'device_already_registered')
        if inserted:
            db.execute('INSERT INTO dashboard_audit(actor_id,action,details) VALUES(%s,%s,%s)',
                       (user['id'],'device_enrolled',Jsonb({'device_id':str(body.device_id),'label':body.label})))
    return {'device_id':str(body.device_id),'registered':True}
