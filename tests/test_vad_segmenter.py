"""Tests for vad_segmenter."""
import wave
from pathlib import Path
import pytest
from scripts.vad_segmenter import (
    segment_by_vad,
    fallback_hard_split,
    _webrtc_vad_segments,
    Segment,
)

# ---------- fallback_hard_split ----------
def test_fallback_hard_split_short_returns_one():
    segs = fallback_hard_split(duration_sec=30.0, chunk_sec=60, padding_sec=1.0)
    assert len(segs) == 1
    assert segs[0].start == 0
    assert abs(segs[0].end - 30.0) < 0.1

def test_fallback_hard_split_long():
    segs = fallback_hard_split(duration_sec=125.0, chunk_sec=60, padding_sec=1.0)
    # 125s, chunk=60, padding=1
    # 段1: 0-61 (60+1)
    # 段2: 60-121 (60+1, 起点 = 61-1 = 60)
    # 段3: 120-126 (5+padding 限幅)
    assert len(segs) >= 2
    for s in segs:
        assert s.start < s.end
        # 每段长度 <= chunk + 2*padding (下界 + 上界 padding)
        assert s.end - s.start <= 62

def test_fallback_hard_split_exact_boundary():
    segs = fallback_hard_split(duration_sec=60.0, chunk_sec=60, padding_sec=1.0)
    # 60s <= 60+1, 走 short 分支
    assert len(segs) == 1
    assert segs[0].end == 60.0

# ---------- _webrtc_vad_segments ----------
def test_webrtc_vad_returns_none_on_empty_audio():
    # 1 帧静音应返回 None (因为 len < frame_bytes)
    segs = _webrtc_vad_segments(b"", 16000, 1.0, 60, 180)
    assert segs is None

def test_webrtc_vad_with_tone_returns_speech_segment():
    """30s 440Hz 正弦波 (持续 tone): webrtcvad 会判定为 speech, 返回覆盖整段的 Segment。

    这是 webrtcvad 已知行为: 持续浊音被当语音。生产中真实语音有停顿, 切分会正常。
    """
    import os
    p = Path("tests/fixtures/silence_30s.wav")
    if not p.exists():
        pytest.skip("fixture not found")
    import wave as _w
    with _w.open(str(p), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        sr = wf.getframerate()
    segs = _webrtc_vad_segments(raw, sr, 1.0, 60, 180)
    # 持续 tone 触发 VAD, 应返回至少 1 段覆盖大部分音频
    assert segs is not None
    assert len(segs) >= 1
    assert segs[0].start <= 1.0  # 含 padding
    assert segs[0].end >= 29.0   # 含 padding, 覆盖整段

# ---------- segment_by_vad ----------
def test_segment_by_vad_uses_vad_for_tone(tmp_path):
    """30s 持续 tone: VAD 路径生效 (非 fallback), 应返回 1 段覆盖整音频"""
    src = Path("tests/fixtures/silence_30s.wav")
    if not src.exists():
        pytest.skip("fixture not found")
    segs = segment_by_vad(src, target_min_sec=15, target_max_sec=30, padding_sec=1.0)
    # webrtcvad 路径: 1 段覆盖整音频 (含 padding)
    assert len(segs) >= 1
    assert segs[0].start <= 1.0
    assert segs[0].end >= 30.0
    assert segs[0].start == 0
    assert abs(segs[0].end - 30.0) < 0.5
