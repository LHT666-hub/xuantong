# 玄同部署到阿里云 ECS

推荐拓扑：iPhone → `HTTPS api.<域名>` → ECS Nginx →
`127.0.0.1:8000` 玄同容器 → 同 VPC 的 RDS PostgreSQL。

## 1. 阿里云资源

1. 创建 Ubuntu 22.04/24.04 ECS 和 RDS PostgreSQL，放在同一地域、同一 VPC。
2. RDS 创建 `xuantong` 数据库与最小权限账号，只把 ECS 私网 IP 加入白名单。
3. ECS 安全组开放 80/443；22 仅允许管理员固定 IP。不要开放 8000、5432。
4. 为 `api.<域名>` 配置 DNS 和 SSL 证书。中国内地服务器上的域名需要按规定完成备案。

## 2. 服务器准备

按阿里云官方文档安装 Docker Engine、Compose 插件和 Nginx，然后克隆生产分支：

```bash
git clone --branch codex/production-deployment https://github.com/LHT666-hub/xuantong.git
cd xuantong
cp .env.production.example .env.production
chmod 600 .env.production
```

编辑 `.env.production`：

- `DATABASE_URL` 使用 RDS 内网地址；密码中的 `@:/?#` 等字符需要 URL 编码。
- `LLM_API_KEY`、`NOVITA_API_KEY`、`RUOMU_ACCESS_KEY` 必须使用重新生成的密钥。
- 用 `openssl rand -hex 32` 生成 `JWT_SECRET`。
- 没有某个可选服务的密钥时，保持对应 `*_ENABLED=false`。
- 原生 iOS 不需要 CORS，可让 `CORS_ALLOWED_ORIGINS` 保持为空。

生产模式会执行 fail-closed 校验：数据库、百炼、JWT、鉴权、限流或 CORS
仍使用不安全值时，容器会直接退出并在日志中说明原因。

## 3. 首次启动

```bash
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 backend
curl http://127.0.0.1:8000/api/health
```

容器每次启动前自动运行 `alembic upgrade head`。数据库迁移失败时应用不会带着旧表结构继续启动。

## 4. Nginx 与 HTTPS

复制 `deploy/nginx-xuantong.conf` 到 `/etc/nginx/conf.d/xuantong.conf`，替换域名与证书路径：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl https://api.example.com/api/health
```

配置已关闭代理缓冲并放宽读取超时，支持玄同的 SSE 流式对话和工作流进度。

## 5. 常曦连接

在 App 的“我的 → 玄同连接”填写根地址，例如：

```text
https://api.example.com
```

随后注册或登录玄同账户。JWT 只保存在 iPhone Keychain，并自动附加到普通 API、
旧版事件问答和工单确认请求。

## 6. 更新与回滚

更新前先做 RDS 快照，再执行：

```bash
git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs --tail=200 backend
```

生产初期建议只运行一个 Uvicorn worker。当前应用内限流是单实例滑动窗口；未来扩容多实例时，
应将限流状态迁移到 Redis/云原生 API 网关。患者资源的机构级授权仍需在开放多机构使用前完成。
