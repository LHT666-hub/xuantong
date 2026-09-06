# 玄同 Xuantong

> 数字化家庭医生团队多智能体系统 —— 让一个 AI 团队，像真实的家庭医生签约团队一样协作。

玄同模拟基层医疗中「家庭医生签约团队」的协作模式：患者上报一个健康事件后，系统自动完成
**智能分诊 → 多 Agent 会诊 → 风险分级 → 人工审核（必要时）→ 任务生成与执行 → 服务闭环归档**
的全流程。底层由 FastAPI 提供服务，LangGraph 编排工作流，阿里云百炼（DashScope）Qwen 系列模型分层驱动各个 Agent。

> ⚠️ **诚实声明**：本项目当前是**架构骨架（scaffold）**，不是可直接上线的生产系统。
> 204 个测试通过验证的是「流程能跑通、各组件接口正确」，而非「临床可用」。
> 真实知识库、用户认证、前端、生产部署等关键能力仍缺失。详见 [HANDOVER.md](./HANDOVER.md)。

---

## 核心技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| Web 框架 | **FastAPI** + Uvicorn | 异步 REST API，统一 `/api` 前缀 |
| 工作流引擎 | **LangGraph** StateGraph | 13 节点编排，`Send` 并行扇出 + 条件路由 |
| LLM 运行时 | **阿里云百炼 DashScope**（Qwen 系列） | 多模型分层路由，兼容 OpenAI 接口 |
| 数据校验 | **Pydantic v2** + pydantic-settings | Schema 与环境配置 |
| 持久化 | **SQLAlchemy 2.0**（async） | SQLite（开发）/ PostgreSQL（生产，asyncpg） |
| 迁移 | **Alembic** | 已配置，但 `versions/` 为空（待补齐） |
| 检索 | **rank-bm25** + numpy | RAG 当前为 BM25-only 降级模式 |
| 测试 | **pytest** + pytest-asyncio | `asyncio_mode=auto`，204 个测试 |
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
                                              GET /api/events/{id}/status   查询执行状态
                                              GET /api/tasks                任务看板
                                              GET /api/patients/{id}/timeline  时间线回溯
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

---

## 快速开始

### 环境要求

- **Python >= 3.12**
- 阿里云百炼（DashScope）API Key（[申请地址](https://bailian.console.aliyun.com/)）
- 开发环境无需数据库服务（默认使用 SQLite，自动建表）

### 1. 克隆与安装

```bash
git clone https://github.com/LHT666-hub/xuantong.git
cd xuantong

# 以可编辑模式安装（含核心依赖）
pip install -e .

# 安装开发/测试依赖
pip install -e ".[dev]"
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
```

> 💡 没有 API Key 时，可设 `LLM_PROVIDER=mock` 离线跑通流程与测试。

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

服务启动后访问交互式文档：<http://127.0.0.1:8000/docs>

### 4. 运行测试

```bash
pytest tests/ -v
```

预期结果：**204 passed**。

---

## API 端点

> 当前代码中实际注册并可访问的端点如下（统一 `/api` 前缀）。
> 标注 ⚠️ 的端点存在但返回空列表 / 占位数据，业务逻辑尚未完整实现。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 基础健康检查 |
| GET | `/api/health/detail` | 详细状态（app / llm / agents / workflow） |
| GET | `/api/agents` | 数字化家庭医生团队花名册 |
| GET | `/api/patients` | 患者列表 |
| GET | `/api/patients/{patient_id}` | 患者详情 |
| GET | `/api/health-records/{patient_id}` | ⚠️ 患者健康档案（占位） |
| POST | `/api/events` | 提交事件 → 触发 Workflow → 返回 event + workflow_summary + task_ids |
| GET | `/api/events/{event_id}` | 事件详情 |
| GET | `/api/events/{event_id}/status` | 事件 Workflow 执行状态 |
| GET | `/api/tasks` | 任务列表（支持过滤 + 分页） |
| GET | `/api/tasks/{task_id}` | 单个任务详情 |
| POST | `/api/tasks/{task_id}/complete` | 完成任务 → 记录 ServiceOutcome + Timeline |
| GET | `/api/outcomes` | 服务结果查询 |
| GET | `/api/patients/{patient_id}/timeline` | 患者时间线（支持过滤 + 分页） |
| GET | `/api/care-teams` | ⚠️ 照护团队列表（返回空） |
| POST | `/api/care-teams` | ⚠️ 创建照护团队（占位） |

---

## 项目目录结构

```
xuantong/
├── app/
│   ├── main.py                 # FastAPI 应用入口 + lifespan 组件装配
│   ├── config.py               # Pydantic Settings 环境配置
│   ├── api/
│   │   ├── routes/             # REST API 路由（events/tasks/patients/...）
│   │   ├── middleware/         # 全局异常处理
│   │   └── deps.py             # 依赖注入
│   ├── domain/
│   │   └── rules/              # 确定性临床规则引擎（风险分级/生命体征阈值/DDI）
│   ├── database/               # SQLAlchemy 引擎 / Session / Base
│   ├── models/                 # 18 个 ORM 数据模型
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/               # 业务服务层
│   ├── events/                 # 事件领域逻辑
│   ├── task_engine/            # 任务引擎
│   └── xuantong/               # ── 核心智能层 ──
│       ├── agents/             # 8 个 Agent 实现（5 实现 / 3 stub）
│       ├── llm/                # LLM 多模型分层 + Vision/Speech 多模态
│       ├── rag/                # RAG：BM25 检索 / 重排 / 证据分级 / 安全过滤 / 受众分层
│       │   └── data/           # 仅 4 份示例知识文档
│       ├── runtime/            # State + AgentRegistry
│       ├── safety/             # Safety Guard 四层
│       └── workflow/           # LangGraph StateGraph 工作流编排
├── alembic/                    # 迁移配置（versions/ 为空，待补齐）
├── tests/                      # 204 个测试（api/domain/rag/safety/workflow/xuantong）
├── pyproject.toml              # 依赖与构建配置
├── Dockerfile                  # ⚠️ 含 --reload，不适合生产
├── docker-compose.yml          # backend + supabase-db
├── .env.example                # 环境变量模板
└── HANDOVER.md                 # 项目交接文档（必读）
```

---

## 当前状态（诚实评估）

| 维度 | 状态 |
|------|------|
| 架构骨架 | ✅ 完成（API / 工作流 / Agent 注册 / Safety / RAG 结构 / 数据模型） |
| 测试覆盖 | ✅ 204 passed（验证接口契约与流程贯通） |
| 真实知识库 | ❌ 仅 4 份示例文档，向量检索未启用，BM25-only 降级 |
| 用户认证 | ❌ 无 JWT/OAuth2 中间件 |
| 前端 | ❌ 完全从零，无任何前端代码 |
| 生产部署 | ⚠️ Docker/CORS/日志/监控/CI 均需修正与补齐 |
| 多模态上传 | ⚠️ Vision/Speech 后端就绪，但无 HTTP 上传入口 |
| **生产可用度** | **约 30%** |

> 这是一个**可运行、可测试、结构清晰的起点**，而非终点。
> 接手前请务必阅读 [HANDOVER.md](./HANDOVER.md)，其中按 P0~P3 优先级列出了真正需要完成的工作、技术决策记录与已知坑点。

---

## License

待定（占位）。尚未确定开源许可证，使用前请与维护者确认。
