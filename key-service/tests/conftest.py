import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import generate_test_audio as gen  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def fixtures() -> Path:
    """Generate the known-key WAVs once if they're missing."""
    if not all((gen.FIXTURES / f"{stem}.wav").exists() for stem in gen.KEYS):
        gen.main()
    return gen.FIXTURES
