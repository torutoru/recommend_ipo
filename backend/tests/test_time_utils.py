"""KST 직렬화 테스트.

Render(UTC) 에서 돌아도 응답에 나가는 모든 시각이 +09:00 로 나와야 한다.
TZ 환경변수를 UTC 로 강제한 subprocess 로 검증.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent


def _run_in_utc(script: str) -> str:
    """`TZ=UTC` 환경에서 Python 서브프로세스 실행 → stdout 반환."""
    env = dict(os.environ)
    env["TZ"] = "UTC"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_now_iso_kst_has_plus9_suffix_even_under_utc():
    out = _run_in_utc(
        "from app.time_utils import now_iso_kst; print(now_iso_kst())"
    )
    assert out.endswith("+09:00"), f"KST suffix missing: {out!r}"


def test_now_kst_returns_asia_seoul_tz():
    out = _run_in_utc(
        "from app.time_utils import now_kst; "
        "d = now_kst(); print(d.tzinfo); print(d.utcoffset().total_seconds())"
    )
    # UTC 환경에서도 tzinfo 가 Asia/Seoul, offset 32400s(=9시간) 이어야 함
    lines = out.split("\n")
    assert "Asia/Seoul" in lines[0]
    assert lines[1].strip() == "32400.0"


def test_turso_disabled_during_tests():
    """conftest 의 `_force_tmp_sqlite_path` 가 TURSO 설정을 비워 use_turso() 가 False.

    `.env.local` 에 운영 Turso 접속 정보가 있어도 테스트 세션에서는 반드시 비워져야 한다.
    """
    from app.config import get_settings, use_turso

    s = get_settings()
    assert s.turso_database_url == ""
    assert s.turso_auth_token == ""
    assert use_turso(s) is False


def test_turso_env_loads_into_fresh_settings_outside_conftest():
    """참고: conftest 보호가 없는 raw Settings 는 환경을 그대로 반영.

    즉, 운영에서 TURSO_* 가 설정돼 있으면 `use_turso()` 가 True 가 되고 Turso 를 쓴다.
    conftest 가 해당 값을 **설정 객체 레벨에서 덮어쓰기** 때문에 테스트가 안전해지는 구조를 명시 검증.
    """
    env = dict(os.environ)
    env["TURSO_DATABASE_URL"] = "libsql://fake-production.turso.io"
    env["TURSO_AUTH_TOKEN"] = "fake-token"
    env["PYTHONIOENCODING"] = "utf-8"
    script = (
        "from app.config import Settings, use_turso\n"
        "s = Settings()\n"
        "assert s.turso_database_url == 'libsql://fake-production.turso.io'\n"
        "assert s.turso_auth_token == 'fake-token'\n"
        "assert use_turso(s) is True\n"
        "print('loaded')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "loaded"


def test_health_last_collected_at_is_kst_under_utc():
    """/api/health 와 /api/collect/status 응답의 시각이 +09:00 로 나오는지."""
    out = _run_in_utc(
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "from app import store, collect_service\n"
        "from app.config import get_settings\n"
        "# 임시 DB 초기화 + 가짜 수집 run 1건 삽입\n"
        "from pathlib import Path, PurePath\n"
        "import tempfile\n"
        "d = tempfile.mkdtemp()\n"
        "get_settings().sqlite_path = Path(d) / 'kst.sqlite'\n"
        "store.init_db()\n"
        "with store.connect() as c:\n"
        "    rid = store.start_collect_run(c, 7)\n"
        "    store.finish_collect_run(c, rid, collected=0, errors=0, note='test')\n"
        "collect_service._reset_for_tests()\n"
        "client = TestClient(create_app())\n"
        "h = client.get('/api/health').json()\n"
        "s = client.get('/api/collect/status').json()\n"
        "print(h['last_collected_at'])\n"
        "print(s['last_collected_at'])\n"
    )
    for line in out.strip().split("\n"):
        assert line.endswith("+09:00"), f"non-KST timestamp: {line!r}"
