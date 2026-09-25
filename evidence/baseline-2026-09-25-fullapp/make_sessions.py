"""Create or delete ISOLATED SYNTHETIC test sessions for the full-application load baseline.

Runs INSIDE the api container (uses the app's own models + security helpers so the
rows are byte-for-byte what a real Google sign-in would produce). It never touches
pre-existing users/sessions: every synthetic user has google_sub prefixed with
SYNTH_PREFIX, and delete only removes those.

    python make_sessions.py create 10   # prints JSON: [{raw_token, csrf_token, user_id}, ...]
    python make_sessions.py delete       # removes ALL synthetic users (CASCADE removes their sessions)
"""
import json
import sys

from sqlalchemy import select

from app.auth import security
from app.db.models import Session as SessionModel, User
from app.db.session import SessionLocal

SYNTH_PREFIX = "loadtest-synthetic-baseline-2026-09-25:"


def create(n: int) -> None:
    out = []
    db = SessionLocal()
    try:
        for i in range(n):
            user = User(google_sub=f"{SYNTH_PREFIX}{i}", display_name=f"loadtest-{i}")
            db.add(user)
            db.flush()
            raw_token, token_hash = security.new_session_token()
            csrf_token = security.new_csrf_token()
            db.add(SessionModel(token_hash=token_hash, user_id=user.user_id,
                                csrf_token=csrf_token, expires_at=security.session_expiry()))
            out.append({"raw_token": raw_token, "csrf_token": csrf_token, "user_id": str(user.user_id)})
        db.commit()
    finally:
        db.close()
    print(json.dumps(out))


def delete() -> None:
    db = SessionLocal()
    try:
        users = db.execute(select(User).where(User.google_sub.like(SYNTH_PREFIX + "%"))).scalars().all()
        for u in users:
            db.delete(u)  # sessions cascade via ondelete="CASCADE"
        db.commit()
        print(json.dumps({"deleted_users": len(users)}))
    finally:
        db.close()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "create":
        create(int(sys.argv[2]))
    elif cmd == "delete":
        delete()
    else:
        raise SystemExit(f"unknown command: {cmd}")
