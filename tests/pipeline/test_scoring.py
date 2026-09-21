"""Requirement-level scoring with hand-built vectors, so each expected ranking is known exactly (no model involved)."""
import random

import numpy as np
import pytest

from app.matching.recommend import recommend
from app.matching.scoring import JobVectors, RequirementVectors, rank_jobs, score_job
from app.processing.errors import ProcessingError

DIM = 8


def unit(*coords):
    v = np.zeros(DIM, dtype=np.float32)
    v[:len(coords)] = coords
    return v / np.linalg.norm(v)


E = [unit(*([0] * i + [1])) for i in range(DIM)]        # orthogonal basis: cosine 1 with itself, 0 with the others


def mix(i, j, w):
    """A unit vector whose cosine with E[i] is w and with E[j] is sqrt(1-w^2)."""
    return w * E[i] + np.sqrt(1 - w * w) * E[j]


def req(rid, text, *alt_vecs, importance="REQUIRED", skills=(), alts=None):
    alts = alts or tuple(f"{text} #{i}" for i in range(len(alt_vecs)))
    return RequirementVectors(rid, 0, importance, text, tuple(alts), np.stack(alt_vecs).astype(np.float32), tuple(skills))


def job(jid, *reqs):
    return JobVectors(jid, tuple(reqs))


def chunks(*vecs):
    return np.stack(vecs).astype(np.float32)


def test_clear_best_and_weak_match():
    resume = chunks(E[0], E[1])                                   # resume covers topics 0 and 1
    best = job("j-best", req("a", "topic 0", E[0]), req("b", "topic 1", E[1]))
    weak = job("j-weak", req("c", "topic 5", E[5]), req("d", "topic 6", E[6]))
    page, total, _ = rank_jobs(resume, [weak, best])
    assert [m.job_id for m in page] == ["j-best", "j-weak"] and total == 2
    assert page[0].score == pytest.approx(1.0) and page[1].score == pytest.approx(0.0, abs=1e-6)


def test_and_requirements_all_contribute_to_the_mean():
    resume = chunks(E[0])                                         # only topic 0
    both = job("both", req("a", "topic 0", E[0]), req("b", "topic 1", E[1]))   # AND: two requirement rows
    one = job("one", req("c", "topic 0", E[0]))
    assert score_job(resume, both)[0].score == pytest.approx(0.5)            # (1 + 0) / 2: missing one AND halves the score
    assert score_job(resume, one)[0].score == pytest.approx(1.0)
    page, _, _ = rank_jobs(resume, [both, one])
    assert [m.job_id for m in page] == ["one", "both"]


def test_or_alternatives_need_only_one_and_do_not_require_both():
    java_only = chunks(E[1])                                      # resume knows "Java" (E1) but not "Python" (E0)
    or_job = job("or", req("a", "Python or Java", E[0], E[1], alts=("Python", "Java")))
    and_job = job("and", req("b", "Python", E[0]), req("c", "Java", E[1]))
    assert score_job(java_only, or_job)[0].score == pytest.approx(1.0)       # one alternative is enough
    assert score_job(java_only, and_job)[0].score == pytest.approx(0.5)      # both were required
    m = score_job(java_only, or_job)[0].requirements[0]
    assert m.alternative_index == 1                                          # the matching alternative is reported


def test_multiple_requirements_use_max_per_requirement_then_mean():
    resume = chunks(mix(0, 7, 0.9), mix(1, 7, 0.6), E[2])
    j = job("j", req("a", "r0", E[0]), req("b", "r1", E[1]), req("c", "r2", E[3]))
    m, _ = score_job(resume, j)
    assert [round(x.score, 4) for x in m.requirements] == [0.9, 0.6, 0.0]
    assert m.score == pytest.approx((0.9 + 0.6 + 0.0) / 3, abs=1e-5)
    assert [x.chunk_index for x in m.requirements] == [0, 1, 0]              # closest passage indexes; ties go to the lowest index


def test_preferred_requirements_never_change_the_score():
    resume = chunks(E[0])
    plain = job("p", req("a", "r0", E[0]))
    with_pref = job("q", req("a", "r0", E[0]), req("b", "nice", E[5], importance="PREFERRED"))
    assert score_job(resume, plain)[0].score == score_job(resume, with_pref)[0].score


def test_equal_scores_break_ties_by_job_id_ascending_regardless_of_input_order():
    resume = chunks(E[0])
    jobs = [job(jid, req("a", "topic 0", E[0])) for jid in ("j-c", "j-a", "j-b")]
    for order in ([0, 1, 2], [2, 1, 0], [1, 2, 0]):
        page, _, _ = rank_jobs(resume, [jobs[i] for i in order])
        assert [m.job_id for m in page] == ["j-a", "j-b", "j-c"]


def test_near_equal_scores_are_ordered_by_score_when_they_differ_beyond_tie_precision():
    resume = chunks(mix(0, 7, 0.800001), mix(1, 7, 0.8))
    higher_score_later_id = job("b-job", req("a", "r", E[0]))     # 0.800001
    lower_score_earlier_id = job("a-job", req("b", "r", E[1]))    # 0.800000
    page, _, _ = rank_jobs(resume, [lower_score_earlier_id, higher_score_later_id])
    assert [m.job_id for m in page] == ["b-job", "a-job"]         # the score difference wins over job_id order


def test_fewer_than_five_and_more_than_five_jobs():
    resume = chunks(E[0])
    three = [job(f"j{i}", req("a", "r", mix(0, 7, 0.9 - i * 0.1))) for i in range(3)]
    page, total, _ = rank_jobs(resume, three, top_k=5)
    assert len(page) == 3 and total == 3
    eight = [job(f"j{i}", req("a", "r", mix(0, 7, 0.95 - i * 0.05))) for i in range(8)]
    page, total, _ = rank_jobs(resume, eight, top_k=5)
    assert [m.job_id for m in page] == ["j0", "j1", "j2", "j3", "j4"] and total == 8
    page2, _, _ = rank_jobs(resume, eight, top_k=5, offset=5)
    assert [m.job_id for m in page2] == ["j5", "j6", "j7"]                    # pagination continues the same ranking
    assert rank_jobs(resume, [], top_k=5)[0] == []


def test_ranking_is_deterministic_under_shuffling():
    rng = random.Random(7)
    resume = chunks(E[0], E[1], E[2])
    jobs = [job(f"j{i:02d}", req("a", "r", mix(rng.randrange(3), 7, rng.choice([0.3, 0.5, 0.7]))),
               req("b", "s", mix(rng.randrange(3), 6, rng.choice([0.4, 0.6])))) for i in range(30)]
    first = [m.job_id for m in rank_jobs(resume, jobs, top_k=30)[0]]
    for seed in range(5):
        shuffled = jobs[:]
        random.Random(seed).shuffle(shuffled)
        assert [m.job_id for m in rank_jobs(resume, shuffled, top_k=30)[0]] == first


def test_aggregation_happens_before_top_k_a_global_vector_limit_would_rank_differently():
    """Job A has one very strong requirement and one unmet; job B has two moderate ones. The contract says B wins
    (mean 0.6 > 0.475). A naive 'take the top-1 nearest requirement vector globally' would pick A."""
    resume = chunks(mix(0, 7, 0.95), mix(1, 7, 0.6), mix(2, 7, 0.6))
    a = job("A", req("a1", "strong", E[0]), req("a2", "unmet", E[5]))
    b = job("B", req("b1", "moderate", E[1]), req("b2", "moderate", E[2]))
    naive = max((float((r.vectors @ resume.T).max()), j.job_id) for j in (a, b) for r in j.requirements)
    assert naive[1] == "A"                                                    # what an early LIMIT would surface first
    page, _, _ = rank_jobs(resume, [a, b], top_k=1)
    assert page[0].job_id == "B" and page[0].score == pytest.approx(0.6, abs=1e-5)


def test_jobs_without_required_requirements_or_with_incomplete_vectors_are_omitted_and_counted():
    resume = chunks(E[0])
    ok = job("ok", req("a", "r", E[0]))
    none_required = job("none", req("b", "nice", E[0], importance="PREFERRED"))
    incomplete = job("inc", RequirementVectors("c", 0, "REQUIRED", "r", ("x", "y"), np.stack([E[0]]).astype(np.float32)))  # 1 of 2 vectors
    page, total, diag = rank_jobs(resume, [ok, none_required, incomplete])
    assert [m.job_id for m in page] == ["ok"] and total == 1
    assert (diag.considered, diag.omitted_no_required, diag.omitted_incomplete) == (3, 1, 1)


def test_duplicate_logical_requirements_count_once():
    resume = chunks(E[0])
    dup = job("dup", req("a", "Python  APIs", E[0]), req("b", "python apis", E[0]), req("c", "other", E[1]))
    single = job("single", req("a", "Python APIs", E[0]), req("c", "other", E[1]))
    assert score_job(resume, dup)[0].score == score_job(resume, single)[0].score == pytest.approx(0.5)


def test_no_chunks_is_insufficient_resume_information():
    with pytest.raises(ValueError):
        rank_jobs(np.zeros((0, DIM), dtype=np.float32), [job("j", req("a", "r", E[0]))])
    with pytest.raises(ProcessingError) as exc:
        recommend(np.zeros((0, DIM), dtype=np.float32), [], [job("j", req("a", "r", E[0]))], ["Python"])
    assert exc.value.code == "INSUFFICIENT_RESUME_INFORMATION"
