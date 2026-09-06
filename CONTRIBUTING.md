# 贡献指南 · 玄同 Xuantong

感谢参与「玄同」数字化家庭医生系统的建设。本文档帮助你在本地快速搭建开发环境，并遵循统一的协作规范。

## 一、开发环境设置

要求：**Python 3.12+**、Git；可选 Docker（用于本地联调数据库 / Redis）。

```bash
# 1. 克隆并进入项目
git clone https://github.com/LHT666-hub/xuantong.git
cd xuantong

# 2. 创建虚拟环境
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖（含开发依赖）
pip install --upgrade pip
pip install -e ".[dev]"

# 4. 准备环境变量
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
# 本地开发保持 LLM_PROVIDER=mock 即可，无需真实 API Key

# 5. 初始化数据库（默认 SQLite，开箱即用）
alembic upgrade head

# 6. 启动服务
uvicorn app.main:app --reload --port 8000
# 健康检查： http://localhost:8000/api/health
```

### 使用 Docker 联调

```bash
docker compose up --build      # 启动 backend + postgres + redis
```

## 二、代码规范

- **语言版本**：始终面向 Python 3.12 编写，善用类型注解（type hints）。
- **风格**：遵循 PEP 8；命名清晰，模块职责单一。
- **目录约束**：
  - `app/api/` 路由层，只做参数校验与编排，不写业务逻辑；
  - `app/services/`、`app/domain/` 承载业务与领域规则；
  - `app/xuantong/` 为核心智能体 / 工作流 / RAG 实现。
- **配置**：新增配置项统一在 `app/config.py` 的 `Settings` 中声明，并同步到 `.env.example`，**严禁**在代码中硬编码密钥。
- **依赖**：新增运行时依赖请写入 `pyproject.toml` 的 `dependencies`，开发依赖写入 `[project.optional-dependencies].dev`，随后更新锁定文件：
  ```bash
  pip install pip-tools
  pip-compile pyproject.toml -o requirements.txt --strip-extras --no-emit-index-url
  pip-compile pyproject.toml -o requirements-dev.txt --strip-extras --no-emit-index-url --extra dev
  ```

## 三、测试要求

- 提交前必须本地通过全部测试：
  ```bash
  pytest tests/ -v
  ```
- 测试默认使用 **mock provider**，不依赖真实 LLM / 外部服务：
  ```bash
  set LLM_PROVIDER=mock                          # Windows
  # export LLM_PROVIDER=mock                      # macOS / Linux
  ```
- 新增功能请补充对应单元测试；修复缺陷请补充可复现该缺陷的回归测试。
- CI（`.github/workflows/ci.yml`）会在每次 PR 上自动运行 `pytest` 与 Docker 构建，**两项均须通过**方可合并。

## 四、PR 流程

1. 从最新的 `master` 切出功能分支：`git checkout -b feat/your-topic`。
2. 小步提交，遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：
   - `feat:` 新功能 · `fix:` 缺陷修复 · `docs:` 文档 · `refactor:` 重构 · `test:` 测试 · `chore:` 构建/杂项
3. 推送分支并发起 Pull Request，目标分支为 **`master`**。
4. PR 描述需包含：改动动机、主要变更点、测试方式、影响范围（如接口 / 数据库 / 环境变量）。
5. 至少 1 名维护者 Review 通过且 CI 全绿后合并，推荐 **Squash Merge**。

## 五、分支策略

| 分支 | 用途 | 保护规则 |
| --- | --- | --- |
| `master` | 主干，始终可发布 | 禁止直接 push，须经 PR + CI + Review |
| `feat/*`、`fix/*` | 功能 / 缺陷分支 | 从 `master` 切出，合并回 `master` |
| `hotfix/*` | 紧急线上修复 | 从 `master` 切出，修复后合并回 `master` |

- 远程默认分支为 **`master`**（非 `main`）。
- 保持分支短生命周期，频繁 rebase / 合并主干以减少冲突。

## 六、安全须知

- **切勿**提交 `.env`、API Key、数据库凭据等敏感信息（已在 `.gitignore` 中忽略）。
- 生产部署通过环境变量或密钥管理服务注入配置。
- 涉及患者数据的改动需注意脱敏与访问控制，遵循最小权限原则。
