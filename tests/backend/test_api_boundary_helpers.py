"""Focused regressions for request buffering and public validation envelopes."""

import asyncio

import pytest

pytest.importorskip("pgvector")

from fastapi.exceptions import RequestValidationError

from app.api.resume import _parse_single_pdf
from app.main import _validation_fields
from app.processing.errors import ProcessingError


def _multipart(parts: str) -> tuple[bytes, str]:
    return parts.encode(), "multipart/form-data; boundary=boundary"


def test_prepare_parser_accepts_starlette_style_multipart_file_without_spooling():
    body, content_type = _multipart(
        '--boundary\r\n'
        'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
        'Content-Type: application/pdf\r\n\r\n'
        '%PDF-1.4\r\n'
        '--boundary--\r\n'
    )
    assert _parse_single_pdf(body, content_type) == b"%PDF-1.4"


def test_prepare_parser_rejects_multiple_files():
    body, content_type = _multipart(
        '--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\na\r\n'
        '--boundary\r\nContent-Disposition: form-data; name="file"; filename="b.pdf"\r\n\r\nb\r\n'
        '--boundary--\r\n'
    )
    with pytest.raises(ProcessingError) as exc:
        _parse_single_pdf(body, content_type)
    assert exc.value.code == "PDF_REQUIRED"


def test_validation_envelope_omits_input_values():
    fields = _validation_fields(RequestValidationError([{
        "type": "string_too_long", "loc": ("body", "content", "description"),
        "msg": "too long", "input": "private resume text",
    }]))
    assert fields == ["content.description"]


@pytest.mark.parametrize("media_type", ["application/json", "application/vnd.api+json; charset=utf-8"])
def test_streamed_json_over_limit_never_dispatches_to_handler(media_type):
    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from app.main import enforce_body_limits

    app = FastAPI()
    app.middleware("http")(enforce_body_limits)
    calls = []

    @app.put("/api/resume")
    async def save(request: Request):
        calls.append(await request.json())
        return {"saved": True}

    async def chunks():
        yield b'{"value":1}'
        yield b" " * (256 * 1024 + 1)

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.test") as client:
            return await client.put(
                "/api/resume", headers={"content-type": media_type}, content=chunks()
            )

    response = asyncio.run(exercise())
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert calls == []
