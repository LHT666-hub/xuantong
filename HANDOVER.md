# 玄同 Xuantong 项目交接文档（HANDOVER）

> 写给接手开发者：这份文档的目标是**诚实**。
> 这里不会美化现状。你会看到一个测试全绿（307 passed）、工程基建基本齐备的系统，
> 但距离「能给真实患者用」仍有明确差距 —— 差距不在工程，而在**知识规模、Agent 智能深度与临床验证**。
> 请在动手前完整读完本文，尤其是 [§3 真正需要做的](#3-真正需要做的按优先级) 和 [§5 已知坑点](#5-已知坑点)。

---

## 1. 项目概述

- **定位**：面向基层医疗的「数字化家庭医生团队」AI 系统。
- **核心理念**：用多个 AI Agent 模拟真实的家庭医生签约团队（家庭医生 + 护士 + 公卫医师 + 药师 + 助理）协作。
- **业务主线**：

  ```
  患者事件上报 → 智能分诊 → 多 Agent 会诊 → 风险分级 → （必要时）人工审核
            → 任务生成与执行 → 服务结果记录 → 时间线归档（闭环）
  ```

- **技术底座**：FastAPI（服务）+ LangGraph（工作流编排）+ 阿里云百炼 DashScope Qwen（LLM）+ SQLAlchemy（持久化）+ JWT 认证 + SSE 实时推送。
- **仓库**：`https://github.com/LHT666-hub/xuantong.git`，主分支为 **`master`**（注意：不是 `main`）。
- **前端**：changxi iOS app 为对接前端，`/api/v1` 系列端点（chat / speech / documents / stream / 会话管理）已接线。

---

## 2. 已完成的

以下能力**已实现并有测试覆盖**（307 passed），但请注意「实现」≠「临床可用」：

### 2.1 工程基建（本轮新增，原 P0/P2 已基本清零）

- ✅ **用户认证体系**：JWT 手写实现（passlib[bcrypt] + python-jose），`/api/auth/register|login|me`，含角色门控（医生 / 患者 / 管理员）。
- ✅ **患者独立 CRUD**：完整增删改查 + 搜索 + 分页（`/api/patients`），不再是「事件附带创建」。
- ✅ **Patient / CareTeam / HealthRecord 完整 CRUD**：`care-teams`、`health-records` 不再是占位空返回。
- ✅ **Alembic 迁移脚本**：初始 schema 迁移（`c5524abe4c47`）+ `chat_messages` 迁移（`f3a9c1d2e4b5`），`versions/` 不再为空。
- ✅ **依赖锁定**：`requirements.txt` + `requirements-dev.txt`，可复现构建。
- ✅ **结构化日志 + PHI 脱敏**：JSON 结构化输出，患者隐私字段自动脱敏（`app/observability/`）。
- ✅ **请求追踪中间件**：每请求生成 request_id，写入响应头 `X-Request-ID`，记录 request_start/request_end 结构化日志。
- ✅ **fail-closed CORS**：白名单收敛（`CORS_ALLOWED_ORIGINS`），非法来源默认拒绝。
- ✅ **LangSmith 链路追踪**（可选）：`ENABLE_TRACING=true` 开启。
- ✅ **多阶段 Dockerfile**：非 root 用户、健康检查、生产镜像不含 dev 依赖与 `--reload`。
- ✅ **docker-compose**：backend + Postgres + Redis。
- ✅ **GitHub Actions CI/CD**：自动化测试与构建。
- ✅ **CONTRIBUTING.md**：贡献指南。
- ✅ **统一异常层次**：`XuantongError` 基类 + 全局异常处理器（`app/exceptions.py`）。

### 2.2 RAG（本轮大幅升级）

- ✅ **向量检索已激活**：哈希向量器（字符 n-gram HashingVectorizer，256 维，**零模型依赖**）+ BM25，RRF 融合。不再是 BM25-only 降级。
- ✅ **知识库扩充**：4 → **16 篇**，覆盖基层指南（高血压/糖尿病/COPD/卒中）、药物（降压/降糖/基药目录）、政策（国家/上海/奉贤三级）。
- ✅ **检索质量评估体系**：50 题 ground truth（`app/xuantong/rag/data/evaluation/`），**recall@5 = 94%**，可回归监控。
- ✅ **RAG 评估环路接入工作流**：节点 3 检索后 LLM 评估相关性，不达标自动查询重写重试。

### 2.3 实时通信与前端对接（本轮新增）

- ✅ **SSE 实时推送**：`GET /api/v1/events/{id}/stream` 工作流状态实时推送（替代轮询）。
- ✅ **对话流式输出**：`POST /api/v1/chat/stream`。
- ✅ **changxi iOS 前端 API 桥接**：`POST /api/v1/chat`（轻量对话）、`/api/v1/speech/transcribe`（语音转写）、`/api/v1/documents/analyze`（文档分析，analyze/ocr/bp 三模式），multipart 与 JSON base64/URL 双兼容。
- ✅ **会话持久化（ChatService）**：会话与消息 CRUD + 落库。
- ✅ **文档管理 + 对象存储接口**：上传 / presign 下载 / 删除。

### 2.4 原有核心骨架（延续）

- ✅ **FastAPI 服务框架** + 完整 REST API（系统 / 认证 / 患者 / 事件 / 任务 / 照护团队 / changxi v1）。
- ✅ **LangGraph StateGraph 工作流**：13 节点，`Send` 并行扇出 + 条件路由（高风险触发 HITL）；**Postgres checkpointer 分支可选**（`WORKFLOW_CHECKPOINT_BACKEND=postgres`）。
- ✅ **8 Agent 注册体系**：5 个有真实 Prompt 实现，3 个为 stub（中医 / 营养 / 康复）。
- ✅ **Safety Guard 四层**：InputGuard / OutputGuard（四态）/ ActionGuard / HITL。
- ✅ **LLM 多模型分层路由**：6 类模型 + 超时 + 指数退避重试。
- ✅ **多模态后端**：VisionService / SpeechService 已串联 HTTP 端点（原「无上传入口」问题已解决）。
- ✅ **临床规则引擎**：风险分级、生命体征阈值、DDI —— 但仍仅几条硬编码示例规则（见 §3 P3 延续项）。
- ✅ **307 个测试用例全部通过**（`pytest tests/ -v`）。

---

## 3. 真正需要做的（按优先级）

> 原 P0（认证 / 患者 CRUD / 迁移 / 依赖锁定）与大部分 P2（部署 / 日志 / SSE / 上传端点）已完成。
> 剩余工作重心是**知识规模、智能深度、性能与前端完整对接**。

### P1 — 到 MVP 的关键路径

| 项 | 现状 | 需要做 |
|----|------|--------|
| **灌入更多医学知识** | 16 篇起步语料，覆盖常见病种指南与政策 | 接入开源医学数据集扩充：**MedicalGPT-zh、DISC-Med-SFT、shibing624/medical**（含版权/合规审查） |
| **升级真实 Embedding** | 哈希向量器（词面匹配，无语义理解） | 接入 **DashScope text-embedding-v3** + **ChromaDB** 持久化向量检索 |
| **实现剩余 3 个 Agent** | 中医师 / 营养师 / 康复师仅 stub | 设计角色、Prompt、模型分配，接入会诊流程 |
| **前端 changxi 完整对接** | chat / speech / documents 端点已接线 | 健康数据同步、通知推送等完整功能对接 |

### P2 — 性能与运营

| 项 | 现状 | 需要做 |
|----|------|--------|
| **异步工作流执行** | 工作流在 HTTP 请求内同步执行，长流程阻塞 | **arq + Redis** 任务队列，解除 HTTP 阻塞（Redis 已在 compose 中就位） |
| **LLM 语义缓存** | 无，重复问题重复计费 | **GPTCache** 语义缓存 |
| **速率限制** | 无 | **slowapi** 限流（防刷、防 LLM 成本失控） |
| **Langfuse 可观测性平台** | 已有结构化日志 + LangSmith（可选） | **Langfuse** 自托管，比 LangSmith 更全面（成本追踪 / 评估 / 回放） |
| **Prompt 工程迭代** | Prompt 为初版，未经真实临床数据打磨 | 用真实/仿真病例迭代，做临床合理性评审 |

### P3 — 深化与扩展

| 项 | 现状 | 需要做 |
|----|------|--------|
| **CrossEncoder 重排升级** | 规则版重排（降级方案） | `sentence-transformers` + BAAI/bge-reranker-v2-m3（约需 2GB 显存） |
| **多轮对话记忆** | 会话持久化已有，但无长期记忆 / 上下文压缩 | `memory/` 模块（现为空壳） |
| **HealthKit / 蓝牙设备数据同步** | 无 | 可穿戴设备数据接入（iOS 端 HealthKit） |
| **临床规则扩充 / DDI 数据库** | 硬编码示例规则 | 接入真实临床指南与权威 DDI 数据源，规则可配置化 |
| **随访管理** | `Followup` 模型存在，业务逻辑不完整 | 随访计划生成、提醒、闭环跟踪 |

---

## 4. 技术决策记录

- **为什么选 LangGraph 而非其他工作流引擎？**
  会诊场景需要「一个事件并行扇出给多个专家 Agent，再汇聚综合」，LangGraph 的 `Send` 原语天然支持动态并行扇出 + 条件路由（高风险走 HITL 分支），比线性 DAG 或纯代码 if-else 更易表达和可视化。配合 checkpointer（memory / Postgres 双分支）可支持中断恢复。

- **RAG 为什么是「哈希向量 + BM25」而不是真 Embedding？**
  阶段性权衡。哈希向量器（HashingVectorizer，字符 n-gram）**零模型依赖、零显存、可离线测试**，配合 RRF 融合已把 recall@5 提到 94%，解决了「BM25-only 词面匹配漏召回」的主要痛点。但它**没有语义理解**（同义改写仍会漏）。
  **升级路径**：DashScope text-embedding-v3（API 调用，无本地显存负担）+ ChromaDB 持久化，`rag_vector_enabled` 与向量维度配置已预留。

- **认证为什么手写 JWT 而不用现成 OAuth2 框架？**
  需求边界清晰（注册/登录/me + 三角色门控），passlib + python-jose 组合足够，避免引入重量级认证框架带来的复杂度与攻击面。若后续接入微信/医保等第三方身份，再评估升级。

- **SSE 而不是 WebSocket？**
  工作流状态推送与对话流式是**单向服务器推送**场景，SSE 基于 HTTP、自动重连、穿透代理友好，实现与运维成本远低于 WebSocket。双向交互需求出现前不升级。

- **模型分层策略（成本控制）**
  - `qwen3-max`：贵但强，**仅**主智能体（家庭医生，负责分析与综合决策）使用。
  - `qwen-plus`：会诊专家（护士/公卫/药师）使用，性价比平衡。
  - `qwen-flash`：便宜，执行类（家医助理）使用。
  - `qwen3-vl-flash` / `qwen3-asr-flash`：多模态（图片/语音）。
  目的：把算力花在刀刃上，避免每个 Agent 都用最贵模型导致成本失控。

- **Safety Guard 为什么分四层？**
  医疗场景安全责任分层、各司其职：
  - InputGuard 管「进来的」——危机信号（如自杀倾向）和注入攻击；
  - OutputGuard 管「出去给患者看的」——四态处置防止有害/不当内容直达患者；
  - ActionGuard 管「系统要做的动作」——按风险分级，决定能否自动执行；
  - HITL 管「拿不准的」——高风险/临界情况交人工审核。
  分层让安全策略可独立测试、独立演进，而非揉成一坨。`/api/v1/chat` 轻量对话虽不走 13 节点工作流，但入站 InputGuard、出站 OutputGuard 双重过滤不缺席。

---

## 5. 已知坑点

- ⚠️ **SQLAlchemy UUID 列**：赋值时必须用 `UUID()` 包装字符串值，直接传字符串会报错。
- ⚠️ **passlib 与 bcrypt 版本兼容性**：bcrypt 5.x 移除了 passlib 依赖的内部 API，会导致告警/报错。锁定 `bcrypt<4.1` 或使用兼容版本组合，升级前先跑认证测试。
- ⚠️ **BM25 小语料负分**：语料库 < 10 篇文档时，IDF 计算会产生**负分**，即使匹配成功。
  **不要**过滤 `score <= 0`（会导致小语料返回空）。正确做法：**min-max 归一化**所有分数，始终返回 top_k。
  代码位置：`app/xuantong/rag/knowledge_base.py` 的 `_bm25_only()`（纯 BM25 降级路径）。RRF 融合路径（`_hybrid_rrf()`）不用 min-max，按排名 `1/(rrf_k+rank)` 累加归一化 —— 改检索逻辑时两条路径都要顾及。
- ⚠️ **qwen-turbo 在北京地域不支持 Function Calling**：执行类 Agent **必须**用 `qwen-flash`，不要用 `qwen-turbo`。
- ⚠️ **Git 远程分支是 `master` 不是 `main`**：CI、部署脚本、PR 目标分支注意。
- ⚠️ **思考模式（enable_thinking）单独计价**：输出 token 价格约为普通的 **4-5 倍**，非必要不开启。当前仅家庭医生（`qwen3-max`）开启。
- ⚠️ **JWT_SECRET 默认值不可上生产**：`.env.example` 中是占位符，部署前必须替换为强随机密钥，否则 token 可被伪造。
- ⚠️ **工作流同步执行**：`POST /api/events` 会在请求内跑完整个工作流，真实 LLM 下耗时较长，客户端超时要设足；根治靠 P2 的 arq 异步化。

---

## 6. 参考项目说明

工作区 `c:\Users\LHT\Desktop\玄同\` 下另有 7 个参考项目，其核心思路已部分移植进玄同 RAG，但原始代码仍可作为进一步参考：

| 项目 | 参考价值 |
|------|----------|
| **LingYi** | 中医 RAG 参考（混合检索 + CrossEncoder 重排） |
| **_ref_drugclaw** | 药物 RAG 参考（证据分级 + 实体解析） |
| **medharness** | 医疗安全参考（PHI 脱敏 + 注入检测） |
| **MAS-in-diabetes** | 多 Agent 系统参考（受众分层） |
| **careflow** | 护理工作流参考 |
| **_ref_family-doctor** | 家庭医生 Agent 设计参考 |
| **Pipecat-agents** | 语音 Agent 参考（实时语音交互） |

> 移植到玄同 RAG 的模块包括：证据分级（`evidence.py`）、实体解析（`entity_resolver.py`）、受众分层（`audience_filter.py`）、安全过滤（`safety_filter.py`）、查询重写（`query_rewriter.py`）、评分（`grader.py`）等。

---

## 7. 工作量估算（给接手人的预期）

> **进度对照**：原始估算到 MVP 约 **6-8 周（1-2 人全职）**。本轮改进已消化约 **4 周**的量
> （P0 全部 + P2 大部分 + RAG 激活与评估体系 + 前端 API 桥接）。**剩余到 MVP 约 2-4 周。**

| 阶段 | 内容 | 估算 | 状态 |
|------|------|------|------|
| ~~P0~~ | 认证 + 患者 CRUD + Alembic 迁移 + 依赖锁定 | ~~1-2 周~~ | ✅ 已完成 |
| **P1** | 知识灌注（开源数据集）+ 真实 Embedding 升级 | 约 **1-2 周** | ⬜ 待做 |
| **P1** | 剩余 3 Agent + Prompt 迭代启动 | 约 **1 周** | ⬜ 待做 |
| **P1** | 前端 changxi 完整功能对接 | 约 **1-2 周**（可与后端并行） | ⬜ 部分完成（API 已接线） |
| **P2** | 异步工作流（arq）+ 缓存 + 限流 + Langfuse | 约 **1-2 周** | ⬜ 待做（MVP 后亦可） |
| **P3** | CrossEncoder / 多轮记忆 / HealthKit / 规则与 DDI 深化 | **持续性工作** | ⬜ 待做 |
| **合计** | 到 MVP 可用 | **约 2-4 周（1-2 人全职）** | |

> 估算为粗粒度参考，真实进度高度依赖：知识源可得性与合规审查、临床专家评审投入、前端对接范围。

---

## 8. 如何开始

### 环境与运行

```bash
# 1. 克隆（注意分支是 master）
git clone https://github.com/LHT666-hub/xuantong.git
cd xuantong

# 2. 安装（建议虚拟环境，Python >= 3.12）
pip install -e ".[dev]"
pip install -r requirements-dev.txt

# 3. 配置环境变量
#    复制 .env.example 为 .env，填入百炼 API Key，并替换 JWT_SECRET
#    没有 Key 时设 LLM_PROVIDER=mock 离线跑通

# 4. 跑测试，确认环境正常（应 307 passed）
pytest tests/ -v

# 5. 启动服务，访问 http://127.0.0.1:8000/docs
uvicorn app.main:app --reload

# 或者：docker compose up -d 一键起 backend + Postgres + Redis
```

### 推荐的开发顺序

1. **先跑通现状**：装依赖 → 跑测试 → 启动服务 → 注册/登录拿 token → 用 `/docs` 提交一个事件，观察工作流闭环与 SSE 推送（建议先用 `LLM_PROVIDER=mock`，零成本理解流程）。
2. **读核心代码**：`app/main.py`（装配 + 中间件）→ `app/xuantong/workflow/`（13 节点）→ `app/xuantong/rag/`（混合检索 + 评估环路）→ `app/api/routes/chat.py`、`stream.py`（changxi 对接）→ `app/xuantong/safety/`（四层）。
3. **攻 P1**：知识灌注与 Embedding 升级（RAG）、剩余 3 Agent、前端完整对接 —— 三者可并行（不同人）。
4. **P2/P3 持续迭代**：异步工作流、语义缓存、限流、Langfuse、CrossEncoder、多轮记忆、设备数据同步。

### 给接手人的几句话

- 测试全绿只代表**接口契约和流程贯通**，不代表临床正确性 —— 任何面向患者的输出都需临床专家评审，这一条从未改变，且现在是离「真实患者」最近的时候，更要守住。
- 改 RAG 时务必记住 §5 的 **BM25 负分坑**与**双路径（`_bm25_only` / `_hybrid_rrf`）归一化差异**；改完跑一遍 50 题评估集，别让 recall@5 回退。
- 涉及 LLM 的改动注意**成本**（模型分层 + 思考模式计价），别无意把所有 Agent 切到 `qwen3-max`。
- 动认证相关代码先读 §5 的 **passlib/bcrypt 版本坑**，依赖升级前先跑认证测试。
- 有疑虑先查 [README.md](./README.md) 的架构图和本文 §4 的决策记录，理解「为什么这么设计」再动手。
