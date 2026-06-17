"""Tests for mimo_audio client. Only unit tests; integration test is in Task 2."""
import os
import pytest
from pathlib import Path
from scripts.mimo_audio import (
    transcribe_wav,
    _assert_within_size_limit,
    _client,
    MiMoASRError,
)


def test_assert_within_size_limit_rejects_oversize(tmp_path):
    big = tmp_path / "big.wav"
    big.write_bytes(b"x" * (11 * 1024 * 1024))  # 11MB
    with pytest.raises(MiMoASRError, match="size limit"):
        _assert_within_size_limit(big, max_mb=10)


def test_assert_within_size_limit_accepts_small(tmp_path):
    small = tmp_path / "small.wav"
    small.write_bytes(b"x" * 1024)  # 1KB
    # 不应抛异常
    _assert_within_size_limit(small, max_mb=10)


def test_client_raises_without_key(monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(MiMoASRError, match="MIMO_API_KEY not set"):
        _client(api_key=None)


def test_client_uses_provided_key():
    c = _client(api_key="sk-test")
    # OpenAI 客户端 base_url 应是 MiMo 端点
    assert "xiaomimimo.com" in str(c.base_url)


def test_assert_within_size_limit_boundary_at_limit(tmp_path):
    # 恰好 10MB（max_mb=10），边界处应通过
    at_limit = tmp_path / "at_limit.wav"
    at_limit.write_bytes(b"x" * (10 * 1024 * 1024))
    _assert_within_size_limit(at_limit, max_mb=10)


def test_assert_within_size_limit_just_over_limit(tmp_path):
    # 10MB + 1 byte，刚好超限，应抛异常
    over_limit = tmp_path / "over_limit.wav"
    over_limit.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(MiMoASRError, match="size limit"):
        _assert_within_size_limit(over_limit, max_mb=10)
