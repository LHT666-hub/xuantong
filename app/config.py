from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "玄同 Xuantong"
    environment: str = "development"  # development / test / production
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./xuantong.db"
    database_echo: bool = False  # 开发时可开启 SQL 日志

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Supabase Storage（文档/图片对象存储）
    supabase_storage_bucket: str = "documents"
    supabase_presign_expires_seconds: int = 3600

    # LLM
    llm_provider: str = "mock"  # mock / qwen / deepseek
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"  # 兼容旧配置，作为 fallback

    # LLM 多模型分层配置
    llm_model_lead: str = "qwen3-max"           # 主智能体（最强推理）
    llm_model_specialist: str = "qwen-plus"      # 专科Agent（1M上下文+FC）
    llm_model_execution: str = "qwen-flash"      # 执行Agent（低成本+FC）
    llm_model_nutrition: str = "qwen3.8-flash"   # 食养排序（Qwen3.8 无 plus 型号）
    llm_model_vision: str = "qwen3-vl-flash"     # 视觉识别
    llm_model_ocr: str = "qwen3.5-ocr"            # OCR（百炼当前推荐稳定代际）
    llm_model_asr: str = "qwen3-asr-flash"       # 语音识别

    # LLM 调用参数
    llm_timeout: float = 60.0                    # 单次调用超时（秒）
    llm_max_retries: int = 3                     # 最大重试次数
    llm_retry_base_delay: float = 1.0            # 重试基础延迟（秒），指数退避

    # Agent → 模型层级映射
    llm_agent_model_map: dict[str, str] = {
        "family_doctor": "lead",
        "nurse": "specialist",
        "public_health": "specialist",
        "pharmacist": "specialist",
        "tcm": "specialist",
        "nutrition": "execution",
        "rehabilitation": "execution",
        "assistant": "execution",
    }

    # Novita AI 医疗模型（Ling 3.0 Flash Santé）
    novita_api_key: str = ""
    novita_base_url: str = "https://api.novita.ai/openai"
    medical_model_id: str = "inclusionai/ling-3.0-flash-sante"
    use_medical_model: bool = True

    # 医疗 Agent 列表 —— 这些 Agent 优先走 Novita Ling 3.0
    medical_agents: list[str] = [
        "family_doctor", "tcm", "nutrition", "rehabilitation",
    ]

    # 若木 D 模式：只作为外部知识库/联网证据层，最终回答仍由玄同选择的模型生成。
    ruomu_enabled: bool = False
    ruomu_base_url: str = "https://bailian-kb-chat.2947520194.workers.dev"
    ruomu_access_key: str = ""
    ruomu_timeout: float = 25.0

    # RAG 配置
    rag_enabled: bool = True
    rag_max_retries: int = 3
    rag_top_k: int = 5
    rag_relevance_threshold: float = 0.5
    rag_data_dir: str = "app/xuantong/rag/data"

    # RAG 混合检索配置
    rag_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_bm25_enabled: bool = True
    rag_vector_enabled: bool = True  # 零依赖哈希向量器（HashingVectorizer）
    rag_vector_dim: int = 256        # 哈希向量维度
    rag_vector_ngram: int = 3        # 字符 n-gram 的 n 值
    rag_rrf_k: int = 60
    rag_use_reranker: bool = True

    # --- Workflow ---
    workflow_checkpoint_backend: str = "memory"  # memory / postgres

    # --- Observability ---
    log_level: str = "INFO"
    cors_allowed_origins: str = "*"

    # --- API perimeter ---
    api_auth_required: bool = False
    rate_limit_enabled: bool = False
    rate_limit_requests_per_minute: int = 120
    rate_limit_auth_requests_per_minute: int = 12

    # Tracing (LangSmith) —— 默认关闭，通过环境变量无侵入接入 LangGraph 链路追踪
    enable_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "xuantong"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_model_for_tier(self, tier: str) -> str:
        """根据模型层级获取具体模型名称"""
        tier_map = {
            "lead": self.llm_model_lead,
            "specialist": self.llm_model_specialist,
            "execution": self.llm_model_execution,
            "vision": self.llm_model_vision,
            "ocr": self.llm_model_ocr,
            "asr": self.llm_model_asr,
        }
        return tier_map.get(tier, self.llm_model)

    def get_model_for_agent(self, agent_role: str) -> str:
        """根据 Agent 角色获取对应模型名称"""
        if agent_role == "nutrition":
            return self.llm_model_nutrition
        tier = self.llm_agent_model_map.get(agent_role, "execution")
        return self.get_model_for_tier(tier)

    def is_medical_agent(self, agent_role: str) -> bool:
        """判断 Agent 是否属于医疗类（优先走 Ling 3.0）"""
        return agent_role in self.medical_agents

    def get_timeout_for_tier(self, tier: str) -> float:
        """根据模型层级获取超时时间（秒）。

        当前所有层级共用全局 llm_timeout；未来可按层级差异化配置。
        """
        return self.llm_timeout

    # --- Authentication ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    def validate_production(self) -> None:
        """拒绝使用不安全默认值启动生产服务。"""
        if self.environment.lower() != "production":
            return

        errors: list[str] = []
        if self.debug:
            errors.append("DEBUG 必须为 false")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            errors.append("DATABASE_URL 必须使用 postgresql+asyncpg")
        if self.llm_provider != "qwen" or not self.llm_api_key:
            errors.append("必须配置 LLM_PROVIDER=qwen 和 LLM_API_KEY")
        if len(self.jwt_secret) < 32 or self.jwt_secret in {
            "change-me-in-production",
            "your-secret-key-change-in-production",
        }:
            errors.append("JWT_SECRET 必须是至少 32 字符的随机值")
        if not self.api_auth_required:
            errors.append("API_AUTH_REQUIRED 必须为 true")
        if not self.rate_limit_enabled:
            errors.append("RATE_LIMIT_ENABLED 必须为 true")
        if self.cors_allowed_origins.strip() == "*":
            errors.append("CORS_ALLOWED_ORIGINS 生产环境不得为 *")
        if self.ruomu_enabled and not self.ruomu_access_key:
            errors.append("启用若木时必须配置 RUOMU_ACCESS_KEY")
        if self.use_medical_model and not self.novita_api_key:
            errors.append("启用医疗模型时必须配置 NOVITA_API_KEY")
        if errors:
            raise RuntimeError("生产配置不安全：" + "；".join(errors))
