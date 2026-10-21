"""Monthly totals computed in PostgreSQL from merged intervals, never summed PC time."""
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import UUID
import re
import hashlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from psycopg.types.json import Jsonb
from .auth import authorize, scope, departments
from .db import connect

router=APIRouter(prefix='/api/v1')
TZ=ZoneInfo('Europe/Moscow')
STATES=('active','afk','locked','unknown')

# All clipping, membership filtering and overlaps stay in the database.
# Priority represents the most active of simultaneous computers. No double time.
REPORT_SQL='''
WITH authorized_memberships AS MATERIALIZED (
 SELECT employee_id,range_agg(tstzrange(valid_from,coalesce(valid_to,'infinity'::timestamptz),'[)')) ranges
 FROM department_memberships WHERE group_id=ANY(%(access_group)s::uuid[])
 AND valid_from<%(end)s AND (valid_to IS NULL OR valid_to>%(start)s) GROUP BY employee_id
), clipped AS (
 SELECT e.employee_id,e.state,e.key_presses,e.start_at,e.end_at,
        greatest(e.start_at,%(start)s,m.lo) lo,least(e.end_at,%(end)s,m.hi) hi,
        (%(access_group)s::uuid[] IS NULL OR (e.start_at>=m.lo AND e.end_at<=m.hi)) keys_allowed
 FROM events e LEFT JOIN authorized_memberships am ON am.employee_id=e.employee_id CROSS JOIN LATERAL (
   SELECT %(start)s::timestamptz lo,%(end)s::timestamptz hi WHERE %(access_group)s::uuid[] IS NULL
   UNION ALL
   SELECT lower(r),upper(r) FROM unnest(am.ranges) r WHERE lower(r)<e.end_at AND upper(r)>e.start_at
 ) m
 WHERE e.employee_id IS NOT NULL AND e.start_at<%(end)s AND e.end_at>%(start)s
   AND (%(access_group)s::uuid[] IS NULL OR am.employee_id IS NOT NULL)
   AND (%(group)s::uuid[] IS NULL OR EXISTS (
     SELECT 1 FROM department_memberships selected WHERE selected.employee_id=e.employee_id
     AND selected.group_id=ANY(%(group)s::uuid[]) AND selected.valid_from<%(end)s
     AND (selected.valid_to IS NULL OR selected.valid_to>%(start)s)))
   AND (%(employee)s::uuid IS NULL OR e.employee_id=%(employee)s::uuid)
), slices AS (
 SELECT employee_id,state,key_presses,end_at,keys_allowed,d::date AS day,
   tstzrange(greatest(lo,d AT TIME ZONE 'Europe/Moscow'),
             least(hi,(d+interval '1 day') AT TIME ZONE 'Europe/Moscow'),'[)') span
 FROM clipped CROSS JOIN LATERAL generate_series(
   (lo AT TIME ZONE 'Europe/Moscow')::date::timestamp,
   ((hi-interval '1 microsecond') AT TIME ZONE 'Europe/Moscow')::date::timestamp,interval '1 day') d
 WHERE hi>lo
), merged AS (
 SELECT employee_id,day,
   coalesce(range_agg(span) FILTER(WHERE state='active'),'{}'::tstzmultirange) a,
   coalesce(range_agg(span) FILTER(WHERE state='afk'),'{}'::tstzmultirange) f,
   coalesce(range_agg(span) FILTER(WHERE state='locked'),'{}'::tstzmultirange) l,
   coalesce(range_agg(span) FILTER(WHERE state='unknown'),'{}'::tstzmultirange) u,
   sum(CASE WHEN keys_allowed AND (end_at-interval '1 microsecond') AT TIME ZONE 'Europe/Moscow'>=day::timestamp
       AND (end_at-interval '1 microsecond') AT TIME ZONE 'Europe/Moscow'<day::timestamp+interval '1 day'
       THEN key_presses ELSE 0 END)::bigint keys
 FROM slices GROUP BY employee_id,day
), normalized AS (
 SELECT employee_id,day,keys,a,f-a f,l-(a+f) l,u-(a+f+l) u FROM merged
)
SELECT employee_id,day,keys,
  coalesce((SELECT sum(extract(epoch FROM upper(r)-lower(r))) FROM unnest(a) r),0)::float8 active,
  coalesce((SELECT sum(extract(epoch FROM upper(r)-lower(r))) FROM unnest(f) r),0)::float8 afk,
  coalesce((SELECT sum(extract(epoch FROM upper(r)-lower(r))) FROM unnest(l) r),0)::float8 locked,
  coalesce((SELECT sum(extract(epoch FROM upper(r)-lower(r))) FROM unnest(u) r),0)::float8 unknown,
  CASE WHEN %(segments)s THEN (
    SELECT coalesce(jsonb_agg(jsonb_build_object('state',state,'start',lower(r),'end',upper(r)) ORDER BY lower(r)),'[]')
    FROM (SELECT 'active' state,unnest(a) r UNION ALL SELECT 'afk',unnest(f)
          UNION ALL SELECT 'locked',unnest(l) UNION ALL SELECT 'unknown',unnest(u)) parts
  ) END segments
FROM normalized ORDER BY day,employee_id
'''

def bounds(month):
    if not re.fullmatch(r'20[2-9][0-9]-(0[1-9]|1[0-2])',month): raise HTTPException(422,'invalid_month')
    year,m=map(int,month.split('-'))
    start=datetime(year,m,1,tzinfo=TZ)
    return start,start+timedelta(days=monthrange(year,m)[1])

def period_bounds(month=None,start_date=None,end_date=None):
    if month is not None:
        if start_date is not None or end_date is not None:raise HTTPException(422,'ambiguous_period')
        return bounds(month)
    if start_date is None or end_date is None:raise HTTPException(422,'period_required')
    if not 2020<=start_date.year<=2099 or not 2020<=end_date.year<=2099 or end_date<start_date:
        raise HTTPException(422,'invalid_period')
    if (end_date-start_date).days>=366:raise HTTPException(422,'period_too_long')
    return datetime.combine(start_date,datetime.min.time(),tzinfo=TZ),datetime.combine(end_date+timedelta(days=1),datetime.min.time(),tzinfo=TZ)

def public_report(value):
    """Combine already de-overlapped states; never rewrite raw client events/cache."""
    if isinstance(value,list):return [public_report(x) for x in value]
    if not isinstance(value,dict):return value
    result={k:public_report(v) for k,v in value.items()}
    if 'afk' in result and 'locked' in result:
        result['afk']+=result.pop('locked')
    if result.get('state')=='locked':result['state']='afk'
    if 'segments' in result:
        merged=[]
        for segment in result['segments'] or []:
            if merged and merged[-1]['state']==segment['state'] and merged[-1]['end']==segment['start']:
                merged[-1]['end']=segment['end']
            else:merged.append(dict(segment))
        result['segments']=merged
    return result

def period_metadata(result,start,end):
    result['period']={'start_date':start.date(),'end_date':(end-timedelta(days=1)).date()}
    return public_report(result)

def zero(): return dict(active=0,afk=0,locked=0,unknown=0,keys=0)

def group_list(value):
    return value if value is None or isinstance(value,list) else [value]

def membership_status(db, people, groups):
    # Read live, never cache membership badges alongside historical metrics.
    if groups is None or not people:return
    rows=db.execute('''
        SELECT employee_id,bool_or(valid_to IS NULL) current,
               max(valid_from) FILTER(WHERE valid_to IS NULL) joined_at,
               max(valid_to) left_at
        FROM department_memberships WHERE group_id=ANY(%s::uuid[])
        AND employee_id=ANY(%s::uuid[]) GROUP BY employee_id
    ''',(groups,[p['id'] for p in people.values()]))
    for row in rows:
        people[str(row['employee_id'])]['department_membership']={k:v for k,v in row.items() if k!='employee_id'}


def raw_report_data(db, start, end, group_id=None, employee_id=None, segments=False, *, access_groups=...):
    group_id=group_list(group_id)
    access_groups=group_id if access_groups is ... else group_list(access_groups)
    # Include employees with observed membership during this period, even if removed later.
    employees=db.execute('''SELECT e.id,e.principal,e.display_name,e.enabled,e.present FROM employees e
       WHERE (%s::uuid IS NULL OR e.id=%s::uuid) AND (%s::uuid[] IS NULL OR EXISTS (
        SELECT 1 FROM department_memberships m WHERE m.employee_id=e.id AND m.group_id=ANY(%s::uuid[])
         AND m.valid_from<%s AND (m.valid_to IS NULL OR m.valid_to>%s))) ORDER BY e.display_name,e.principal''',
        (employee_id,employee_id,group_id,group_id,end,start)).fetchall()
    if employee_id and not employees: raise HTTPException(404,'employee_not_found')
    rows=db.execute(REPORT_SQL,{'start':start,'end':end,'group':group_id,'access_group':access_groups,'employee':employee_id,'segments':segments}).fetchall()
    people={str(e['id']):{**e,'totals':zero(),'days':[]} for e in employees}
    days={ (start+timedelta(days=n)).date():{'day':(start+timedelta(days=n)).date(),**zero()}
        for n in range((end.date()-start.date()).days)}
    total=zero()
    for r in rows:
        person=people.get(str(r['employee_id']))
        if not person: continue
        person['days'].append({k:v for k,v in r.items() if k!='employee_id' and (k!='segments' or segments)})
        for k in total:
            person['totals'][k]+=r[k];days[r['day']][k]+=r[k];total[k]+=r[k]
    membership_status(db,people,group_id)
    return {'totals':total,'days':list(days.values()),'employees':list(people.values()),
            'timezone':'Europe/Moscow','generated_at':datetime.now(TZ)}

def report_data(db, start, end, group_id=None, employee_id=None, segments=False, *, access_groups=...):
    # Department selection chooses people; access_groups alone limits their history.
    # The default preserves restricted behavior for internal callers.
    group_id=group_list(group_id)
    access_groups=group_id if access_groups is ... else group_list(access_groups)
    if employee_id or segments or (end-start).days<=1:
        return raw_report_data(db,start,end,group_id,employee_id,segments,access_groups=access_groups)
    # Cache only day statistics. Authorization and current employee labels are always read fresh.
    directory=db.execute('SELECT snapshot_hash FROM directory_sync WHERE id=1').fetchone()
    signature=directory['snapshot_hash'] if directory else ''
    signature+=':'+str(db.execute('SELECT revision FROM structure_version WHERE id=1').fetchone()['revision'])
    def cache_scope(groups):return ','.join(sorted(str(i) for i in groups)) if groups is not None else '*'
    scope_key=hashlib.sha256(('v2:access='+cache_scope(access_groups)).encode()).hexdigest()
    versions={r['day']:r['revision'] for r in db.execute(
        'SELECT day,revision FROM report_versions WHERE day>=%s AND day<%s',(start.date(),end.date()))}
    cache={r['day']:r['data'] for r in db.execute(
        '''SELECT c.day,c.data FROM report_cache c LEFT JOIN report_versions v ON v.day=c.day
        WHERE c.scope=%s AND c.day>=%s AND c.day<%s AND c.directory_hash=%s
        AND c.revision=coalesce(v.revision,0)''',(scope_key,start.date(),end.date(),signature))}
    dates=[(start+timedelta(days=n)).date() for n in range((end-start).days)]
    missing=[d for d in dates if d not in cache]
    if missing:
        lo=datetime.combine(min(missing),datetime.min.time(),tzinfo=TZ)
        hi=datetime.combine(max(missing)+timedelta(days=1),datetime.min.time(),tzinfo=TZ)
        fresh=raw_report_data(db,lo,hi,None,access_groups=access_groups)
        fresh_days={d:[] for d in missing}
        for person in fresh['employees']:
            for day in person['days']:
                if day['day'] in fresh_days:
                    fresh_days[day['day']].append({'employee_id':str(person['id']),**{k:day[k] for k in zero()}})
        for day,rows in fresh_days.items():
            db.execute('''INSERT INTO report_cache(scope,day,revision,directory_hash,data) VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(scope,day) DO UPDATE SET revision=excluded.revision,directory_hash=excluded.directory_hash,
                data=excluded.data,updated_at=now()''',(scope_key,day,versions.get(day,0),signature,Jsonb(rows)))
            cache[day]=rows
    employees=db.execute('''SELECT e.id,e.principal,e.display_name,e.enabled,e.present FROM employees e
        WHERE %s::uuid[] IS NULL OR EXISTS (SELECT 1 FROM department_memberships m WHERE m.employee_id=e.id
        AND m.group_id=ANY(%s::uuid[]) AND m.valid_from<%s AND (m.valid_to IS NULL OR m.valid_to>%s))
        ORDER BY e.display_name,e.principal''',(group_id,group_id,end,start)).fetchall()
    people={str(e['id']):{**e,'totals':zero(),'days':[]} for e in employees}
    total=zero(); days=[]
    for day in dates:
        daily={'day':day,**zero()}
        for row in cache[day]:
            person=people.get(row['employee_id'])
            if not person: continue
            person['days'].append({'day':day,**{k:row[k] for k in zero()}})
            for k in total:
                person['totals'][k]+=row[k];daily[k]+=row[k];total[k]+=row[k]
        days.append(daily)
    membership_status(db,people,group_id)
    return {'totals':total,'days':days,'employees':list(people.values()),
            'timezone':'Europe/Moscow','generated_at':datetime.now(TZ)}


@router.get('/reports/month')
def month_report(request: Request,month: str,department: UUID|None=None,employee: UUID|None=None):
    start,end=bounds(month)
    with connect() as db:
        user=authorize(request,db);authorized=scope(db,user,department)
        result=report_data(db,start,end,authorized,employee,access_groups=authorized)
        result['directory']=db.execute('SELECT last_success FROM directory_sync WHERE id=1').fetchone()
        if user['is_admin'] and employee is None and department is None:
            result['unassigned_intervals']=db.execute('''SELECT count(*) n FROM events
                WHERE employee_id IS NULL AND start_at<%s AND end_at>%s''',(end,start)).fetchone()['n']
        return period_metadata(result,start,end)

@router.get('/reports/day')
def day_report(request: Request,day: date,employee: UUID,department: UUID|None=None):
    start=datetime.combine(day,datetime.min.time(),tzinfo=TZ)
    if not 2020<=day.year<=2099: raise HTTPException(422,'invalid_day')
    with connect() as db:
        user=authorize(request,db);authorized=scope(db,user,department)
        end=start+timedelta(days=1)
        result=report_data(db,start,end,authorized,employee,True,access_groups=authorized)
        result['devices']=db.execute('''SELECT d.id,d.label,d.hostname,bool_or(e.resolution='local_ldap_binding') AS local_account FROM events e
            JOIN devices d ON d.id=e.device_id WHERE e.employee_id=%s AND e.start_at<%s AND e.end_at>%s
            AND (%s::uuid[] IS NULL OR EXISTS (SELECT 1 FROM department_memberships m
                WHERE m.employee_id=e.employee_id AND m.group_id=ANY(%s::uuid[])
                AND greatest(e.start_at,m.valid_from,%s)<least(e.end_at,coalesce(m.valid_to,'infinity'),%s)))
            GROUP BY d.id,d.label,d.hostname ORDER BY d.label''',(employee,end,start,authorized,authorized,start,end)).fetchall()
        return period_metadata(result,start,end)

@router.get('/reports/period')
def period_report(request:Request,start_date:date,end_date:date,department:UUID|None=None,employee:UUID|None=None,details:bool=False):
    start,end=period_bounds(start_date=start_date,end_date=end_date)
    if details and not employee:raise HTTPException(422,'employee_required')
    with connect() as db:
        user=authorize(request,db);authorized=scope(db,user,department)
        result=report_data(db,start,end,authorized,employee,details,access_groups=authorized)
        if details:
            result['devices']=db.execute('''SELECT d.id,d.label,d.hostname,bool_or(e.resolution='local_ldap_binding') local_account
                FROM events e JOIN devices d ON d.id=e.device_id WHERE e.employee_id=%s AND e.start_at<%s AND e.end_at>%s
                AND (%s::uuid[] IS NULL OR EXISTS(SELECT 1 FROM department_memberships m WHERE m.employee_id=e.employee_id
                    AND m.group_id=ANY(%s::uuid[]) AND greatest(e.start_at,m.valid_from,%s)<least(e.end_at,coalesce(m.valid_to,'infinity'),%s)))
                GROUP BY d.id,d.label,d.hostname ORDER BY d.label''',(employee,end,start,authorized,authorized,start,end)).fetchall()
        if user['is_admin'] and employee is None and department is None:
            result['unassigned_intervals']=db.execute('SELECT count(*) n FROM events WHERE employee_id IS NULL AND start_at<%s AND end_at>%s',(end,start)).fetchone()['n']
        return period_metadata(result,start,end)

@router.get('/admin/settings')
def settings(request: Request):
    with connect() as db:
        authorize(request,db,admin=True)
        return {
          'groups':db.execute('''SELECT g.id,g.name,g.present,
              coalesce((SELECT jsonb_agg(employee_id ORDER BY employee_id) FROM group_memberships m WHERE m.group_id=g.id AND valid_to IS NULL),'[]') members
              FROM directory_groups g ORDER BY g.name''').fetchall(),
          'departments':db.execute('''SELECT d.*,g.name AS ldap_name,g.present AS source_available,
              coalesce((SELECT jsonb_object_agg(employee_id,(valid_from AT TIME ZONE 'Europe/Moscow')::date) FROM department_memberships m WHERE m.group_id=d.id AND valid_to IS NULL),'{}') membership_starts,
              coalesce((SELECT jsonb_agg(employee_id ORDER BY employee_id) FROM department_memberships m WHERE m.group_id=d.id AND valid_to IS NULL),'[]') members,
              coalesce((SELECT jsonb_agg(employee_id ORDER BY employee_id) FROM department_heads h WHERE h.group_id=d.id),'[]') heads
              FROM departments d LEFT JOIN directory_groups g ON g.id=d.ldap_group_id ORDER BY d.enabled DESC,d.name''').fetchall(),
          'employees':db.execute('SELECT id,principal,display_name,enabled,present FROM employees ORDER BY principal').fetchall(),
          'devices':db.execute('''SELECT d.id,d.label,d.hostname,d.enabled,d.last_seen,d.agent_version,
              last_event.state,last_event.resolution,last_event.end_at AS observed_at,u.principal,u.display_name
              FROM devices d LEFT JOIN LATERAL (
                SELECT employee_id,state,end_at,resolution FROM events WHERE device_id=d.id ORDER BY start_at DESC LIMIT 1
              ) last_event ON true LEFT JOIN employees u ON u.id=last_event.employee_id ORDER BY d.label''').fetchall(),
          'directory':db.execute('SELECT last_success,users_count,groups_count,error FROM directory_sync WHERE id=1').fetchone()}


def department_summary(db,user,start,end,department=None):
    authorized=scope(db,user,department)
    result=report_data(db,start,end,authorized,access_groups=authorized)
    result['departments']=[]
    for d in departments(db,user):
        if department and d['id']!=department:continue
        data=report_data(db,start,end,[d['id']])
        result['departments'].append({**d,'totals':data['totals'],'employees_count':len(data['employees']),
            'observed_count':sum(bool(p['days']) for p in data['employees'])})
    return result

@router.get('/reports/departments')
def department_report(request: Request,month: str|None=None,department: UUID|None=None,start_date:date|None=None,end_date:date|None=None):
    start,end=period_bounds(month,start_date,end_date)
    with connect() as db:
        user=authorize(request,db)
        return period_metadata(department_summary(db,user,start,end,department),start,end)


def csv_cell(value):
    # Prevent spreadsheet formula execution, including formulas hidden after whitespace.
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r','\n')):
        return "'"+value
    return value

@router.get('/reports/export')
def export_report(request: Request,month: str|None=None,kind: str='employees',department: UUID|None=None,employee: UUID|None=None,start_date:date|None=None,end_date:date|None=None,format:str='csv'):
    import csv
    from io import StringIO
    from fastapi.responses import Response
    if kind not in ('employees','daily','departments'):raise HTTPException(422,'invalid_export_kind')
    if kind=='departments' and employee:raise HTTPException(422,'invalid_export_scope')
    if format not in ('csv','xlsx'):raise HTTPException(422,'invalid_export_format')
    start,end=period_bounds(month,start_date,end_date)
    period=[str(start.date()),str((end-timedelta(days=1)).date())]
    with connect() as db:
        user=authorize(request,db);authorized=scope(db,user,department)
        data=public_report(department_summary(db,user,start,end,department) if kind=='departments' else report_data(db,start,end,authorized,employee,access_groups=authorized))
        label=next((d['name'] for d in departments(db,user) if d['id']==department),
            'Все сотрудники' if user['is_admin'] else 'Все доступные отделы')
        # One explicit schema drives labels AND values in both file formats.
        metric_columns=[('Активность (часов)','active'),('AFK (часов)','afk'),('Неизвестно (часов)','unknown'),('Нажатия клавиш','keys')]
        def metrics(t):return [int(t[key]) if key=='keys' else round(t[key]/3600,4) for _,key in metric_columns]
        columns=[label for label,_ in metric_columns]
        rows=[]
        if kind=='departments':
            header=['Период с (Москва)','Период по (Москва)','Отдел','Сотрудников','Сотрудников с данными']+columns
            rows=[period+[d['name'],d['employees_count'],d['observed_count']]+metrics(d['totals']) for d in data['departments']]
            rows.append(period+['Общий итог без повторного учёта сотрудников',len(data['employees']),sum(bool(p['days']) for p in data['employees'])]+metrics(data['totals']))
        elif kind=='daily':
            header=['Дата (Москва)','Отдел / область','Сотрудник','Логин']+columns
            rows=[[str(day['day']),label,p['display_name'],p['principal']]+metrics(day)
                for p in data['employees'] for day in p['days']]
        else:
            header=['Период с (Москва)','Период по (Москва)','Отдел / область','Сотрудник','Логин','Дней с данными']+columns
            rows=[period+[label,p['display_name'],p['principal'],len(p['days'])]+metrics(p['totals']) for p in data['employees']]
    filename=f'activity-{kind}-{period[0]}_{period[1]}.{format}'
    if format=='xlsx':
        from .spreadsheet_export import workbook_bytes
        return Response(workbook_bytes(header,rows),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})
    stream=StringIO(newline='');writer=csv.writer(stream,delimiter=';',lineterminator='\r\n',quoting=csv.QUOTE_ALL)
    writer.writerow(header)
    for row in rows:writer.writerow([csv_cell(v) for v in row])
    return Response(stream.getvalue().encode('utf-8-sig'),media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})
