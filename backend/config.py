from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env 只用于本机；系统存在额外环境变量时不报错。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # dev 是本机开发；test 会额外启用测试数据库保护；prod 留给最终部署。
    app_env: Literal["dev", "test", "prod"] = "dev"
    # Pydantic 启动时校验连接串格式；开发/部署默认始终读这一项。
    database_url: PostgresDsn
    # 测试库只能在 APP_ENV=test 时启用；迁移、应用与 pytest 共用这一条选择规则。
    test_database_url: PostgresDsn | None = None
    # embedding 模型是摄取与检索共享的不变量，任何一边都不能自行硬编码另一个名字。
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    # reranker 可为空表示先走无重排降级；变量名与 .env.example 的 RERANKER_MODEL 一致。
    reranker_model: str | None = None
    # 学习日、毕业跨天和复测日期都使用同一时区。
    timezone: str = "Asia/Shanghai"
    # 这些是相对项目根目录的目录；启动时由 lifespan 幂等创建。
    upload_dir: Path = Path("storage/uploads")
    chroma_dir: Path = Path("storage/chroma")
    model_cache_dir: Path = Path("storage/models")
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    # 网络调用统一从此读取超时；provider 不得把 60 秒写死在多个文件。
    llm_timeout_seconds: float = 60.0
    # 单次回答的输出上限；provider 必须把它传给 max_tokens。
    #
    # 为什么从 800 提到 4000（实测得出，不是拍脑袋）：
    # 当前配置的 `deepseek-flash` 是**推理模型**，它先输出 reasoning_content（思考）
    # 再输出正文，而**两者共享 max_tokens**。用项目真实形状的 prompt 实测：
    #   max_tokens=800  → 思考 970~1217 字，有一轮正文只剩 9 字（被思考挤掉）；
    #   max_tokens=3000 → 思考 908~1404 字，三轮正文都完整。
    # 当前聊天检索最多提供 8 段证据；prompt 变长后推理内容更容易占用共享预算，
    # 表现为「模型偶发返回空回答 / 回答被截断」——那是预算问题，不是网络抖动。
    llm_max_output_tokens: int = 4000
    # 首轮失败（空回答或可重试的上游故障）时改用这个更大的预算再试一次。
    #
    # 为什么要「加大预算重试」而不是原样重试：
    # 实测下来空回答的主因是思考占满了预算，原样重试等于再赌一次同样的额度。
    # 加大预算才是对症的；对 429/5xx 这类故障，加大预算也无害。
    llm_retry_max_output_tokens: int = 8000
    # 多轮对话带多少历史（估算 token 上限）。
    # 规格篇 16 把「多轮对话与上下文预算」列为 P1，这里按 token 预算裁剪而不是写死条数。
    #
    # 为什么不能写死条数：每轮长度差异极大 —— 短问答时本可多带几轮，
    # 而长解答时几条就能把推理模型的输出预算挤掉
    # （实测过 reasoning_content 吃掉 max_tokens 导致正文为空）。
    # 取 1200 是「够记住上几轮在聊什么、又不喧宾夺主」的量：
    # 资料证据本身通常已占几百到一千多 token。
    llm_history_token_budget: int = 1200

    @model_validator(mode="after")
    def reject_development_database_in_test(self) -> "Settings":
        # test 环境不允许静默回退到开发 DATABASE_URL，迁移和 pytest 都必须显式给测试 URL。
        if self.app_env == "test" and self.test_database_url is None:
            raise ValueError("APP_ENV=test 时必须设置 TEST_DATABASE_URL")
        active_url = self.test_database_url if self.app_env == "test" else self.database_url
        database_name = str(active_url).rstrip("/").rsplit("/", 1)[-1]
        if self.app_env == "test" and not database_name.endswith("_test"):
            raise ValueError("TEST_DATABASE_URL 必须指向 _test 数据库")
        return self

    @property
    def active_database_url(self) -> PostgresDsn:
        """返回本进程当前唯一允许使用的数据库 URL。"""
        # 所有运行期 engine、Alembic env.py 与测试 app 都调用这里，避免三条路径选出不同库。
        if self.app_env == "test":
            assert self.test_database_url is not None  # 已由 validator 保证，保留给类型检查器。
            return self.test_database_url
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    # 一个进程只解析一次；测试改环境变量后调用 cache_clear()。
    return Settings()
