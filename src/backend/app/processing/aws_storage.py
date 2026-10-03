"""Private, short-lived S3 input storage for AWS processing mode."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

MAX_TEMP_PDF_BYTES = 5 * 1024 * 1024


class S3TemporaryStorage:
    def __init__(self, bucket: str, prefix: str, *, client, ttl_seconds: int = 3600):
        normalized = prefix.strip("/")
        if not bucket or not normalized or any(part in {".", ".."} for part in PurePosixPath(normalized).parts):
            raise ValueError("S3 temporary bucket and safe prefix are required")
        if ttl_seconds <= 0:
            raise ValueError("temporary storage TTL must be positive")
        self.bucket = bucket
        self.prefix = normalized
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.ttl = timedelta(seconds=ttl_seconds)

    @staticmethod
    def _key(reference: str) -> str:
        try:
            parsed = uuid.UUID(reference)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("invalid temporary object reference") from None
        return parsed.hex + ".pdf"

    def _object_key(self, reference: str) -> str:
        return f"{self.prefix}/{self._key(reference)}"

    def store(self, data: bytes, *, now: datetime | None = None) -> str:
        if not isinstance(data, bytes) or not data:
            raise ValueError("temporary PDF must be non-empty bytes")
        if len(data) > MAX_TEMP_PDF_BYTES:
            raise ValueError("temporary PDF exceeds the 5 MiB size limit")
        reference = str(uuid.uuid4())
        args = {
            "Bucket": self.bucket,
            "Key": self._object_key(reference),
            "Body": data,
            "ContentType": "application/pdf",
            "ServerSideEncryption": "AES256",
        }
        if now is not None:
            args["Metadata"] = {"uploaded-at": now.astimezone(timezone.utc).isoformat()}
        self.client.put_object(**args)
        return reference

    def read(self, reference: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=self._object_key(reference))["Body"]
        data = body.read(MAX_TEMP_PDF_BYTES + 1)
        if len(data) > MAX_TEMP_PDF_BYTES:
            raise ValueError("temporary PDF exceeds the 5 MiB size limit")
        return data

    def delete(self, reference: str | None) -> bool:
        if reference is None:
            return False
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(reference))
        return True

    def expire(self, references: list[str], *, now: datetime | None = None) -> int:
        cutoff = now or datetime.now(timezone.utc)
        removed = 0
        for reference in references:
            key = self._object_key(reference)
            try:
                info = self.client.head_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                if getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                    continue
                raise
            modified = info.get("LastModified")
            if modified is not None and (cutoff - modified).total_seconds() >= self.ttl_seconds:
                self.client.delete_object(Bucket=self.bucket, Key=key)
                removed += 1
        return removed

    def cleanup_orphans(self, live_references: set[str], *, older_than: datetime) -> int:
        live_names = {self._key(value) for value in live_references}
        removed = 0
        token = None
        while True:
            args = {"Bucket": self.bucket, "Prefix": self.prefix + "/"}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                name = key.removeprefix(self.prefix + "/")
                if "/" in name or not name.endswith(".pdf") or name in live_names:
                    continue
                if item.get("LastModified") and item["LastModified"] <= older_than:
                    self.client.delete_object(Bucket=self.bucket, Key=key)
                    removed += 1
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
            if not token:
                break
        return removed
