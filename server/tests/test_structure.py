from datetime import datetime,timedelta,timezone
from uuid import uuid4
import csv,io
import pytest
from app.db import connect
from app.structure import sync_departments
from app.reports import report_data,bounds,csv_cell
from test_dashboard import people,client_login,event
from test_server import database,batch,register,post


def create(c,people,**overrides):
    body={'name':'Ручной отдел','members':[str(people['employee'])],'heads':[str(people['head'])]}
    body.update(overrides)
    r=c.post('/api/v1/admin/departments',json=body);assert r.status_code==200,r.text
    return r.json()


def test_create_manual_and_membership_starts_now(people):
    c=client_login();d=create(c,people)
    with connect() as db:
        assert db.execute('SELECT ldap_group_id FROM departments WHERE id=%s',(d['id'],)).fetchone()['ldap_group_id'] is None
        r=db.execute('SELECT valid_from FROM department_memberships WHERE group_id=%s',(d['id'],)).fetchone()
        assert datetime.now(timezone.utc)-r['valid_from']<timedelta(seconds=5)
    head=client_login('head')
    assert d['id'] in [d['id'] for d in head.get('/api/v1/auth/me').json()['departments']]


def test_detach_freezes_members_sync_ignores_manual_then_reattach(people):
    c=client_login();d=str(people['group'])
    r=c.put('/api/v1/admin/departments/'+d,json={'name':'Независимый','revision':1,'heads':[str(people['head'])]})
    assert r.status_code==200,r.text
    with connect() as db:
        before=db.execute('SELECT employee_id,valid_from FROM department_memberships WHERE group_id=%s',(d,)).fetchall()
        db.execute('UPDATE group_memberships SET valid_to=now() WHERE group_id=%s',(d,))
        db.execute('INSERT INTO group_memberships(group_id,employee_id) VALUES(%s,%s)',(d,people['outsider']))
        sync_departments(db)
        assert db.execute('SELECT employee_id,valid_from FROM department_memberships WHERE group_id=%s',(d,)).fetchall()==before
    r=c.put('/api/v1/admin/departments/'+d,json={'name':'ignored','ldap_group_id':d,'revision':2,'heads':[]})
    assert r.status_code==200,r.text
    with connect() as db:
        assert db.execute('SELECT name FROM departments WHERE id=%s',(d,)).fetchone()['name']=='group'
        assert db.execute('SELECT employee_id FROM department_memberships WHERE group_id=%s AND valid_to IS NULL',(d,)).fetchone()['employee_id']==people['outsider']
        assert db.execute('SELECT count(*) n FROM department_memberships WHERE group_id=%s AND valid_to IS NOT NULL',(d,)).fetchone()['n']==1


def test_ldap_sync_renames_and_updates_only_synced_department(people):
    c=client_login();manual=create(c,people)
    with connect() as db:
        db.execute("UPDATE directory_groups SET name='Changed' WHERE id=%s",(people['group'],))
        db.execute('UPDATE group_memberships SET valid_to=now() WHERE group_id=%s',(people['group'],))
        sync_departments(db)
        assert db.execute('SELECT name FROM departments WHERE id=%s',(people['group'],)).fetchone()['name']=='Changed'
        assert db.execute('SELECT count(*) n FROM department_memberships WHERE group_id=%s AND valid_to IS NULL',(people['group'],)).fetchone()['n']==0
        assert db.execute('SELECT count(*) n FROM department_memberships WHERE group_id=%s AND valid_to IS NULL',(manual['id'],)).fetchone()['n']==1


def test_conflicting_edits_names_and_group_binding(people):
    c=client_login();d=create(c,people)
    assert c.post('/api/v1/admin/departments',json={'name':'Ручной отдел'}).status_code==409
    assert c.post('/api/v1/admin/departments',json={'name':'Another','ldap_group_id':str(people['group'])}).status_code==409
    assert c.put('/api/v1/admin/departments/'+d['id'],json={'name':'New','revision':2}).status_code==409
    assert c.put('/api/v1/admin/departments/'+d['id'],json={'name':'New','revision':1}).status_code==200
    assert c.put('/api/v1/admin/departments/'+d['id'],json={'name':'Lost','revision':1}).status_code==409


def test_all_accessible_departments_union_and_export_no_double_keys(people):
    c=client_login();d=create(c,people)
    with connect() as db:
        db.execute("UPDATE department_memberships SET valid_from='2026-09-01' WHERE group_id=%s",(d['id'],))
    event(people,'employee','2026-09-10T12:00:00Z','2026-09-10T13:00:00Z',keys=8)
    event(people,'outsider','2026-09-10T12:00:00Z','2026-09-10T13:00:00Z',keys=999)
    h=client_login('head');r=h.get('/api/v1/reports/departments?month=2026-09');assert r.status_code==200,r.text
    data=r.json();assert data['totals']['keys']==8 and data['totals']['active']==3600
    assert sum(d['totals']['keys'] for d in data['departments'])==16
    assert len(data['employees'])==1
    for kind in ['employees','daily','departments']:
        r=h.get('/api/v1/reports/export?month=2026-09&kind='+kind)
        assert r.status_code==200 and r.content.startswith(b'\xef\xbb\xbf') and '999' not in r.text and 'outsider' not in r.text
        assert r.headers['cache-control']=='no-store'
        assert h.get(f'/api/v1/reports/export?month=2026-09&kind={kind}&department={people["othergroup"]}').status_code==403
    assert h.get(f'/api/v1/reports/export?month=2026-09&employee={people["outsider"]}').status_code==404
    with connect() as db:db.execute('DELETE FROM department_heads')
    r=h.get('/api/v1/reports/export?month=2026-09');assert len(list(csv.reader(io.StringIO(r.content.decode('utf-8-sig')),delimiter=';')))==1


def test_department_change_invalidates_cache_without_ldap_sync(people):
    c=client_login();d=create(c,people)
    with connect() as db:
        db.execute("UPDATE department_memberships SET valid_from='2026-09-01' WHERE group_id=%s",(d['id'],))
    event(people,'employee','2026-09-10T12:00:00Z','2026-09-10T13:00:00Z',keys=8)
    start,end=bounds('2026-09')
    with connect() as db:
        assert report_data(db,start,end,d['id'])['totals']['keys']==8
        # Removing a member now must retain old department history.
    r=c.put('/api/v1/admin/departments/'+d['id'],json={'name':'Ручной отдел','members':[],'revision':1});assert r.status_code==200
    with connect() as db:assert report_data(db,start,end,d['id'])['totals']['keys']==8


@pytest.mark.parametrize('value',['=HYPERLINK("x")','+formula','-formula','@formula',' \t=1+1','\n=1'])
def test_csv_formula_injection(value):assert csv_cell(value).startswith("'")


def test_missing_ldap_group_does_not_erase_last_membership_but_revokes_head(people):
    c=client_login('head')
    with connect() as db:
        db.execute('UPDATE directory_groups SET present=false WHERE id=%s',(people['group'],));sync_departments(db)
        assert db.execute('SELECT count(*) n FROM department_memberships WHERE group_id=%s AND valid_to IS NULL',(people['group'],)).fetchone()['n']==1
    assert c.get(f'/api/v1/reports/month?month=2026-09&department={people["group"]}').status_code==403


def test_local_binding_device_specific_no_retroactive_assignment(people):
    c=client_login();value=batch();headers=register(value);e=value['events'][0]
    e['identity'].update(account_type='local',realm='',domain_uid=None,principal='local',local_user='local',uid=1001,shift_id='')
    assert post(c,value,headers).status_code==200
    body={'device_id':value['device_id'],'local_user':'local','local_uid':1001,'employee_id':str(people['employee']),'personal_account_confirmed':True}
    assert c.put('/api/v1/admin/local-accounts',json={**body,'personal_account_confirmed':False}).status_code==422
    assert c.put('/api/v1/admin/local-accounts',json=body).status_code==200
    with connect() as db:
        assert db.execute('SELECT employee_id FROM events WHERE event_id=%s',(e['event_id'],)).fetchone()['employee_id'] is None
        binding=db.execute('SELECT * FROM local_employee_bindings').fetchone()
    fresh=dict(e,event_id=str(uuid4()),start=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(),end=(datetime.now(timezone.utc)+timedelta(seconds=16)).isoformat())
    value['events']=[fresh];assert post(c,value,headers).status_code==200
    with connect() as db:
        row=db.execute('SELECT employee_id,resolution FROM events WHERE event_id=%s',(fresh['event_id'],)).fetchone()
        assert row=={'employee_id':people['employee'],'resolution':'local_ldap_binding'}
    another=batch();ha=register(another);another['events']=[{**fresh,'event_id':str(uuid4()),'device_id':another['device_id']}]
    assert post(c,another,ha).status_code==200
    with connect() as db:assert db.execute('SELECT employee_id FROM events WHERE event_id=%s',(another['events'][0]['event_id'],)).fetchone()['employee_id'] is None
    assert c.put('/api/v1/admin/local-accounts',json={**body,'employee_id':None,'previous_binding_id':str(binding['id'])}).status_code==200
    fresh['event_id']=str(uuid4());assert post(c,value,headers).status_code==200
    with connect() as db:assert db.execute('SELECT employee_id FROM events WHERE event_id=%s',(fresh['event_id'],)).fetchone()['employee_id'] is None
    assert client_login('head').get('/api/v1/admin/local-accounts').status_code==403


def test_membership_date_backfills_reports_and_ldap_preserves_it(people):
    c=client_login();g=str(people['group']);e=str(people['employee'])
    event(people,'employee','2026-09-09T12:00:00Z','2026-09-09T12:01:00Z',keys=371)
    params={'month':'2026-09','department':g}
    assert c.get('/api/v1/reports/month',params=params).json()['totals']['keys']==0
    body={'name':'group','ldap_group_id':g,'revision':1,'heads':[str(people['head'])],'membership_starts':{e:'2026-09-01'}}
    response=c.put('/api/v1/admin/departments/'+g,json=body)
    assert response.status_code==200,response.text
    with connect() as db:
        sync_departments(db)
        start=db.execute('SELECT valid_from FROM department_memberships WHERE group_id=%s AND employee_id=%s AND valid_to IS NULL',(g,e)).fetchone()['valid_from']
        assert start==datetime(2026,8,31,21,tzinfo=timezone.utc)
        audit=db.execute("SELECT details FROM dashboard_audit WHERE action='department_updated' ORDER BY created_at DESC LIMIT 1").fetchone()
        assert audit['details']['membership_starts'][e]=='2026-09-01'
    assert c.get('/api/v1/reports/month',params=params).json()['totals']['keys']==371
    d=next(d for d in c.get('/api/v1/admin/settings').json()['departments'] if d['id']==g)
    assert d['membership_starts'][e]=='2026-09-01'
    body.pop('membership_starts');body['revision']=2
    assert c.put('/api/v1/admin/departments/'+g,json=body).status_code==200
    assert c.get('/api/v1/reports/month',params=params).json()['totals']['keys']==371
    assert client_login('head').put('/api/v1/admin/departments/'+g,json={**body,'revision':3,'membership_starts':{e:'2026-01-01'}}).status_code==403


def test_membership_date_validation_and_atomic_rejection(people):
    c=client_login();g=str(people['group']);e=str(people['employee'])
    body={'name':'group','ldap_group_id':g,'revision':1}
    for changes in ({e:'2099-01-01'},{e:'2019-01-01'},{str(people['outsider']):'2026-09-01'}):
        assert c.put('/api/v1/admin/departments/'+g,json={**body,'membership_starts':changes}).status_code==422
    with connect() as db:
        db.execute("INSERT INTO department_memberships(group_id,employee_id,valid_from,valid_to) VALUES(%s,%s,'2026-08-01','2026-08-20')",(g,e))
    r=c.put('/api/v1/admin/departments/'+g,json={**body,'membership_starts':{e:'2026-08-10'}})
    assert r.status_code==422 and r.json()['detail']=='membership_date_overlaps_history'
    with connect() as db:
        assert db.execute('SELECT revision FROM departments WHERE id=%s',(g,)).fetchone()['revision']==1
    created=create(c,people,name='Backdated',membership_starts={e:'2026-09-01'})
    d=next(d for d in c.get('/api/v1/admin/settings').json()['departments'] if d['id']==created['id'])
    assert d['membership_starts'][e]=='2026-09-01'
