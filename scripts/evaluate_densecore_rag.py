"""Real HTTP upload/retrieval and PostgreSQL quality evaluation on a disposable DB.

Run with the same EMBEDDING_* environment as the test API. No mocked vectors or
answer LLM are used. The fixture is synthetic; this is a small retrieval probe,
not a benchmark of Korean language understanding or answer correctness.
"""
import argparse
import asyncio
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.modules.documents.embedding import QWEN_RETRIEVAL_INSTRUCTION, embed_query, embed_texts


def measure(ranked, relevant):
    rank = next((i for i, section in enumerate(ranked, 1) if section in relevant), None)
    return {
        "reciprocal_rank": 1 / rank if rank else 0,
        **{f"hit@{k}": float(bool(set(ranked[:k]) & relevant)) for k in (1, 3, 6)},
        **{f"recall@{k}": len(set(ranked[:k]) & relevant) / len(relevant) for k in (1, 3, 6)},
    }


def average(rows):
    return {key: statistics.mean(row[key] for row in rows) for key in rows[0]} if rows else {}


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right)) / (math.hypot(*left) * math.hypot(*right))


def compare_reference(path, fixture, vectors):
    reference = json.loads(path.read_text())
    ref = {row["id"]: row for row in reference["items"]}
    actual = {row["id"]: row for row in vectors}
    similarities = []
    deltas = []
    for key, row in actual.items():
        assert ref[key]["text"] == row["text"], key
        assert len(ref[key]["embedding"]) == len(row["embedding"]) == 1024
        similarities.append(cosine(ref[key]["embedding"], row["embedding"]))
        deltas.append(max(abs(a - b) for a, b in zip(ref[key]["embedding"], row["embedding"])))
    measurements = []
    rankings = []
    for case in fixture["queries"]:
        ranked = sorted(fixture["sections"], key=lambda section: -cosine(ref[case["id"]]["embedding"], ref[section["id"]]["embedding"]))
        ids = [section["id"] for section in ranked]
        rankings.append({"id": case["id"], "ranking": ids})
        if case["relevant_sections"]:
            measurements.append(measure(ids, set(case["relevant_sections"])))
    return {"metadata": reference["metadata"], "reference_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "vector_pairs": len(similarities), "cosine_min": min(similarities), "cosine_mean": statistics.mean(similarities),
            "cosine_max": max(similarities), "max_absolute_component_delta": max(deltas),
            "reference_retrieval": average(measurements), "reference_rankings": rankings,
            "scope": "Q8 DenseCore versus official full-precision Transformers; diagnostic agreement, not bitwise parity"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:18082")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/densecore_rag_quality.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--document-id", type=int, help="Reuse this test upload when repeating evaluation")
    parser.add_argument("--reference-vectors", type=Path, help="Optional official Transformers vectors for these exact inputs")
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    # Never target a normal application database with this upload/evaluation tool.
    if engine.url.database != "densecore_rag_e2e" or settings.embedding_provider != "densecore":
        raise SystemExit("Requires disposable database densecore_rag_e2e and EMBEDDING_PROVIDER=densecore")
    fixture = json.loads(args.fixture.read_text())
    sections = {row["title"]: row["id"] for row in fixture["sections"]}
    document = "\n\n".join(f'# {row["title"]}\n\n{row["text"]}' for row in fixture["sections"])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "document.md").write_text(document)
    started = time.perf_counter()
    with httpx.Client(base_url=args.api_url, timeout=120) as client:
        if args.document_id is None:
            with engine.connect() as connection:
                if connection.scalar(text("SELECT count(*) FROM documents")):
                    raise SystemExit("Use an empty test DB or --document-id to reuse the existing test upload")
            response = client.post("/api/documents", data={"title": "합성 개인 기록 검색 평가", "categories": '["career","financial","health"]'},
                                   files={"file": ("synthetic-personal-records.md", document.encode(), "text/markdown")})
            response.raise_for_status()
            uploaded = response.json()
            (args.output / "upload.json").write_text(json.dumps(uploaded, ensure_ascii=False, indent=2))
            document_id = uploaded["id"]
        else:
            document_id = args.document_id
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = client.get("/api/documents")
            response.raise_for_status()
            current = next(row for row in response.json() if row["id"] == document_id)
            if current["status"] == "ready":
                break
            if current["status"] == "failed":
                raise RuntimeError(f'Indexing failed: {current["error"]}')
            time.sleep(1)
        else:
            raise TimeoutError("Indexing did not finish in 600 seconds")
        index_seconds = time.perf_counter() - started
        version_id = current["active_version_id"]
        with engine.connect() as connection:
            version = dict(connection.execute(text("SELECT embedding_model, embedding_dimensions, status, content_hash FROM document_versions WHERE id=:id"), {"id": version_id}).mappings().one())
            stored = [dict(row) for row in connection.execute(text("SELECT id, ordinal, section, embedding::text AS vector, text FROM document_chunks WHERE version_id=:id ORDER BY ordinal"), {"id": version_id}).mappings()]
        assert len(stored) == len(fixture["sections"]), (len(stored), len(fixture["sections"]))
        vectors = [json.loads(row["vector"]) for row in stored]
        assert all(len(vector) == 1024 and all(math.isfinite(x) for x in vector) and abs(math.hypot(*vector) - 1) < 1e-4 for vector in vectors)
        assert version["embedding_model"] == settings.embedding_model and version["embedding_dimensions"] == 1024
        assert version["content_hash"] == hashlib.sha256(document.encode()).hexdigest()
        regenerated = asyncio.run(embed_texts([stored[0]["text"]]))[0]
        storage_max_delta = max(abs(a - b) for a, b in zip(regenerated, vectors[0]))
        assert storage_max_delta < 1e-4, storage_max_delta
        vector_evidence = [{"id": sections[row["section"]], "text": row["text"], "embedding": vector}
                           for row, vector in zip(stored, vectors)]
        (args.output / "vectors.json").write_text(json.dumps(vector_evidence, ensure_ascii=False))
        source = client.get(f'/api/documents/chunks/{stored[0]["id"]}')
        source.raise_for_status()
        assert source.json()["text"] == stored[0]["text"]
        rows = []
        for case in fixture["queries"]:
            query_started = time.perf_counter()
            vector = embed_query(case["query"])
            vector_evidence.append({"id": case["id"], "query": case["query"],
                                    "text": f'Instruct: {QWEN_RETRIEVAL_INSTRUCTION}\nQuery:{case["query"]}', "embedding": vector})
            (args.output / "vectors.json").write_text(json.dumps(vector_evidence, ensure_ascii=False))
            with engine.connect() as connection:
                ranked = [dict(row) for row in connection.execute(text("SELECT id, section, 1-(embedding <=> CAST(:vector AS vector)) AS cosine FROM document_chunks WHERE version_id=:id ORDER BY embedding <=> CAST(:vector AS vector), id"), {"id": version_id, "vector": json.dumps(vector)}).mappings()]
            vector_seconds = time.perf_counter() - query_started
            query_started = time.perf_counter()
            response = client.post("/api/advisor/context/preview", json={"message": case["query"], "categories": ["career", "financial", "health"], "document_search": True})
            response.raise_for_status()
            preview = response.json()
            assert not any(flag["code"] == "document_embedding_unavailable" for flag in preview["data_quality_flags"])
            citations = preview["document_citations"]
            assert all(row["document_id"] == document_id and row["version_id"] == version_id for row in citations)
            relevant = set(case["relevant_sections"])
            raw_sections = [sections[row["section"]] for row in ranked]
            api_sections = [sections[row["section"]] for row in citations]
            row = {**case, "vector_ranking": [{"section": sections[r["section"]], "cosine": r["cosine"]} for r in ranked],
                   "api_ranking": api_sections, "api_flags": preview["data_quality_flags"],
                   "vector_query_seconds": vector_seconds, "api_query_seconds": time.perf_counter() - query_started}
            if relevant:
                row.update(vector_metrics=measure(raw_sections, relevant), api_metrics=measure(api_sections, relevant))
            rows.append(row)
            (args.output / "queries.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print(f'{case["id"]}: vector={raw_sections[:3]} api={api_sections[:3]}', flush=True)
        # Explicit sharing must override a matching vector.
        response = client.patch(f"/api/documents/{document_id}", json={"sharing_enabled": False})
        response.raise_for_status()
        response = client.post("/api/advisor/context/preview", json={"message": fixture["queries"][0]["query"], "categories": ["career", "financial", "health"]})
        response.raise_for_status()
        assert not response.json()["document_citations"]
        response = client.patch(f"/api/documents/{document_id}", json={"sharing_enabled": True})
        response.raise_for_status()
    answerable = [row for row in rows if row["relevant_sections"]]
    negatives = [row for row in rows if not row["relevant_sections"]]
    report = {
        "scope": "One synthetic Korean document; retrieval only; no answer-generation or production-data evaluation",
        "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        "document_sha256": hashlib.sha256(document.encode()).hexdigest(),
        "provider": settings.embedding_provider, "model": settings.embedding_model,
        "loaded_model_id": settings.embedding_densecore_model_id,
        "document_id": document_id, "version_id": version_id, "chunks": len(stored), "dimensions": 1024,
        "unit_norm_min": min(math.hypot(*vector) for vector in vectors), "unit_norm_max": max(math.hypot(*vector) for vector in vectors),
        "stored_vector_regeneration_max_delta": storage_max_delta,
        "upload_to_ready_seconds": index_seconds if args.document_id is None else None,
        "reused_document": args.document_id is not None,
        "answerable_queries": len(answerable), "unanswerable_queries": len(negatives),
        "vector": average([row["vector_metrics"] for row in answerable]),
        "api_hybrid": average([row["api_metrics"] for row in answerable]),
        "by_kind": {kind: {"count": len(group := [r for r in answerable if r["kind"] == kind]),
                            "vector": average([r["vector_metrics"] for r in group]), "api_hybrid": average([r["api_metrics"] for r in group])}
                    for kind in sorted({row["kind"] for row in answerable})},
        "unanswerable_with_citations": sum(bool(row["api_ranking"]) for row in negatives),
        "api_latency_seconds": {"median": statistics.median(row["api_query_seconds"] for row in rows), "max": max(row["api_query_seconds"] for row in rows)},
        "checks": {"http_upload": args.document_id is None, "postgresql_vector_storage": True, "chunk_source_api": True, "privacy_exclusion": True},
    }
    if args.reference_vectors:
        report["reference_comparison"] = compare_reference(args.reference_vectors, fixture, vector_evidence)
    (args.output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
