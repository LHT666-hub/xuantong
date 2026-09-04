"""实体解析模块测试。

测试从 DrugClaw 移植的实体解析逻辑。
"""

from __future__ import annotations

import pytest

from app.xuantong.rag.entity_resolver import EntityResolver, EntityVariant


class TestEntityResolver:
    """实体解析器测试。"""

    @pytest.fixture
    def resolver(self) -> EntityResolver:
        return EntityResolver()

    def test_exact_match_standard_name(self, resolver: EntityResolver) -> None:
        """精确匹配 — 标准名称直接匹配。"""
        variants = resolver.resolve("氨氯地平")
        assert len(variants) == 1
        assert variants[0].original == "氨氯地平"
        assert variants[0].normalized == "氨氯地平"
        assert variants[0].variant_type == "exact_match"
        assert variants[0].confidence == 1.0

    def test_exact_match_synonym(self, resolver: EntityResolver) -> None:
        """同义词匹配 — 商品名映射到标准名。"""
        variants = resolver.resolve("络活喜")
        assert len(variants) == 1
        assert variants[0].original == "络活喜"
        assert variants[0].normalized == "氨氯地平"
        assert variants[0].variant_type == "exact_match"

    def test_exact_match_english_name(self, resolver: EntityResolver) -> None:
        """英文名匹配 — 英文名映射到中文标准名。"""
        variants = resolver.resolve("Amlodipine")
        assert len(variants) == 1
        assert variants[0].normalized == "氨氯地平"
        assert variants[0].variant_type == "exact_match"

    def test_exact_match_case_insensitive(self, resolver: EntityResolver) -> None:
        """大小写不敏感匹配。"""
        variants = resolver.resolve("amlodipine")
        assert len(variants) == 1
        assert variants[0].normalized == "氨氯地平"

    def test_fuzzy_match_typo(self, resolver: EntityResolver) -> None:
        """模糊匹配 — 拼写错误纠正。"""
        # "氨氯地评" 应该是 "氨氯地平" 的拼写错误
        variants = resolver.resolve("氨氯地评")
        assert len(variants) >= 1
        # 应该找到模糊匹配
        fuzzy_matches = [v for v in variants if v.variant_type == "fuzzy_match"]
        assert len(fuzzy_matches) >= 1
        # 标准化结果应该是氨氯地平
        assert any(v.normalized == "氨氯地平" for v in variants)

    def test_fuzzy_match_similar_name(self, resolver: EntityResolver) -> None:
        """模糊匹配 — 相似名称。"""
        # "硝苯地平" 的变体
        variants = resolver.resolve("硝苯地评")
        fuzzy_matches = [v for v in variants if v.variant_type == "fuzzy_match"]
        assert len(fuzzy_matches) >= 1

    def test_no_match_returns_original(self, resolver: EntityResolver) -> None:
        """无匹配 — 返回原名。"""
        variants = resolver.resolve("完全不存在的药物名称XYZ")
        assert len(variants) == 1
        assert variants[0].original == "完全不存在的药物名称XYZ"
        assert variants[0].normalized == "完全不存在的药物名称XYZ"
        assert variants[0].variant_type == "no_match"
        assert variants[0].confidence == 0.0

    def test_multiple_synonyms(self, resolver: EntityResolver) -> None:
        """多个同义词都能正确映射。"""
        test_cases = [
            ("拜新同", "硝苯地平"),
            ("科素亚", "氯沙坦"),
            ("代文", "缬沙坦"),
            ("倍他乐克", "美托洛尔"),
            ("开博通", "卡托普利"),
        ]
        for synonym, standard in test_cases:
            variants = resolver.resolve(synonym)
            assert len(variants) == 1
            assert variants[0].normalized == standard, (
                f"{synonym} 应该映射到 {standard}，实际映射到 {variants[0].normalized}"
            )

    def test_batch_resolve(self, resolver: EntityResolver) -> None:
        """批量解析。"""
        entity_names = ["氨氯地平", "络活喜", "不存在的药物"]
        results = resolver.resolve_batch(entity_names)

        assert len(results) == 3
        assert "氨氯地平" in results
        assert "络活喜" in results
        assert "不存在的药物" in results

        # 验证每个结果
        assert results["氨氯地平"][0].variant_type == "exact_match"
        assert results["络活喜"][0].normalized == "氨氯地平"
        assert results["不存在的药物"][0].variant_type == "no_match"

    def test_empty_batch_resolve(self, resolver: EntityResolver) -> None:
        """空批量解析。"""
        results = resolver.resolve_batch([])
        assert results == {}

    def test_other_drugs(self, resolver: EntityResolver) -> None:
        """其他药物解析。"""
        # 氢氯噻嗪
        variants = resolver.resolve("双克")
        assert variants[0].normalized == "氢氯噻嗪"

        # 螺内酯
        variants = resolver.resolve("安体舒通")
        assert variants[0].normalized == "螺内酯"

        # 地尔硫卓
        variants = resolver.resolve("合心爽")
        assert variants[0].normalized == "地尔硫卓"


class TestEntityVariant:
    """EntityVariant 模型测试。"""

    def test_create_variant(self) -> None:
        """创建 EntityVariant。"""
        variant = EntityVariant(
            original="络活喜",
            normalized="氨氯地平",
            variant_type="exact_match",
            confidence=1.0,
        )
        assert variant.original == "络活喜"
        assert variant.normalized == "氨氯地平"
        assert variant.variant_type == "exact_match"
        assert variant.confidence == 1.0

    def test_variant_defaults(self) -> None:
        """EntityVariant 默认值。"""
        variant = EntityVariant(
            original="test",
            normalized="test",
            variant_type="no_match",
        )
        assert variant.confidence == 1.0  # 默认值
