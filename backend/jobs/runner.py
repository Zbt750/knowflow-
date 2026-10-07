"""后台任务运行器：在独立线程里持续领取并执行资料处理任务。

为什么用线程而不是 asyncio 任务：
索引构建是 CPU 密集型（embedding 编码），放进事件循环会卡住所有 HTTP 请求。
用独立线程 + 自己的 Session，与请求处理完全隔离。

生命周期：
- `lifespan` 启动时 `start()`，关闭时 `stop()` 并 join；
- 上传接口在入队后调用 `notify()`，线程立刻被唤醒，不必等轮询周期。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from backend.jobs.worker import (
    make_worker_id,
    recover_expired_jobs,
    requeue_stale_pending_jobs,
    run_pending_jobs,
)
from backend.retrieval.stack import RetrievalStack

logger = logging.getLogger(__name__)

# 空闲时的轮询间隔：既是「没有通知时的兜底」，也是租约过期的检查周期。
IDLE_POLL_SECONDS = 1.0
# 单轮最多处理多少个任务，避免长期占住线程导致 stop() 迟迟不返回。
JOBS_PER_CYCLE = 3


class MaterialJobRunner:
    """单线程任务运行器。"""

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        stack: RetrievalStack,
        materials_root,
        worker_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._stack = stack
        self._materials_root = materials_root
        self._worker_id = worker_id or make_worker_id()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 供 /health 与脚本观察：本进程已完成多少任务、最近一次错误码。
        self.completed = 0
        self.last_error_code: str | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name=f"material-jobs-{self._worker_id}", daemon=True
        )
        self._thread.start()
        logger.info("资料任务线程已启动 worker=%s", self._worker_id)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def notify(self) -> None:
        """上传或重试后调用：立刻唤醒线程去领任务。"""
        self._wake.set()

    def run_once(self, *, now: datetime | None = None) -> list[JobRunResult]:
        """处理一轮可领任务；返回本轮的执行结果（空列表表示没有任务）。

        返回结果而不是计数：调用方需要看到每个任务的成败与错误码，
        只给一个数字会让「哪份资料失败了」无从判断。
        """
        with self._session_factory() as session:
            # 先回收租约过期的任务，否则崩溃留下的 running 会永远卡住。
            recover_expired_jobs(session, now=now)
            requeue_stale_pending_jobs(session, now=now)
            session.commit()
            results = run_pending_jobs(
                session,
                materials_root=self._materials_root,
                embedder=self._stack.embedder,
                vector_store=self._stack.vector_store,
                keyword_index=self._stack.keyword_index,
                worker_id=self._worker_id,
                limit=JOBS_PER_CYCLE,
                now=now,
            )
            session.commit()
        for result in results:
            if result.status == "succeeded":
                self.completed += 1
            elif result.error_code:
                self.last_error_code = result.error_code
        return results

    def _loop(self) -> None:
        while not self._stop.is_set():
            processed = 0
            try:
                processed = len(self.run_once())
            except Exception:  # noqa: BLE001 - 线程里任何异常都必须被吃掉并记录
                logger.exception("资料任务线程出现未预期错误")
            if processed:
                # 还有活就立刻继续，不必等下一个周期。
                continue
            # 没有任务：等待通知，或被空闲周期唤醒（用于检查租约过期）。
            self._wake.wait(IDLE_POLL_SECONDS)
            self._wake.clear()

    def health(self) -> dict[str, object]:
        """只暴露安全的运行状态：不含路径、连接串与模型本地路径。"""
        return {
            "worker_id": self._worker_id,
            "alive": bool(self._thread and self._thread.is_alive()),
            "completed": self.completed,
            "last_error_code": self.last_error_code,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
