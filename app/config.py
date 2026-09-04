from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "玄同 Xuantong"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./xuantong.db"
    database_echo: bool = False  # 开发时可开启 SQL 日志

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # LLM
    llm_provider: str = "mock"  # mock / qwen / deepseek
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"  # 兼容旧配置，作为 fallback

    # LLM 多模型分层配置
    llm_model_lead: str = "qwen3-max"           # 主智能体（最强推理）
    llm_model_specialist: str = "qwen-plus"      # 专科Agent（1M上下文+FC）
    llm_model_execution: str = "qwen-flash"      # 执行Agent（低成本+FC）
    llm_model_vision: str = "qwen3-vl-flash"     # 视觉识别
    llm_model_ocr: str = "qwen-vl-ocr"           # OCR
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

    # RAG 配置
    rag_enabled: bool = True
    rag_max_retries: int = 3
    rag_top_k: int = 5
    rag_relevance_threshold: float = 0.5
    rag_data_dir: str = "app/xuantong/rag/data"

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
        tier = self.llm_agent_model_map.get(agent_role, "execution")
        return self.get_model_for_tier(tier)
