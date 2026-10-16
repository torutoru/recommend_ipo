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
def _use_sample_data_default():
    """엔드포인트 테스트는 기본적으로 샘플 데이터 응답을 가정한다.

    get_settings() 는 lru_cache 되어 있어 Settings 객체가 공유된다.
    테스트에서는 use_sample_data=True 로 복구해 다른 테스트가 바꿔도 영향 받지 않게 한다.
    """
    s = get_settings()
    original = s.use_sample_data
    s.use_sample_data = True
    try:
        yield
    finally:
        s.use_sample_data = original
