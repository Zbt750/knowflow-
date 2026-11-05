"""资料处理 worker：领取任务、构建索引、成功/失败/重试，以及崩溃恢复。

为什么要租约（lease）而不是简单加锁：
一次索引构建可能跑几十秒（要加载 embedding 模型），用长事务持锁会拖住数据库；
租约是「一段时间内我负责」的声明，超时未被续期就说明 worker 已经死了，
任务可以被别人重新领取 —— 这是崩溃后能自愈的关键。

为什么失败要重试而且有上限：
模型加载失败、向量库短暂不可用都是可恢复的；但格式损坏的资料重试一万次也不会成功，
所以 max_attempts 用尽后必须落到 failed 终态，并只记录稳定错误码与安全摘要。
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm import Session

from backend.models.jobs import DocumentJob
from backend.models.rag import Material
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import Embedder, VectorStore
from backend.services.ingestion_service import (
    IngestionError,
    activate_version,
    build_index,
    compute_index_version,
    drop_version,
    parse_material,
    plan_material,
    rebuild_keyword_index,
)

logger = logging.getLogger(__name__)

# 租约时长：远大于一次索引构建的正常耗时，避免正常任务被误判为死亡。
DEFAULT_LEASE_SECONDS = 300
# 重试退避基数：第 n 次重试等待 base * 2^(n-1) 秒。
RETRY_BACKOFF_SECONDS = 5


@dataclass(frozen=True)
class JobRunResult:
    """一次任务执行的结果。"""

    job_id: UUID
    status: str
    index_version: str | None = None
    error_code: str | None = None
    chunk_count: int = 0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_worker_id() -> str:
    """worker 标识：进程内随机，便于在日志里区分是谁领走了任务。"""
    return f"worker-{secrets.token_hex(4)}"


def enqueue_job(
    session: Session,
    *,
    material_id: UUID,
    job_type: str,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> DocumentJob:
    """创建一条待处理任务；用户点重试就是再建一行，绝不把失败行改回 pending。"""
    if job_type not in {"ingest", "reindex", "delete"}:
        raise ValueError(f"未知 job_type：{job_type}")
    job = DocumentJob(
        material_id=material_id,
        job_type=job_type,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_run_at=now or now_utc(),
    )
    session.add(job)
    session.flush()
    return job


def claim_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DocumentJob | None:
    """领取一个可执行任务。

    可执行 = 待处理/重试中且退避已到期，或「运行中但租约已过期」（说明原 worker 死了）。
    """
    current = now or now_utc()
    job = session.scalars(
        select(DocumentJob)
        .where(
            DocumentJob.next_run_at <= current,
            (
                (DocumentJob.status.in_(("pending", "retry")))
                | (
                    (DocumentJob.status == "running")
                    & (DocumentJob.lease_until.is_not(None))
                    & (DocumentJob.lease_until < current)
                )
            ),
        )
        .order_by(DocumentJob.next_run_at, DocumentJob.created_at)
        .limit(1)
        # 跳过被其他 worker 同时选中的行，避免两个 worker 重复构建同一版本索引。
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None

    job.status = "running"
    job.worker_id = worker_id
    job.attempts += 1
    job.lease_until = current + timedelta(seconds=lease_seconds)
    session.flush()
    return job


def recover_expired_jobs(session: Session, *, now: datetime | None = None) -> int:
    """把租约过期的运行中任务改回 retry，让它们能被重新领取。返回恢复条数。"""
    current = now or now_utc()
    expired = session.scalars(
        select(DocumentJob).where(
            DocumentJob.status == "running",
            DocumentJob.lease_until.is_not(None),
            DocumentJob.lease_until < current,
        )
    ).all()
    for job in expired:
        # attempts 已经计过一次，这里不再累加，避免崩溃一次就吃掉一次重试机会。
        job.status = "retry"
        job.worker_id = None
        job.lease_until = None
        job.next_run_at = current
        job.error_code = "lease_expired"
        job.error_message = "worker 租约过期，任务已回收"
    if expired:
        session.flush()
    return len(expired)


def requeue_stale_pending_jobs(session: Session, *, now: datetime | None = None) -> int:
    """把「pending 但资料已经在索引中」的任务改回可领取。

    用途：进程在把资料标成 indexing 之后、建索引之前崩溃，重启后任务仍是 pending，
    但资料状态已经变了；此时必须让任务重新可领，否则资料永远停在 indexing。
    """
    current = now or now_utc()
    stale = session.scalars(
        select(DocumentJob)
        .join(Material, Material.id == DocumentJob.material_id)
        .where(
            DocumentJob.status.in_(("pending", "retry")),
            Material.status == "indexing",
        )
    ).all()
    for job in stale:
        job.next_run_at = current
    if stale:
        session.flush()
    return len(stale)


def run_job(
    session: Session,
    job: DocumentJob,
    *,
    materials_root: Path,
    embedder: Embedder,
    vector_store: VectorStore,
    keyword_index: KeywordIndex | None = None,
    now: datetime | None = None,
) -> JobRunResult:
    """执行一条已领取的任务。

    成功 → `succeeded` + 激活新版本；失败 → 还有重试机会就 `retry` 并退避，
    用完 `max_attempts` 则 `failed`，同时把资料状态置为 failed 并记录稳定错误码。
    """
    material = session.get(Material, job.material_id)
    if material is None:
        # 资料已被删除：任务没有意义，直接判失败（delete 任务除外，它由删除流程负责）。
        #
        # 必须在写状态**之前**把要用的字段取出来：删除资料会级联删掉任务行，
        # `_settle_failure` 因此可能回滚事务，而回滚会让 job 上所有属性过期。
        # 之后再读 job.id / job.status 会抛 ObjectDeletedError。
        job_id = job.id
        _settle_failure(session, job, "material_not_found", "资料不存在", now=now)
        return JobRunResult(
            job_id=job_id, status="failed", error_code="material_not_found"
        )

    try:
        if job.job_type == "delete":
            # 删除任务的正文与向量清理由资料服务负责，这里只标记完成。
            _settle_success(session, job, index_version=None)
            return JobRunResult(job_id=job.id, status="succeeded")

        # 解析失败时版本号还没算出来，失败清理必须能接受 None。
        # 少了这一行，任何解析失败都会被 UnboundLocalError 覆盖成「内部错误」，
        # 真正的原因（例如源文件缺失）就永远看不到。
        index_version: str | None = None

        material.status = "indexing"
        material.last_error_code = None
        material.last_error_message = None
        # 必须 commit 而不是 flush：`runner.run_once()` 是整批任务结束后才提交一次，
        # 而 READ COMMITTED 下**未提交的行对外不可见** —— 于是 API 永远返回不到
        # `indexing`，前端「建立索引中」标签成了死代码，验收步骤也做不到。
        # 提交后状态立刻对外可见，而任务此时已带租约（running + lease_until），
        # 因此进程若在这里崩掉，会被 recover_expired_jobs 回收重试。
        session.commit()
        # 供测试在「中间态刚刚提交」这一刻观察外部可见性。
        _after_indexing_committed()

        # 顺序很重要：先解析（纯内存）→ 用正文 hash 算出版本号 → 再写库。
        # 反过来会先用占位版本写一遍、再用真实版本写一遍，库里留下两倍块数。
        plan = plan_material(material, materials_root=materials_root)
        index_version = compute_index_version(plan.content_hash, embedder.model_name)

        # 写库之前必须确认资料还在。
        #
        # 为什么：删除接口会先删数据库记录再清向量，两步不在同一个事务里。
        # 如果用户在这中间删掉了资料（例如「重建索引」之后紧接着点删除），
        # 而这个任务此时才继续往下走，就会出现两种坏结果：
        #   - 已经能写块的阶段：插入块时外键失败，报成 internal_error；
        #   - 已经能写向量的阶段：产出一批**永远召不回、也无人清理**的孤儿向量
        #     （检索层查不到正文会丢弃它们，但它们一直占着索引）。
        # 显式查一次数据库即可挡掉：前面已经 commit 过，不会命中陈旧的身份映射。
        if session.get(Material, material.id) is None:
            logger.info("资料已被删除，放弃本次索引入库 material=%s", material.id)
            _settle_success(session, job, index_version=None)
            return JobRunResult(job_id=job.id, status="succeeded")

        parsed = parse_material(
            session, material, plan=plan, index_version=index_version
        )

        # 第二次确认：解析（读文件、切块）也可能耗时，这段时间里资料同样可能被删。
        # 此时块已经写进库了，必须连同向量一起清掉，不能只放弃就完事 ——
        # 否则会留下「块在、资料不在」的残留（外键约束若开启还会直接失败）。
        if session.get(Material, material.id) is None:
            logger.info("资料在解析期间被删除，回滚本次写入 material=%s", material.id)
            session.rollback()
            drop_version(
                session,
                material,
                index_version=index_version,
                vector_store=vector_store,
            )
            _settle_success(session, job, index_version=None)
            return JobRunResult(job_id=job.id, status="succeeded")

        outcome = build_index(
            session,
            material,
            index_version=index_version,
            embedder=embedder,
            vector_store=vector_store,
            keyword_index=keyword_index,
        )
        activate_version(session, material, index_version)
        # 必须在激活之后重建：关键词索引只收录 ready + 当前激活版本的块，
        # 早一步重建会得到一个空索引，表现为「关键词路永远召回 0 条」。
        if keyword_index is not None:
            rebuild_keyword_index(session, keyword_index)

        _settle_success(session, job, index_version=index_version)
        return JobRunResult(
            job_id=job.id,
            status="succeeded",
            index_version=index_version,
            chunk_count=outcome.chunk_count,
        )
    except IngestionError as error:
        # 业务失败也必须留日志：只把错误码写进数据库的话，
        # 排查时根本看不到是「哪一步、什么原因」失败的。
        # 日志里记的是错误码与异常类型，绝不含绝对路径或密钥。
        logger.warning(
            "任务失败 job=%s material=%s type=%s code=%s detail=%s",
            job.id,
            material.id,
            job.job_type,
            error.code,
            (error.detail or "")[:200],
        )
        _cleanup_failed_version(
            session, material, index_version=index_version, vector_store=vector_store
        )
        _settle_failure(session, job, error.code, error.detail or error.code, now=now)
        _mark_material_failed(session, material, job, error.code)
        return JobRunResult(job_id=job.id, status=job.status, error_code=error.code)
    except SQLAlchemyError as error:
        # 显式 commit 之后，提交失败不再由外层 `run_pending_jobs` 捕获，
        # 必须在这里处理：否则任务会留在 `running` 状态直到租约过期才被回收。
        # 这类失败几乎都是瞬时故障（连接抖动、死锁），所以按可重试处理。
        logger.warning(
            "任务提交数据库失败 job=%s material=%s error=%s",
            job.id,
            material.id,
            type(error).__name__,
        )
        _safe_rollback(session)
        _settle_failure(session, job, "database_unavailable", type(error).__name__, now=now)
        _mark_material_failed_after_rollback(session, job, material, "database_unavailable")
        return JobRunResult(job_id=job.id, status=job.status, error_code="database_unavailable")
    except Exception as error:  # noqa: BLE001 - 任何未预期异常都要落到可重试状态
        logger.exception("任务执行出现未预期错误 job=%s", job.id)
        _cleanup_failed_version(
            session, material, index_version=index_version, vector_store=vector_store
        )
        # 错误码必须是登记过的稳定业务码。曾经这里是 `unexpected:{类名}`，
        # 前端没有这个键，于是把 `unexpected:PdfReadError` 这样的 Python 类名
        # 直接显示给用户 —— 那不是「可理解的失败原因」。
        # 异常类型仍然有用，但它属于日志（上面已经 exception 过了），不属于界面。
        code = "internal_error"
        _settle_failure(session, job, code, type(error).__name__, now=now)
        _mark_material_failed(session, material, job, code)
        return JobRunResult(job_id=job.id, status=job.status, error_code=code)


def run_pending_jobs(
    session: Session,
    *,
    materials_root: Path,
    embedder: Embedder,
    vector_store: VectorStore,
    keyword_index: KeywordIndex | None = None,
    worker_id: str | None = None,
    limit: int = 1,
    now: datetime | None = None,
) -> list[JobRunResult]:
    """连续领取并执行任务，直到没有可领的或达到 limit。返回执行结果列表。"""
    identity = worker_id or make_worker_id()
    results: list[JobRunResult] = []
    for _ in range(max(limit, 0)):
        job = claim_job(session, worker_id=identity, now=now)
        if job is None:
            break
        results.append(
            run_job(
                session,
                job,
                materials_root=materials_root,
                embedder=embedder,
                vector_store=vector_store,
                keyword_index=keyword_index,
                now=now,
            )
        )
    return results




def _flush_job_tolerating_deleted(session: Session, job: DocumentJob) -> bool:
    """刷新任务状态；任务行已被级联删除时回滚并返回 False。

    为什么需要：删除资料会通过外键级联删掉 document_jobs，而后台任务可能刚好
    在删完之后才走到写状态这一步，于是 UPDATE 匹配 0 行并抛 `StaleDataError`
    （flush 期抛出）。表现为「用户删掉资料之后后台线程报错」。

    刻意**不做「先查一次」的判断**：`session.get` 会命中身份映射里的陈旧对象，
    查出来的结果并不代表行真的还在。直接 flush + 捕获才可靠。

    失败时必须 rollback：否则 session 进入「待回滚」状态，
    调用方后续任何操作都会抛 `PendingRollbackError`，变成一串看不懂的连锁错误。
    """
    try:
        session.flush()
        return True
    except StaleDataError:
        logger.info("任务行已被删除（资料被删），跳过状态写入")
        session.rollback()
        return False


def _settle_success(session: Session, job: DocumentJob, *, index_version: str | None) -> None:
    """把任务标记为成功；任务行已被删除时静默收尾。"""
    job.status = "succeeded"
    job.lease_until = None
    job.error_code = None
    job.error_message = None
    job.result_index_version = index_version
    _flush_job_tolerating_deleted(session, job)


def _settle_failure(
    session: Session,
    job: DocumentJob,
    code: str,
    message: str,
    *,
    now: datetime | None = None,
) -> None:
    """按剩余重试次数决定落到 retry 还是 failed，并写入安全的错误摘要。"""
    current = now or now_utc()
    attempts = job.attempts
    max_attempts = job.max_attempts
    job.error_code = code
    # 只保存安全摘要：堆栈与绝对路径一律留在日志，绝不进数据库或接口。
    job.error_message = _safe_message(message, code)
    job.lease_until = None
    if attempts >= max_attempts:
        job.status = "failed"
        job.worker_id = None
    else:
        job.status = "retry"
        backoff = RETRY_BACKOFF_SECONDS * (2 ** max(attempts - 1, 0))
        job.next_run_at = current + timedelta(seconds=backoff)
    _flush_job_tolerating_deleted(session, job)


def _after_indexing_committed() -> None:
    """「indexing 状态刚刚提交」这一刻的测试钩子。

    默认什么都不做。测试通过 monkeypatch 替换它，用来验证这一瞬间
    状态确实能被另一个数据库会话读到（即对 API 可见）。
    """
    return None


def _safe_rollback(session: Session) -> None:
    """回滚失败的事务，且不让回滚本身再抛异常掩盖原始错误。"""
    try:
        session.rollback()
    except Exception:  # noqa: BLE001 - 回滚失败只能记录，不能中断错误处理
        logger.warning("回滚事务失败", exc_info=True)


def _mark_material_failed_after_rollback(
    session: Session, job: DocumentJob, material: Material, code: str
) -> None:
    """回滚之后重新加载实体再落失败状态。

    回滚会让 session 里的对象过期，直接赋值可能失败或写入错误状态；
    因此这里从数据库重新取一次，拿到干净的状态再改。
    """
    try:
        fresh_job = session.get(DocumentJob, job.id)
        fresh_material = session.get(Material, material.id)
        if fresh_job is None:
            return
        _settle_failure(session, fresh_job, code, code)
        if fresh_material is not None:
            _mark_material_failed(session, fresh_material, fresh_job, code)
    except Exception:  # noqa: BLE001 - 尽力而为：状态落不下也不该二次抛错
        logger.warning("回滚后保存失败状态出错 job=%s", getattr(job, "id", None))


def _mark_material_failed(
    session: Session, material: Material, job: DocumentJob, code: str
) -> None:
    """只有任务彻底失败才把资料置为 failed；还能重试时保留旧版本可检索。"""
    if job.status == "failed":
        material.status = "failed"
    else:
        # 还能重试：资料回到「已有激活版本就 ready，否则 pending」，
        # 这样旧版本在重试期间依然可以被检索。
        material.status = "ready" if material.active_index_version else "pending"
    material.last_error_code = code
    material.last_error_message = _safe_message(code, code)
    session.flush()


def _cleanup_failed_version(
    session: Session,
    material: Material,
    *,
    index_version: str | None,
    vector_store: VectorStore,
) -> None:
    """清理本次失败产生的新版本，避免留下半个索引版本。

    必须传入**本次真正尝试写入的版本号**：用别的值重算会算出不同结果，
    `drop_version` 就会去删一个不存在的版本，真正的殘留反而留下来。
    """
    if not index_version:
        return
    try:
        drop_version(session, material, index_version=index_version, vector_store=vector_store)
    except Exception:  # noqa: BLE001 - 清理失败不能掩盖原始错误
        logger.warning("清理失败版本时出错 material=%s version=%s", material.id, index_version)


def _safe_message(message: str, code: str) -> str:
    """把错误摘要限制在安全范围内：去掉换行、截断长度，且绝不包含绝对路径。"""
    cleaned = " ".join(str(message).split())
    if len(cleaned) > 200:
        cleaned = cleaned[:200]
    return cleaned or code
