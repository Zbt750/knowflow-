"""Streaming must not move a Provider's ContextVar lifecycle across tasks."""
import asyncio
import pytest
from backend.chat import http_clients
from backend.chat.service import _stream_deltas
from backend.errors import AppError

class Alive:
    async def is_disconnected(self): return False

@pytest.mark.parametrize('failure',[False,True])
def test_stream_iterator_and_close_have_one_task_owner(failure):
    owners=[]
    class Model:
        timeout=1
        @http_clients.call_entry('text_stream')
        async def stream(self,messages,*,attempt=1):
            owner=asyncio.current_task();owners.append(owner)
            try:
                yield '中文正文 '
                assert asyncio.current_task() is owner
                yield r'\[\sum_{n=1}^{\infty}x^n=\frac{x}{1-x}\]'
                if failure:raise AppError('generation_failed',retryable=False)
            finally:
                assert asyncio.current_task() is owner
    async def run():
        parts=[]
        async def consume():
            async for _ in _stream_deltas(Model(),[],parts,Alive(),{'disconnected':False},'当前这道题怎么做'):pass
        if failure:
            with pytest.raises(AppError) as error:await consume()
            assert error.value.code=='generation_failed'
        else:await consume()
        assert len(parts)==2 and len(owners)==1
        assert http_clients.CALL.get() is None
    asyncio.run(run())

@pytest.mark.parametrize('disconnect',[False,True])
def test_stream_cancellation_closes_in_original_context_without_leaking_tasks(disconnect):
    closed=[]
    class Model:
        timeout=1
        @http_clients.call_entry('text_stream')
        async def stream(self,messages,*,attempt=1):
            owner=asyncio.current_task()
            try:
                yield '部分正文'
                await asyncio.Event().wait()
            finally:
                closed.append(asyncio.current_task() is owner)
    class Request:
        disconnected=False
        async def is_disconnected(self):return self.disconnected
    async def run():
        request=Request();flags={'disconnected':False};parts=[]
        iterator=_stream_deltas(Model(),[],parts,request,flags,'当前题')
        await anext(iterator)
        if disconnect:
            request.disconnected=True
            assert [chunk async for chunk in iterator]==[]
            assert flags['disconnected']
        else:await iterator.aclose()
        assert closed==[True]
        assert http_clients.CALL.get() is None
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    asyncio.run(run())
