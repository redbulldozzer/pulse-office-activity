from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app import auth, main
from app.db import connect
from app.reports import report_data, bounds
from test_server import database

@pytest.fixture
def people(database, monkeypatch):
    ids={k:uuid4() for k in ['admin','head','employee','outsider','group','othergroup','device']}
    monkeypatch.setattr(auth,'ADMIN_GROUP',str(ids['othergroup']))
    with connect() as db:
        db.execute('TRUNCATE login_attempts,dashboard_audit')
        for i,k in enumerate(['admin','head','employee','outsider']):
            db.execute("INSERT INTO employees(id,realm,principal,domain_uid,display_name,enabled) VALUES(%s,'example.invalid',%s,%s,%s,true)",(ids[k],k,100+i,k))
        for k in ['group','othergroup']:
            db.execute('INSERT INTO directory_groups(id,name,is_department) VALUES(%s,%s,true)',(ids[k],k))
        db.execute("INSERT INTO group_memberships(group_id,employee_id,valid_from) VALUES(%s,%s,'2026-01-01'),(%s,%s,'2026-09-10')",(ids['othergroup'],ids['admin'],ids['group'],ids['employee']))
        db.execute('INSERT INTO departments(id,name,ldap_group_id) SELECT id,name,id FROM directory_groups')
        db.execute('INSERT INTO department_memberships SELECT * FROM group_memberships')
        db.execute('INSERT INTO department_heads(group_id,employee_id) VALUES(%s,%s)',(ids['group'],ids['head']))
        db.execute("INSERT INTO directory_sync(id,last_success,last_attempt) VALUES(1,now(),now())")
        db.execute("INSERT INTO devices(id,label,token_hash) VALUES(%s,'test','test')",(ids['device'],))
    def bind(name,password):
        if password!='correct':raise auth.HTTPException(401,'invalid_credentials')
        return ids[name]
    monkeypatch.setattr(auth,'ldap_authenticate',bind)
    return ids

def client_login(name='admin'):
    client=TestClient(main.app,base_url=auth.ORIGIN)
    response=client.post('/api/v1/auth/login',json={'login':name,'password':'correct'},headers={'Origin':auth.ORIGIN})
    assert response.status_code==200,response.text
    response=client.get('/api/v1/auth/me');assert response.status_code==200,response.text
    client.headers.update({'Origin':auth.ORIGIN,'X-CSRF-Token':response.json()['csrf_token']})
    return client

def event(ids,person,start,end,state='active',keys=0):
    with connect() as db:
        db.execute('''INSERT INTO events(event_id,device_id,employee_id,resolution,start_at,end_at,duration_ms,state,key_presses,boundary_key_drops,payload,payload_hash)
            VALUES(%s,%s,%s,'ipa_uuid',%s,%s,0,%s,%s,0,'{}','test')''',(uuid4(),ids['device'],ids[person],start,end,state,keys))

def test_opaque_secure_session_and_logout(people):
    c=client_login();cookie=c.cookies.get(auth.COOKIE)
    assert cookie and len(cookie)>40
    with connect() as db:assert db.execute('SELECT token_hash FROM dashboard_sessions').fetchone()['token_hash']!=cookie
    assert c.get('/api/v1/auth/me').headers['cache-control']=='no-store'
    assert c.post('/api/v1/auth/logout').status_code==200
    assert c.get('/api/v1/auth/me').status_code==401

def test_head_cannot_read_other_department_or_employee(people):
    c=client_login('head');g=str(people['group'])
    assert [p['id'] for p in c.get('/api/v1/reports/month?month=2026-09').json()['employees']]==[str(people['employee'])]
    assert c.get(f'/api/v1/reports/month?month=2026-09&department={people["othergroup"]}').status_code==403
    assert c.get(f'/api/v1/reports/month?month=2026-09&department={g}&employee={people["outsider"]}').status_code==404
    assert c.get(f'/api/v1/reports/day?day=2026-09-11&department={g}&employee={people["outsider"]}').status_code==404
    assert c.get('/api/v1/admin/settings').status_code==403
    assert c.put(f'/api/v1/admin/departments/{g}',json={'name':'group','enabled':False,'heads':[], 'revision':1}).status_code==403
    r=c.get(f'/api/v1/reports/month?month=2026-09&department={g}');assert r.status_code==200
    assert [p['id'] for p in r.json()['employees']]==[str(people['employee'])]

def test_grant_revocation_and_disabled_user_apply_to_existing_session(people):
    c=client_login('head')
    with connect() as db:db.execute('DELETE FROM department_heads')
    assert c.get(f'/api/v1/reports/month?month=2026-09&department={people["group"]}').status_code==403
    with connect() as db:db.execute('UPDATE employees SET enabled=false WHERE id=%s',(people['head'],))
    assert c.get('/api/v1/auth/me').status_code==401

def test_stale_directory_fails_closed(people):
    c=client_login()
    with connect() as db:db.execute("UPDATE directory_sync SET last_success=now()-interval '16 minutes'")
    assert c.get('/api/v1/auth/me').status_code==503
    assert c.post('/api/v1/auth/logout').status_code==200

def test_csrf_origin_and_audit(people):
    c=client_login();url=f'/api/v1/admin/departments/{people["group"]}';body={'name':'group','ldap_group_id':str(people['group']),'heads':[str(people['outsider'])],'revision':1}
    assert c.put(url,json=body,headers={'X-CSRF-Token':'bad'}).status_code==403
    assert c.put(url,json=body,headers={'Origin':'https://evil.example'}).status_code==403
    assert c.put(url,json=body).status_code==200
    with connect() as db:assert db.execute('SELECT count(*) n FROM dashboard_audit').fetchone()['n']==1

def test_failed_login_throttles_without_echo(people):
    c=TestClient(main.app,base_url=auth.ORIGIN)
    for _ in range(10):
        r=c.post('/api/v1/auth/login',json={'login':'employee','password':'sensitive-bad'},headers={'Origin':auth.ORIGIN})
        assert r.status_code==401 and 'sensitive-bad' not in r.text
    assert c.post('/api/v1/auth/login',json={'login':'employee','password':'correct'},headers={'Origin':auth.ORIGIN}).status_code==429
    assert c.post('/api/v1/auth/login',json={'login':'employee','password':''},headers={'Origin':auth.ORIGIN}).status_code==422

def test_expired_session(people):
    c=client_login()
    with connect() as db:db.execute("UPDATE dashboard_sessions SET last_seen=now()-interval '31 minutes'")
    assert c.get('/api/v1/auth/me').status_code==401

def test_overlap_priority_and_midnight_counts(people):
    event(people,'employee','2026-09-10T20:59:50Z','2026-09-10T21:00:10Z',keys=7)
    event(people,'employee','2026-09-10T20:59:55Z','2026-09-10T21:00:05Z',keys=3)
    event(people,'employee','2026-09-10T20:59:40Z','2026-09-10T21:00:20Z','afk')
    event(people,'employee','2026-09-10T20:59:30Z','2026-09-10T21:00:30Z','locked')
    start,end=bounds('2026-09')
    with connect() as db:r=report_data(db,start,end,employee_id=people['employee'])
    assert r['totals']==dict(active=20,afk=20,locked=20,unknown=0,keys=10)
    assert r['employees'][0]['days'][0]['keys']==0
    assert r['employees'][0]['days'][1]['keys']==10

def test_month_boundary_and_late_arrival(people):
    event(people,'employee','2026-08-31T20:59:50Z','2026-08-31T21:00:10Z',keys=9)
    start,end=bounds('2026-09')
    with connect() as db:r=report_data(db,start,end,employee_id=people['employee'])
    assert r['totals']['active']==10 and r['totals']['keys']==9
    event(people,'employee','2026-09-02T09:00:00Z','2026-09-02T09:01:00Z',keys=2)
    with connect() as db:r=report_data(db,start,end,employee_id=people['employee'])
    assert r['totals']['active']==70 and r['totals']['keys']==11

def test_membership_clipping_no_past_history_or_boundary_keys(people):
    event(people,'employee','2026-09-09T10:00:00Z','2026-09-09T11:00:00Z',keys=100)
    event(people,'employee','2026-09-09T23:59:50Z','2026-09-10T00:00:10Z',keys=7)
    event(people,'employee','2026-09-10T10:00:00Z','2026-09-10T10:01:00Z',keys=3)
    start,end=bounds('2026-09')
    with connect() as db:r=report_data(db,start,end,group_id=people['group'])
    assert r['totals']['active']==70 and r['totals']['keys']==3

def test_day_segments_are_normalized(people):
    event(people,'employee','2026-09-10T12:00:00Z','2026-09-10T13:00:00Z')
    event(people,'employee','2026-09-10T12:00:00Z','2026-09-10T14:00:00Z','locked')
    c=client_login();r=c.get(f'/api/v1/reports/day?day=2026-09-10&employee={people["employee"]}')
    assert r.status_code==200,r.text
    assert [d['id'] for d in r.json()['devices']]==[str(people['device'])]
    segments=r.json()['employees'][0]['days'][0]['segments']
    assert [s['state'] for s in segments]==['active','afk']


def test_cache_invalidates_after_ingestion_and_directory_change(people):
    start,end=bounds('2026-09')
    event(people,'employee','2026-09-10T12:00:00Z','2026-09-10T12:01:00Z',keys=5)
    with connect() as db:
        r=report_data(db,start,end);assert r['totals']['keys']==5
    event(people,'employee','2026-09-10T12:01:00Z','2026-09-10T12:02:00Z',keys=7)
    with connect() as db:
        db.execute("INSERT INTO report_versions(day) VALUES('2026-09-10') ON CONFLICT(day) DO UPDATE SET revision=report_versions.revision+1")
        r=report_data(db,start,end);assert r['totals']['keys']==12
        r=report_data(db,start,end,group_id=people['group']);assert r['totals']['keys']==12
        db.execute("UPDATE department_memberships SET valid_from='2026-09-11' WHERE group_id=%s",(people['group'],))
        db.execute("UPDATE directory_sync SET snapshot_hash='changed'")
        r=report_data(db,start,end,group_id=people['group']);assert r['totals']['keys']==0
