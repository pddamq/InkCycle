"""全书语义检索：分块 + TF-IDF 向量（纯 Python，无额外依赖）。"""
import json
import math
import re
from collections import Counter

from . import db

CHUNK_SIZE = 480
CHUNK_OVERLAP = 80
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _chunk_text(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - CHUNK_OVERLAP)
    return chunks


def _tfidf_vec(tokens: list[str], df: dict, n_docs: int) -> dict:
    tf = Counter(tokens)
    total = sum(tf.values()) or 1
    vec = {}
    for t, c in tf.items():
        idf = math.log((n_docs + 1) / (df.get(t, 0) + 1)) + 1
        vec[t] = (c / total) * idf
    return vec


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) | set(b))
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def index_project(project_id: int, chapter_id: int | None = None) -> int:
    """重建项目（或单章）文本块索引。返回写入块数。"""
    where = "c.project_id=? AND c.current_version_id IS NOT NULL"
    args: list = [project_id]
    if chapter_id:
        where += " AND c.id=?"
        args.append(chapter_id)
        db.execute("DELETE FROM text_chunks WHERE project_id=? AND chapter_id=?", (project_id, chapter_id))
    else:
        db.execute("DELETE FROM text_chunks WHERE project_id=?", (project_id,))

    rows = db.query(
        f"""SELECT c.id AS chapter_id, c.title, v.content
            FROM chapters c
            JOIN chapter_versions v ON v.id=c.current_version_id
            WHERE {where}
            ORDER BY c.volume_id, c.idx""",
        tuple(args),
    )
    now = db.now()
    n = 0
    for row in rows:
        for i, chunk in enumerate(_chunk_text(row["content"] or "")):
            db.execute(
                "INSERT INTO text_chunks(project_id, chapter_id, ref_type, ref_id, title, chunk_idx, content, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (project_id, row["chapter_id"], "chapter", row["chapter_id"],
                 row["title"] or "", i, chunk, now),
            )
            n += 1
    _rebuild_vectors(project_id, chapter_id)
    return n


def _rebuild_vectors(project_id: int, chapter_id: int | None = None) -> None:
    where = "project_id=?"
    args: list = [project_id]
    if chapter_id:
        where += " AND chapter_id=?"
        args.append(chapter_id)
    chunks = db.query(f"SELECT id, content FROM text_chunks WHERE {where}", tuple(args))
    if not chunks:
        return
    docs = [_tokens(c["content"]) for c in chunks]
    df: dict[str, int] = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n_docs = len(docs)
    for row, toks in zip(chunks, docs):
        vec = _tfidf_vec(toks, df, n_docs)
        db.execute("UPDATE text_chunks SET tfidf=? WHERE id=?", (json.dumps(vec, ensure_ascii=False), row["id"]))


def semantic_search(project_id: int, query: str, limit: int = 8, exclude_chapter_id: int | None = None) -> list[dict]:
    qtok = _tokens(query)
    if not qtok:
        return []
    chunks = db.query(
        "SELECT id, chapter_id, title, content, tfidf FROM text_chunks WHERE project_id=?",
        (project_id,),
    )
    if not chunks:
        index_project(project_id)
        chunks = db.query(
            "SELECT id, chapter_id, title, content, tfidf FROM text_chunks WHERE project_id=?",
            (project_id,),
        )
    df: dict[str, int] = {}
    for c in chunks:
        for t in set(_tokens(c["content"])):
            df[t] = df.get(t, 0) + 1
    qvec = _tfidf_vec(qtok, df, len(chunks) or 1)
    hits = []
    for c in chunks:
        if exclude_chapter_id and c["chapter_id"] == exclude_chapter_id:
            continue
        vec = db.jload(c.get("tfidf"), {})
        score = _cosine(qvec, vec)
        if query in (c["content"] or ""):
            score += 0.35
        if score <= 0.01:
            continue
        snippet = (c["content"] or "").replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "…"
        hits.append({
            "chapter_id": c["chapter_id"],
            "title": c["title"],
            "snippet": snippet,
            "score": round(score, 4),
        })
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:limit]
