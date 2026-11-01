from datetime import datetime,timedelta,timezone
from backend.services.post_graduation_service import project_post_practice

NOW=datetime(2026,10,9,tzinfo=timezone.utc)
def row(i,result='right',independent=True,reliable=True):
    return dict(identity=str(i),time=NOW-timedelta(days=3-i),number=1,result=result,independent=independent,reliable=reliable,type='single_choice',tags=['skillA','skillB'])
def project(rows,**kw):return project_post_practice(rows,now=NOW,graduated_at=NOW-timedelta(days=10),**kw)
def test_single_and_multiple_risks():
    assert project([row(0,'wrong')]).status=='INSUFFICIENT'
    assert project([row(0,'wrong'),row(1,'wrong')]).status=='CONSOLIDATE'
def test_recovery_requires_distinct_cross_day_coverage():
    assert project([row(0),row(1),row(2)]).status=='GOOD'
    rows=[row(0),row(1),row(2)]
    for r in rows:r['identity']='same'
    assert project(rows).status=='INSUFFICIENT'
def test_unreliable_unknown_assisted_and_truncated_do_not_grant_good():
    assert project([row(0,'wrong',reliable=False)]).reliable_attempt_count==0
    assert project([row(0,independent=False)]).status=='REVIEW'
    assert project([row(0),row(1),row(2)],truncated=True).status!='GOOD'
def test_generation_no_attempts_and_future_records_do_not_improve():
    assert project([]).status=='INSUFFICIENT'
    r=row(0);r['time']=NOW+timedelta(days=1)
    assert project([r]).observed_attempt_count==0
