"""零依赖哈希向量器测试。

覆盖维度、归一化、相似度区分、批量一致性与确定性。
"""

import math

from app.xuantong.rag.hashing_vectorizer import HashingVectorizer


class TestHashingVectorizer:
    """HashingVectorizer 单元测试。"""

    def test_embed_produces_correct_dimension(self):
        """输出向量维度等于 dim（默认 256）。"""
        vec = HashingVectorizer().embed("高血压患者需要长期服用降压药物")
        assert len(vec) == 256

        custom = HashingVectorizer(dim=64).embed("测试文本")
        assert len(custom) == 64

    def test_embed_is_normalized(self):
        """输出向量 L2 范数 ≈ 1.0。"""
        vec = HashingVectorizer().embed("糖尿病饮食控制与血糖监测")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-9

    def test_similar_texts_higher_score(self):
        """相似文本的余弦相似度高于不相关文本。"""
        vz = HashingVectorizer()
        base = vz.embed("高血压患者需要服用降压药物")
        similar = vz.embed("高血压患者需要长期服用降压药物控制血压")
        unrelated = vz.embed("今天天气晴朗适合外出踏青放风筝")

        sim_similar = vz.cosine_similarity(base, similar)
        sim_unrelated = vz.cosine_similarity(base, unrelated)

        assert sim_similar > sim_unrelated

    def test_different_texts_lower_score(self):
        """完全不同文本的相似度显著低于自身。"""
        vz = HashingVectorizer()
        a = vz.embed("中医针灸治疗颈椎病")
        b = vz.embed("量子计算机的超导比特架构")
        self_sim = vz.cosine_similarity(a, a)

        cross = vz.cosine_similarity(a, b)
        assert self_sim > cross
        assert cross < 0.5

    def test_embed_batch(self):
        """批量嵌入与逐条嵌入结果一致。"""
        vz = HashingVectorizer()
        texts = ["高血压治疗指南", "糖尿病饮食建议", "感冒常见症状"]
        batch = vz.embed_batch(texts)
        assert len(batch) == len(texts)
        for text, batch_vec in zip(texts, batch):
            assert batch_vec == vz.embed(text)

    def test_deterministic(self):
        """相同输入产生完全相同的输出。"""
        vz1 = HashingVectorizer()
        vz2 = HashingVectorizer()
        text = "黄帝内经素问：上古之人，春秋皆度百岁"
        assert vz1.embed(text) == vz2.embed(text)
        assert vz1.embed(text) == vz1.embed(text)

    def test_empty_text_returns_zero_vector(self):
        """空文本返回零向量而非崩溃。"""
        vec = HashingVectorizer().embed("")
        assert len(vec) == 256
        assert all(v == 0.0 for v in vec)

    def test_cosine_similarity_dimension_mismatch(self):
        """维度不一致或空向量返回 0.0，不抛异常。"""
        vz = HashingVectorizer()
        assert vz.cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
        assert vz.cosine_similarity([], []) == 0.0
        assert vz.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
