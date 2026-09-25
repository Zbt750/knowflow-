# 后端镜像：先装依赖再拷贝源码，源码改动不会让依赖层失效。
FROM python:3.12-slim

# 可选：为构建加速指定系统包与 PyPI 的镜像源。
#
# 默认是**空** —— 空即走官方源（apt 用 deb.debian.org、pip 用 pypi.org），
# 所以不传参数时行为与以前完全一致，仓库里也不会写死任何第三方镜像。
#
# 为什么需要这个开关：在部分网络环境下官方源极慢（实测本机 files.pythonhosted.org
# 只有 ~25 kB/s，一个 19 MB 的包下了 13 分钟，整轮构建 26 分钟还没结束）。
# 此时可以在本机 .env.compose 里指定镜像源，把构建压回几分钟：
#
#   APT_MIRROR=mirrors.aliyun.com
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#
# 注意 PIP_INDEX_URL 只影响**构建期**装依赖，不影响运行期行为。
ARG APT_MIRROR=
ARG PIP_INDEX_URL=

# 只装运行期需要的最小系统包：
# - libgomp1 是 torch 的运行时依赖（装了向量依赖才用得上，没装也不报错）；
# - curl 供健康检查使用（compose 的 healthcheck 需要在容器内执行命令）。
#
# APT_MIRROR 非空时先改写 apt 源。Debian 12+ 用 deb822 格式的
# /etc/apt/sources.list.d/debian.sources，老格式是 /etc/apt/sources.list，
# 两个都试、谁在就改谁。
RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then \
        if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
            sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
        fi; \
        if [ -f /etc/apt/sources.list ]; then \
            sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list; \
        fi; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends libgomp1 curl; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=dev \
    TIMEZONE=Asia/Shanghai

# 依赖层：只有 requirements 变化时才重装。
# PIP_INDEX_URL 非空时用它当索引（构建加速）；为空则走官方 PyPI。
COPY requirements.txt requirements-embed.txt ./
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# 向量检索依赖是可选的，默认用构建参数控制：
#   docker compose build --build-arg INSTALL_EMBED=1
# 离线机器可以把 wheel 预下载到 ./deploy/wheels 后走本地安装。
ARG INSTALL_EMBED=0
RUN if [ "$INSTALL_EMBED" = "1" ]; then \
        if [ -n "$PIP_INDEX_URL" ]; then \
            pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements-embed.txt; \
        else \
            pip install --no-cache-dir -r requirements-embed.txt; \
        fi; \
    fi

COPY backend ./backend
COPY migrations ./migrations
COPY scripts ./scripts
COPY seed ./seed
COPY alembic.ini pytest.ini ./

# 持久化目录（compose 会挂载卷覆盖它们）。
RUN mkdir -p storage/uploads storage/chroma storage/models

RUN chmod +x backend/docker-entrypoint.sh

EXPOSE 8000

# 健康检查用真实接口：它同时验证数据库连接与进程存活。
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["backend/docker-entrypoint.sh"]