# 玄同 (Xuantong)

数字化家庭医生团队多智能体系统

## 技术栈

- **Web 框架**: FastAPI + Uvicorn
- **工作流引擎**: LangGraph StateGraph
- **LLM**: 阿里云百炼 (DashScope) - Qwen 系列多模型分层
- **数据库**: SQLite (开发) / PostgreSQL+Supabase (生产)
- **测试**: pytest

## 核心能力

### 8 个 AI Agent 团队

| Agent | 角色 | 模型 | 阶段 |
|-------|------|------|------|
| FamilyDoctorAgent | 团队负责人/统一入口 | qwen3-max | consultation |
| NurseAgent | 专业护理观察 | qwen-plus | consultation |
| PublicHealthAgent | 公卫随访管理 | qwen-plus | consultation |
| PharmacistAgent | 用药安全 | qwen-plus | consultation |
| AssistantAgent | 连接性劳动执行 | qwen-flash | execution |
| TCM/Nutrition/Rehabilitation | 预留 | - | - |

### Safety Guard 四层安全守卫

- **InputGuard**: 危机检测、注入攻击防护
- **OutputGuard**: 4 态输出审查 (PASS/REWRITE/BLOCK/ESCALATE)
- **ActionGuard**: 动作风险分级 (LOW/MEDIUM/HIGH/CRITICAL)
- **HITL**: Human-in-the-Loop 人工审核

### LangGraph 工作流

```
START → multimodal_detection → input_guard → rag_retrieval → analyze → dispatch
      → [Send 并行] consult → synthesis → risk_assessment → output_guard
      → action_guard → [条件] hitl → task_generation → execution → timeline → END
```

### RAG 评估环路

检索 → 评分 → 重写 → 重试（最多 3 次），确保检索质量。

### 多模态支持

- **文本**: 常规事件上报
- **图片**: POST /api/events/image → VisionService (qwen3-vl-flash)
- **语音**: POST /api/events/audio → SpeechService (qwen3-asr-flash)

## 快速开始

### 安装依赖

```bash
cd xuantong
pip install -e .
```

### 配置环境变量

复制 `.env.example` 为 `.env`，填入百炼 API Key：

```bash
LLM_PROVIDER=qwen
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 启动服务

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 运行测试

```bash
python -m pytest tests/ -v
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/health/detail | 详细状态 |
| GET | /api/agents | Agent 花名册 |
| POST | /api/events | 提交事件（触发 workflow） |
| POST | /api/events/image | 上传图片事件 |
| POST | /api/events/audio | 上传音频事件 |
| GET | /api/tasks | 任务列表 |
| POST | /api/tasks/{id}/complete | 完成任务 |
| GET | /api/patients/{id}/timeline | 患者时间线 |

## 项目结构

```
xuantong/
├── app/
│   ├── api/routes/          # REST API 路由
│   ├── domain/rules/        # 确定性临床规则引擎
│   ├── models/              # SQLAlchemy 模型
│   ├── schemas/             # Pydantic 数据模型
│   ├── services/            # 业务服务层
│   └── xuantong/            # 核心智能层
│       ├── agents/          # 8 个 Agent 实现
│       ├── llm/             # LLM 多模型分层
│       ├── rag/             # RAG 评估环路
│       ├── runtime/         # State + Registry
│       ├── safety/          # Safety Guard 四层
│       └── workflow/        # LangGraph 工作流
├── tests/                   # 131 个测试
└── pyproject.toml
```

## 测试覆盖

- **131 个测试全部通过**
- 覆盖：API、领域规则、Safety Guard、Agent 智能、LangGraph 工作流、RAG、端到端闭环

## License

MIT
