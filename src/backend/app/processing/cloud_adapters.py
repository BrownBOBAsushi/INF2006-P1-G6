"""Explicit local/AWS adapter selection with fail-closed AWS configuration."""
from __future__ import annotations

import os
from datetime import timedelta
from urllib.parse import urlsplit

from app.processing.local_storage import LocalTempStorage


def processing_mode() -> str:
    mode = os.environ.get("PROCESSING_MODE", "local").strip().lower()
    if mode not in {"local", "aws"}:
        raise RuntimeError("PROCESSING_MODE must be local or aws")
    return mode


def _aws_settings() -> tuple[str, int]:
    region = os.environ.get("AWS_REGION", "").strip()
    ttl = int(os.environ.get("PROCESSING_TEMP_TTL_SECONDS", "3600"))
    if not region or ttl <= 0:
        raise RuntimeError("AWS processing requires AWS_REGION and a positive temporary TTL")
    return region, ttl


def make_storage():
    ttl = int(os.environ.get("PROCESSING_TEMP_TTL_SECONDS", "3600"))
    if processing_mode() == "local":
        return LocalTempStorage(os.environ.get("PROCESSING_TEMP_DIR", "/tmp/internship-matcher-processing"),
                                ttl=timedelta(seconds=ttl))
    region, ttl = _aws_settings()
    bucket = os.environ.get("PROCESSING_TEMP_BUCKET", "").strip()
    prefix = os.environ.get("PROCESSING_TEMP_PREFIX", "").strip()
    if not bucket or not prefix:
        raise RuntimeError("AWS processing requires PROCESSING_TEMP_BUCKET and PROCESSING_TEMP_PREFIX")
    import boto3
    from botocore.config import Config
    from app.processing.aws_storage import S3TemporaryStorage

    client = boto3.client("s3", region_name=region, config=Config(
        connect_timeout=3, read_timeout=25, retries={"max_attempts": 2}
    ))
    return S3TemporaryStorage(bucket, prefix, client=client, ttl_seconds=ttl)


def make_task_queues():
    region, _ = _aws_settings()
    urls = {
        "EXTRACTION": os.environ.get("PROCESSING_EXTRACTION_QUEUE_URL", "").strip(),
        "EMBEDDING": os.environ.get("PROCESSING_EMBEDDING_QUEUE_URL", "").strip(),
    }
    if not all(urls.values()):
        raise RuntimeError("AWS processing requires both task queue URLs")
    identities = set()
    for url in urls.values():
        try:
            parsed = urlsplit(url)
            if (parsed.scheme.lower() != "https" or not parsed.hostname or not parsed.path
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError
            port = parsed.port
        except ValueError:
            raise RuntimeError("AWS task queue URLs must be valid HTTPS SQS URLs") from None
        identities.add((parsed.hostname.lower(), None if port == 443 else port, parsed.path))
    if len(identities) != len(urls):
        raise RuntimeError("AWS extraction and embedding queue URLs must be distinct")
    import boto3
    from botocore.config import Config
    from app.processing.sqs_transport import SqsTaskQueue

    client = boto3.client("sqs", region_name=region, config=Config(
        connect_timeout=3, read_timeout=25, retries={"max_attempts": 2}
    ))
    return {kind: SqsTaskQueue(url, kind, client=client) for kind, url in urls.items()}
