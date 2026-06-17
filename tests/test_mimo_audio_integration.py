"""
Integration test for mimo_audio.transcribe_wav.
真实调 MiMo API。需要 MIMO_API_KEY 环境变量。
如未设置则 skip。
"""
import os
import pytest
from pathlib import Path
from scripts.mimo_audio import transcribe_wav, MiMoASRError

FIXTURE = Path(__file__).parent / "fixtures" / "silence_30s.wav"

pytestmark = pytest.mark.skipif(
    not os.environ.get("MIMO_API_KEY"),
    reason="MIMO_API_KEY not set; integration test requires real API",
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
