"""Pure admission decision for a server-read resource and epoch-owned sessions.

Not a user authentication system. Principal comes from the local controlled
runtime's nonce/window; no body field can declare ownership or grant authority.
"""
import re,time,json
from pathlib import Path
from filelock import FileLock


def consume_permit(*,window_path,claim_path,grant,nonce,now=None):
    """Linearize grant consumption against close_window; no business calls here.

    After consumption the operation is in-flight, not a reusable grant. Closing
    rejects later consumption; it cannot undo an already committed DB action.
    """
    window_path=Path(window_path);claim_path=Path(claim_path)
    with FileLock(str(window_path.parent/'admission.lock'),timeout=2):
        live=json.loads(window_path.read_text(encoding='utf-8'))
        if (not live.get('enabled') or live.get('expires_at',0)<=(time.time() if now is None else now)
                or live.get('epoch')!=grant['epoch'] or live.get('nonce')!=nonce):
            return False,'authorization_revoked_before_consumption'
        claim_path.parent.mkdir(exist_ok=True)
        try:
            with claim_path.open('x',encoding='utf-8') as f:json.dump(grant,f)
        except FileExistsError:return False,'handoff_already_claimed_read_state_first'
        return True,'consumed_once_before_business'


def close_window(window_path):
    window_path=Path(window_path)
    with FileLock(str(window_path.parent/'admission.lock'),timeout=2):
        value=json.loads(window_path.read_text(encoding='utf-8'));value['enabled']=False
        from scripts.naiwa_freeze_gate_20261021 import atomic_json
        atomic_json(window_path,value)


def register_session(path,session_id,owner):
    """Merge server-created session ownership; parallel creates must not lose IDs."""
    path=Path(path)
    with FileLock(str(path.parent/'sessions.lock'),timeout=2):
        live=json.loads(path.read_text(encoding='utf-8'))
        if session_id in live and live[session_id]!=owner:
            raise RuntimeError('session_owner_collision')
        live[session_id]=owner
        from scripts.naiwa_freeze_gate_20261021 import atomic_json
        atomic_json(path,live)


def admit_handoff(*,method,path,body,resource,sessions,window,epoch,principal,now=None):
    now=time.time() if now is None else now
    match=re.fullmatch(r'/api/practice-requests/([0-9a-f-]{36})/(send|plan|decline)',path)
    if method!='POST' or not match:return False,'route_not_authorized'
    if not window.get('enabled') or window.get('expires_at',0)<=now or window.get('epoch')!=epoch:
        return False,'window_expired_or_wrong_epoch'
    if not resource or resource.get('id')!=match[1]:return False,'resource_not_authorized'
    source=resource.get('source_conversation_id');owner=sessions.get(source,{})
    if owner.get('epoch')!=epoch or owner.get('principal')!=principal or owner.get('purpose')!='qa':
        return False,'source_not_owned'
    if resource.get('expires_at',0)<=now:return False,'draft_expired'
    action=match[2]
    if action=='send':
        if resource.get('status')!='draft' or resource.get('confirmation_a'):return False,'draft_already_sent'
        if body.get('source_conversation_id')!=source:return False,'source_mismatch'
        target=body.get('target_study_session_id')
    elif action=='plan':
        if resource.get('status') not in {'pending','proposed'} or not resource.get('confirmation_a'):return False,'draft_not_sent'
        target=body.get('study_session_id')
        if target!=resource.get('target_study_session_id'):return False,'target_mismatch'
    else:
        if resource.get('status') not in {'draft','pending','proposed','failed'}:return False,'decline_state_invalid'
        target=resource.get('target_study_session_id')
        if not target:return True,'owned_unsent_decline'
    target_owner=sessions.get(target,{})
    if (target_owner.get('epoch')!=epoch or target_owner.get('principal')!=principal
            or target_owner.get('purpose')!='study'):return False,'target_not_owned'
    bound=resource.get('target_study_session_id')
    if bound and bound!=target:return False,'target_mismatch'
    if resource.get('task_session_id') and resource['task_session_id']!=target:return False,'task_owner_mismatch'
    return True,'exact_owned_handoff'
