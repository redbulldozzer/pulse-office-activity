from uuid import uuid4
from test_dashboard import people, client_login
from test_server import database
from app.db import connect
from app.main import token_hash

def test_enroll_retry_conflict_disabled_and_no_secret_audit(people):
    c=client_login(); url='/api/v1/admin/devices/enroll'
    body={'device_id':str(uuid4()),'label':'pc-new','token':'a'*64}
    assert c.post(url,json=body).status_code==200
    assert c.post(url,json=body).status_code==200
    assert c.post(url,json={**body,'token':'b'*64}).status_code==409
    with connect() as db:
        row=db.execute('SELECT token_hash FROM devices WHERE id=%s',(body['device_id'],)).fetchone()
        assert row['token_hash']==token_hash(body['token'])
        audit=db.execute("SELECT details FROM dashboard_audit WHERE action='device_enrolled'").fetchall()
        assert len(audit)==1 and 'token' not in audit[0]['details']
        db.execute('UPDATE devices SET enabled=false WHERE id=%s',(body['device_id'],))
    assert c.post(url,json=body).status_code==409

def test_enroll_requires_current_admin_origin_and_csrf(people):
    url='/api/v1/admin/devices/enroll'; body={'device_id':str(uuid4()),'label':'pc','token':'a'*64}
    assert client_login('head').post(url,json=body).status_code==403
    c=client_login()
    assert c.post(url,json=body,headers={'Origin':'https://wrong.example'}).status_code==403
    assert c.post(url,json=body,headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.post(url,json={**body,'token':'short'}).status_code==422
    with connect() as db:
        assert not db.execute('SELECT 1 FROM devices WHERE id=%s',(body['device_id'],)).fetchone()
