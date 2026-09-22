"""Embedding module: pinned model, dimension read from the model, validation, reproducibility, batching."""
import numpy as np
import pytest

from app.processing.config import EMBEDDING_DIM, EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_REVISION, EMBEDDING_VERSION
from app.processing.embeddings import EmbeddingModel
from app.processing.errors import EmptyTextError, TokenLimitError


def test_model_is_the_pinned_minilm_and_dimension_comes_from_the_model(model):
    assert (model.name, model.revision) == (EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_REVISION)
    assert model.name == "sentence-transformers/all-MiniLM-L6-v2" and len(model.revision) == 40
    assert model.dim == EMBEDDING_DIM == 384 == int(model._model.get_embedding_dimension())
    assert model.version == EMBEDDING_VERSION and EMBEDDING_MODEL_REVISION in model.version
    assert model._model.max_seq_length == 240


def test_valid_text_gives_a_unit_float32_vector_of_the_expected_shape(model):
    v = model.embed(["Built REST APIs using Flask."])
    assert v.shape == (1, 384) and v.dtype == np.float32
    assert np.isfinite(v).all() and abs(float(np.linalg.norm(v[0])) - 1.0) < 1e-3
    assert model.embed_one("Built REST APIs using Flask.").shape == (384,)


@pytest.mark.parametrize("bad", ["", " ", "\t\n", None, 5])
def test_empty_or_invalid_input_is_rejected_safely(model, bad):
    with pytest.raises(EmptyTextError):
        model.embed([bad])


def test_over_limit_input_is_rejected_not_truncated(model):
    with pytest.raises(TokenLimitError):
        model.embed(["word " * 400])
    assert model.embed(["word " * 200]).shape == (1, 384)         # 200 word pieces + specials < 240


def test_same_input_gives_bitwise_identical_vectors_across_calls_and_fresh_instances(model):
    text = "Implemented REST endpoints in Java using Spring Boot and dependency injection."
    a, b = model.embed([text]), model.embed([text])
    assert np.array_equal(a, b)
    fresh = EmbeddingModel()                                       # new load of the pinned revision
    assert np.array_equal(a, fresh.embed([text]))


def test_batching_preserves_order_and_matches_single_calls(model):
    texts = ["Python web API", "Organised a bake sale", "Trained a neural network with PyTorch", "SQL joins"]
    batch = model.embed(texts, batch_size=2)
    for i, t in enumerate(texts):
        assert np.allclose(batch[i], model.embed([t])[0], atol=1e-5)
    assert model.embed([]).shape == (0, 384)


def test_semantics_the_prd_example_related_wording_scores_above_unrelated(model):
    resume, related, unrelated = model.embed(["Built REST APIs using Flask.", "Backend development using Python web frameworks.",
                                              "Organised the annual charity bake sale."])
    assert float(resume @ related) > float(resume @ unrelated) + 0.2


def test_uncached_model_fails_instead_of_silently_downloading():
    with pytest.raises(Exception):
        EmbeddingModel(name="sentence-transformers/this-model-does-not-exist-xyz", revision="0" * 40)   # local_files_only=True
