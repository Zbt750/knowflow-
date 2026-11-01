"""Process-local network guard for the explicitly offline closeout harness."""
import os,sys
BLOCKED=[]
_installed=False


def install():
    global _installed
    if _installed:return
    if os.environ.get('PHASE45I_CLOSE_OFFLINE')!='1':return
    def audit(event,args):
        if event!='socket.connect' or len(args)<2:return
        address=args[1]
        if isinstance(address,tuple) and len(address)>=2:
            host,port=address[:2]
            if host not in {'127.0.0.1','localhost','::1'} or port==5433:
                BLOCKED.append({'host':str(host),'port':port})
                raise RuntimeError('Offline acceptance blocked external/development socket')
    sys.addaudithook(audit);_installed=True
