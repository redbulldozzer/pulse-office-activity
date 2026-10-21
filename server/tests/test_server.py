import copy
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app import main
from app.db import connect, migrate
from app.directory import apply_snapshot, expand_members
from app.schema import Batch


def batch():
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    device = str(uuid4())
    return {'schema_version':1,'device_id':device,'hostname':'test-host','agent_version':'0.1.0',
        'events':[{'schema_version':1,'event_id':str(uuid4()),'device_id':device,'boot_id':str(uuid4()),
            'start':now.isoformat(),'end':(now+timedelta(seconds=15)).isoformat(),'duration_ms':15000,
            'identity':{'account_type':'domain_shared','principal':'employee1','realm':'example.invalid',
                'local_user':'office-workspace','uid':1001,'domain_uid':373400010,
                'shift_id':'a'*32,'desktop_session':'c2'},
            'state':'active','reason':'','key_presses':11,'boundary_key_drops':0}]}


@pytest.mark.parametrize('change', [
    lambda b:b['events'][0].update(key_presses=-1),
    lambda b:b['events'][0].update(key_presses=True),
    lambda b:b['events'][0].update(state='locked'),
    lambda b:b['events'][0].update(typed_text='must not be collected'),
    lambda b:b['events'][0].update(duration_ms=1000),
    lambda b:b['events'][0].update(device_id=str(uuid4())),
    lambda b:b['events'][0].update(identity=None),
    lambda b:b['events'][0]['identity'].update(realm=''),
    lambda b:b['events'].append(copy.deepcopy(b['events'][0])),
])
def test_invalid_batch(change):
    value=batch();change(value)
    with pytest.raises(ValidationError):Batch.model_validate(value)


def test_local_and_unknown_are_distinct():
    value=batch();event=value['events'][0]
    event['identity'].update(account_type='local',realm='',domain_uid=None,shift_id='')
    assert Batch.model_validate(value).events[0].identity.account_type=='local'
    event.update(identity=None,state='unknown',key_presses=0,reason='observation_gap')
    assert Batch.model_validate(value).events[0].identity is None


def test_early_pilot_without_uid_is_never_guessed():
    value=batch();value['events'][0]['identity']['domain_uid']=None
    identity=Batch.model_validate(value).events[0].identity
    assert main.resolve(None,identity)==(None,'missing_domain_uid')


def test_nested_groups_and_cycle():
    users={'uid=one':{'id':'one'},'uid=two':{'id':'two'}}
    groups={'cn=a':{'id':'a','members':['uid=one','cn=b']},
            'cn=b':{'id':'b','members':['uid=two','CN=A']}}
    assert expand_members(users,groups)=={'a':{'one','two'},'b':{'one','two'}}


@pytest.fixture
def database(monkeypatch):
    name=os.getenv('TEST_DB_NAME')
    if not name:pytest.skip('set TEST_DB_NAME to a disposable PostgreSQL database')
    assert name.endswith('_test'), 'Never run destructive fixtures against production'
    monkeypatch.setenv('DB_NAME',name)
    migrate()
    with connect() as db:
        db.execute('TRUNCATE departments,department_memberships,report_cache,report_versions,events,devices,account_bindings,group_memberships,directory_groups,employees,directory_sync CASCADE')
    with TestClient(main.app) as client:yield client


def register(value):
    token='test-'+str(uuid4())
    with connect() as db:
        db.execute('INSERT INTO devices(id,label,token_hash) VALUES(%s,%s,%s)',
                   (value['device_id'],'test',main.token_hash(token)))
    return {'Authorization':'Bearer '+token}


def post(client,value,headers):
    return client.post('/api/v1/events',json=value,headers=headers)


def test_retry_committed_event_without_double_count(database):
    value=batch();headers=register(value)
    assert post(database,value,headers).status_code==200  # simulate discarded response
    response=post(database,value,headers)
    assert response.json()=={'accepted_event_ids':[value['events'][0]['event_id']]}
    with connect() as db:
        assert db.execute('SELECT count(*) n,sum(key_presses) keys FROM events').fetchone()=={'n':1,'keys':11}
        assert {r['revision'] for r in db.execute('SELECT revision FROM report_versions')}=={1}


def test_conflict_rolls_back_entire_batch(database):
    value=batch();headers=register(value)
    assert post(database,value,headers).status_code==200
    changed=copy.deepcopy(value);changed['events'][0]['key_presses']=99
    new=copy.deepcopy(value['events'][0]);new['event_id']=str(uuid4());changed['events'].insert(0,new)
    assert post(database,changed,headers).status_code==409
    with connect() as db:assert db.execute('SELECT count(*) n FROM events').fetchone()['n']==1


def test_tokens_bound_to_device_and_revocation(database):
    a=batch();b=batch();headers=register(a);register(b)
    assert post(database,b,headers).status_code==401
    assert post(database,a,{}).status_code==401
    with connect() as db:db.execute('UPDATE devices SET enabled=false WHERE id=%s',(a['device_id'],))
    assert post(database,a,headers).status_code==401


def test_cross_device_event_id_conflict(database):
    a=batch();b=batch();ha=register(a);hb=register(b)
    b['events'][0]['event_id']=a['events'][0]['event_id']
    assert post(database,a,ha).status_code==200
    assert post(database,b,hb).status_code==409


def test_directory_rename_recreate_and_delayed_identity(database):
    value=batch();headers=register(value);employee=str(uuid4());group=str(uuid4())
    assert post(database,value,headers).status_code==200
    user={'id':employee,'realm':'example.invalid','principal':'employee1','domain_uid':373400010,
          'display_name':'Стажер','enabled':True}
    groups={'cn=sales':{'id':group,'name':'sales','members':['uid=employee1']}}
    apply_snapshot({'uid=employee1':user},groups)
    with connect() as db:
        row=db.execute('SELECT employee_id,resolution FROM events').fetchone()
        assert str(row['employee_id'])==employee and row['resolution']=='ipa_uuid'
    # Renaming preserves UUID and historical binding.
    renamed={**user,'principal':'renamed'}
    apply_snapshot({'uid=renamed':renamed},{'cn=sales':{**groups['cn=sales'],'members':['uid=renamed']}})
    late=copy.deepcopy(value);late['events'][0]['event_id']=str(uuid4())
    assert post(database,late,headers).status_code==200
    # Recreated login with a different UID never acquires the older identity.
    replacement={**user,'id':str(uuid4()),'domain_uid':373400099}
    apply_snapshot({'uid=renamed':renamed,'uid=employee1':replacement},groups)
    new=copy.deepcopy(value);new['events'][0]['event_id']=str(uuid4());new['events'][0]['identity']['domain_uid']=373400099
    assert post(database,new,headers).status_code==200
    with connect() as db:
        rows=db.execute('SELECT employee_id,count(*) n FROM events GROUP BY employee_id').fetchall()
        assert {str(r['employee_id']):r['n'] for r in rows}=={employee:2,replacement['id']:1}
        assert db.execute('SELECT count(*) n FROM group_memberships WHERE valid_to IS NOT NULL').fetchone()['n']==1


def test_database_failure_no_ack(database,monkeypatch):
    import psycopg
    def unavailable():raise psycopg.OperationalError('not for disclosure')
    value=batch();headers=register(value);monkeypatch.setattr(main,'connect',unavailable)
    response=post(database,value,headers)
    assert response.status_code==503
    assert response.json()=={'detail':'database_unavailable'}


def test_invalid_input_not_echoed(database):
    value=batch();value['events'][0]['secret_extra']='SENSITIVE_MARKER'
    response=post(database,value,{})
    assert response.status_code==422 and 'SENSITIVE_MARKER' not in response.text


def test_reused_login_and_uid_is_ambiguous(database):
    value=batch();headers=register(value)
    first={'id':str(uuid4()),'realm':'example.invalid','principal':'employee1','domain_uid':373400010,
           'display_name':'First','enabled':True}
    second={**first,'id':str(uuid4()),'display_name':'Second'}
    apply_snapshot({'uid=employee1':first},{})
    assert post(database,value,headers).status_code==200
    apply_snapshot({'uid=employee1':second},{})
    value['events'][0]['event_id']=str(uuid4())
    assert post(database,value,headers).status_code==200
    with connect() as db:
        rows=db.execute('SELECT employee_id,resolution FROM events ORDER BY received_at').fetchall()
        assert str(rows[0]['employee_id'])==first['id']
        assert rows[1]['employee_id'] is None and rows[1]['resolution']=='ambiguous_domain'


def test_failed_sync_preserves_last_snapshot(database,monkeypatch):
    from app import directory
    user={'id':str(uuid4()),'realm':'example.invalid','principal':'one','domain_uid':123,
          'display_name':'One','enabled':True}
    apply_snapshot({'uid=one':user},{})
    def broken():raise RuntimeError('temporary_ldap_failure')
    monkeypatch.setattr(directory,'read_directory',broken)
    with pytest.raises(RuntimeError):directory.sync_once()
    with connect() as db:
        assert db.execute('SELECT count(*) n FROM employees WHERE present').fetchone()['n']==1
        status=db.execute('SELECT * FROM directory_sync').fetchone()
        assert status['last_success'] is not None and status['error']=='RuntimeError'
