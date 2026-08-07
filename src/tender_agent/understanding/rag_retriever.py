import math
import os
import hashlib
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Sequence, Tuple

from loguru import logger
from sqlalchemy import distinct, or_

from data.knowledge.models import Certificate, TemplateSection
from tender_agent.knowledge.section_copier import extract_section_text_from_master
from tender_agent.knowledge.certificate_filters import usable_certificate_filters
from ..core.db import engine, get_db_session

_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}
_INDEX_CACHE_LOCK = threading.RLock()
_INDEX_CACHE_MAX_COMPANIES = 64
_TECH_TEXT_CACHE: Dict[str, str] = {}


def _company_cache_key(company_id: str) -> str:
    return str(company_id or "").strip() or "__shared__"


def _store_cached_indexes(
    company_id: str,
    categories: Sequence[str],
    section_rows: Sequence[Any],
    expires_at: float,
) -> None:
    key = _company_cache_key(company_id)
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[key] = {
            "expires_at": float(expires_at),
            "categories": list(categories),
            "section_rows": list(section_rows),
            "updated_at": time.time(),
        }
        if len(_INDEX_CACHE) > _INDEX_CACHE_MAX_COMPANIES:
            oldest_key = min(
                _INDEX_CACHE,
                key=lambda item: float(_INDEX_CACHE[item].get("updated_at") or 0.0),
            )
            _INDEX_CACHE.pop(oldest_key, None)


def _read_cached_indexes(company_id: str = "") -> Tuple[List[str], List[Any]]:
    key = _company_cache_key(company_id)
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.get(key) or {}
        return list(cached.get("categories") or []), list(cached.get("section_rows") or [])


def _company_scope_filter(model: Any, company_id: str):
    company_id = str(company_id or "").strip()
    if not company_id:
        return model.scope == "shared"
    return or_(model.company_id == company_id, model.scope == "shared")


def _leaf_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for n in nodes:
        children = n.get("children") or []
        if children:
            result.extend(_leaf_nodes(children))
        else:
            result.append(n)
    return result


def _material_index(assignments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {str(a.get("node_id", "")): a.get("materials", []) or [] for a in assignments}


def _get_cached_indexes(db, company_id: str = "") -> Tuple[List[str], List[Any]]:
    now = time.time()
    ttl = int(os.getenv("RAG_INDEX_CACHE_TTL_SEC", "300"))
    key = _company_cache_key(company_id)
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.get(key) or {}
        if now < float(cached.get("expires_at") or 0):
            return list(cached.get("categories") or []), list(cached.get("section_rows") or [])

    categories = [
        r[0]
        for r in db.query(distinct(Certificate.category)).filter(
            *usable_certificate_filters(Certificate),
            _company_scope_filter(Certificate, company_id),
        )
        if r[0]
    ]
    rows = db.query(TemplateSection).filter(
        TemplateSection.is_current == True,
        TemplateSection.deleted_at.is_(None),
        TemplateSection.level <= 4,
        _company_scope_filter(TemplateSection, company_id),
    ).all()
    section_rows = [
        SimpleNamespace(
            chapter_id=r.chapter_id,
            title=r.title,
            full_path=r.full_path,
            keywords=r.keywords,
            start_block_idx=r.start_block_idx,
            end_block_idx=r.end_block_idx,
            metadata_info=getattr(r, "metadata_info", {}) or {},
        )
        for r in rows
    ]
    _store_cached_indexes(company_id, categories, section_rows, now + max(0, ttl))
    return categories, section_rows


def _dispose_db_pool_after_error() -> None:
    try:
        engine.dispose()
    except Exception:
        pass


def _tokens(text: str) -> List[str]:
    if not text:
        return []
    seps = [" ", "-", "_", "/", "，", "。", "（", "）", "(", ")", "、", "：", ":"]
    for s in seps:
        text = text.replace(s, " ")
    raw = [x.strip() for x in text.split() if x.strip()]
    words = []
    for w in raw:
        words.extend([w[i:j] for i in range(len(w)) for j in range(i + 2, min(i + 5, len(w) + 1))])
    words.extend(raw)
    return list(dict.fromkeys(words))


def _score(query: str, doc: str) -> float:
    q = set(_tokens(query))
    d = set(_tokens(doc))
    if not q or not d:
        return 0.0
    inter = len(q & d)
    union = len(q | d)
    return inter / max(union, 1)


def _bm25_rank(query: str, docs: Sequence[str]) -> Dict[int, float]:
    q_tokens = _tokens(query)
    if not q_tokens or not docs:
        return {}
    tokenized = [_tokens(doc) for doc in docs]
    avgdl = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
    df = Counter()
    for tokens in tokenized:
        df.update(set(tokens))

    scores: Dict[int, float] = {}
    k1 = 1.5
    b = 0.75
    n_docs = len(docs)
    for idx, tokens in enumerate(tokenized):
        if not tokens:
            continue
        tf = Counter(tokens)
        doc_len = len(tokens)
        score = 0.0
        for token in q_tokens:
            if token not in tf:
                continue
            idf = math.log(1 + (n_docs - df[token] + 0.5) / (df[token] + 0.5))
            denom = tf[token] + k1 * (1 - b + b * doc_len / max(avgdl, 1))
            score += idf * (tf[token] * (k1 + 1)) / max(denom, 1e-9)
        if score > 0:
            scores[idx] = score
    return scores


def _hashed_vector(tokens: List[str], dims: int = 128) -> List[float]:
    vector = [0.0] * dims
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        vector[int.from_bytes(digest, "big") % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _hybrid_rank(
    query: str,
    items: Sequence[Any],
    text_getter: Callable[[Any], str],
    topk: int = 8,
) -> List[Tuple[Any, Dict[str, float]]]:
    docs = [text_getter(item) for item in items]
    bm25 = _bm25_rank(query, docs)
    q_vec = _hashed_vector(_tokens(query))
    vector_scores = {
        idx: _cosine(q_vec, _hashed_vector(_tokens(doc)))
        for idx, doc in enumerate(docs)
        if doc
    }
    max_bm25 = max(bm25.values(), default=1.0)

    ranked: List[Tuple[Any, Dict[str, float]]] = []
    for idx, item in enumerate(items):
        bm25_norm = bm25.get(idx, 0.0) / max_bm25
        vector = vector_scores.get(idx, 0.0)
        lexical = _score(query, docs[idx])
        if bm25_norm <= 0 and lexical <= 0 and vector < 0.18:
            continue
        hybrid = bm25_norm * 0.70 + lexical * 0.20 + vector * 0.10
        if hybrid <= 0:
            continue
        ranked.append(
            (
                item,
                {
                    "hybrid": round(hybrid, 4),
                    "bm25": round(bm25_norm, 4),
                    "vector": round(vector, 4),
                    "lexical": round(lexical, 4),
                },
            )
        )
    ranked.sort(key=lambda row: row[1]["hybrid"], reverse=True)
    return ranked[:topk]


def _resolve_tech_master_path() -> Path:
    configured = os.getenv("TECH_MASTER_PATH", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path("data/knowledge/master") / "技术文件.docx",
            Path("scripts") / "技术文件.docx",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate

    master_dir = Path("data/knowledge/master")
    if master_dir.exists():
        docx_files = sorted(master_dir.glob("*.docx"))
        for file in docx_files:
            if "技术" in file.name:
                return file
        for file in docx_files:
            if "商务" not in file.name:
                return file
        if docx_files:
            return docx_files[0]
    return Path("data/knowledge/master") / "技术文件.docx"


def _tech_section_text(section: TemplateSection | None) -> str:
    if section is None or not section.chapter_id:
        return ""
    max_chars = int(os.getenv("RAG_TECH_SECTION_CONTENT_CHARS", "6000"))
    meta = getattr(section, "metadata_info", {}) or {}
    master_path = Path(str(meta.get("source_file_path") or "")) if meta.get("source_file_path") else _resolve_tech_master_path()
    key = f"{master_path.resolve() if master_path.exists() else master_path}|{section.chapter_id}|{section.start_block_idx}|{section.end_block_idx}|{max_chars}"
    if key in _TECH_TEXT_CACHE:
        return _TECH_TEXT_CACHE[key]
    try:
        text = extract_section_text_from_master(section, str(master_path), max_chars=max_chars)
    except Exception as exc:
        logger.warning("[rag] extract tech section text failed chapter_id={}: {}", section.chapter_id, str(exc)[:120])
        text = ""
    _TECH_TEXT_CACHE[key] = text
    return text


def _cert_fact(row: Certificate) -> Dict[str, Any]:
    meta = row.metadata_info or {}
    summary = (
        meta.get("summary")
        or meta.get("excerpt")
        or meta.get("ocr_text")
        or meta.get("text")
        or ""
    )
    return {
        "source": "certificate",
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "subcategory": row.subcategory,
        "cert_number": row.cert_number,
        "issuer": row.issuer,
        "issue_date": row.issue_date.isoformat() if row.issue_date else None,
        "expire_date": row.expire_date.isoformat() if row.expire_date else None,
        "file_path": row.file_path,
        "summary": str(summary)[:500],
    }


def _tech_fact(section: TemplateSection | None, chapter_id: str) -> Dict[str, Any]:
    content = _tech_section_text(section)
    return {
        "source": "tech_section",
        "id": str(section.id) if section else None,
        "chapter_id": chapter_id,
        "title": section.title if section else None,
        "full_path": section.full_path if section else None,
        "span": max(0, int(section.end_block_idx or 0) - int(section.start_block_idx or 0)) if section else None,
        "content": content,
        "content_preview": content[:800],
        "note": "技术母版章节",
    }


def _build_material_fact_caches(
    assignments: List[Dict[str, Any]],
    db,
    company_id: str = "",
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
    needed_categories = set()
    needed_chapter_ids = set()
    needed_section_ids = set()
    for assignment in assignments or []:
        for material in assignment.get("materials") or []:
            if not isinstance(material, dict):
                continue
            if material.get("source") == "certificate" and material.get("category") and not material.get("id"):
                needed_categories.add(str(material.get("category")))
            if material.get("source") == "tech_section" and material.get("chapter_id"):
                needed_chapter_ids.add(str(material.get("chapter_id")))
                if material.get("section_id"):
                    needed_section_ids.add(str(material.get("section_id")))

    cert_cache: Dict[str, List[Dict[str, Any]]] = {}
    if needed_categories:
        rows = (
            db.query(Certificate)
            .filter(
                *usable_certificate_filters(Certificate),
                Certificate.category.in_(list(needed_categories)),
                _company_scope_filter(Certificate, company_id),
            )
            .order_by(Certificate.category.asc(), Certificate.updated_at.desc())
            .all()
        )
        for row in rows:
            cert_cache.setdefault(row.category, []).append(_cert_fact(row))

    tech_cache: Dict[str, Dict[str, Any]] = {}
    if needed_chapter_ids or needed_section_ids:
        rows = (
            db.query(TemplateSection)
            .filter(
                or_(
                    TemplateSection.id.in_(list(needed_section_ids)),
                    TemplateSection.chapter_id.in_(list(needed_chapter_ids)),
                ),
                TemplateSection.is_current == True,
                TemplateSection.deleted_at.is_(None),
                _company_scope_filter(TemplateSection, company_id),
            )
            .order_by(TemplateSection.start_block_idx.asc())
            .all()
        )
        for row in rows:
            if not row.chapter_id:
                continue
            fact = _tech_fact(row, row.chapter_id)
            tech_cache[f"id:{row.id}"] = fact
            chapter_key = f"chapter:{row.chapter_id}"
            current = tech_cache.get(chapter_key)
            if current is None or (company_id and str(row.company_id or "") == company_id):
                tech_cache[chapter_key] = fact
    return cert_cache, tech_cache


def _material_facts_from_db(
    node_materials: List[Dict[str, Any]],
    cert_cache: Dict[str, List[Dict[str, Any]]],
    tech_cache: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    for m in node_materials:
        if m.get("source") == "certificate":
            if m.get("id") or m.get("name") or m.get("file_path"):
                facts.append(
                    {
                        "source": "certificate",
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "category": m.get("category"),
                        "subcategory": m.get("subcategory"),
                        "cert_number": m.get("cert_number"),
                        "issuer": m.get("issuer"),
                        "issue_date": m.get("issue_date"),
                        "expire_date": m.get("expire_date"),
                        "file_path": m.get("file_path"),
                        "file_type": m.get("file_type"),
                        "summary": str(m.get("summary") or "")[:500],
                    }
                )
                continue
            category = str(m.get("category", "")).strip()
            if not category:
                continue
            max_count = int(m.get("max_count") or 3)
            facts.extend((cert_cache.get(category) or [])[: max(1, min(max_count, 8))])
        elif m.get("source") == "tech_section":
            chapter_id = str(m.get("chapter_id", "")).strip()
            if not chapter_id:
                continue
            section_id = str(m.get("section_id") or "").strip()
            facts.append(
                tech_cache.get(f"id:{section_id}")
                or tech_cache.get(f"chapter:{chapter_id}")
                or _tech_fact(None, chapter_id)
            )
        elif m.get("source") == "manual":
            facts.append({
                "source": "manual",
                "note": str(m.get("note", "请人工补充")),
            })

    dedup: Dict[str, Dict[str, Any]] = {}
    for f in facts:
        key = f"{f.get('source')}|{f.get('id') or f.get('chapter_id') or f.get('note')}"
        dedup[key] = f
    return list(dedup.values())


def _assigned_material_hits(materials: List[Dict[str, Any]], material_facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for material in materials or []:
        if not isinstance(material, dict):
            continue
        source = str(material.get("source") or "")
        if source == "certificate":
            hits.append(
                {
                    "source": "certificate",
                    "name": material.get("name") or material.get("category"),
                    "category": material.get("category"),
                    "confidence": 1.0,
                    "reason": "material_mapper_assignment",
                }
            )
        elif source == "tech_section":
            hits.append(
                {
                    "source": "tech_section",
                    "name": material.get("title") or material.get("chapter_id"),
                    "chapter_id": material.get("chapter_id"),
                    "confidence": 1.0,
                    "reason": "material_mapper_assignment",
                }
            )
        elif source == "manual":
            hits.append(
                {
                    "source": "manual",
                    "name": material.get("note") or "人工补充",
                    "confidence": 0.0,
                    "reason": "manual_required",
                }
            )

    for fact in material_facts or []:
        if fact.get("source") == "certificate":
            hits.append(
                {
                    "source": "certificate",
                    "name": fact.get("name"),
                    "category": fact.get("category"),
                    "confidence": 1.0,
                    "reason": "material_fact",
                }
            )
        elif fact.get("source") == "tech_section":
            hits.append(
                {
                    "source": "tech_section",
                    "name": fact.get("title") or fact.get("chapter_id"),
                    "chapter_id": fact.get("chapter_id"),
                    "confidence": 1.0,
                    "reason": "material_fact",
                }
            )
    return _dedupe_hits(hits)


def _candidate_hits(
    cert_ranked_rows: List[Tuple[Any, Dict[str, float]]],
    tech_ranked_rows: List[Tuple[Any, Dict[str, float]]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for category, score in cert_ranked_rows[:limit]:
        hits.append(
            {
                "source": "certificate_category",
                "name": str(category),
                "category": str(category),
                "confidence": score.get("hybrid", 0.0),
                "scores": score,
                "reason": "hybrid_retrieval_candidate",
            }
        )
    for section, score in tech_ranked_rows[:limit]:
        hits.append(
            {
                "source": "tech_section_candidate",
                "name": section.title,
                "chapter_id": section.chapter_id,
                "full_path": section.full_path,
                "confidence": score.get("hybrid", 0.0),
                "scores": score,
                "reason": "hybrid_retrieval_candidate",
            }
        )
    hits.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    return _dedupe_hits(hits)[:limit]


def _dedupe_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dedup: Dict[str, Dict[str, Any]] = {}
    for hit in hits:
        key = f"{hit.get('source')}|{hit.get('category') or hit.get('chapter_id') or hit.get('name')}"
        if key not in dedup or float(hit.get("confidence") or 0) > float(dedup[key].get("confidence") or 0):
            dedup[key] = hit
    return list(dedup.values())


def _build_retrieval_summary(rag_contexts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    assigned_count = 0
    fact_count = 0
    high_confidence_count = 0

    for node_id, ctx in rag_contexts.items():
        materials = ctx.get("materials") or []
        facts = ctx.get("material_facts") or []
        assigned_hits = _assigned_material_hits(materials, facts)
        candidate_hits = []
        for item in (ctx.get("scores") or {}).get("cert", [])[:3]:
            candidate_hits.append(
                {
                    "source": "certificate_category",
                    "name": item.get("name"),
                    "category": item.get("name"),
                    "confidence": item.get("hybrid", 0.0),
                    "reason": "hybrid_retrieval_candidate",
                }
            )
        for item in (ctx.get("scores") or {}).get("tech", [])[:3]:
            candidate_hits.append(
                {
                    "source": "tech_section_candidate",
                    "name": item.get("title"),
                    "chapter_id": item.get("chapter_id"),
                    "confidence": item.get("hybrid", 0.0),
                    "reason": "hybrid_retrieval_candidate",
                }
            )
        top_hits = _dedupe_hits(assigned_hits + candidate_hits)
        top_hits.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        confidence = float(ctx.get("confidence") or 0)
        if assigned_hits:
            assigned_count += 1
            confidence = max(confidence, 1.0)
        if facts:
            fact_count += 1
        if confidence >= 0.6:
            high_confidence_count += 1
        nodes.append(
            {
                "node_id": node_id,
                "node_name": ctx.get("node_name"),
                "has_assignment": bool(materials),
                "material_count": len(materials),
                "material_fact_count": len(facts),
                "confidence": round(confidence, 4),
                "retrieval_method": ctx.get("retrieval_method"),
                "top_hits": top_hits[:6],
            }
        )

    return {
        "nodes": nodes,
        "stats": {
            "total_nodes": len(nodes),
            "assigned_nodes": assigned_count,
            "fact_nodes": fact_count,
            "high_confidence_nodes": high_confidence_count,
        },
    }


async def build_rag_contexts(state: Dict[str, Any]) -> Dict[str, Any]:
    outline = state.get("final_outline") or state.get("outline") or []
    assignments = state.get("material_assignments") or []
    company_id = str(state.get("company_id") or "").strip()
    logger.info("[rag] start building contexts")
    if not outline:
        return {"rag_contexts": {}, "warnings": ["[rag] empty outline"]}

    leaves = _leaf_nodes(outline)
    assignment_map = _material_index(assignments)

    categories: List[str] = []
    section_rows: List[Any] = []
    cert_fact_cache: Dict[str, List[Dict[str, Any]]] = {}
    tech_fact_cache: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    db = None
    try:
        db = next(get_db_session())
        categories, section_rows = _get_cached_indexes(db, company_id=company_id)
        cert_fact_cache, tech_fact_cache = _build_material_fact_caches(assignments, db, company_id=company_id)
    except Exception as exc:
        _dispose_db_pool_after_error()
        categories, section_rows = _read_cached_indexes(company_id)
        cache_note = f"，使用缓存索引 categories={len(categories)}, tech={len(section_rows)}" if categories or section_rows else ""
        warnings.append(f"[rag] 数据库不可用，降级关键词匹配{cache_note}: {str(exc)[:80]}")

    rag_contexts: Dict[str, Dict[str, Any]] = {}
    try:
        for leaf in leaves:
            node_id = str(leaf.get("id", ""))
            node_name = str(leaf.get("name", ""))
            materials = assignment_map.get(node_id, [])

            cert_ranked_rows = _hybrid_rank(node_name, categories, lambda c: str(c), topk=8)
            tech_ranked_rows = _hybrid_rank(
                node_name,
                section_rows,
                lambda s: f"{s.chapter_id or ''} {s.title or ''} {s.full_path or ''} {' '.join(s.keywords or [])}",
                topk=8,
            )

            cert_candidates = [c for c, _ in cert_ranked_rows]
            tech_candidates = [
                {
                    "chapter_id": s.chapter_id,
                    "title": s.title,
                    "full_path": s.full_path,
                    "span": max(0, int(s.end_block_idx or 0) - int(s.start_block_idx or 0)),
                    "content_preview": _tech_section_text(s)[:800],
                }
                for s, _ in tech_ranked_rows
            ]
            score_values = [score["hybrid"] for _, score in cert_ranked_rows + tech_ranked_rows]
            confidence = max(score_values) if score_values else 0.0

            material_facts: List[Dict[str, Any]] = []
            if db is not None:
                try:
                    material_facts = _material_facts_from_db(materials, cert_fact_cache, tech_fact_cache)
                except Exception as exc:
                    warnings.append(f"[rag] material facts failed node={node_id}: {str(exc)[:80]}")

            context = {
                "node_id": node_id,
                "node_name": node_name,
                "materials": materials,
                "material_facts": material_facts,
                "cert_candidates": cert_candidates,
                "tech_candidates": tech_candidates,
                "scores": {
                    "cert": [{"name": c, **score} for c, score in cert_ranked_rows],
                    "tech": [
                        {
                            "chapter_id": s.chapter_id,
                            "title": s.title,
                            **score,
                        }
                        for s, score in tech_ranked_rows
                    ],
                },
                "retrieval_method": "hybrid_bm25_hash_vector_rerank",
                "confidence": round(confidence, 4),
            }
            context["top_hits"] = _dedupe_hits(
                _assigned_material_hits(materials, material_facts)
                + _candidate_hits(cert_ranked_rows, tech_ranked_rows)
            )[:8]
            rag_contexts[node_id] = context
    finally:
        if db is not None:
            db.close()

    retrieval_summary = _build_retrieval_summary(rag_contexts)
    logger.info(
        "[rag] done, leaves={}, contexts={}, assigned={}, fact_nodes={}, high_conf={}",
        len(leaves),
        len(rag_contexts),
        retrieval_summary["stats"]["assigned_nodes"],
        retrieval_summary["stats"]["fact_nodes"],
        retrieval_summary["stats"]["high_confidence_nodes"],
    )
    return {"rag_contexts": rag_contexts, "retrieval_summary": retrieval_summary, "warnings": warnings}
