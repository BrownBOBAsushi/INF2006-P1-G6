"""The 240-token limit measured with the model's own tokenizer: below, at, above, very long, and empty inputs."""
import copy

import pytest

from app.processing.chunking import chunk_entry, chunk_resume_content, split_units
from app.processing.config import MAX_INPUT_TOKENS
from app.processing.errors import EmptyTextError, ProcessingError, TokenLimitError
from app.processing.pipeline import embed_resume

LIMIT = MAX_INPUT_TOKENS


def _st_len(model, text):
    """Token count from the SentenceTransformer's OWN tokenizer (independent of our TokenCounter)."""
    return len(model._model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])


def _entry_with_body_tokens(counter, heading, n_words):
    return chunk_entry(counter, heading, " ".join(["data"] * n_words))


def test_limit_is_240_and_measured_in_tokens_not_words_or_characters(model):
    assert LIMIT == 240
    text = "unbelievably counterintuitive electroencephalography " * 40      # 120 words, ~480 word pieces
    assert len(text.split()) < LIMIT and len(text) > LIMIT
    assert model.counter.count(text) > LIMIT                                 # few words, many tokens
    with pytest.raises(TokenLimitError):
        model.embed([text])


def test_below_the_limit_is_a_single_chunk(model):
    chunks = _entry_with_body_tokens(model.counter, "Project: Small", 50)
    assert len(chunks) == 1 and model.counter.count(chunks[0]) < LIMIT


def test_exactly_at_the_limit_stays_one_chunk_and_one_over_splits(model):
    c, heading = model.counter, "Project: Boundary"
    fits = None
    for n in range(100, 400):                                                # find the largest single-chunk body
        chunks = _entry_with_body_tokens(c, heading, n)
        if len(chunks) == 1:
            fits = (n, chunks[0])
        else:
            break
    n, chunk = fits
    assert c.count(chunk) == LIMIT                                           # exactly 240 tokens including specials
    over = _entry_with_body_tokens(c, heading, n + 1)
    assert len(over) >= 2 and all(c.count(x) <= LIMIT for x in over)
    assert sum(x.count("data") for x in over) == n + 1                        # nothing dropped, nothing duplicated


def test_very_long_text_is_split_never_truncated_and_stays_lossless(model):
    words = [f"token{i}" for i in range(6000)]
    chunks = chunk_entry(model.counter, "Experience: Marathon", " ".join(words))
    assert len(chunks) > 20
    assert all(model.counter.count(x) <= LIMIT and _st_len(model, x) <= LIMIT for x in chunks)
    body = "".join(x.split("\n", 1)[1] for x in chunks).replace(" ", "")
    assert body == "".join(words)
    vecs = model.embed(chunks)                                                # every actual embedding input is accepted
    assert vecs.shape == (len(chunks), 384)


def test_sentence_and_bullet_boundaries_are_preferred_over_token_cuts(model):
    sentences = [f"Sentence {i} describes work done on the reporting pipeline." for i in range(60)]
    chunks = chunk_entry(model.counter, "Project: Bullets", "\n".join("- " + s for s in sentences))
    assert len(chunks) > 1
    rebuilt = " ".join(x.split("\n", 1)[1] for x in chunks)
    assert rebuilt == " ".join(sentences)                                     # every chunk boundary is a sentence boundary
    assert split_units("- one.\n- two. three.") == ["one.", "two.", "three."]


def test_empty_input(model):
    assert chunk_entry(model.counter, "Project: Empty", "") == []
    assert chunk_entry(model.counter, "Project: Empty", "   \n  ") == []
    content = {"skills": ["Python"], "projects": [{"title": "", "description": "", "technologies": []}], "experience": [], "education": []}
    assert chunk_resume_content(model.counter, content) == []
    for bad in ("", "   ", "\n"):
        with pytest.raises(EmptyTextError):
            model.embed([bad])


def test_embed_resume_processes_only_inputs_within_the_limit_for_every_fixture_profile(model, profiles):
    for pid, p in profiles.items():
        emb = embed_resume(p["content"], model)
        assert emb.chunks and emb.vectors.shape == (len(emb.chunks), 384)
        assert all(_st_len(model, c["text"]) <= LIMIT for c in emb.chunks)


def test_embed_resume_on_content_that_really_exceeds_240_tokens(model):
    long_desc = " ".join(f"Implemented feature {i} in the billing service and wrote tests for it." for i in range(45))
    content = {"skills": ["Python"], "projects": [{"title": "Billing platform", "description": long_desc, "technologies": ["Python", "SQL"]}],
               "experience": [], "education": []}
    assert model.counter.count("Project: Billing platform\n" + long_desc) > LIMIT * 2
    emb = embed_resume(content, model)
    assert len(emb.chunks) >= 3
    assert all(_st_len(model, c["text"]) <= LIMIT for c in emb.chunks)
    assert [(c["section"], c["entry_index"], c["chunk_index"]) for c in emb.chunks] == \
           [("PROJECT", 0, i) for i in range(len(emb.chunks))]                # stable evidence positions
    assert emb.chunks[-1]["text"].rstrip().endswith("Technologies: Python, SQL.")


def test_chunk_cap_is_an_error_not_a_silent_drop(model):
    entry = {"title": "P", "description": " ".join(["Built a thing that works well."] * 60), "technologies": []}
    content = {"skills": [], "projects": [copy.deepcopy(entry) for _ in range(60)], "experience": [], "education": []}
    with pytest.raises(ProcessingError) as exc:
        chunk_resume_content(model.counter, content)
    assert exc.value.code == "INVALID_CONTENT" and exc.value.reason == "chunk_cap"


def test_backend_chunker_is_identical_to_the_evaluation_harness_chunker(model, profiles):
    import evaluate as ev
    for p in profiles.values():
        prod = [c["text"] for c in chunk_resume_content(model.counter, p["content"])]
        harness = [c["text"] for c in ev.chunk_profile(ev.TokenCounter(model.counter.tok), p["content"])]
        assert prod == harness
    long_body = " ".join(f"Sentence {i} about the reporting pipeline and its tests." for i in range(80))
    entry = {"title": "Long", "description": long_body, "technologies": ["Python"]}
    content = {"skills": [], "projects": [entry], "experience": [], "education": []}
    assert [c["text"] for c in chunk_resume_content(model.counter, content)] == \
           [c["text"] for c in ev.chunk_profile(ev.TokenCounter(model.counter.tok), content)]
