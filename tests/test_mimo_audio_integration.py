"""
Integration test for mimo_audio.transcribe_wav.
真实调 MiMo API。Key 解析优先级: 参数 > env var > key file (见 mimo_audio._resolve_api_key).
如果三个来源都没有则 skip.
"""
import os
import pytest
from pathlib import Path
from scripts.mimo_audio import transcribe_wav, MiMoASRError, _resolve_api_key

FIXTURE = Path(__file__).parent / "fixtures" / "silence_30s.wav"

pytestmark = pytest.mark.skipif(
    not _resolve_api_key(None),
    reason="MIMO API key not provided via arg / env var / key file; integration test requires real API",
)


def test_fixture_exists():
    """sanity check: fixture 30s 静音 wav 存在"""
    assert FIXTURE.exists()
    assert FIXTURE.stat().st_size > 100_000  # 30s 16k mono wav 至少 ~960KB


def test_transcribe_wav_returns_str():
    """调真实 MiMo ASR。30s 静音/440Hz 音调预期返回 str（可能空或占位符如 '<chinese>'）。"""
    text = transcribe_wav(FIXTURE, language="zh")
    print(f"\n[integration] MiMo ASR returned text: {text!r}")
    assert isinstance(text, str)
    # 即便是静音，MiMo 也会返回非 None 的 str（可能包含占位符）
    assert text is not None
