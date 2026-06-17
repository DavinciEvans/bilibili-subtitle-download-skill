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
