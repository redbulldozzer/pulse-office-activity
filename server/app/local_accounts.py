"""Explicit per-device personal local-account -> LDAP employee bindings."""
from uuid import UUID,uuid4
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb
from .db import connect
from .auth import authorize

router=APIRouter(prefix='/api/v1/admin')

def local_accounts(db):
    return db.execute('''WITH observed AS (
        SELECT device_id,payload->'identity'->>'local_user' local_user,
            (payload->'identity'->>'uid')::bigint local_uid,max(end_at) last_seen
        FROM events WHERE payload->'identity'->>'account_type'='local'
        GROUP BY device_id,payload->'identity'->>'local_user',(payload->'identity'->>'uid')::bigint
    ) SELECT o.*,d.label,d.hostname,b.id AS binding_id,b.employee_id,b.valid_from,
        u.principal,u.display_name FROM observed o JOIN devices d ON d.id=o.device_id
        LEFT JOIN local_employee_bindings b ON b.device_id=o.device_id AND b.local_user=o.local_user
          AND b.local_uid=o.local_uid AND b.valid_to IS NULL
        LEFT JOIN employees u ON u.id=b.employee_id ORDER BY d.label,o.local_user''').fetchall()

@router.get('/local-accounts')
def list_accounts(request:Request):
    with connect() as db:
        authorize(request,db,admin=True)
        return {'accounts':local_accounts(db)}

class Binding(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id:UUID
    local_user:str=Field(min_length=1,max_length=255)
    local_uid:int=Field(ge=0,le=2147483647)
    employee_id:UUID|None
    previous_binding_id:UUID|None=None
    personal_account_confirmed:bool=False

@router.put('/local-accounts')
def bind_account(body:Binding,request:Request):
    with connect() as db:
        user=authorize(request,db,write=True,admin=True)
        # Same device lock as ingestion: create/close cannot race an accepted event.
        if not db.execute('SELECT id FROM devices WHERE id=%s FOR UPDATE',(body.device_id,)).fetchone():raise HTTPException(404,'device_not_found')
        if body.employee_id:
            if not body.personal_account_confirmed:raise HTTPException(422,'personal_account_required')
            if not db.execute('SELECT 1 FROM employees WHERE id=%s AND present AND enabled',(body.employee_id,)).fetchone():raise HTTPException(422,'invalid_employee')
        current=db.execute('SELECT * FROM local_employee_bindings WHERE device_id=%s AND local_user=%s AND local_uid=%s AND valid_to IS NULL',
            (body.device_id,body.local_user,body.local_uid)).fetchone()
        if (current['id'] if current else None)!=body.previous_binding_id:raise HTTPException(409,'binding_changed')
        observed=db.execute('''SELECT 1 FROM events WHERE device_id=%s AND payload->'identity'->>'account_type'='local'
            AND payload->'identity'->>'local_user'=%s AND (payload->'identity'->>'uid')::bigint=%s LIMIT 1''',
            (body.device_id,body.local_user,body.local_uid)).fetchone()
        if not observed:raise HTTPException(404,'local_account_not_observed')
        if current and current['employee_id']==body.employee_id:return {'ok':True}
        if current:db.execute('UPDATE local_employee_bindings SET valid_to=now() WHERE id=%s',(current['id'],))
        if body.employee_id:
            db.execute('INSERT INTO local_employee_bindings(id,device_id,local_user,local_uid,employee_id) VALUES(%s,%s,%s,%s,%s)',
                (uuid4(),body.device_id,body.local_user,body.local_uid,body.employee_id))
        db.execute('INSERT INTO dashboard_audit(actor_id,action,details) VALUES(%s,%s,%s)',
            (user['id'],'local_account_bound' if body.employee_id else 'local_account_unbound',Jsonb(body.model_dump(mode='json'))))
    return {'ok':True}
