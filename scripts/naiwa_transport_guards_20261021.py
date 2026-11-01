"""Isolation-only bounded authorization/write synchronization and stream guards."""
import asyncio,os,threading
from contextlib import contextmanager,asynccontextmanager
from filelock import FileLock,Timeout
from scripts.phase5_eval_meter import BudgetStop

class AuthorizationMutex:
    """Fresh OS lock handle per outer operation; logical task-aware reentrancy.

    Order: authorization -> ledger RLock -> ledger file lock. Never reverse it.
    Async writers acquire off-loop; synchronous contenders on the event-loop
    thread fail closed immediately, rather than blocking the writer's loop.
    """
    def __init__(self,path):self.path=str(path);self.held={};self.mutex=threading.Lock()
    def key(self):
        try:task=asyncio.current_task()
        except RuntimeError:task=None
        return (os.getpid(),threading.get_ident(),id(task) if task else None)
    @contextmanager
    def hold(self):
        key=self.key()
        with self.mutex:nested=key in self.held
        if nested:yield;return
        lock=FileLock(self.path,thread_local=False)
        try:lock.acquire(timeout=0 if key[2] is not None else 3)
        except Timeout:raise BudgetStop('authorization_lock_busy') from None
        with self.mutex:self.held[key]=lock
        try:yield
        finally:
            with self.mutex:self.held.pop(key,None)
            lock.release()
    @asynccontextmanager
    async def ahold(self):
        key=self.key()
        with self.mutex:nested=key in self.held
        if nested:yield;return
        lock=FileLock(self.path,thread_local=False)
        job=asyncio.create_task(asyncio.to_thread(lock.acquire,timeout=3))
        try:await asyncio.shield(job)
        except asyncio.CancelledError:
            try:await asyncio.shield(job)
            finally:lock.release()
            raise
        except Timeout:raise BudgetStop('authorization_lock_busy') from None
        with self.mutex:self.held[key]=lock
        try:yield
        finally:
            with self.mutex:self.held.pop(key,None)
            lock.release()

def bounded_write_timeout(timeout):return min(float(timeout),2.0) if timeout is not None else 2.0

class SyncWriteGuard:
    def __init__(self,gate,stream):self.gate=gate;self.stream=stream
    def read(self,*a,**kw):return self.stream.read(*a,**kw)
    def close(self):return self.stream.close()
    def get_extra_info(self,name):return self.stream.get_extra_info(name)
    def start_tls(self,*a,**kw):return SyncWriteGuard(self.gate,self.stream.start_tls(*a,**kw))
    def write(self,buffer,timeout=None):
        # Linearization: permission is checked while holding the same OS lock
        # as seal(). The bounded native write remains under that lock.
        if not buffer:return None
        with self.gate.authorization.hold():
            record=self.gate.authorize_write()
            self.gate.mark_write(record,len(buffer))
            return self.stream.write(buffer,timeout=bounded_write_timeout(timeout))

class AsyncWriteGuard:
    def __init__(self,gate,stream):self.gate=gate;self.stream=stream
    async def read(self,*a,**kw):return await self.stream.read(*a,**kw)
    async def aclose(self):return await self.stream.aclose()
    def get_extra_info(self,name):return self.stream.get_extra_info(name)
    async def start_tls(self,*a,**kw):return AsyncWriteGuard(self.gate,await self.stream.start_tls(*a,**kw))
    async def write(self,buffer,timeout=None):
        if not buffer:return None
        async with self.gate.authorization.ahold():
            record=self.gate.authorize_write()
            self.gate.mark_write(record,len(buffer))
            return await asyncio.wait_for(self.stream.write(buffer,timeout=bounded_write_timeout(timeout)),timeout=2.0)
