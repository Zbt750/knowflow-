# 前端镜像：Node 构建产物交给 Nginx 提供静态文件。
FROM node:22-alpine AS build

WORKDIR /app

# 依赖层：package 文件没变就不重新安装。
COPY package.json package-lock.json ./
RUN npm ci

# 只拷贝真实存在的 tsconfig（tsconfig.json 内部会引用 tsconfig.node.json）。
COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src

# 只跑 vite build：类型检查在 CI/本机 npm run build 里已经做过，
# 放进镜像只会拖长构建（而且需要 devDependencies 的全部类型信息）。
RUN npx vite build

FROM nginx:1.27-alpine

# 配置文件名以 .template 结尾会触发官方镜像的 envsubst；
# 本配置里没有任何占位变量，envsubst 不改写它是安全的（nginx 内置变量 $host 等
# 不是环境变量，envsubst 不会替换）。
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1