from datetime import datetime, timedelta, timezone

import pytest

from app.processing.local_storage import LocalTempStorage


def test_temp_upload_round_trips_and_expires_without_path_control(tmp_path):
    storage = LocalTempStorage(tmp_path, ttl=timedelta(seconds=10))
    reference = storage.store(b"synthetic pdf", now=datetime(2026, 10, 2, tzinfo=timezone.utc))

    assert storage.read(reference) == b"synthetic pdf"
    with pytest.raises(ValueError):
        storage.read("../../outside.pdf")

    removed = storage.expire([reference], now=datetime(2026, 10, 2, 0, 0, 11, tzinfo=timezone.utc))

    assert removed == 1
    assert not storage.path_for(reference).exists()


def test_orphan_cleanup_preserves_live_uploads(tmp_path):
    storage = LocalTempStorage(tmp_path, ttl=timedelta(seconds=10))
    old = storage.store(b"old", now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    live = storage.store(b"live", now=datetime(2026, 10, 2, tzinfo=timezone.utc))

    removed = storage.cleanup_orphans({live}, older_than=datetime(2026, 10, 2, 0, 0, 11, tzinfo=timezone.utc))

    assert removed == 1
    assert storage.path_for(old).exists() is False
    assert storage.read(live) == b"live"


def test_orphan_cleanup_removes_abandoned_staging_uploads(tmp_path):
    storage = LocalTempStorage(tmp_path, ttl=timedelta(seconds=10))
    abandoned = tmp_path / ".upload-crashed-process"
    abandoned.write_bytes(b"private content")
    old_time = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()
    abandoned.touch()
    import os
    os.utime(abandoned, (old_time, old_time))

    removed = storage.cleanup_orphans(set(), older_than=datetime(2026, 10, 2, 0, 0, 11, tzinfo=timezone.utc))

    assert removed == 1
    assert not abandoned.exists()
