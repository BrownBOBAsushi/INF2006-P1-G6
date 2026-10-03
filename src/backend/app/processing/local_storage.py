"""Private, temporary filesystem storage for the AWS-free worker path."""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


class LocalTempStorage:
    def __init__(self, root: str | Path, *, ttl: timedelta = timedelta(hours=1)):
        if ttl <= timedelta(0):
            raise ValueError("temporary storage TTL must be positive")
        self.root = Path(root)
        self.ttl = ttl
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _key(reference: str) -> str:
        try:
            parsed = uuid.UUID(reference)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("invalid temporary object reference") from None
        return f"{parsed.hex}.pdf"

    def path_for(self, reference: str) -> Path:
        return self.root / self._key(reference)

    def store(self, data: bytes, *, now: datetime | None = None) -> str:
        if not isinstance(data, bytes) or not data:
            raise ValueError("temporary PDF must be non-empty bytes")
        reference = str(uuid.uuid4())
        target = self.path_for(reference)
        fd, temp_name = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_name, target)
            if now is not None:
                timestamp = now.timestamp()
                os.utime(target, (timestamp, timestamp))
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            Path(temp_name).unlink(missing_ok=True)
            raise
        return reference

    def read(self, reference: str) -> bytes:
        return self.path_for(reference).read_bytes()

    def delete(self, reference: str | None) -> bool:
        if reference is None:
            return False
        path = self.path_for(reference)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def expire(self, references: list[str], *, now: datetime | None = None) -> int:
        timestamp = (now or datetime.now(timezone.utc)).timestamp() - self.ttl.total_seconds()
        removed = 0
        for reference in references:
            path = self.path_for(reference)
            try:
                if path.stat().st_mtime <= timestamp:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed

    def cleanup_orphans(self, live_references: set[str], *, older_than: datetime) -> int:
        live_names = {self._key(value) for value in live_references}
        removed = 0
        cutoff = older_than.timestamp()
        for path in self.root.iterdir():
            staging = path.name.startswith(".upload-")
            if (not staging and not path.name.endswith(".pdf")) or path.name in live_names:
                continue
            try:
                if path.is_file() and path.stat().st_mtime <= cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed
