"""Run-scoped isolated synthetic accounts for the resume-to-matches journey baseline (v2).

Runs INSIDE the api container (uses the app's own models + security so rows are byte-for-byte a real
sign-in). Isolation is by an explicit RUN ID, not a broad prefix: every account this run creates has
google_sub = f"{PREFIX}{run_id}:{i}", and DELETE removes ONLY the exact user_ids listed in a manifest
this run produced. There is NO "known-clean" pre-deletion and NO broad prefix wipe, so accounts from
other runs are never touched.

NEVER prints session tokens. `create` stages tokens and the accumulated exact-ID manifest in a unique
container directory, commits, then atomically publishes both files. The orchestrator docker-cp's them
to restricted paths outside the repo; stdout contains only this invocation's user_ids (UUIDs).

    python synthetic.py create <n> <run_id> <tokens.json> <manifest.json>
    python synthetic.py delete <manifest.json>                 # deletes ONLY those user_ids; prints counts
"""
import json
import os
import sys
import uuid

from sqlalchemy import select

from app.auth import security
from app.db.models import Session as SessionModel, User
from app.db.session import SessionLocal

PREFIX = "loadtest-journey-v2:"


def create(n: int, run_id: str, tokens_path: str, manifest_path: str) -> None:
    tokens, user_ids = [], []
    nonce = uuid.uuid4().hex
    temp_paths = [f"{path}.tmp-{nonce}" for path in (tokens_path, manifest_path)]
    db = SessionLocal()
    commit_attempted = False
    try:
        prior_ids = []
        try:
            with open(manifest_path) as f:
                prior_ids = json.load(f).get("user_ids", [])
        except FileNotFoundError:
            pass
        for i in range(n):
            user = User(google_sub=f"{PREFIX}{run_id}:{i}", display_name=f"journeyv2-{i}")
            db.add(user)
            db.flush()
            raw_token, token_hash = security.new_session_token()
            csrf_token = security.new_csrf_token()
            db.add(SessionModel(token_hash=token_hash, user_id=user.user_id,
                                csrf_token=csrf_token, expires_at=security.session_expiry()))
            tokens.append({"user_id": str(user.user_id), "raw_token": raw_token, "csrf_token": csrf_token})
            user_ids.append(str(user.user_id))
        # Prepare the sensitive output before committing. Publish it atomically only
        # after commit; any failure compensates by deleting this exact ID set.
        for path, payload in zip(temp_paths, (
            {"run_id": run_id, "sessions": tokens},
            {"user_ids": sorted(set(prior_ids) | set(user_ids))}
        )):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
        commit_attempted = True
        db.commit()
        os.replace(temp_paths[0], tokens_path)
        os.replace(temp_paths[1], manifest_path)
    except BaseException:
        db.rollback()
        if commit_attempted and user_ids:
            try:
                _delete_users(user_ids)
            except Exception as cleanup_error:  # preserve original failure, expose compensation failure
                print(f"CREATE_COMPENSATION_FAILED: {type(cleanup_error).__name__}", file=sys.stderr)
        # The manifest may already contain successful earlier scenarios; leave it
        # intact unless its atomic replacement completed (the final operation).
        for path in (tokens_path,):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        raise
    finally:
        db.close()
        for path in temp_paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    print(json.dumps({"created": len(user_ids), "run_id": run_id, "user_ids": user_ids}))


def _delete_users(ids: list[str]) -> tuple[int, int]:
    """Delete only the exact account IDs supplied by this invocation."""
    db = SessionLocal()
    try:
        found = db.execute(select(User).where(User.user_id.in_(ids))).scalars().all() if ids else []
        for u in found:
            db.delete(u)
        db.commit()
        remaining = db.execute(select(User.user_id).where(User.user_id.in_(ids))).scalars().all() if ids else []
        return len(found), len(remaining)
    finally:
        db.close()


def delete(manifest_path: str) -> None:
    with open(manifest_path) as f:
        ids = json.load(f)["user_ids"]
    deleted, remaining = _delete_users(ids)
    print(json.dumps({"requested": len(ids), "deleted": deleted, "remaining": remaining}))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "create":
        create(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "delete":
        delete(sys.argv[2])
    else:
        raise SystemExit(f"unknown command: {cmd}")
