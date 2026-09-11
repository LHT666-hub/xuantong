# 玄同后端：阿里云 ECS + 宝塔面板部署手册

> 适用项目：`xuantong` FastAPI 后端  
> 部署方式：Docker Compose 运行 FastAPI，阿里云 RDS PostgreSQL 持久化，宝塔 Nginx 提供 HTTPS 和反向代理  
> 文档核对日期：2026-09-11

## 1. 部署架构

```text
常曦 iOS / 浏览器
        |
        | HTTPS :443
        v
阿里云安全组
        |
        v
宝塔 Nginx
        |
        | http://127.0.0.1:8000
        v
FastAPI backend (Docker)
        |
        | VPC 内网 :5432
        v
阿里云 RDS PostgreSQL
```

公网只暴露 `80/443`；`8000` 仅绑定 ECS 本机。RDS 使用 VPC 内网连接，不申请或使用公网地址。

## 2. 准备资源

1. 购买阿里云 ECS，建议起步配置：
   - 2 vCPU / 4 GiB RAM（4 GiB 只适合低并发演示，生产建议 8 GiB）；
   - 40 GiB 或更大的 ESSD；
   - Ubuntu 22.04/24.04 LTS 或 Alibaba Cloud Linux 3；
   - 公网 IPv4 和足够的带宽。
2. 创建 RDS PostgreSQL，建议 PostgreSQL 16：
   - 与 ECS 放在同一地域、VPC 和可互通的交换机；
   - 创建 `xuantong` 数据库及专用的 `xuantong` 账号；
   - 白名单只加 ECS 的私网 IP，不加 `0.0.0.0/0`；
   - 记录 RDS 内网地址和端口。
3. 准备一个 API 子域名，例如 `api.example.com`，添加 `A` 记录指向 ECS 公网 IP。
4. ECS 在中国内地地域且使用域名对外服务时，先完成 ICP 备案；域名已在其他服务商备案时，通常还需完成阿里云接入备案。
5. 准备密钥：
   - 阿里云百炼 DashScope API Key；
   - 如启用 Novita 医疗模型，准备 `NOVITA_API_KEY`；
   - 如启用若木，准备 `RUOMU_ACCESS_KEY`。

## 3. 配置阿里云安全组

在 **ECS 控制台 → 实例 → 安全组 → 入方向规则** 中配置：

| 端口 | 来源 | 用途 |
| --- | --- | --- |
| TCP 80 | `0.0.0.0/0` | HTTP，申请证书和跳转 HTTPS |
| TCP 443 | `0.0.0.0/0` | HTTPS API |
| TCP 22 | 管理员固定公网 IP `/32` | SSH |
| 宝塔实际面板端口 | 管理员固定公网 IP `/32` | 面板管理 |

不要向公网放行 `8000` 或 `5432`。SSH 和面板端口也不应长期允许 `0.0.0.0/0`。阿里云官方也建议 Web 服务只公开 80/443，管理端口限制可信 IP。

## 4. 安装并加固宝塔

1. 用 SSH 登录一台纯净 ECS。
2. 从[宝塔官方快速安装页](https://docs.bt.cn/getting-started/quick-installation-of-bt-panel)复制当前系统对应的最新安装命令，不要从第三方教程复制脚本。
3. 首次登录后立即：
   - 修改面板用户名、强密码、默认端口和安全入口；
   - 开启二次验证；
   - 将面板“授权 IP”限制为管理员 IP；
   - 在宝塔“安全”页只放行 80/443 及必要的管理端口。
4. 在宝塔“软件商店”安装：
   - Nginx；
   - Docker 管理器（需要 Docker Engine 与 Compose v2）。

不需要安装宝塔的 MySQL、PHP、phpMyAdmin 或 Redis；数据库使用阿里云 RDS PostgreSQL。

SSH 中确认：

```bash
docker --version
docker compose version
git --version
```

## 5. 拉取项目

```bash
mkdir -p /www/wwwroot
cd /www/wwwroot
git clone https://github.com/LHT666-hub/xuantong.git
cd xuantong
```

生产环境建议部署经过验证的 tag 或 commit，不要无条件追踪开发分支。例如：

```bash
git fetch --tags
git checkout <已验证的-tag-或-commit>
```

## 6. 确认生产部署文件

项目已提供三个生产部署文件：

| 文件 | 作用 |
| --- | --- |
| `docker-compose.prod.yml` | 只运行 backend，绑定 `127.0.0.1:8000`，启动前自动执行 Alembic |
| `.env.production.example` | 生产环境变量模板 |
| `deploy/nginx-xuantong.conf` | 宝塔 Nginx 反向代理参考配置 |

确认 Compose 中的 backend 端口为：

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

后续命令均显式使用 `docker-compose.prod.yml`，不要在生产机上运行开发用的 `docker-compose.yml`。

## 7. 配置生产环境变量

```bash
cd /www/wwwroot/xuantong
umask 077
cp .env.production.example .env.production
openssl rand -hex 32
```

随机值用作 `JWT_SECRET`。不要在聊天、工单或 Git 中传递 `.env.production`。编辑该文件至少配置：

```dotenv
# 阿里云 RDS PostgreSQL 内网连接
DATABASE_URL=postgresql+asyncpg://xuantong:<URL编码后的密码>@<RDS内网地址>:5432/xuantong

# 应用
ENVIRONMENT=production
DEBUG=false
API_AUTH_REQUIRED=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=120
RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE=12

JWT_SECRET=<随机值>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# 原生 iOS 不需要 CORS；没有 Web 管理端时留空
CORS_ALLOWED_ORIGINS=

# 百炼
LLM_PROVIDER=qwen
LLM_API_KEY=<DashScope-API-Key>
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_LEAD=qwen3-max
LLM_MODEL_SPECIALIST=qwen-plus
LLM_MODEL_EXECUTION=qwen-flash
LLM_MODEL_VISION=qwen3-vl-flash
LLM_MODEL_OCR=qwen3.5-ocr
LLM_MODEL_ASR=qwen3-asr-flash

# 如无 Novita Key，必须关闭，否则生产配置校验会拒绝启动
USE_MEDICAL_MODEL=false
NOVITA_API_KEY=

# 如无若木 Key，保持关闭
RUOMU_ENABLED=false
RUOMU_ACCESS_KEY=

LOG_LEVEL=INFO
WORKFLOW_CHECKPOINT_BACKEND=postgres
```

补充说明：

- `ENVIRONMENT=production` 会启用项目的生产安全校验；密钥、认证、限流或 CORS 不安全时服务会拒绝启动。
- 原生 iOS 请求不受浏览器 CORS 限制；增加 Web 管理端时再填写精确 HTTPS origin。
- 生产镜像已安装 `langgraph-checkpoint-postgres`，工作流断点使用同一 RDS 持久化。

检查权限：

```bash
chmod 600 /www/wwwroot/xuantong/.env.production
```

## 8. 构建、迁移并启动

```bash
cd /www/wwwroot/xuantong

# 校验编排并启动；backend 启动前会自动执行 Alembic
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.yml up -d --build
```

检查状态：

```bash
docker compose -f docker-compose.prod.yml ps
curl --fail http://127.0.0.1:8000/api/health
docker compose -f docker-compose.prod.yml logs --tail=100 backend
```

如 backend 反复重启，先看最后的错误：

```bash
docker compose -f docker-compose.prod.yml logs --tail=200 backend
```

常见原因是 `.env` 未通过生产安全校验、API Key 无效或数据库迁移失败。

## 9. 在宝塔创建 HTTPS 反向代理

### 9.1 创建站点和证书

1. 宝塔 **网站 → 添加站点**，域名填 `api.example.com`；应用类型可选静态站点，不需要 PHP。
2. 确认 DNS 已指向 ECS，且 80/443 可访问。
3. 进入 **站点设置 → SSL**，申请 Let's Encrypt 证书或上传已购买的证书，开启强制 HTTPS。

若 HTTP 验证失败，先暂停反向代理和重定向后重试，或改用 DNS 验证。参见[宝塔 SSL 官方文档](https://docs.bt.cn/getting-started/deploy-ssl)。

### 9.2 添加反向代理

进入 **站点设置 → 反向代理 → 添加反向代理**：

- 代理名称：`xuantong-api`
- 目标 URL：`http://127.0.0.1:8000`
- 发送域名：`$host`
- 缓存：关闭

宝塔反向代理的官方操作说明见[反向代理文档](https://docs.bt.cn/user-guide/site/php/site-config/reverse-proxy)。

### 9.3 为 SSE 和长请求调整 Nginx

在该站点生成的反向代理配置中确认包含以下参数。如已有 `location /`，将参数合并进现有块，不要再建第二个 `location /`。

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $request_id;

    # SSE 不应被代理缓冲或缓存
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    # 报告/语音上传上限，可按业务需求收紧
    client_max_body_size 30m;
}
```

保存前先点击 Nginx 配置检查，成功后重载 Nginx。

## 10. 验收

### 10.1 基础健康检查

```bash
curl --fail https://api.example.com/api/health
curl --fail https://api.example.com/api/health/detail
```

再访问：

```text
https://api.example.com/docs
```

如 API 文档不应公开，验收完后在宝塔为 `/docs`、`/redoc` 和 `/openapi.json` 设置 IP 白名单或访问认证。

### 10.2 注册和登录

```bash
curl -X POST https://api.example.com/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"deploy-check","email":"deploy-check@example.com","password":"Replace-With-A-Strong-Test-Password","role":"patient"}'

curl -X POST https://api.example.com/api/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=deploy-check' \
  --data-urlencode 'password=Replace-With-A-Strong-Test-Password'
```

登录接口必须使用表单编码，不是 JSON。验收后删除测试账号，或使用专门的测试租户/数据库。

### 10.3 SSE

用真实事件 ID 检查 SSE：

```bash
curl -N https://api.example.com/api/v1/events/<event-id>/stream \
  -H 'Authorization: Bearer <access-token>'
```

如响应被长时间攒成一大块才返回，重点检查 `proxy_buffering off`。

### 10.4 外网端口

从另一台机器确认：

- `https://api.example.com` 可访问；
- ECS 公网 IP 的 `8000/5432/6379` 均不可访问；
- 证书链完整，没有 HTTP 混合内容。

## 11. 对接常曦 iOS

将 iOS 工程的 `CX_API_BASE_URL` 设为：

```text
https://api.example.com
```

不要在地址末尾再加 `/api`，客户端会按不同功能自动选择 `/api`、`/api/auth` 或 `/api/v1`前缀。Release 版对非本地地址强制使用 HTTPS。

## 12. 日常更新

更新前先备份数据库，再部署新的已验证 tag/commit：

```bash
cd /www/wwwroot/xuantong

git fetch --tags
git checkout <新的已验证-tag-或-commit>

docker compose -f docker-compose.prod.yml up -d --build

docker compose -f docker-compose.prod.yml ps
curl --fail http://127.0.0.1:8000/api/health
docker compose -f docker-compose.prod.yml logs --tail=100 backend
```

不要在未检查数据库迁移兼容性的情况下盲目回退代码。如新版本失败，优先保留数据库和 `.env`，切回上一个已验证镜像/代码版本，并根据迁移脚本决定是否需要数据恢复。

## 13. 备份与恢复演练

优先在 RDS 控制台配置自动备份、快照保留和跨地域备份。需要额外逻辑备份时，
从同 VPC 的受控运维机使用 `pg_dump` 连接 RDS 内网地址：

```bash
mkdir -p /www/backup/xuantong
PGPASSWORD='<RDS密码>' pg_dump -h '<RDS内网地址>' -U xuantong -d xuantong \
  > /www/backup/xuantong/xuantong-$(date +%F-%H%M%S).sql
```

建议在宝塔计划任务中配置：

- 每日 PostgreSQL 逻辑备份，至少保留 7–14 天；
- 加密后异机或对象存储备份，不要只放在同一块 ECS 磁盘；
- 定期备份 `.env` 和 Nginx 站点配置；
- 每月在非生产环境做一次恢复演练。

该系统涉及健康数据，备份、日志和数据库都应按敏感数据管理；限制人员和网络访问，并制定数据留存与删除策略。

## 14. 常见问题

### 502 Bad Gateway

```bash
curl -v http://127.0.0.1:8000/api/health
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 backend
```

本机健康检查失败，说明问题在容器或环境配置；本机成功但域名 502，检查宝塔反向代理目标和 Nginx 错误日志。

### 外网连接超时

检查 DNS、ECS 安全组、宝塔防火墙、Nginx 是否监听 80/443。阿里云安全组是有状态规则，通常配置入方向放行即可，见[阿里云安全组官方文档](https://help.aliyun.com/zh/ecs/user-guide/start-using-security-groups)。

### 容器启动后立即退出

先查日志：

```bash
docker compose logs --tail=200 backend
```

重点检查 `ENVIRONMENT`、`LLM_API_KEY`、`JWT_SECRET`、`API_AUTH_REQUIRED`、`RATE_LIMIT_ENABLED`、`CORS_ALLOWED_ORIGINS`、`USE_MEDICAL_MODEL` 和 `NOVITA_API_KEY`。

### 数据库无法连接

```bash
nc -vz <RDS内网地址> 5432
```

确认 ECS 与 RDS 在同一地域/VPC、RDS 白名单包含 ECS 私网 IP，并核对
`.env.production` 中账号、数据库名及 URL 编码后的密码。

## 15. 上线前检查清单

- [ ] 域名已解析，中国内地 ECS 的备案/接入备案已完成
- [ ] 安全组只对公网开放 80/443
- [ ] SSH 和宝塔面板只允许管理员 IP
- [ ] backend 仅绑定 `127.0.0.1:8000`
- [ ] RDS 仅允许 ECS 私网访问，未开放公网连接
- [ ] `.env.production` 权限为 `600`，密钥未入 Git
- [ ] `ENVIRONMENT=production`，认证和限流已开启
- [ ] CORS 为精确白名单，不是 `*`
- [ ] HTTPS 证书有效且能自动续期
- [ ] SSE 反向代理已关闭 buffering/cache
- [ ] Alembic 已执行到 `head`
- [ ] 外网健康检查、登录、主业务和 SSE 均验收通过
- [ ] 已配置加密异机备份和恢复演练
