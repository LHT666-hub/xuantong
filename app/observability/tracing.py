"""LangSmith/LangChain 链路追踪配置。

通过环境变量注入，LangGraph 无侵入自动采集工作流执行链路。
未配置 API Key 时完全 no-op，零开销。

设计意图
--------
LangChain / LangGraph 在运行时读取 ``LANGCHAIN_TRACING_V2`` 等环境变量后，
会自动将节点执行、LLM 调用、工具调用等上报到 LangSmith，无需在业务工作流
代码中插入任何埋点。本模块在应用启动阶段按配置注入这些环境变量。

安全 / 零开销
-------------
- ``enable_tracing=False``（默认）时立即返回，不做任何事。
- 即便开启但未配置 API Key，也仅记录一条 info 日志后返回，绝不影响启动。
"""

import logging
import os

logger = logging.getLogger(__name__)


def setup_tracing(settings) -> bool:
    """配置 LangSmith 追踪。返回是否启用成功。

    Args:
        settings: Settings 实例（需含 enable_tracing / langsmith_api_key /
            langsmith_project 字段，缺失时按默认值处理）。

    Returns:
        bool: 成功注入追踪环境变量返回 True；未启用或缺少 API Key 返回 False。
    """
    if not getattr(settings, "enable_tracing", False):
        return False

    api_key = getattr(settings, "langsmith_api_key", "")
    if not api_key:
        logger.info("LangSmith tracing disabled: no API key configured")
        return False

    project = getattr(settings, "langsmith_project", "xuantong") or "xuantong"

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project

    logger.info("LangSmith tracing enabled for project: %s", project)
    return True
