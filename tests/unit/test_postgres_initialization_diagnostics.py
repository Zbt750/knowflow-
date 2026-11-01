"""No PostgreSQL: fake Popen plus explicitly bounded local Python probes."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from desktop import postgres as pg


def command(tmp_path):
    return [str(tmp_path/'initdb.exe'), '-D', str(tmp_path/'cluster'), '--pwfile=private.tmp']


def test_normal_exit_persists_separate_redacted_logs_and_run_identity(monkeypatch,tmp_path):
    calls=[]
    def launch(argv,**kw):
        calls.append(argv)
        kw['stdout'].write(b'normal stdout\npassword=do-not-publish\n')
        kw['stderr'].write(b'normal stderr\n')
        return SimpleNamespace(pid=765,wait=lambda **_:0)
    monkeypatch.setattr(pg.subprocess,'Popen',launch)
    result=pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    diagnostic=result.diagnostic
    record=json.loads(open(diagnostic['manifest_path'],encoding='utf-8').read())
    assert record['initialization_state']=='exited_ok' and record['root_returncode']==0
    assert record['run_id'] and record['root_pid']==765 and record['parent_pid']
    assert record['data_directory']==str((tmp_path/'cluster').resolve())
    assert 'normal stdout' in open(record['stdout_log'],encoding='utf-8').read()
    assert 'normal stderr' in open(record['stderr_log'],encoding='utf-8').read()
    assert 'do-not-publish' not in ''.join(p.read_text(encoding='utf-8') for p in (tmp_path/'logs').rglob('*') if p.is_file())
    assert len(calls)==1 and 'private.tmp' not in json.dumps(record)


def test_timeout_unknown_identity_does_not_kill_or_retry(monkeypatch,tmp_path):
    calls=[]
    def launch(argv,**kw):
        calls.append(argv);kw['stderr'].write(b'failed probe\n')
        def wait(**_):raise subprocess.TimeoutExpired(argv,90)
        return SimpleNamespace(pid=987,wait=wait,kill=lambda:pytest.fail('unverified fake may not be killed'))
    monkeypatch.setattr(pg.subprocess,'Popen',launch)
    with pytest.raises(pg.PostgresCommandFailure) as caught:pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    d=caught.value.diagnostic
    assert d['timed_out'] and d['initialization_state']=='timed_out'
    assert d['cleanup_state']=='blocked_unknown_identity' and d['root_returncode'] is None
    assert d['descendant_cleanup']['descendants_state']=='unknown'
    assert d['descendant_cleanup']['root_process_id']==987 and len(calls)==1
    assert 'failed probe' in open(d['stderr_log'],encoding='utf-8').read()


def test_nonzero_exit_and_full_record_survive_failed_result_wrapper(monkeypatch,tmp_path):
    monkeypatch.setattr(pg.subprocess,'Popen',lambda *a,**kw:SimpleNamespace(pid=12,wait=lambda **_:7))
    result=pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    with pytest.raises(pg.PostgresCommandFailure) as caught:
        pg._failed_result('desktop_postgres_initialization_failed',command(tmp_path),result,stage='initdb',timeout=90,cwd=tmp_path)
    assert caught.value.diagnostic['root_returncode']==7
    assert caught.value.diagnostic['natural_returncode']==7
    assert caught.value.diagnostic['initialization_state']=='exited_error'
    assert Path(caught.value.diagnostic['manifest_path']).is_file()


def test_logs_are_written_while_fake_process_is_still_waiting_and_split_secret_is_redacted(monkeypatch,tmp_path):
    def launch(argv,**kw):
        def wait(**_):
            kw['stdout'].write(b'first completed line\nplain-se');kw['stdout'].flush()
            time.sleep(.3)
            paths=list((tmp_path/'logs').glob('initdb-*/stdout.log'))
            assert len(paths)==1 and 'first completed line' in paths[0].read_text(encoding='utf-8')
            assert 'plain-se' not in paths[0].read_text(encoding='utf-8')
            kw['stdout'].write(b'cret\n');return 0
        return SimpleNamespace(pid=12,wait=wait)
    monkeypatch.setattr(pg.subprocess,'Popen',launch)
    r=pg._run(command(tmp_path),stage='initdb',cwd=tmp_path,diagnostic_secrets=('plain-secret',))
    assert 'plain-secret' not in r.stdout.decode() and '[REDACTED]' in r.stdout.decode()


def test_unique_run_folders_never_overwrite_an_earlier_record(monkeypatch,tmp_path):
    monkeypatch.setattr(pg.subprocess,'Popen',lambda *a,**kw:SimpleNamespace(pid=12,wait=lambda **_:0))
    first=pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    original=Path(first.diagnostic['manifest_path']).read_bytes()
    second=pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    assert first.diagnostic['run_id']!=second.diagnostic['run_id']
    assert Path(first.diagnostic['manifest_path']).read_bytes()==original


def binding(process,tmp_path):
    identity={'verified':True,'pid':process.pid,'creation_filetime':123,'executable':str(tmp_path/'initdb.exe')}
    return {'run_id':'new-run','data_directory':str(tmp_path/'cluster'),'command':process.args,
        'directory_bound':True,'identity':identity,'executable':identity['executable']}


@pytest.mark.parametrize('mismatch',['run','directory','command','creation','unqueryable','outside_directory'])
def test_cleanup_refuses_mismatched_or_unreadable_identity(monkeypatch,tmp_path,mismatch):
    from desktop import postgres_diagnostics as d
    p=SimpleNamespace(pid=13,args=command(tmp_path),_naiwa_init_run_id='new-run',_naiwa_init_data_directory=str(tmp_path/'cluster'),
        kill=lambda:pytest.fail('identity is not verified'))
    b=binding(p,tmp_path);current=dict(b['identity'])
    if mismatch=='run':p._naiwa_init_run_id='old-run'
    if mismatch=='directory':p._naiwa_init_data_directory=str(tmp_path/'other')
    if mismatch=='command':b['command']=['old-command']
    if mismatch=='creation':current['creation_filetime']=999
    if mismatch=='unqueryable':current={'verified':False,'winerror':5}
    if mismatch=='outside_directory':b['directory_bound']=False
    monkeypatch.setattr(d,'_root_identity',lambda _:current)
    result=d._stop_owned_root(p,b)
    assert result['cleanup_state']=='blocked_unknown_identity' and result['descendants_state']=='unknown'


@pytest.mark.parametrize('failure',[False,True])
def test_verified_root_cleanup_never_claims_descendants_cleaned(monkeypatch,tmp_path,failure):
    from desktop import postgres_diagnostics as d
    calls=[]
    def kill():
        calls.append('kill')
        if failure:raise PermissionError(13,'denied')
    p=SimpleNamespace(pid=13,args=command(tmp_path),_naiwa_init_run_id='new-run',_naiwa_init_data_directory=str(tmp_path/'cluster'),
        poll=lambda:None,kill=kill,wait=lambda **_:-1)
    b=binding(p,tmp_path);monkeypatch.setattr(d,'_root_identity',lambda _:b['identity'])
    result=d._stop_owned_root(p,b)
    assert result['descendants_state']=='unknown' and calls==['kill']
    assert result['cleanup_state']==('root_cleanup_failed' if failure else 'root_stopped_descendants_unknown')
    assert result['root_returncode']==(None if failure else -1)


def test_partial_version_file_is_not_a_success_or_permission_to_reinitialize(monkeypatch,tmp_path):
    from desktop.runtime_paths import RuntimePaths
    m=pg.ManagedPostgres(RuntimePaths.windows(resources=tmp_path/'resources',local_app_data=tmp_path/'data'),tmp_path/'bin',port=18761)
    m.cluster.mkdir(parents=True);(m.cluster/'PG_VERSION').write_text('18')
    monkeypatch.setattr(pg,'_run',lambda *a,**kw:pytest.fail('partial cluster must not launch anything'))
    with pytest.raises(ValueError,match='partial_cluster'):m._initialize()
    assert (m.cluster/'PG_VERSION').read_text()=='18'


def test_log_reader_failure_is_recorded_before_any_launch(monkeypatch,tmp_path):
    from desktop import postgres_diagnostics as d
    def fail(_):raise PermissionError(13,'capture denied')
    monkeypatch.setattr(d,'_capture_reader',fail)
    monkeypatch.setattr(pg.subprocess,'Popen',lambda *a,**kw:pytest.fail('cannot launch without logs'))
    with pytest.raises(pg.PostgresCommandFailure) as caught:pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    assert caught.value.diagnostic['initialization_state']=='capture_failed'
    assert caught.value.diagnostic['failure_phase']=='capture_file_setup'


@pytest.mark.parametrize('state',['timed_out','running','launch_failed','capture_failed','bad_json'])
def test_failed_run_manifest_blocks_reinitialization_even_without_cluster_files(monkeypatch,tmp_path,state):
    from desktop.runtime_paths import RuntimePaths
    m=pg.ManagedPostgres(RuntimePaths.windows(resources=tmp_path/'resources',local_app_data=tmp_path/'data'),tmp_path/'bin',port=18761)
    marker=m.paths.data/'logs/initdb-old/run.json';marker.parent.mkdir(parents=True)
    marker.write_text('invalid' if state=='bad_json' else json.dumps({'initialization_state':state}))
    monkeypatch.setattr(pg,'_run',lambda *a,**kw:pytest.fail('may not launch a second initialization'))
    with pytest.raises(ValueError,match='initialization_attempt_exists'):m._initialize()
    assert marker.exists()


def test_root_already_exited_after_timeout_is_recorded_without_any_kill(monkeypatch,tmp_path):
    from desktop import postgres_diagnostics as d
    p=SimpleNamespace(pid=13,args=command(tmp_path),_naiwa_init_run_id='new-run',_naiwa_init_data_directory=str(tmp_path/'cluster'),
        poll=lambda:6,kill=lambda:pytest.fail('already exited'))
    b=binding(p,tmp_path);monkeypatch.setattr(d,'_root_identity',lambda _:b['identity'])
    result=d._stop_owned_root(p,b)
    assert result['root_returncode']==6 and result['root_end_reason']=='exited_after_deadline'
    assert result['descendants_state']=='unknown'


def test_timeout_and_verified_cleanup_failure_are_independent_and_not_retried(monkeypatch,tmp_path):
    from desktop import postgres_diagnostics as d
    launches=[]
    def launch(argv,**kw):
        launches.append(argv)
        def wait(**_):raise subprocess.TimeoutExpired(argv,90)
        def kill():raise PermissionError(13,'denied')
        return SimpleNamespace(pid=13,args=argv,wait=wait,poll=lambda:None,kill=kill)
    monkeypatch.setattr(pg.subprocess,'Popen',launch)
    monkeypatch.setattr(d,'_root_identity',lambda p:{'verified':True,'pid':13,'creation_filetime':123,'executable':str(tmp_path/'initdb.exe')})
    with pytest.raises(pg.PostgresCommandFailure) as caught:pg._run(command(tmp_path),stage='initdb',cwd=tmp_path)
    record=json.loads(Path(caught.value.diagnostic['manifest_path']).read_text(encoding='utf-8'))
    assert record['initialization_state']=='timed_out' and record['cleanup_state']=='root_cleanup_failed'
    assert record['descendant_cleanup']['error_type']=='PermissionError' and len(launches)==1


def test_local_python_probe_natural_exit_records_native_handle_and_logs(tmp_path):
    probe=tmp_path/'probe.py'
    probe.write_text("import sys;print('probe stdout',flush=True);print('probe stderr',file=sys.stderr,flush=True)")
    result=pg._run([sys.executable,str(probe),'-D',str(tmp_path/'probe-data')],stage='initdb',cwd=tmp_path,timeout=5)
    assert result.returncode==0 and result.diagnostic['natural_returncode']==0
    assert b'probe stdout' in result.stdout and b'probe stderr' in result.stderr
    assert result.diagnostic['root_identity_at_launch']['verified']


def test_local_python_probe_timeout_only_stops_verified_owned_handle(tmp_path):
    probe=tmp_path/'probe.py'
    # Self-exits even if verification fails: never leave an unbounded probe.
    probe.write_text("import time;print('bounded probe',flush=True);time.sleep(3)")
    with pytest.raises(pg.PostgresCommandFailure) as caught:
        pg._run([sys.executable,str(probe),'-D',str(tmp_path/'probe-data')],stage='initdb',cwd=tmp_path,timeout=.3)
    d=caught.value.diagnostic
    assert d['initialization_state']=='timed_out' and d['natural_returncode'] is None
    assert d['cleanup_state']=='root_stopped_descendants_unknown'
    assert d['descendant_cleanup']['identity_verified'] and d['root_returncode'] is not None
    assert 'bounded probe' in d['stdout_tail']
