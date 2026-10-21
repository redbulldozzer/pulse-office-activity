"""Independent departments. LDAP is a read-only optional membership source."""
from uuid import UUID, uuid4
from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from .db import connect
from .auth import authorize

router=APIRouter(prefix='/api/v1/admin')


def invalidate_structure(db):
    db.execute('UPDATE structure_version SET revision=revision+1 WHERE id=1')


def reconcile(db, department_id, wanted):
    wanted={str(i) for i in wanted}
    current={str(r['employee_id']) for r in db.execute('SELECT employee_id FROM department_memberships WHERE group_id=%s AND valid_to IS NULL',(department_id,))}
    for employee in current-wanted:
        db.execute('UPDATE department_memberships SET valid_to=now() WHERE group_id=%s AND employee_id=%s AND valid_to IS NULL',(department_id,employee))
    for employee in wanted-current:
        db.execute('INSERT INTO department_memberships(group_id,employee_id) VALUES(%s,%s)',(department_id,employee))
    return current!=wanted


def sync_departments(db):
    # Caller holds the same lock as every manual update. Detaching never races a sync.
    changed=False
    for d in db.execute('''SELECT d.*,g.name AS ldap_name FROM departments d JOIN directory_groups g
        ON g.id=d.ldap_group_id WHERE g.present ORDER BY d.id FOR UPDATE OF d''').fetchall():
        wanted=[r['employee_id'] for r in db.execute('SELECT employee_id FROM group_memberships WHERE group_id=%s AND valid_to IS NULL',(d['ldap_group_id'],))]
        membership_changed=reconcile(db,d['id'],wanted)
        if membership_changed or d['name']!=d['ldap_name']:
            # Keep the last name if it now conflicts with another enabled department.
            # Membership updates must not break the entire IPA sync due to a label collision.
            conflict=db.execute('SELECT 1 FROM departments WHERE enabled AND lower(name)=lower(%s) AND id<>%s',(d['ldap_name'],d['id'])).fetchone()
            name=d['name'] if conflict else d['ldap_name']
            if membership_changed or name!=d['name']:
                db.execute('UPDATE departments SET name=%s,revision=revision+1 WHERE id=%s',(name,d['id']))
                changed=True
    if changed: invalidate_structure(db)


class DepartmentBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=120)
    ldap_group_id: UUID|None=None
    enabled: bool=True
    members: list[UUID]=Field(default_factory=list,max_length=10000)
    heads: list[UUID]=Field(default_factory=list,max_length=100)
    revision: int|None=Field(default=None,ge=1)
    membership_starts: dict[UUID,date]=Field(default_factory=dict,max_length=10000)


def save_department(db, body, actor_id, department_id=None):
    db.execute('SELECT pg_advisory_xact_lock(17010202)')
    existing=None
    if department_id:
        existing=db.execute('SELECT * FROM departments WHERE id=%s FOR UPDATE',(department_id,)).fetchone()
        if not existing: raise HTTPException(404,'department_not_found')
        if body.revision!=existing['revision']: raise HTTPException(409,'department_changed')
    else:
        department_id=uuid4()
    if not body.name.strip(): raise HTTPException(422,'invalid_department_name')
    if len(set(body.members))!=len(body.members) or len(set(body.heads))!=len(body.heads):
        raise HTTPException(422,'duplicate_employee')
    if body.ldap_group_id:
        group=db.execute('SELECT id,name FROM directory_groups WHERE id=%s AND present',(body.ldap_group_id,)).fetchone()
        if not group: raise HTTPException(422,'group_not_found')
        name=group['name']
        members=[r['employee_id'] for r in db.execute('SELECT employee_id FROM group_memberships WHERE group_id=%s AND valid_to IS NULL',(body.ldap_group_id,))]
    else:
        name=body.name.strip(); members=body.members
        if existing and existing['ldap_group_id'] and 'members' not in body.model_fields_set:
            members=[r['employee_id'] for r in db.execute('SELECT employee_id FROM department_memberships WHERE group_id=%s AND valid_to IS NULL',(department_id,))]
        for member in members:
            if not db.execute('SELECT 1 FROM employees WHERE id=%s',(member,)).fetchone(): raise HTTPException(422,'invalid_member')
    for head in body.heads:
        if not db.execute('SELECT 1 FROM employees WHERE id=%s AND present AND enabled',(head,)).fetchone(): raise HTTPException(422,'invalid_head')
    if existing:
        db.execute('UPDATE departments SET name=%s,ldap_group_id=%s,enabled=%s,revision=revision+1 WHERE id=%s',
            (name,body.ldap_group_id,body.enabled,department_id))
    else:
        db.execute('INSERT INTO departments(id,name,ldap_group_id,enabled) VALUES(%s,%s,%s,%s)',(department_id,name,body.ldap_group_id,body.enabled))
    # Only explicitly edited dates change. Ordinary LDAP reconciliation preserves them.
    for employee,day in body.membership_starts.items():
        if employee not in members:raise HTTPException(422,'membership_date_requires_member')
        if day<date(2020,1,1) or day>datetime.now(ZoneInfo('Europe/Moscow')).date():
            raise HTTPException(422,'invalid_membership_date')
        start=datetime.combine(day,datetime.min.time(),tzinfo=ZoneInfo('Europe/Moscow'))
        if db.execute('SELECT 1 FROM department_memberships WHERE group_id=%s AND employee_id=%s AND valid_to IS NOT NULL AND valid_to>%s',
                      (department_id,employee,start)).fetchone():
            raise HTTPException(422,'membership_date_overlaps_history')
    reconcile(db,department_id,members)
    for employee,day in body.membership_starts.items():
        start=datetime.combine(day,datetime.min.time(),tzinfo=ZoneInfo('Europe/Moscow'))
        db.execute('UPDATE department_memberships SET valid_from=%s WHERE group_id=%s AND employee_id=%s AND valid_to IS NULL',
                   (start,department_id,employee))
    db.execute('DELETE FROM department_heads WHERE group_id=%s',(department_id,))
    for head in body.heads:db.execute('INSERT INTO department_heads(group_id,employee_id) VALUES(%s,%s)',(department_id,head))
    invalidate_structure(db)
    db.execute('INSERT INTO dashboard_audit(actor_id,action,details) VALUES(%s,%s,%s)',(actor_id,
        'department_updated' if existing else 'department_created',Jsonb({'id':str(department_id),**body.model_dump(mode='json')})))
    return {'id':department_id,'revision':existing['revision']+1 if existing else 1}


def write(request,body,department_id=None):
    try:
        with connect() as db:
            user=authorize(request,db,write=True,admin=True)
            return save_department(db,body,user['id'],department_id)
    except UniqueViolation:
        raise HTTPException(409,'department_name_or_group_in_use') from None

@router.post('/departments')
def create(body: DepartmentBody,request: Request):return write(request,body)

@router.put('/departments/{department_id}')
def update(department_id: UUID,body: DepartmentBody,request: Request):return write(request,body,department_id)
