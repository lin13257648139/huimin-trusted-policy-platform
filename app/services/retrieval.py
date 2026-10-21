from __future__ import annotations

import re
from collections import Counter, OrderedDict
from datetime import date
from math import log, sqrt
from threading import Lock

from app.config import settings
from app.domain.models import Evidence
from app.services.ai_runtime import ModelRuntimeError, embed_texts
from app.services.catalog import load_evidence

_DOCUMENT_EMBEDDING_CACHE_LIMIT = 4
_document_embedding_cache: OrderedDict[
    tuple[int, str, str, tuple[str, ...]], tuple[tuple[float, ...], ...]
] = OrderedDict()
_document_embedding_cache_lock = Lock()

DOMAIN_ANCHORS = (
    "救助", "低保", "保障", "家庭", "申请", "材料", "办理", "收入", "支出",
    "财产", "户籍", "居住", "急难", "政策", "窗口", "残疾", "医疗", "教育",
    "导办", "必需信息", "保密", "安全措施", "赡养", "抚养", "扶养", "义务人", "D值",
    "特困", "供养", "劳动能力", "生活来源", "街道", "办结", "照料", "丧葬",
)
OUT_OF_DOMAIN_ANCHORS = (
    "量子", "卫星", "轨道", "编程", "代码", "股票", "基金", "彩票", "天气",
    "菜谱", "游戏", "影视", "足球", "旅游", "景点", "旅游攻略", "数学题",
)
GATE_BYPASS_MARKERS = (
    "忽略领域", "绕过领域", "跳过领域", "无视领域", "强制回答", "取消限制",
    "无视规则", "绕过限制", "越过限制", "跳过校验", "关闭校验", "解除限制",
)
SMUGGLING_CONNECTORS = (
    "顺便", "附带", "捎带", "只要加上", "同时写上", "但请提到", "硬塞",
)
ELIGIBILITY_RELATION_MARKERS = (
    "是否", "算不算", "计入", "影响", "申报", "核查", "认定", "属于", "资格", "条件",
)
ELIGIBILITY_ANCHORS = (
    "低保", "救助", "保障", "收入", "财产", "资格", "申请", "特困", "供养"
)
UNSUPPORTED_ASSISTANCE_TOPICS = (
    "住房救助", "教育救助", "就业救助", "流浪乞讨", "孤儿福利",
)


def _is_legitimate_eligibility_relation(compact: str, off_domain: list[str]) -> bool:
    """Allow domain-external facts only when they are being tested as eligibility facts.

    Words such as “股票” can be a legitimate household-asset question.  Merely
    placing several policy words next to an unrelated request is not enough: the
    query must state an eligibility relation and must not use an explicit
    smuggling connector.
    """

    if not off_domain or any(marker in compact for marker in SMUGGLING_CONNECTORS):
        return False
    has_relation = any(marker in compact for marker in ELIGIBILITY_RELATION_MARKERS)
    has_eligibility_anchor = any(anchor in compact for anchor in ELIGIBILITY_ANCHORS)
    return has_relation and has_eligibility_anchor


def domain_gate(query: str) -> dict[str, object]:
    """Deterministic allow/deny gate shared by every retrieval route."""

    compact = re.sub(r"\s+", "", query)
    matched = sorted({anchor for anchor in DOMAIN_ANCHORS if anchor in compact})
    off_domain = sorted({anchor for anchor in OUT_OF_DOMAIN_ANCHORS if anchor in compact})
    bypass = sorted({marker for marker in GATE_BYPASS_MARKERS if marker in compact})
    if bypass:
        return {
            "passed": False,
            "reason_code": "gate_bypass_attempt",
            "reason": "检测到要求绕过领域限制的指令，已拒绝检索。",
            "matched_anchors": matched,
            "off_domain_anchors": off_domain,
        }
    unsupported_topics = sorted(
        topic for topic in UNSUPPORTED_ASSISTANCE_TOPICS if topic in compact
    )
    if unsupported_topics:
        return {
            "passed": False,
            "reason_code": "unsupported_social_assistance_topic",
            "reason": "问题属于社会救助相关领域，但当前知识库尚未覆盖该具体事项。",
            "matched_anchors": matched,
            "off_domain_anchors": off_domain,
            "unsupported_topics": unsupported_topics,
        }
    if not matched:
        return {
            "passed": False,
            "reason_code": "no_social_assistance_anchor",
            "reason": "问题不属于当前社会救助政策知识域。",
            "matched_anchors": [],
            "off_domain_anchors": off_domain,
        }
    if off_domain and not _is_legitimate_eligibility_relation(compact, off_domain):
        return {
            "passed": False,
            "reason_code": "off_domain_keyword_smuggling",
            "reason": "问题主体属于域外内容，附带政策词不能绕过领域限制。",
            "matched_anchors": matched,
            "off_domain_anchors": off_domain,
        }
    return {
        "passed": True,
        "reason_code": "in_domain",
        "reason": "命中社会救助政策领域锚点。",
        "matched_anchors": matched,
        "off_domain_anchors": off_domain,
    }


def _terms(text: str) -> list[str]:
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text.lower())
    latin = re.findall(r"[a-z0-9]+", normalized)
    chinese = [normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))]
    return latin + chinese


def _resolve_as_of(as_of: date | None) -> date:
    return as_of or date.fromisoformat(settings.policy_as_of)


def _evidence_active_on(item: Evidence, as_of: date) -> bool:
    if item.effective_from and as_of < item.effective_from:
        return False
    if item.effective_to and as_of > item.effective_to:
        return False
    return True


def _temporal_catalog(as_of: date) -> tuple[list[Evidence], int]:
    all_items = list(load_evidence().values())
    active = [item for item in all_items if _evidence_active_on(item, as_of)]
    return active, len(all_items) - len(active)


def search_evidence(
    query: str, limit: int = 5, *, as_of: date | None = None
) -> list[dict[str, object]]:
    """离线、可解释的字段加权BM25检索。

    标题和条款号具有更高权重，连续短语命中再获得小幅加分。返回匹配词，便于
    在评测阶段检查为什么某条证据被召回。语义向量和重排器仍作为可插拔增强项，
    未配置时不会伪装成已启用。
    """

    effective_date = _resolve_as_of(as_of)
    catalog, _ = _temporal_catalog(effective_date)
    query_terms = Counter(_terms(query))
    if not query_terms or not domain_gate(query)["passed"]:
        return []
    doc_terms: list[Counter[str]] = []
    for item in catalog:
        searchable_quote = item.verbatim_quote or item.excerpt
        weighted = Counter(_terms(searchable_quote))
        if item.plain_language_explanation:
            weighted.update(
                {term: count for term, count in Counter(_terms(item.plain_language_explanation)).items()}
            )
        weighted.update({term: count * 3 for term, count in Counter(_terms(item.title)).items()})
        weighted.update({term: count * 2 for term, count in Counter(_terms(item.article or "")).items()})
        doc_terms.append(weighted)
    frequencies: Counter[str] = Counter()
    for terms in doc_terms:
        frequencies.update(terms.keys())

    document_lengths = [sum(terms.values()) for terms in doc_terms]
    average_length = sum(document_lengths) / max(len(document_lengths), 1)
    query_phrase = re.sub(r"\s+", "", query.lower())
    k1, b = 1.5, 0.75
    ranked: list[tuple[float, Evidence, list[str]]] = []
    for item, terms, document_length in zip(catalog, doc_terms, document_lengths, strict=True):
        score = 0.0
        matched_terms: list[str] = []
        for term, query_count in query_terms.items():
            if term not in terms:
                continue
            matched_terms.append(term)
            inverse = log(1 + (len(catalog) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            frequency = terms[term]
            denominator = frequency + k1 * (
                1 - b + b * document_length / max(average_length, 1)
            )
            score += inverse * (frequency * (k1 + 1) / denominator) * min(query_count, 2)
        searchable = re.sub(
            r"\s+",
            "",
            (
                f"{item.title}{item.article or ''}{item.verbatim_quote or item.excerpt}"
                f"{item.plain_language_explanation or ''}"
            ).lower(),
        )
        if len(query_phrase) >= 2 and query_phrase in searchable:
            score += 2.5
        coverage = len(set(matched_terms)) / max(len(query_terms), 1)
        # 自然语言问题通常包含“是否、需要、怎么办”等口语，要求命中一半二元词会
        # 错杀正确证据。BM25的IDF已抑制“救助”等高频词；这里要求至少命中三个
        # 二元词或15%的查询覆盖，并把实际匹配词返回给评测报告审计。
        sufficient_signal = (
            coverage >= 0.5
            if len(query_terms) <= 4
            else len(set(matched_terms)) >= 3 or coverage >= 0.15
        )
        if score > 0 and (len(query_terms) == 1 or sufficient_signal):
            ranked.append((score, item, sorted(set(matched_terms))))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "score": round(score, 3),
            "matched_terms": matched_terms,
            "match_coverage": round(len(matched_terms) / max(len(query_terms), 1), 3),
            "evidence": evidence.model_dump(mode="json"),
        }
        for score, evidence, matched_terms in ranked[:limit]
    ]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _embed_query_and_documents(
    query: str, documents: tuple[str, ...]
) -> tuple[list[float], list[list[float]], str, int, bool]:
    """Embed stable policy documents once while keeping resident queries uncached.

    The cache key binds vectors to the embedding function, configured model and
    optional model digest, plus the exact policy text.  User queries are always
    sent only for the current request and are never retained in the cache.
    Holding the lock during a cold fill prevents concurrent requests from
    duplicating the expensive full-catalog embedding operation.
    """

    model = str(settings.ollama_embedding_model)
    digest = str(getattr(settings, "ollama_embedding_model_digest", None) or "")
    cache_key = (id(embed_texts), model, digest, documents)
    with _document_embedding_cache_lock:
        cached = _document_embedding_cache.get(cache_key)
        if cached is None:
            embedded = embed_texts([query, *documents])
            document_vectors = tuple(
                tuple(float(value) for value in vector)
                for vector in embedded.vectors[1:]
            )
            _document_embedding_cache[cache_key] = document_vectors
            _document_embedding_cache.move_to_end(cache_key)
            while len(_document_embedding_cache) > _DOCUMENT_EMBEDDING_CACHE_LIMIT:
                _document_embedding_cache.popitem(last=False)
            return (
                embedded.vectors[0],
                [list(vector) for vector in document_vectors],
                embedded.model_id,
                embedded.latency_ms,
                False,
            )
        _document_embedding_cache.move_to_end(cache_key)

    query_embedding = embed_texts([query])
    return (
        query_embedding.vectors[0],
        [list(vector) for vector in cached],
        query_embedding.model_id,
        query_embedding.latency_ms,
        True,
    )


def search_evidence_result(
    query: str, limit: int = 5, *, as_of: date | None = None
) -> dict[str, object]:
    """Return the actual retrieval route and a safe deterministic fallback.

    Hybrid mode uses reciprocal-rank fusion over BM25 and a configured local
    embedding model. If the model is absent or invalid, the response says so
    and keeps the deterministic ranking; it never labels fallback as semantic.
    """

    effective_date = _resolve_as_of(as_of)
    catalog, excluded_count = _temporal_catalog(effective_date)
    gate = domain_gate(query)
    if not gate["passed"]:
        return {
            "query": query,
            "as_of": effective_date.isoformat(),
            "items": [],
            "domain_gate": gate,
            "temporal_filter": {
                "enabled": True,
                "active_evidence": len(catalog),
                "excluded_evidence": excluded_count,
                "rule": "effective_from <= as_of <= effective_to；空边界视为开放区间",
            },
            "answerability": {"supported": False, "reason": gate["reason"]},
            "retriever": {
                "name": "domain-gate",
                "semantic_enabled": False,
                "degraded": False,
                "reason": "领域门拒绝后未调用BM25或语义模型",
            },
        }
    lexical = search_evidence(query, limit=max(limit, 10), as_of=effective_date)
    base: dict[str, object] = {
        "query": query,
        "as_of": effective_date.isoformat(),
        "items": lexical[:limit],
        "domain_gate": gate,
        "temporal_filter": {
            "enabled": True,
            "active_evidence": len(catalog),
            "excluded_evidence": excluded_count,
            "rule": "effective_from <= as_of <= effective_to；空边界视为开放区间",
        },
        "answerability": {
            "supported": bool(lexical),
            "reason": None if lexical else "没有检索到达到最小词项覆盖率的有效期内证据",
        },
        "retriever": {
            "name": "field-weighted-bm25",
            "semantic_enabled": False,
            "degraded": False,
            "reason": None,
        },
    }
    if settings.ai_mode != "hybrid" or not settings.ollama_embedding_model:
        if settings.ai_mode == "hybrid":
            retriever = base["retriever"]
            if not isinstance(retriever, dict):
                raise TypeError("retriever metadata must be a mapping")
            retriever["degraded"] = True
            retriever["reason"] = "未配置OLLAMA_EMBED_MODEL，使用BM25"
        return base

    documents = tuple(
        (
            f"{item.title}\n{item.article or ''}\n{item.verbatim_quote or item.excerpt}\n"
            f"{item.plain_language_explanation or ''}"
        )
        for item in catalog
    )
    try:
        query_vector, document_vectors, model_id, latency_ms, cache_hit = (
            _embed_query_and_documents(query, documents)
        )
    except ModelRuntimeError as exc:
        retriever = base["retriever"]
        if not isinstance(retriever, dict):
            raise TypeError("retriever metadata must be a mapping") from exc
        retriever["degraded"] = True
        retriever["reason"] = f"语义模型不可用，使用BM25：{exc}"
        return base

    semantic_ranked = sorted(
        (
            (item, vector, _cosine(query_vector, vector))
            for item, vector in zip(catalog, document_vectors, strict=True)
        ),
        key=lambda pair: pair[2],
        reverse=True,
    )
    def result_evidence_id(item: dict[str, object]) -> str:
        evidence = item["evidence"]
        if not isinstance(evidence, dict):
            raise TypeError("retrieval item evidence must be a mapping")
        return str(evidence["evidence_id"])

    bm25_rank = {
        result_evidence_id(item): index for index, item in enumerate(lexical, start=1)
    }
    semantic_rank = {
        item.evidence_id: index for index, (item, _, _) in enumerate(semantic_ranked, start=1)
    }
    semantic_similarity = {item.evidence_id: similarity for item, _, similarity in semantic_ranked}
    by_id = {item.evidence_id: item for item in catalog}
    lexical_by_id = {result_evidence_id(item): item for item in lexical}
    fused: list[tuple[float, str]] = []
    for evidence_id in by_id:
        score = 0.0
        if evidence_id in bm25_rank:
            score += 1 / (60 + bm25_rank[evidence_id])
        if evidence_id in semantic_rank:
            score += 1 / (60 + semantic_rank[evidence_id])
        fused.append((score, evidence_id))
    fused.sort(reverse=True)
    items: list[dict[str, object]] = []
    for score, evidence_id in fused:
        lexical_item = lexical_by_id.get(evidence_id, {})
        if evidence_id not in lexical_by_id and semantic_similarity[evidence_id] < 0.55:
            continue
        items.append(
            {
                "score": round(score, 5),
                "bm25_score": lexical_item.get("score", 0.0),
                "semantic_rank": semantic_rank[evidence_id],
                "semantic_similarity": round(semantic_similarity[evidence_id], 4),
                "matched_terms": lexical_item.get("matched_terms", []),
                "match_coverage": lexical_item.get("match_coverage", 0.0),
                "evidence": by_id[evidence_id].model_dump(mode="json"),
            }
        )
        if len(items) >= limit:
            break
    return {
        "query": query,
        "as_of": effective_date.isoformat(),
        "items": items,
        "domain_gate": gate,
        "temporal_filter": base["temporal_filter"],
        "answerability": {
            "supported": bool(items),
            "reason": None if items else "词项与语义相似度均未达到安全回答阈值",
        },
        "retriever": {
            "name": "rrf(bm25,local-embedding)",
            "semantic_enabled": True,
            "degraded": False,
            "reason": None,
            "model_id": model_id,
            "latency_ms": latency_ms,
            "document_embedding_cache_hit": cache_hit,
        },
    }

