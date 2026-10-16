from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_scoring_config, get_settings  # noqa: E402


@pytest.fixture
def cfg():
    return get_scoring_config()


@pytest.fixture(autouse=True)
def _force_tmp_sqlite_path(tmp_path):
    """모든 테스트가 **운영 DB·운영 Turso 를 건드리지 않도록** 강제.

    사유:
    - 과거 수동 실행 중 운영 SQLite 를 지운 사고가 있었다 (`.claude/co-work/pm-answer-9e0f38f8` 자백).
    - `.env.local` 에 운영 Turso 접속 정보(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)가 들어 있을 수 있다.
      환경에서 USE_TURSO 가 true 로 로드돼도 **테스트에서는 반드시 False** 로 강제한다.
    - get_settings() 는 lru_cache 되어 Settings 객체가 공유되므로, 각 테스트마다 값을 바꾸고 복구.
    """
    s = get_settings()
    original_path = s.sqlite_path
    original_sample = s.use_sample_data
    original_turso_url = s.turso_database_url
    original_turso_token = s.turso_auth_token
    s.sqlite_path = tmp_path / "test.sqlite"
    s.use_sample_data = True
    # 환경에 TURSO_* 가 있어도 테스트에서는 비워 운영 DB 접속 자체를 차단
    s.turso_database_url = ""
    s.turso_auth_token = ""
    try:
        yield
    finally:
        s.sqlite_path = original_path
        s.use_sample_data = original_sample
        s.turso_database_url = original_turso_url
        s.turso_auth_token = original_turso_token
