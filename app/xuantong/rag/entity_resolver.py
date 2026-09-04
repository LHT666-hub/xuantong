"""实体解析模块 — 医疗实体名称标准化与变体扩展。

从 DrugClaw 项目移植的实体解析逻辑，为 RAG 检索提供
医学术语标准化能力。默认使用本地模糊匹配，LLM 扩展可选。

解析策略：
1. 精确匹配（同义词表查找）
2. 模糊匹配（difflib，cutoff=0.6）
3. LLM 变体扩展（可选，需要 llm_runtime）
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 模糊匹配阈值（0-1），0.6 是生物医学名称的最佳平衡点
_DEFAULT_CUTOFF = 0.6

# 最大模糊匹配返回数
_MAX_FUZZY_MATCHES = 3

# 最大 LLM 变体数
_MAX_LLM_VARIANTS = 4


class EntityVariant(BaseModel):
    """实体变体结果。"""

    original: str = Field(description="原始实体名称")
    normalized: str = Field(description="标准化后的实体名称")
    variant_type: str = Field(
        description="变体类型: exact_match/fuzzy_match/llm_variant/no_match"
    )
    confidence: float = Field(default=1.0, description="匹配置信度")


class EntityResolver:
    """医疗实体解析器 — 标准化实体名称并扩展变体。

    参考 DrugClaw 的 EntityResolver 实现，适配玄同的医疗场景。
    内置常见降压药实体索引，支持扩展。
    """

    def __init__(self, llm_runtime: Any = None) -> None:
        """
        Args:
            llm_runtime: LLM 运行时实例（可选），用于变体扩展。
        """
        self.llm_runtime = llm_runtime
        # 标准名 → [同义词列表]
        self._entity_index: dict[str, list[str]] = {}
        # 反向索引：小写名称 → 标准名
        self._reverse_index: dict[str, str] = {}
        self._build_index()

    def _build_index(self) -> None:
        """构建本地实体索引。

        包含常见降压药实体及其同义词/商品名/英文名。
        """
        # 常见降压药实体
        medications = {
            "氨氯地平": ["络活喜", "安内真", "Amlodipine", "苯磺酸氨氯地平"],
            "硝苯地平": ["拜新同", "欣然", "Nifedipine", "硝苯地平控释片"],
            "依那普利": ["悦宁定", "Enalapril", "马来酸依那普利"],
            "氯沙坦": ["科素亚", "Losartan", "氯沙坦钾"],
            "缬沙坦": ["代文", "Valsartan"],
            "美托洛尔": ["倍他乐克", "Metoprolol", "琥珀酸美托洛尔"],
            "氢氯噻嗪": ["双克", "Hydrochlorothiazide", "HCTZ"],
            "螺内酯": ["安体舒通", "Spironolactone"],
            "地尔硫卓": ["合心爽", "Diltiazem", "盐酸地尔硫卓"],
            "卡托普利": ["开博通", "Captopril"],
        }

        for standard_name, synonyms in medications.items():
            # 标准名 → [标准名, 同义词1, 同义词2, ...]
            self._entity_index[standard_name] = [standard_name] + synonyms
            # 同义词 → [标准名]
            for syn in synonyms:
                self._entity_index[syn] = [standard_name]
            # 建立反向索引
            self._reverse_index[standard_name.lower()] = standard_name
            for syn in synonyms:
                self._reverse_index[syn.lower()] = standard_name

    def resolve(self, entity_name: str) -> list[EntityVariant]:
        """解析实体名称。

        解析策略：
        1. 精确匹配（包括同义词）
        2. 模糊匹配（difflib，cutoff=0.6）
        3. 无匹配时返回原名

        Args:
            entity_name: 待解析的实体名称

        Returns:
            EntityVariant 列表，按匹配置信度排序
        """
        variants: list[EntityVariant] = []

        # 1. 精确匹配（包括同义词）
        if entity_name in self._entity_index:
            normalized = self._entity_index[entity_name][0]
            variants.append(EntityVariant(
                original=entity_name,
                normalized=normalized,
                variant_type="exact_match",
                confidence=1.0,
            ))
            return variants

        # 反向索引精确匹配（大小写不敏感）
        if entity_name.lower() in self._reverse_index:
            normalized = self._reverse_index[entity_name.lower()]
            variants.append(EntityVariant(
                original=entity_name,
                normalized=normalized,
                variant_type="exact_match",
                confidence=1.0,
            ))
            return variants

        # 2. 模糊匹配
        all_keys = list(self._entity_index.keys())
        matches = difflib.get_close_matches(
            entity_name, all_keys, n=_MAX_FUZZY_MATCHES, cutoff=_DEFAULT_CUTOFF
        )

        for match in matches:
            normalized = self._entity_index[match][0] if match in self._entity_index else match
            # 计算相似度作为置信度
            similarity = difflib.SequenceMatcher(None, entity_name, match).ratio()
            variants.append(EntityVariant(
                original=entity_name,
                normalized=normalized,
                variant_type="fuzzy_match",
                confidence=round(similarity, 3),
            ))

        # 3. 如果模糊匹配也失败，返回原名
        if not variants:
            variants.append(EntityVariant(
                original=entity_name,
                normalized=entity_name,
                variant_type="no_match",
                confidence=0.0,
            ))

        return variants

    async def resolve_with_llm(self, entity_name: str) -> list[EntityVariant]:
        """使用 LLM 扩展实体变体。

        先执行本地解析，然后调用 LLM 生成额外的同义词/拼写纠正。

        Args:
            entity_name: 待解析的实体名称

        Returns:
            EntityVariant 列表（包含本地 + LLM 结果）
        """
        if not self.llm_runtime:
            return self.resolve(entity_name)

        # 先执行本地解析
        local_variants = self.resolve(entity_name)

        # LLM 生成同义词/拼写纠正
        prompt = f"""给定以下医疗实体名称，生成有助于检索的变体形式：

实体名称: {entity_name}

请提供：
1. 标准/规范化名称（如 INN 名称）
2. 常见同义词或商品名
3. 如果名称可能有拼写错误，建议纠正

仅返回 JSON 格式：
{{"variants": ["变体1", "变体2", ...]}}

规则：
- 仅包含高置信度变体（不要编造生僻名称）
- 列表简短（最多 {_MAX_LLM_VARIANTS} 个变体）
- 不要重复原始输入名称"""

        try:
            result = await self.llm_runtime.generate_json(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            llm_variants = result.get("variants", [])
            if not isinstance(llm_variants, list):
                return local_variants

            # 去重并添加 LLM 变体
            existing_normalized = {v.normalized.lower() for v in local_variants}
            for v in llm_variants[:_MAX_LLM_VARIANTS]:
                v_str = str(v).strip()
                if v_str and v_str.lower() not in existing_normalized:
                    local_variants.append(EntityVariant(
                        original=entity_name,
                        normalized=v_str,
                        variant_type="llm_variant",
                        confidence=0.8,  # LLM 变体默认置信度
                    ))
                    existing_normalized.add(v_str.lower())

            return local_variants
        except Exception as exc:
            logger.debug("LLM 实体变体生成失败: %s", exc)
            return local_variants

    def resolve_batch(self, entity_names: list[str]) -> dict[str, list[EntityVariant]]:
        """批量解析实体名称。

        Args:
            entity_names: 待解析的实体名称列表

        Returns:
            字典，键为原始名称，值为 EntityVariant 列表
        """
        return {name: self.resolve(name) for name in entity_names}
