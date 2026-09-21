"""Unit tests for analytics/evaluate.py: metrics, keyword baseline, chunker and fixture integrity.

Run from the repo root with the analytics environment:  pytest tests/analytics
The chunker tests load the pinned MiniLM tokenizer (downloaded once from the Hugging Face Hub, then cached).
"""
import csv
import math
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics"))
import evaluate as ev  # noqa: E402

FIXTURES = ROOT / "data" / "evaluation"


@pytest.fixture(scope="module")
def counter():
    from transformers import AutoTokenizer
    name = "sentence-transformers/all-MiniLM-L6-v2"
    return ev.TokenCounter(AutoTokenizer.from_pretrained(name, revision=ev.PINNED_REVISIONS[name]))


# ---- metrics ----

def test_precision_at_k_strict_and_lenient():
    labels = {"A": 2, "B": 1, "C": 0, "D": 2, "E": 0, "F": 2}
    ranked = ["A", "B", "C", "D", "E"]
    assert ev.precision_at_k(ranked, labels, 5, 2) == 2 / 5
    assert ev.precision_at_k(ranked, labels, 5, 1) == 3 / 5
    assert ev.precision_ceiling(labels, 5, 2) == 3 / 5
    assert ev.precision_ceiling({"A": 2, "B": 0}, 5, 2) == 1 / 5


def test_ndcg_known_value_and_perfect_ranking():
    labels = {"A": 2, "B": 1, "C": 0, "D": 0, "E": 0, "F": 2}
    dcg = 1 / math.log2(2) + 2 / math.log2(3)          # ranked B, A, C, D, E
    ideal = 2 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert ev.ndcg_at_k(["B", "A", "C", "D", "E"], labels, 5) == pytest.approx(dcg / ideal)
    assert ev.ndcg_at_k(["A", "F", "B", "C", "D"], labels, 5) == pytest.approx(1.0)


def test_rank_jobs_breaks_ties_by_job_id():
    assert ev.rank_jobs({"J3": 0.5, "J1": 0.5, "J2": 0.9}) == ["J2", "J1", "J3"]


# ---- keyword baseline ----

def test_bm25_prefers_docs_with_rare_query_terms_and_zero_without_overlap():
    docs = {"a": ev.keyword_tokens("python flask api"), "b": ev.keyword_tokens("marketing seo content"),
            "c": ev.keyword_tokens("python data analysis")}
    s = ev.bm25_rank_scores({"flask", "python"}, docs)
    assert s["a"] > s["c"] > s["b"] == 0.0


def test_keyword_tokens_keep_c_plus_plus_and_drop_stopwords():
    assert ev.keyword_tokens("Built the C++ and C# apps") == ["built", "c++", "c#", "apps"]


# ---- chunker ----

def _body(chunk, heading):
    assert chunk.startswith(heading + "\n")
    return chunk[len(heading) + 1:]


def test_short_entry_is_one_chunk_with_heading_and_technologies(counter):
    chunks = ev.chunk_entry(counter, "Project: Demo", "Built an API. Wrote tests.", ["Python", "pytest"])
    assert len(chunks) == 1
    assert chunks[0] == "Project: Demo\nBuilt an API. Wrote tests. Technologies: Python, pytest."


def test_long_entry_splits_by_sentence_keeps_heading_and_loses_nothing(counter):
    sentences = [f"Sentence number {i} describes work on the data pipeline in some detail today." for i in range(80)]
    heading = "Experience: Long role"
    chunks = ev.chunk_entry(counter, heading, "\n".join(f"- {s}" for s in sentences))
    assert len(chunks) > 1
    assert all(counter.count(c) <= ev.MAX_TOKENS for c in chunks)
    assert all(c.startswith(heading + "\n") for c in chunks)
    rebuilt = " ".join(_body(c, heading) for c in chunks)
    assert rebuilt == " ".join(sentences)                      # order preserved, each sentence exactly once


def test_single_overlong_sentence_is_split_at_token_boundaries_without_loss(counter):
    words = [f"word{i}" for i in range(900)]
    sentence = " ".join(words)                                   # no sentence punctuation at all
    heading = "Project: Huge"
    chunks = ev.chunk_entry(counter, heading, sentence)
    assert len(chunks) > 3
    assert all(counter.count(c) <= ev.MAX_TOKENS for c in chunks)
    assert all(c.startswith(heading + "\n") for c in chunks)
    squashed = lambda s: re.sub(r"\s+", "", s)                   # noqa: E731
    assert squashed("".join(_body(c, heading) for c in chunks)) == squashed(sentence)


def test_heading_that_leaves_no_room_raises_instead_of_truncating(counter):
    heading = "Project: " + " ".join(["averyveryverylongheadingword"] * 60)
    with pytest.raises(ev.ChunkTooLong):
        ev.chunk_entry(counter, heading, "x " * 500)


def test_profile_chunk_cap_is_enforced(counter):
    entries = [{"title": f"P{i}", "description": "Did a thing.", "technologies": []} for i in range(101)]
    with pytest.raises(ev.ChunkTooLong):
        ev.chunk_profile(counter, {"skills": [], "projects": entries, "experience": [], "education": []})


def test_only_projects_and_experience_are_chunked(counter):
    content = {"skills": ["Python"], "projects": [{"title": "A", "description": "Did A.", "technologies": []}],
               "experience": [{"title": "B", "description": "Did B.", "technologies": []}],
               "education": [{"qualification": "BSc", "details": "x"}]}
    chunks = ev.chunk_profile(counter, content)
    assert [(c["section"], c["entry_index"], c["chunk_index"]) for c in chunks] == [("PROJECT", 0, 0), ("EXPERIENCE", 0, 0)]


def test_all_fixture_chunks_fit_budget(counter):
    fx = ev.load_fixtures(FIXTURES, FIXTURES / "labels.csv")
    for p in fx["profiles"].values():
        assert all(counter.count(c["text"]) <= ev.MAX_TOKENS for c in ev.chunk_profile(counter, p["content"]))
    for j in fx["jobs"].values():
        assert all(counter.count(c) <= ev.MAX_TOKENS for c in ev.chunk_job(counter, j))


# ---- fixtures ----

def test_fixture_shape_split_and_coverage():
    fx = ev.load_fixtures(FIXTURES, FIXTURES / "labels.csv")
    assert len(fx["jobs"]) == 30 and len(fx["profiles"]) == 10
    splits = [p["split"] for p in fx["profiles"].values()]
    assert splits.count("development") == 5 and splits.count("held_out") == 5
    assert all(len(v) == 30 for v in fx["labels"].values())
    assert all(any(v == 2 for v in fx["labels"][p].values()) for p in fx["profiles"])   # every profile has a relevant job


def test_fixtures_contain_no_contact_details():
    text = (FIXTURES / "profiles.json").read_text(encoding="utf-8") + (FIXTURES / "jobs.json").read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    assert not re.search(r"\+?\d[\d ()-]{7,}\d", text)


def _copy_fixtures(tmp_path):
    dst = tmp_path / "fx"
    shutil.copytree(FIXTURES, dst)
    return dst


def test_missing_label_is_rejected(tmp_path):
    dst = _copy_fixtures(tmp_path)
    rows = list(csv.reader((dst / "labels.csv").open(encoding="utf-8")))
    with (dst / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows[:-1])
    with pytest.raises(ev.FixtureError, match="unlabelled"):
        ev.load_fixtures(dst, dst / "labels.csv")


def test_invalid_relevance_is_rejected(tmp_path):
    dst = _copy_fixtures(tmp_path)
    text = (dst / "labels.csv").read_text(encoding="utf-8").replace("P01,J01,2,", "P01,J01,3,", 1)
    (dst / "labels.csv").write_text(text, encoding="utf-8")
    with pytest.raises(ev.FixtureError, match="relevance"):
        ev.load_fixtures(dst, dst / "labels.csv")
