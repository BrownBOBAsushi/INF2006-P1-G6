"""Isolated synthetic accounts for the resume-to-matches journey baseline.

Runs INSIDE the api container (uses the app's own models + security so rows are
byte-for-byte a real sign-in). NEVER prints session tokens: `create` writes them to a
file INSIDE the container (then the orchestrator docker-cp's it to a path OUTSIDE the
repo). Only counts are printed. `delete` removes ONLY accounts created by this run
(google_sub prefixed with SYNTH_PREFIX); their sessions/profiles/chunks/operations
cascade. Existing user data is never touched.

    python synthetic.py create 40 /tmp/journey_sessions.json   # writes file, prints {"created": 40}
    python synthetic.py delete                                  # prints {"deleted_users": N}
"""
import json
import sys

from sqlalchemy import select

from app.auth import security
from app.db.models import Session as SessionModel, User
from app.db.session import SessionLocal

SYNTH_PREFIX = "loadtest-journey-2026-09-25:"


def create(n: int, out_path: str) -> None:
    out = []
    db = SessionLocal()
    try:
        for i in range(n):
            user = User(google_sub=f"{SYNTH_PREFIX}{i}", display_name=f"journey-{i}")
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
    with open(out_path, "w") as f:
        json.dump(out, f)
    print(json.dumps({"created": len(out), "out_path": out_path}))


def delete() -> None:
    db = SessionLocal()
    try:
        users = db.execute(select(User).where(User.google_sub.like(SYNTH_PREFIX + "%"))).scalars().all()
        for u in users:
            db.delete(u)
        db.commit()
        print(json.dumps({"deleted_users": len(users)}))
    finally:
        db.close()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "create":
        create(int(sys.argv[2]), sys.argv[3])
    elif cmd == "delete":
        delete()
    else:
        raise SystemExit(f"unknown command: {cmd}")
