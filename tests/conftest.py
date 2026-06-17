"""
Pytest fixtures shared across tests.

`monkeypatch_key_file` redirects `scripts.mimo_audio.DEFAULT_KEY_FILE` to a
tmp file in the test sandbox, so the real `~/.openclaw/workspace/mimo_api_key`
is never read during tests. By default the tmp file is empty; individual tests
can write content to `tmp_key_file` (the fixture's return value) to simulate
"key file exists with this content".
"""
import pytest

from scripts import mimo_audio


@pytest.fixture
def tmp_key_file(tmp_path, monkeypatch):
    """Point DEFAULT_KEY_FILE at an empty tmp file; tests may write to it."""
    fake = tmp_path / "mimo_api_key"
    fake.write_text("")  # empty → _read_key_file returns None
    monkeypatch.setattr(mimo_audio, "DEFAULT_KEY_FILE", fake)
    return fake


@pytest.fixture
def monkeypatch_key_file(tmp_key_file):
    """Alias matching the name used in test_mimo_audio.py."""
    return tmp_key_file
