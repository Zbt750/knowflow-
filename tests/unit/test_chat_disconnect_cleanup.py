import asyncio

from backend.chat.service import _wait_disconnected


def test_disconnect_poll_exits_if_request_swallows_external_cancellation():
    async def run():
        started = asyncio.Event()

        class Request:
            swallowed = False

            async def is_disconnected(self):
                started.set()
                try:
                    await asyncio.sleep(20)
                except asyncio.CancelledError:
                    if self.swallowed:
                        raise
                    self.swallowed = True
                    return False
                return False

        task = asyncio.create_task(_wait_disconnected(Request()))
        try:
            await started.wait()
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.3)
            assert task in done, "Cancellation must not leave finally.gather waiting forever"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
