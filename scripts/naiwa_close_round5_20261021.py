"""Close-only control writer; cannot grant a model authorization or quota."""
from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_transport_guards_20261021 import AuthorizationMutex
from scripts.naiwa_freeze_gate_20261021 import ROUND,atomic_json

def close(reason):
    with AuthorizationMutex(ROUND/'authorization-write.lock').hold():
        atomic_json(ROUND/'control.json',{'paid_enabled':False,'authorization_received':False,
            'active_scene':None,'reason':reason,'time':time.time()})

if __name__=='__main__':close(sys.argv[1] if len(sys.argv)>1 else 'explicit_close')
