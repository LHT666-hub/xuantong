# 玄同 Xuantong

> 数字化家庭医生团队多智能体系统 —— 让一个 AI 团队，像真实的家庭医生签约团队一样协作。

玄同模拟基层医疗中「家庭医生签约团队」的协作模式：患者上报一个健康事件后，系统自动完成
**智能分诊 → 多 Agent 会诊 → 风险分级 → 人工审核（必要时）→ 任务生成与执行 → 服务闭环归档**
的全流程。底层由 FastAPI 提供服务，LangGraph 编排工作流，阿里云百炼（DashScope）Qwen 系列模型分层驱动各个 Agent。

> ⚠️ **诚实声明**：本项目已具备**可演示、可对接的准生产骨架**：307 个测试全绿、JWT 认证、
> 混合检索 RAG（16 篇知识文档，recall@5=94%）、SSE 实时推送、结构化日志 + PHI 脱敏、
> 多阶段 Docker 构建与 CI/CD 均已落地，changxi iOS 前端 API 已接线。
> 但**尚不等于「临床可用」**：真实医学知识库仍需大规模灌注、3 个 Agent 仍为 stub、
> Prompt 未经真实临床数据打磨、前端功能未完整对接。详见 [HANDOVER.md](./HANDOVER.md)。

---

## 核心技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| Web 框架 | **FastAPI** + Uvicorn | 异步 REST API，统一 `/api` 前缀 |
| 工作流引擎 | **LangGraph** StateGraph | 13 节点编排，`Send` 并行扇出 + 条件路由，RAG 评估环路已接入 |
| LLM 运行时 | **阿里云百炼 DashScope**（Qwen 系列） | 多模型分层路由，兼容 OpenAI 接口 |
| 数据校验 | **Pydantic v2** + pydantic-settings | Schema 与环境配置 |
| 持久化 | **SQLAlchemy 2.0**（async） | SQLite（开发）/ PostgreSQL（生产，asyncpg） |
| 迁移 | **Alembic** | 初始 schema 迁移 + `chat_messages` 迁移已入库 |
| 认证 | **JWT**（passlib[bcrypt] + python-jose） | 注册 / 登录 / 当前用户，角色门控（医生 / 患者 / 管理员） |
| 检索 | **rank-bm25** + numpy + 哈希向量 | BM25 + 哈希向量器混合检索，RRF 融合（零外部模型依赖） |
| 缓存 | **Redis** | docker-compose 内置（当前用于依赖服务，为异步工作流 / 语义缓存预留） |
| 实时推送 | **SSE**（Server-Sent Events） | 工作流状态实时推送 + 对话流式输出 |
| 可观测性 | 结构化 JSON 日志 + 请求追踪 | PHI 自动脱敏、`X-Request-ID`、LangSmith 链路追踪（可选） |
| 测试 | **pytest** + pytest-asyncio | `asyncio_mode=auto`，307 个测试 |
| HTTP 客户端 | **httpx** | LLM 调用与测试 |

---

## 数字化家庭医生团队（8 个 Agent）

| # | Agent | 角色定位 | 模型 | 阶段 | 实现状态 |
|---|-------|----------|------|------|----------|
| 1 | FamilyDoctorAgent（家庭医生） | 团队负责人 / 统一入口：事件分析、成员调度、综合决策 | `qwen3-max`（enable_thinking） | 会诊 | ✅ 已实现 |
| 2 | NurseAgent（护士） | 生命体征解读、趋势分析、红旗征识别 | `qwen-plus` | 会诊 | ✅ 已实现 |
| 3 | PublicHealthAgent（公卫医师） | 慢病管理规范、随访计划、转诊标准 | `qwen-plus` | 会诊 | ✅ 已实现 |
| 4 | PharmacistAgent（药师） | 用药安全审查、药物相互作用（DDI）检查 | `qwen-plus` | 会诊 | ✅ 已实现 |
| 5 | AssistantAgent（家医助理） | 连接性劳动：联系患者、提醒、预约、催办、家属协调 | `qwen-flash` | 执行 | ✅ 已实现 |
| 6 | TCM Agent（中医师） | 中医辨证施治 | 待定 | 会诊 | ⬜ Stub |
| 7 | NutritionAgent（营养师） | 营养指导 | 待定 | 会诊 | ⬜ Stub |
| 8 | RehabilitationAgent（康复师） | 康复训练指导 | 待定 | 会诊 | ⬜ Stub |

**实现进度：5 / 8**（3 个仅为占位 stub，未接入 Prompt 与模型）。

---

## 系统架构

### 服务闭环流程

```
                         ┌──────────────────────────────────────────────┐
                         │              玄同 Xuantong 服务                 │
                         └──────────────────────────────────────────────┘

  患者/家属                FastAPI                 LangGraph StateGraph                  持久化
 ───────────             ──────────              ──────────────────────               ──────────

  上报事件   ──HTTP──▶  POST /api/events  ──▶  ┌─────────────────────────────────┐
 (文本/图片/语音)         (Event 落库)          │ 1  multimodal_detection  多模态识别 │
                                              │ 2  input_guard           输入安全守卫 │
                                              │ 3  rag_retrieval         知识检索     │
                                              │      （评估环路：相关性不足自动重写重试）│
                                              │ 4  analyze               事件分析     │ ──▶ Event
                                              │ 5  dispatch              团队调度     │
                                              │ 6  consult  ── Send 并行扇出 ──┐      │
                                              │      ├─ NurseAgent           │      │ ──▶ AgentRun
                                              │      ├─ PublicHealthAgent    │ 会诊  │
                                              │      └─ PharmacistAgent      │      │
                                              │ 7  synthesis             综合决策 ◀─┘ │
                                              │ 8  risk_assessment       风险分级     │
                                              │ 9  output_guard          输出安全守卫 │
                                              │ 10 action_guard          动作风险分级 │
                                              │ 11 hitl  ◀── 条件路由（高风险触发）── │ ──▶ pending_human
                                              │ 12 task_generation       任务生成     │ ──▶ Task
                                              │ 13 execution + timeline  执行与归档   │ ──▶ ServiceOutcome
                                              └─────────────────────────────────┘        TimelineEntry
                                                          │
                                                          ▼
                                              GET /api/v1/events/{id}/stream  SSE 实时推送
                                              GET /api/events/{id}/status     查询执行状态
                                              GET /api/tasks                  任务看板
                                              GET /api/patients/{id}/timeline 时间线回溯
```

### 四层 Safety Guard

```
  输入 ──▶ [InputGuard]  危机检测 / 注入攻击防护
              │
   Agent 产出 ─▶ [OutputGuard] 四态处置：PASS / REWRITE / BLOCK / ESCALATE
              │
   拟执行动作 ─▶ [ActionGuard] 风险分级：LOW / MEDIUM / HIGH / CRITICAL
              │
   高风险/临界 ─▶ [HITL]      Human-in-the-Loop 人工审核队列
```

### RAG 检索链路（已激活混合检索）

```
  查询 ──▶ KnowledgeBase.hybrid_search()
              ├─ BM25（rank-bm25，字符级分词适配中文）
              └─ 哈希向量器（字符 n-gram HashingVectorizer，256 维，零模型依赖）
                     │
                     ▼  RRF（Reciprocal Rank Fusion）融合
              RAGRetriever.retrieve()
                     │  受众分层过滤 → 重排（规则版）→ 安全过滤
                     ▼
              RAGEvaluationLoop（工作流节点 3）
                     │  LLM 相关性评估 → 不达标自动查询重写重试
                     ▼
                 会诊上下文
```

- **知识语料**：16 篇，覆盖 4 大类 —— 基层指南（高血压/糖尿病/COPD/卒中）、药物（降压/降糖/基药目录）、政策（国家基本公卫/家医签约、上海家医 1+1+1/慢病管理、奉贤家医服务）。
- **评估体系**：50 题 ground truth（`app/xuantong/rag/data/evaluation/`），当前 **recall@5 = 94%**。

---

## 快速开始

### 环境要求

- **Python >= 3.12**
- 阿里云百炼（DashScope）API Key（[申请地址](https://bailian.console.aliyun.com/)）
- 开发环境无需数据库服务（默认使用 SQLite，自动建表）
- 可选：Docker + docker-compose（一键起 Postgres + Redis）

### 1. 克隆与安装

```bash
git clone https://github.com/LHT666-hub/xuantong.git
cd xuantong

# 以可编辑模式安装（含核心依赖）
pip install -e .

# 安装开发/测试依赖（已锁定版本，见 requirements-dev.txt）
pip install -e ".[dev]"
pip install -r requirements-dev.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的百炼 API Key：

```bash
# 数据库（开发默认 SQLite，无需修改）
DATABASE_URL=sqlite+aiosqlite:///./xuantong.db

# LLM Provider：mock（离线测试）/ qwen（真实调用）
LLM_PROVIDER=qwen
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 多模型分层
LLM_MODEL_LEAD=qwen3-max          # 主智能体（家庭医生）
LLM_MODEL_SPECIALIST=qwen-plus    # 会诊专家
LLM_MODEL_EXECUTION=qwen-flash    # 执行类（家医助理）
LLM_MODEL_VISION=qwen3-vl-flash   # 图片理解
LLM_MODEL_ASR=qwen3-asr-flash     # 语音识别

# ── 认证（JWT）──
JWT_SECRET=change-me-in-production   # 生产必须替换为强随机密钥
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# ── 可观测性 ──
LOG_LEVEL=INFO                       # 结构化 JSON 日志（含 PHI 脱敏）
CORS_ALLOWED_ORIGINS=*               # 生产收敛为白名单（fail-closed）
ENABLE_TRACING=false                 # LangSmith 链路追踪（可选）
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=xuantong

# ── RAG（混合检索默认开启）──
RAG_VECTOR_ENABLED=true              # 哈希向量器，零模型依赖
RAG_TOP_K=5

# ── 工作流 ──
WORKFLOW_CHECKPOINT_BACKEND=memory   # 生产可切 postgres（需 pip install -e ".[postgres]"）
```

> 💡 没有 API Key 时，可设 `LLM_PROVIDER=mock` 离线跑通流程与测试。

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

服务启动后访问交互式文档：<http://127.0.0.1:8000/docs>

或使用 docker-compose 一键启动（backend + Postgres + Redis）：

```bash
docker compose up -d
```

### 4. 运行测试

```bash
pytest tests/ -v
```

预期结果：**307 passed**。

---

## API 端点

> 当前代码中实际注册并可访问的端点如下。业务端点统一 `/api` 前缀，
> 认证端点为 `/api/auth`，changxi iOS 前端对接端点为 `/api/v1`。

### 系统与团队

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 基础健康检查 |
| GET | `/api/health/detail` | 详细状态（app / llm / agents / workflow） |
| GET | `/api/agents` | 数字化家庭医生团队花名册 |

### 认证（JWT）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册（角色：医生 / 患者 / 管理员） |
| POST | `/api/auth/login` | 登录，返回 access_token |
| GET | `/api/auth/me` | 当前用户信息（需 Bearer Token） |

### 患者与健康档案（完整 CRUD）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/patients` | 患者列表（搜索 + 分页） |
| POST | `/api/patients` | 创建患者 |
| GET | `/api/patients/{patient_id}` | 患者详情 |
| PUT | `/api/patients/{patient_id}` | 更新患者 |
| DELETE | `/api/patients/{patient_id}` | 删除患者 |
| GET | `/api/health-records` | 健康记录列表 |
| GET | `/api/health-records/{record_id}` | 健康记录详情 |
| GET | `/api/patients/{patient_id}/measurements` | 患者测量数据 |
| GET | `/api/patients/{patient_id}/timeline` | 患者时间线（支持过滤 + 分页） |

### 事件 / 任务 / 结果（服务闭环）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/events` | 提交事件 → 触发 Workflow → 返回 event + workflow_summary + task_ids |
| GET | `/api/events/{event_id}` | 事件详情 |
| GET | `/api/events/{event_id}/status` | 事件 Workflow 执行状态 |
| GET | `/api/tasks` | 任务列表（支持过滤 + 分页） |
| GET | `/api/tasks/{task_id}` | 单个任务详情 |
| POST | `/api/tasks/{task_id}/complete` | 完成任务 → 记录 ServiceOutcome + Timeline |
| GET | `/api/outcomes` | 服务结果查询 |

### 照护团队

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/care-teams` | 照护团队列表 |
| POST | `/api/care-teams` | 创建照护团队 |
| GET | `/api/care-teams/{team_id}` | 团队详情 |
| GET | `/api/care-teams/{team_id}/patients` | 团队签约患者 |

### changxi iOS 前端对接（/api/v1）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat` | 轻量对话（family_doctor 角色直连 LLM，双重 Safety Guard，失败降级不 500） |
| POST | `/api/v1/chat/stream` | 对话流式输出（SSE） |
| POST | `/api/v1/chat/sessions` | 创建会话 |
| GET | `/api/v1/chat/sessions` | 会话列表 |
| POST | `/api/v1/chat/sessions/{session_id}/messages` | 会话内发消息（持久化） |
| GET | `/api/v1/chat/sessions/{session_id}/messages` | 会话历史 |
| DELETE | `/api/v1/chat/sessions/{session_id}` | 删除会话 |
| POST | `/api/v1/speech/transcribe` | 语音转写（multipart 或 JSON base64/URL） |
| POST | `/api/v1/documents/analyze` | 医疗文档分析（analyze / ocr / bp 三种模式） |
| POST | `/api/v1/documents` | 文档上传（对象存储接口，返回 presign） |
| GET | `/api/v1/documents` | 文档列表 |
| GET | `/api/v1/documents/{document_id}/presign` | 获取文档下载地址 |
| DELETE | `/api/v1/documents/{document_id}` | 删除文档 |
| GET | `/api/v1/events/{event_id}/stream` | 工作流状态 SSE 实时推送 |

---

## 项目目录结构

```
xuantong/
├── app/
│   ├── main.py                 # FastAPI 应用入口 + lifespan 组件装配 + 中间件
│   ├── config.py               # Pydantic Settings 环境配置
│   ├── exceptions.py           # 统一异常层次（XuantongError）
│   ├── api/
│   │   ├── routes/             # REST 路由（auth/patients/events/tasks/chat/stream/documents/...）
│   │   ├── middleware/         # 请求追踪中间件（X-Request-ID + 结构化日志）
│   │   └── deps.py             # 依赖注入（含 JWT 鉴权）
│   ├── domain/
│   │   └── rules/              # 确定性临床规则引擎（风险分级/生命体征阈值/DDI）
│   ├── database/               # SQLAlchemy 引擎 / Session / Base
│   ├── models/                 # ORM 数据模型（含 User / ChatSession / ChatMessage）
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/               # 业务服务层（含 ChatService 会话持久化、文档存储）
│   ├── observability/          # 结构化 JSON 日志 + PHI 脱敏 + LangSmith 追踪
│   ├── events/                 # 事件领域逻辑
│   ├── task_engine/            # 任务引擎
│   └── xuantong/               # ── 核心智能层 ──
│       ├── agents/             # 8 个 Agent 实现（5 实现 / 3 stub）
│       ├── llm/                # LLM 多模型分层 + Vision/Speech 多模态
│       ├── rag/                # RAG：BM25+哈希向量混合检索 / RRF / 重排 / 证据分级 / 安全过滤 / 受众分层
│       │   └── data/           # 16 篇知识文档（guidelines/drugs/policies）
│       │       └── evaluation/ # 50 题检索质量 ground truth
│       ├── runtime/            # State + AgentRegistry
│       ├── safety/             # Safety Guard 四层
│       └── workflow/           # LangGraph StateGraph 工作流编排（RAG 环路已接入）
├── alembic/                    # 迁移（initial_schema + add_chat_messages）
├── tests/                      # 307 个测试（api/domain/rag/safety/workflow/xuantong/integration）
├── scripts/                    # 运维辅助脚本
├── .github/workflows/          # GitHub Actions CI/CD
├── pyproject.toml              # 依赖与构建配置
├── requirements.txt            # 生产依赖锁定
├── requirements-dev.txt        # 开发依赖锁定
├── Dockerfile                  # 多阶段构建（非 root 用户 + 健康检查）
├── docker-compose.yml          # backend + Postgres + Redis
├── CONTRIBUTING.md             # 贡献指南
├── .env.example                # 环境变量模板
└── HANDOVER.md                 # 项目交接文档（必读）
```

---

## 当前状态（诚实评估）

| 维度 | 状态 |
|------|------|
| 架构骨架 | ✅ 完成（API / 工作流 / Agent 注册 / Safety / RAG / 数据模型 / 统一异常） |
| 测试覆盖 | ✅ 307 passed（接口契约、流程贯通、集成闭环） |
| 用户认证 | ✅ JWT 注册/登录/me + 角色门控（passlib + python-jose） |
| RAG 检索 | ✅ 混合检索已激活（BM25 + 哈希向量 RRF 融合），16 篇知识文档，recall@5=94%，50 题评估集 |
| 实时通信 | ✅ SSE 工作流状态推送 + 对话流式输出 |
| 多模态 | ✅ 语音转写 / 文档分析 HTTP 端点已上线（/api/v1） |
| 可观测性 | ✅ 结构化 JSON 日志 + PHI 脱敏 + X-Request-ID + LangSmith（可选） |
| 生产部署 | ✅ 多阶段 Dockerfile（非 root）+ docker-compose（Postgres+Redis）+ CI/CD + 依赖锁定 |
| 数据库迁移 | ✅ Alembic 初始迁移 + chat_messages 迁移 |
| 前端 | ⚠️ changxi iOS app API 已接线（chat/speech/documents），完整功能对接未完成 |
| 真实知识库 | ⚠️ 16 篇仅为起步语料，距离覆盖基层医疗全场景仍需大规模灌注 |
| Agent 完整度 | ⚠️ 5/8 实现，中医/营养/康复仍为 stub；Prompt 未经真实临床数据打磨 |
| 异步执行 | ⚠️ 工作流在 HTTP 请求内同步执行，长流程会阻塞（arq + Redis 待做） |
| **生产可用度** | **约 60%**（内部演示 / 试点对接可用；面向真实患者仍需知识灌注 + 临床评审 + 合规审查） |

> 相比上一阶段（架构骨架，约 30%），认证、迁移、部署、可观测性、RAG 激活、前端桥接等
> P0/P2 项已基本清零；剩余工作重心转向**知识规模、Agent 智能深度与临床验证**。
> 接手前请务必阅读 [HANDOVER.md](./HANDOVER.md)，其中按 P1~P3 优先级列出了真正需要完成的工作、技术决策记录与已知坑点。

---

## License

待定（占位）。尚未确定开源许可证，使用前请与维护者确认。
