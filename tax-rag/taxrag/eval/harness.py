"""Evaluation harness. Scores retrieval, citations, jurisdiction/year/version accuracy, faithfulness and completeness
separately. Nothing here scores whether prose 'sounds right'."""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

import yaml

from ..answer import run_mode
from ..store import Store

GOLD_PATH = Path(__file__).with_name("gold.yaml")


def _doc_match(store: Store, exp: dict) -> set[str]:
    docs = store.find_documents(jurisdiction=exp.get("jurisdiction"), document_type=exp.get("document_type"),
                                form_number=exp.get("form_number"), schedule=exp.get("schedule"), publication_number=exp.get("publication_number"))
    return {d["document_id"] for d in docs}


def score_item(store: Store, item: dict, out: dict) -> dict:
    exp = item.get("expected", {})
    ev = out.get("evidence", [])
    top5 = ev[:5]
    m: dict = {}
    # document retrieval
    exp_docs = set()
    for d in exp.get("documents", []):
        exp_docs |= _doc_match(store, d)
    got_docs = [e["document_id"] for e in ev]
    m["doc_hit@1"] = bool(exp_docs) and got_docs[:1] and got_docs[0] in exp_docs
    m["doc_hit@5"] = bool(exp_docs) and any(d in exp_docs for d in got_docs[:5])
    m["doc_expected_indexed"] = bool(exp_docs)
    # chunk/section retrieval: path fragment or page
    frags = [f.lower() for f in exp.get("path_contains", [])]
    pages = exp.get("pages", [])
    def chunk_ok(e):
        ok_path = any(f in e["path_text"].lower() for f in frags) if frags else True
        ok_page = any(abs(e["page_start"] - p) <= 1 for p in pages) if pages else True
        ok_doc = (e["document_id"] in exp_docs) if exp_docs else True
        return ok_doc and ok_path and ok_page
    m["chunk_hit@1"] = bool(ev) and chunk_ok(ev[0])
    m["chunk_hit@5"] = any(chunk_ok(e) for e in top5)
    # citation accuracy: first citation points to expected doc and page (±1)
    cits = out.get("citations", [])
    m["citation_ok"] = bool(cits) and chunk_ok(ev[0]) if ev else False
    # jurisdiction / year / version
    if exp.get("jurisdiction"):
        m["jurisdiction_ok"] = all(e["jurisdiction"] == exp["jurisdiction"] for e in top5) if top5 else False
    if exp.get("tax_year"):
        m["tax_year_ok"] = all(e["tax_year"] in (exp["tax_year"], None) for e in top5) if top5 else False
    if exp.get("draft_or_final"):
        m["version_ok"] = all(e["draft_or_final"] == exp["draft_or_final"] for e in top5) if top5 else False
    if exp.get("years_both"):
        yrs = {e["tax_year"] for e in ev}
        m["both_years_retrieved"] = set(exp["years_both"]) <= yrs
    # abstention
    if exp.get("answer_type") == "insufficient_evidence":
        m["abstained_correctly"] = (not out.get("sufficient_evidence")) or bool((out.get("answer") or {}).get("insufficient"))
    else:
        m["answered"] = bool(out.get("sufficient_evidence"))
    # faithfulness: validated claim ratio (LLM) or 1.0 for extractive (verbatim)
    ans = out.get("answer") or {}
    claims = ans.get("claims", [])
    if claims:
        good = sum(1 for c in claims if c["label"] in ("explicit", "derived"))
        m["faithfulness"] = round(good / len(claims), 3)
        m["explicit_ratio"] = round(sum(1 for c in claims if c["label"] == "explicit") / len(claims), 3)
    # completeness: expected phrases present in evidence text (not in the prose)
    phrases = exp.get("must_mention", [])
    if phrases:
        blob = " ".join(e["text"] for e in top5).lower()
        hits = sum(1 for p in phrases if p.lower() in blob)
        m["completeness"] = round(hits / len(phrases), 3)
    if exp.get("changes_expected"):
        m["changes_found"] = bool(out.get("changes"))
    return m


def run_eval(store: Store, strategy: str | None = None, gold_path: Path | None = None, use_llm: bool = False, limit: int | None = None) -> dict:
    gold = yaml.safe_load((gold_path or GOLD_PATH).read_text())
    items = gold["questions"][:limit] if limit else gold["questions"]
    run_id = "eval_" + uuid.uuid4().hex[:8]
    results = []
    for it in items:
        store.upsert_eval_question({"qid": it["id"], "category": it["category"], "question": it["question"], "mode": it.get("mode", "research"),
                                    "expected": it.get("expected", {}), "reviewer": it.get("reviewer"), "notes": it.get("notes")})
        t = time.perf_counter()
        out = run_mode(store, it["question"], mode=it.get("mode", "research"), jurisdiction=it.get("jurisdiction"), tax_year=it.get("tax_year"),
                       draft_filter=it.get("draft_filter"), strategy=strategy, use_llm=use_llm)
        ms = (time.perf_counter() - t) * 1000
        metrics = score_item(store, it, out)
        store.add_eval_result(run_id, it["id"], strategy or "default", metrics, ms)
        results.append({"id": it["id"], "category": it["category"], "question": it["question"], "metrics": metrics, "latency_ms": round(ms),
                        "top": [f"{e['jurisdiction']} {e['tax_year']} {e['draft_or_final']} {e['path_text'][-70:]} p.{e['page_start']}" for e in out.get("evidence", [])[:3]]})
    # aggregate
    agg: dict[str, list] = {}
    for r in results:
        for k, v in r["metrics"].items():
            if isinstance(v, bool):
                agg.setdefault(k, []).append(1.0 if v else 0.0)
            elif isinstance(v, (int, float)):
                agg.setdefault(k, []).append(float(v))
    summary = {k: {"mean": round(sum(v) / len(v), 3), "n": len(v)} for k, v in sorted(agg.items())}
    by_cat: dict[str, list] = {}
    for r in results:
        m = r["metrics"]
        primary = m["abstained_correctly"] if "abstained_correctly" in m else m["changes_found"] if "changes_found" in m else m.get("chunk_hit@5", False)
        by_cat.setdefault(r["category"], []).append(primary)
    summary["by_category_primary"] = {c: round(sum(1 for x in v if x) / len(v), 3) for c, v in by_cat.items()}
    summary["strategy"] = strategy
    summary["run_id"] = run_id
    summary["mean_latency_ms"] = round(sum(r["latency_ms"] for r in results) / max(1, len(results)))
    return {"summary": summary, "results": results}
