"""RAG 数据模型 — 检索结果、评分结果、RAG 上下文。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    """单条检索结果。"""

    content: str = Field(description="文档正文")
    source: str = Field(default="", description="来源（文件名/章节等）")
    score: float = Field(default=0.0, description="融合相关性得分 0.0-1.0（RRF 归一化）")
    metadata: dict = Field(default_factory=dict, description="附加元数据")
    bm25_score: float = Field(default=0.0, description="BM25 检索分数")
    vector_score: float = Field(default=0.0, description="向量检索分数")
    rerank_score: float = Field(default=0.0, description="重排分数")


class GradeResult(BaseModel):
    """LLM 评分结果。"""

    relevant: bool = Field(description="是否与查询相关")
    score: float = Field(default=0.0, description="评分 0.0-1.0")
    reason: str = Field(default="", description="评分理由")


class RAGResult(BaseModel):
    """RAG 评估环路最终输出。"""

    documents: list[RetrievalResult] = Field(default_factory=list)
    query: str = Field(default="", description="最终使用的查询（可能经过重写）")
    attempts: int = Field(default=1, description="检索尝试次数")
    success: bool = Field(default=True, description="是否找到相关文档")


class RAGContext(BaseModel):
    """RAG 上下文 — 注入到 Agent 的 system prompt。"""

    retrieved_docs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, description="平均置信度")
    sources: list[str] = Field(default_factory=list)
