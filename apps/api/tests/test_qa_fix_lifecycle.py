from datetime import date
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db.session import get_db
from app.models.entities import Assignment,ClassSection,Constraint,OptimizationRun
from app.optimization.solver import solve
from app.services.source_authority import stage_source,preview_activation,activate_source,SourceError,latest_current_run
from app.services.manual_assignment import apply_manual_assignment,check_assignment_change
from app.services.readiness import validate_schedule
from app.services.importer import dashboard
from test_qa_full_audit_regressions import db,setup,workbook

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db]=lambda:db
    try:yield TestClient(app,raise_server_exceptions=False)
    finally:app.dependency_overrides.clear()

def test_manual_version_is_atomic_preserves_solver_metrics_and_effective_views(db,client):
    s,c,ls,gs=setup(db,1,2)
    run=solve(db,2,False,s.id)
    db.refresh(run)  # Compare persisted JSON before and after the manual transaction.
    score=run.score;summary=deepcopy(run.summary)
    old=db.scalar(select(Assignment).where(Assignment.run_id==run.id)).lecturer_id
    new=next(l.id for l in ls if l.id!=old)
    assert apply_manual_assignment(db,s.id,gs[0].id,new,False)['valid']
    manual=latest_current_run(db,s.id)
    assert manual.id!=run.id and manual.summary['solution_origin']=='MANUAL'
    assert manual.summary['experiment'] is None and manual.score is None
    db.refresh(run);assert run.summary==summary and run.score==score
    assert client.get(f'/api/v1/classes?semester_id={s.id}').json()[0]['lecturer_id']==new
    assert client.get(f'/api/v1/classes?semester_id={s.id}&run_id={run.id}').json()[0]['lecturer_id']==old
    assert dashboard(db,s.id)['unassigned_classes']==0
    workloads=client.get(f'/api/v1/workload?semester_id={s.id}').json()
    assert next(w for w in workloads if w['lecturer_id']==new)['teaching_groups']==1
    next_run=solve(db,2,False,s.id)
    assert next_run.summary['experiment'] is not None

def test_manual_commit_failure_preserves_current_version(db,monkeypatch):
    s,c,ls,gs=setup(db,1,2);run=solve(db,2,False,s.id);cid=gs[0].id;sid=s.id;lid=ls[0].id;rid=run.id
    monkeypatch.setattr(db,'commit',lambda:(_ for _ in ()).throw(RuntimeError('QA commit failure')))
    with pytest.raises(RuntimeError):apply_manual_assignment(db,sid,cid,lid,False)
    assert latest_current_run(db,sid).id==rid
    assert len(list(db.scalars(select(OptimizationRun))))==1

def test_lock_endpoint_locks_solver_choice_not_imported_choice(db,client):
    s,c,ls,gs=setup(db,1,2);run=solve(db,2,False,s.id)
    chosen=db.scalar(select(Assignment).where(Assignment.run_id==run.id)).lecturer_id
    gs[0].assigned_lecturer_id=next(l.id for l in ls if l.id!=chosen);db.commit()
    assert client.post(f'/api/v1/classes/{gs[0].id}/lock?semester_id={s.id}').status_code==200
    assert gs[0].assigned_lecturer_id==chosen and gs[0].locked_assignment
    historic=client.get(f'/api/v1/classes?semester_id={s.id}&run_id={run.id}').json()[0]
    assert historic['locked_assignment'] is False
    assert client.post(f'/api/v1/classes/{gs[0].id}/lock?semester_id=999999').status_code==422

@pytest.mark.parametrize('payload',[{}, {'lecturer_id':None},{'lecturer_id':0},{'lecturer_id':'garbage'},{'lecturer_id':-1}])
def test_manual_api_invalid_request_is_structured_422(db,client,payload):
    s,c,ls,gs=setup(db)
    for method,tail in [('post','assignment/check'),('patch','assignment')]:
        response=getattr(client,method)(f'/api/v1/classes/{gs[0].id}/{tail}?semester_id={s.id}',json=payload)
        assert response.status_code==422
        assert isinstance(response.json()['detail'],list)

def test_lock_impact_is_specific_and_lock_edit_invalidates_preview(db,tmp_path):
    s,c,ls,gs=setup(db,0,1)
    a=stage_source(db,workbook(tmp_path/'a.xlsx','[00000]Lecturer 0'),s.id,'CURRENT_SCHEDULE');db.commit()
    pa=preview_activation(db,s.id,a.id,'CURRENT_SCHEDULE');activate_source(db,s.id,a.id,'CURRENT_SCHEDULE',confirmed=True,preview_token=pa['preview_token'])
    b=stage_source(db,workbook(tmp_path/'b.xlsx','[00000]Lecturer 0',room='NEW'),s.id,'CURRENT_SCHEDULE');db.commit()
    before=preview_activation(db,s.id,b.id,'CURRENT_SCHEDULE')
    group=db.scalar(select(ClassSection));group.locked_assignment=True;db.commit()
    after=preview_activation(db,s.id,b.id,'CURRENT_SCHEDULE')
    assert after['lock_impact']==[{'class_id':group.id,'class_code':group.class_code,'lecturer_id':group.assigned_lecturer_id,'course_code':'QA101','effect':'ARCHIVED_NOT_TRANSFERRED'}]
    with pytest.raises(SourceError):activate_source(db,s.id,b.id,'CURRENT_SCHEDULE',confirmed=True,preview_token=before['preview_token'])

def test_confirmed_fixed_import_locks_only_assigned_groups(db,tmp_path):
    s,c,ls,gs=setup(db,0,1)
    src=stage_source(db,workbook(tmp_path/'source.xlsx','[00000]Lecturer 0'),s.id,'CURRENT_SCHEDULE');db.commit()
    p=preview_activation(db,s.id,src.id,'CURRENT_SCHEDULE')
    activate_source(db,s.id,src.id,'CURRENT_SCHEDULE',confirmed=True,preview_token=p['preview_token'],lock_imported=True)
    group=db.scalar(select(ClassSection));assert group.locked_assignment
    run=solve(db,2,False,s.id)
    assert db.scalar(select(Assignment).where(Assignment.run_id==run.id)).lecturer_id==group.assigned_lecturer_id

def test_fixed_import_conflict_rolls_back_activation(db,tmp_path):
    from openpyxl import load_workbook
    s,c,ls,gs=setup(db,0,1);path=workbook(tmp_path/'conflict.xlsx','[00000]Lecturer 0')
    w=load_workbook(path);row=[cell.value for cell in w.active[2]];row[0]=2;row[3]='QA1';w.active.append(row);w.save(path)
    src=stage_source(db,path,s.id,'CURRENT_SCHEDULE');db.commit();p=preview_activation(db,s.id,src.id,'CURRENT_SCHEDULE')
    with pytest.raises(SourceError) as error:activate_source(db,s.id,src.id,'CURRENT_SCHEDULE',confirmed=True,preview_token=p['preview_token'],lock_imported=True)
    assert error.value.detail['code']=='IMPORTED_LOCKS_REQUIRE_REVIEW'
    assert not list(db.scalars(select(ClassSection)))
    db.refresh(s);assert s.active_schedule_source_id is None

def test_semester_switch_edit_and_anchor_guard(db,client):
    a,c,ls,gs=setup(db)
    response=client.post('/api/v1/semesters',json={'name':'QA second','department_name':'QA','head_name':'QA Head','start_date':'2026-08-03','end_date':'2027-01-31'})
    assert response.status_code==200;b=response.json()['id']
    assert client.post(f'/api/v1/semesters/{a.id}/activate').status_code==200
    semesters=client.get('/api/v1/semesters').json();assert [s['id'] for s in semesters if s['is_active']]==[a.id]
    assert client.get(f'/api/v1/classes?semester_id={b}').json()==[]
    body={'name':'QA renamed','head_name':'QA Leader','start_date':'2026-08-03','end_date':'2027-01-31'}
    assert client.patch(f'/api/v1/semesters/{a.id}',json=body).status_code==200
    body['start_date']='2026-08-10'
    assert client.patch(f'/api/v1/semesters/{a.id}',json=body).status_code==422
    db.refresh(a);assert a.start_date==date(2026,8,3)

def test_actual_day_limit_agrees_solver_manual_and_readiness(db):
    s,c,ls,gs=setup(db,2,1)
    gs[1].sessions[0].active_weeks=[2];gs[1].sessions[0].start_date=gs[1].sessions[0].end_date=date(2026,8,10)
    db.add(Constraint(semester_id=s.id,name='one per day',constraint_type='MAX_SESSIONS_PER_DAY',hardness='hard',weight=1,lecturer_id=ls[0].id,target={'max':1},confirmed=True,active=True));db.commit()
    run=solve(db,2,False,s.id)
    assert validate_schedule(db,s.id,run.id)['valid']
    assert check_assignment_change(db,s.id,gs[0].id,ls[0].id)['valid']
    assert len(list(db.scalars(select(Assignment).where(Assignment.run_id==run.id))))==2

def test_final_validation_rejects_manual_snapshot_conflicting_with_hard_seminar(db):
    from app.models.entities import Seminar
    s,c,ls,gs=setup(db,1,1)
    run=solve(db,2,False,s.id)
    db.add(Seminar(semester_id=s.id,name='QA required seminar',chair_name='QA',members=[ls[0].id],
                   alternatives=[{'weekday':2,'periods':[1,2,3]}],hardness='hard',weight=1))
    db.commit()
    result=validate_schedule(db,s.id,run.id)
    assert not result['valid']
    assert 'HARD_SEMINAR_CONFLICT' in {e['code'] for e in result['blocking_errors']}

def test_batch_candidate_checks_reuse_request_snapshot_and_refresh_after_edit(db):
    from sqlalchemy import event
    from app.services.manual_assignment import assignment_check_context
    s,c,ls,gs=setup(db,2,1)
    solve(db,2,False,s.id)
    context=assignment_check_context(db,s.id)
    queries=[]
    def record(*args):queries.append(args[2])
    event.listen(db.bind,'before_cursor_execute',record)
    try:
        results=[check_assignment_change(db,s.id,g.id,ls[0].id,context=context) for g in gs]
    finally:event.remove(db.bind,'before_cursor_execute',record)
    assert queries==[]
    assert sorted(r['valid'] for r in results)==[False,True]
    gs[1].sessions[0].active_weeks=[2]
    gs[1].sessions[0].start_date=gs[1].sessions[0].end_date=date(2026,8,10)
    db.commit()
    assert all(check_assignment_change(db,s.id,g.id,ls[0].id)['valid'] for g in gs)
