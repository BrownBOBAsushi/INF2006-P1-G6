from app.processing import worker


def test_extraction_handler_does_not_construct_embedding_model(monkeypatch):
    calls = []

    class Redactor:
        def redact_lines(self, _lines, **_kwargs):
            calls.append("redact")

    class Model:
        def __init__(self):
            calls.append("model")

    monkeypatch.setattr("app.processing.privacy.get_redactor", lambda: Redactor())
    monkeypatch.setattr("app.processing.embeddings.EmbeddingModel", Model)

    handlers = worker.build_production_handlers("EXTRACTION")

    assert set(handlers) == {"prepare"}
    assert calls == ["redact"]


def test_embedding_handler_does_not_construct_privacy_analyzer(monkeypatch):
    calls = []

    class Model:
        def __init__(self):
            calls.append("model")
        def embed(self, _texts):
            return []

    def forbidden_redactor():
        raise AssertionError("embedding worker must not initialize privacy analyzer")

    monkeypatch.setattr("app.processing.privacy.get_redactor", forbidden_redactor)
    monkeypatch.setattr("app.processing.embeddings.EmbeddingModel", Model)

    handlers = worker.build_production_handlers("EMBEDDING")

    assert set(handlers) == {"embed"}
    assert calls == ["model"]
