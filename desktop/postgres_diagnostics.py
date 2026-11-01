"""Owned initdb diagnostics; no discovery/termination of arbitrary PID trees."""
from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from uuid import uuid4


def _root_identity(process):
    """Query only our Popen handle. Denied/missing information is not identity."""
    if os.name != 'nt' or not getattr(process, '_handle', None):
        return {'verified': False, 'limitation': 'native_owned_handle_unavailable'}
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.GetProcessId.argtypes=[w.HANDLE];k.GetProcessId.restype=w.DWORD
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    k.GetProcessTimes.argtypes=[w.HANDLE]+[ctypes.POINTER(w.FILETIME)]*4
    k.IsProcessInJob.argtypes=[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)]
    handle=int(process._handle);path=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(path))
    times=[w.FILETIME() for _ in range(4)]
    if not k.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)) or not k.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
        return {'verified':False,'winerror':ctypes.get_last_error()}
    pid=int(k.GetProcessId(handle))
    if not pid:return {'verified':False,'winerror':ctypes.get_last_error()}
    result={'verified':True,'pid':pid,
        'executable':str(Path(path.value).resolve()),
        'creation_filetime':(times[0].dwHighDateTime<<32)+times[0].dwLowDateTime}
    in_job=w.BOOL()
    if k.IsProcessInJob(handle,None,ctypes.byref(in_job)):result['in_job']=bool(in_job.value)
    else:result['job_query_error']=ctypes.get_last_error()
    return result


def _capture_reader(stream):
    """Independent file offset: reading logs must never seek the child writer."""
    stream.flush()
    if os.name=='nt':
        from ctypes import wintypes as w
        import msvcrt
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        k.CreateFileW.restype=w.HANDLE
        handle=k.CreateFileW(str(stream.name),0x80000000,7,None,3,0,None)
        if handle==w.HANDLE(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        return os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY),'rb',buffering=0)
    return open(f'/proc/self/fd/{stream.fileno()}','rb',buffering=0)


def _stop_owned_root(process,binding):
    """No taskkill, process-group kill, historical PID lookup, or guessed child."""
    result={'root_process_id':process.pid,'run_id':binding['run_id'],
        'descendants_state':'unknown','root_returncode':None,'cleanup_state':'blocked_unknown_identity'}
    try:
        if (getattr(process,'_naiwa_init_run_id',None)!=binding['run_id']
                or getattr(process,'_naiwa_init_data_directory',None)!=binding['data_directory']
                or list(getattr(process,'args',[]))!=binding['command']):
            result['reason']='launch_binding_mismatch';return result
        current=_root_identity(process)
        if not binding['identity'].get('verified') or current!=binding['identity'] or not binding['directory_bound']:
            result['reason']='owned_handle_identity_or_directory_not_verified';return result
        if current['pid']!=process.pid or Path(current['executable'])!=Path(binding['executable']):
            result['reason']='process_identity_mismatch';return result
        result['identity_verified']=True
        code=process.poll()
        if code is not None:
            result.update(root_returncode=code,cleanup_state='root_exited_descendants_unknown',root_end_reason='exited_after_deadline')
            return result
        process.kill()  # exact retained Windows process handle, never a PID search
        code=process.wait(timeout=5)
        result.update(root_returncode=code,cleanup_state='root_stopped_descendants_unknown',root_end_reason='terminated_owned_handle')
    except (OSError,subprocess.TimeoutExpired) as exc:
        result.update(cleanup_state='root_cleanup_failed',error_type=type(exc).__name__,winerror=getattr(exc,'winerror',None))
    return result


def run_initialization(command,*,timeout,env,extra_env,cwd,secrets=()):
    from desktop.postgres import _command_diagnostic,_diagnostic_text,PostgresCommandFailure
    def safe(value):
        text=str(value)
        for secret in secrets:
            if secret:text=text.replace(secret,'[REDACTED]')
        return _diagnostic_text(text,limit=max(8192,len(text)))
    def safe_object(value):
        if isinstance(value,dict):return {k:safe_object(v) for k,v in value.items()}
        if isinstance(value,list):return [safe_object(v) for v in value]
        return safe(value) if isinstance(value,str) else value
    start=time.monotonic();run_id=uuid4().hex
    base=Path(cwd or Path.cwd()).resolve()
    folder=base/'logs'/('initdb-'+run_id)
    record=_command_diagnostic(command,stage='initdb',timeout=timeout,cwd=base,extra_env=extra_env)
    record.update(run_id=run_id,started_at=datetime.now(timezone.utc).isoformat(),parent_pid=os.getpid(),
        executable_path=str(Path(command[0]).resolve()),data_directory=None,root_pid=None,
        root_returncode=None,natural_returncode=None,initialization_state='preparing',cleanup_state='not_requested',
        descendants_state='unknown',process_information_limitations=['Descendant enumeration not available; no complete-tree claim.'],
        manifest_path=str(folder/'run.json'),stdout_log=str(folder/'stdout.log'),stderr_log=str(folder/'stderr.log'))
    if '-D' in command and command.index('-D')+1<len(command):
        record['data_directory']=str(Path(command[command.index('-D')+1]).resolve())
    def save():
        record['elapsed_seconds']=round(time.monotonic()-start,3)
        payload=json.dumps(safe_object(record),ensure_ascii=False,indent=2)
        temporary=folder/'run.json.tmp'
        temporary.write_text(payload,encoding='utf-8');temporary.replace(folder/'run.json')
    process=None;binding=None;launched=False;folder_created=False;phase='capture_file_setup';readers=[];pump_errors=[];stop=threading.Event();thread=None
    try:
        folder.mkdir(parents=True,exist_ok=False)
        folder_created=True
        (folder/'stdout.log').touch(exist_ok=False);(folder/'stderr.log').touch(exist_ok=False);save()
        with tempfile.TemporaryFile(dir=base) as stdout,tempfile.TemporaryFile(dir=base) as stderr:
            for stream in (stdout,stderr):readers.append(_capture_reader(stream))
            pending=[b'',b''];discard=[False,False]
            def pump(final=False):
                for index,reader in enumerate(readers):
                    deadline=time.monotonic()+.5
                    data=reader.read(65536)
                    while data:
                        for part in data.splitlines(keepends=True):
                            complete=part.endswith(b'\n') or part.endswith(b'\r')
                            if not discard[index]:pending[index]+=part
                            if len(pending[index])>65536:pending[index]=b'';discard[index]=True
                            if complete:
                                line='[oversized diagnostic line omitted]\n' if discard[index] else safe(_diagnostic_text(pending[index],limit=len(pending[index])))
                                with open(record[['stdout_log','stderr_log'][index]],'a',encoding='utf-8') as output:output.write(line)
                                pending[index]=b'';discard[index]=False
                        if time.monotonic()>=deadline:
                            if final:pump_errors.append('capture_still_growing_after_deadline')
                            break
                        data=reader.read(65536)
                    if final and (pending[index] or discard[index]):
                        line='[oversized diagnostic line omitted]' if discard[index] else safe(_diagnostic_text(pending[index],limit=len(pending[index])))
                        with open(record[['stdout_log','stderr_log'][index]],'a',encoding='utf-8') as output:output.write(line)
                        pending[index]=b'';discard[index]=False
            def monitor():
                while not stop.wait(.2):
                    try:pump()
                    except OSError as exc:pump_errors.append(type(exc).__name__);return
            phase='process_launch'
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=env,
                shell=False,cwd=base,creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0,
                start_new_session=os.name!='nt')
            launched=True;record.update(root_pid=process.pid,initialization_state='running')
            phase='process_observation'
            process._naiwa_init_run_id=run_id
            process._naiwa_init_data_directory=record['data_directory']
            identity=_root_identity(process);record['root_identity_at_launch']=identity
            binding={'run_id':run_id,'identity':identity,'executable':record['executable_path'],
                'command':list(command),'data_directory':record['data_directory'],
                'directory_bound':bool(record['data_directory'] and Path(record['data_directory']).is_relative_to(base) and Path(record['data_directory'])!=base)}
            save();thread=threading.Thread(target=monitor,daemon=True);thread.start()
            try:
                code=process.wait(timeout=timeout)
                record.update(root_returncode=code,natural_returncode=code,initialization_state='exited_ok' if code==0 else 'exited_error',end_reason='natural_exit')
            except subprocess.TimeoutExpired:
                record.update(timed_out=True,timeout_exception_type='TimeoutExpired',initialization_state='timed_out',end_reason='deadline_exceeded',timeout_observed_at=datetime.now(timezone.utc).isoformat())
                cleanup=_stop_owned_root(process,binding)
                record.update(descendant_cleanup=cleanup,cleanup_state=cleanup['cleanup_state'],root_returncode=cleanup['root_returncode'])
            finally:
                phase='log_collection'
                stop.set()
                if thread:thread.join(timeout=2)
                # Root writer's Python buffer is relevant to controlled fake Popen tests.
                stdout.flush();stderr.flush()
                if not thread or not thread.is_alive():pump(final=True)
                else:pump_errors.append('log_monitor_did_not_stop')
                for reader in readers:reader.close()
            record['log_collection_errors']=pump_errors
            record['ended_at']=datetime.now(timezone.utc).isoformat();save()
            diagnostic=safe_object({**record,'process_id':process.pid})
            for name in ['stdout','stderr']:
                diagnostic[name+'_tail']=Path(record[name+'_log']).read_text(encoding='utf-8')[-8192:]
            if record.get('timed_out'):raise PostgresCommandFailure('desktop_postgres_command_failed',diagnostic)
            if pump_errors:raise PostgresCommandFailure('desktop_postgres_diagnostics_failed',diagnostic)
            result=subprocess.CompletedProcess(command,record['root_returncode'],Path(record['stdout_log']).read_bytes(),Path(record['stderr_log']).read_bytes())
            result.diagnostic=diagnostic
            return result
    except OSError as exc:
        stop.set()
        if thread:thread.join(timeout=2)
        record.update(_command_diagnostic(command,stage='initdb',timeout=timeout,cwd=base,extra_env=extra_env,os_error=exc))
        record.update(failure_phase=phase,initialization_state='diagnostic_failed' if launched else ('launch_failed' if phase=='process_launch' else 'capture_failed'),end_reason=phase+'_error')
        if launched:
            cleanup=_stop_owned_root(process,binding) if binding else {'cleanup_state':'blocked_unknown_identity','root_returncode':None,'descendants_state':'unknown'}
            record.update(descendant_cleanup=cleanup,cleanup_state=cleanup['cleanup_state'],root_returncode=cleanup['root_returncode'])
        if folder_created:
            try:save()
            except OSError as write_error:record['manifest_write_error']=type(write_error).__name__
        raise PostgresCommandFailure('desktop_postgres_command_failed',safe_object(record)) from None
    finally:
        for reader in readers:
            if not reader.closed:reader.close()
