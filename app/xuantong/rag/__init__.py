"""RAG 评估环路组件。

提供检索、评分、查询重写、证据分级、实体解析、安全过滤、受众分层、
混合检索（BM25 + 向量 + RRF）、重排器与自适应检索闭环。
"""

from app.xuantong.rag.audience_filter import Audience, AudienceFilter
from app.xuantong.rag.base import BaseRAGClient, BaseReranker
from app.xuantong.rag.chroma_retriever import ChromaRAGClient
from app.xuantong.rag.entity_resolver import EntityResolver, EntityVariant
from app.xuantong.rag.evidence import (
    EvidenceGrader,
    EvidenceItem,
    EvidenceKind,
    infer_evidence_kind,
)
from app.xuantong.rag.grader import RetrievalGrader
from app.xuantong.rag.knowledge_base import KnowledgeBase
from app.xuantong.rag.models import (
    GradeResult,
    RAGContext,
    RAGResult,
    RetrievalResult,
)
from app.xuantong.rag.query_rewriter import QueryRewriter
from app.xuantong.rag.rag_loop import RAGEvaluationLoop
from app.xuantong.rag.reranker import CrossEncoderReranker, RuleBasedReranker
from app.xuantong.rag.retriever import RAGRetriever
from app.xuantong.rag.safety_filter import RAGSafetyFilter, SafetyFilterResult

__all__ = [
    "Audience",
    "AudienceFilter",
    "BaseRAGClient",
    "BaseReranker",
    "ChromaRAGClient",
    "CrossEncoderReranker",
    "EntityResolver",
    "EntityVariant",
    "EvidenceGrader",
    "EvidenceItem",
    "EvidenceKind",
    "GradeResult",
    "KnowledgeBase",
    "QueryRewriter",
    "RAGContext",
    "RAGEvaluationLoop",
    "RAGResult",
    "RAGRetriever",
    "RAGSafetyFilter",
    "RetrievalGrader",
    "RetrievalResult",
    "RuleBasedReranker",
    "SafetyFilterResult",
    "infer_evidence_kind",
]
