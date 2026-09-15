import subprocess

def run_alembic(*args):
    return subprocess.run(
        ["alembic", *args],
        cwd="/app",
        capture_output=True,
        text=True,
    )

def test_upgrade_head_is_idempotent():
    result = run_alembic("upgrade", "head")
    assert result.returncode == 0

def test_downgrade_and_upgrade_roundtrip():
    down = run_alembic("downgrade", "-1")
    assert down.returncode == 0
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0