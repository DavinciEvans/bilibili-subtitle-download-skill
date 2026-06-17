"""Unit tests for asr_fallback orchestrator. Uses mocking for B 站 + ASR."""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.asr_fallback import run_asr, _slice_audio, CHARS_PER_CHUNK


# ---------- _slice_audio ----------
def test_slice_audio_calls_ffmpeg(tmp_path):
    src = tmp_path / "src.mp3"
    src.write_bytes(b"fake")
    out = tmp_path / "seg.mp3"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # 让 ffmpeg 创建输出文件
        def fake_run(*args, **kwargs):
            Path(args[0][-1]).write_bytes(b"fake seg")
            return MagicMock(returncode=0)
        mock_run.side_effect = fake_run
        _slice_audio(src, 0.0, 30.0, out)
    assert out.exists()
    assert mock_run.call_count == 1
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd[0]
    assert "-ss" in cmd
    assert "0.000" in cmd
    assert "-to" in cmd
    assert "30.000" in cmd


def test_slice_audio_raises_on_ffmpeg_failure(tmp_path):
    src = tmp_path / "src.mp3"
    src.write_bytes(b"fake")
    out = tmp_path / "seg.mp3"
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr=b"ffmpeg err")):
        with pytest.raises(RuntimeError, match="ffmpeg slice failed"):
            _slice_audio(src, 0.0, 30.0, out)


# ---------- run_asr (mocked) ----------
@pytest.fixture
def fake_audio_file(tmp_path):
    """Create a fake mp3 file representing downloaded audio."""
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"x" * 100)
    return audio


@patch("scripts.asr_fallback.fetch_audio_192k_sync")
@patch("scripts.asr_fallback.segment_by_vad")
@patch("scripts.asr_fallback.transcribe_wav")
@patch("scripts.asr_fallback._slice_audio")
def test_run_asr_full_flow(
    mock_slice, mock_transcribe, mock_vad, mock_fetch, fake_audio_file, tmp_path
):
    # 拉音频: 写个假文件
    def fake_fetch(bv_id, p_num, output_path, **kwargs):
        Path(output_path).write_bytes(b"fake mp3 " * 100)
        return output_path
    mock_fetch.side_effect = fake_fetch

    # VAD 分段: 返回 2 段
    from scripts.vad_segmenter import Segment
    mock_vad.return_value = [Segment(0.0, 30.0), Segment(30.0, 60.0)]

    # 切片: 假成功
    mock_slice.return_value = None

    # ASR: 返回 2 段文本, 模拟段间重复
    mock_transcribe.side_effect = [
        "今天天气真好适合出门",
        "适合出门散步很舒服",  # 与上一段尾部 "适合出门" 重叠
    ]

    output_dir = tmp_path / "out"
    result = run_asr("BV1xx411c7mD", 0, output_dir)

    assert result["bv_id"] == "BV1xx411c7mD"
    assert result["segments_count"] == 2
    assert len(result["chunks"]) >= 1
    # 检查 chunk 文件存在且内容去重
    chunk0 = Path(result["chunks"][0])
    assert chunk0.exists()
    text = chunk0.read_text(encoding="utf-8")
    assert "今天天气真好" in text
    assert "散步很舒服" in text
    # "适合出门" 应该是去重状态: 不重复出现
    assert text.count("适合出门") == 1
    # chunk 文件名格式
    assert "BV1xx411c7mD_chunk_0.txt" in str(result["chunks"][0])


@patch("scripts.asr_fallback.fetch_audio_192k_sync")
@patch("scripts.asr_fallback.segment_by_vad")
@patch("scripts.asr_fallback.transcribe_wav")
@patch("scripts.asr_fallback._slice_audio")
def test_run_asr_no_speech_segments_returns_empty_chunk(
    mock_slice, mock_transcribe, mock_vad, mock_fetch, tmp_path
):
    def fake_fetch(bv_id, p_num, output_path, **kwargs):
        Path(output_path).write_bytes(b"x" * 100)
    mock_fetch.side_effect = fake_fetch
    mock_vad.return_value = []  # 0 段
    mock_slice.return_value = None
    mock_transcribe.return_value = ""

    output_dir = tmp_path / "out"
    result = run_asr("BV1xx", 0, output_dir)
    assert result["segments_count"] == 0
    assert len(result["chunks"]) == 1
    # 空 chunk 标记
    assert Path(result["chunks"][0]).read_text() == ""


@patch("scripts.asr_fallback.fetch_audio_192k_sync")
@patch("scripts.asr_fallback.segment_by_vad")
@patch("scripts.asr_fallback.transcribe_wav")
@patch("scripts.asr_fallback._slice_audio")
def test_run_asr_segment_failure_does_not_break(
    mock_slice, mock_transcribe, mock_vad, mock_fetch, tmp_path
):
    """单段 ASR 失败应不阻断其他段"""
    from scripts.mimo_audio import MiMoASRError
    from scripts.vad_segmenter import Segment
    def fake_fetch(bv_id, p_num, output_path, **kwargs):
        Path(output_path).write_bytes(b"x" * 100)
    mock_fetch.side_effect = fake_fetch
    mock_vad.return_value = [Segment(0.0, 30.0), Segment(30.0, 60.0)]
    mock_slice.return_value = None
    # 第 1 段失败, 第 2 段成功
    mock_transcribe.side_effect = [MiMoASRError("network error"), "第二段内容"]

    output_dir = tmp_path / "out"
    result = run_asr("BV1xx", 0, output_dir)
    assert result["segments_count"] == 2
    text = Path(result["chunks"][0]).read_text()
    assert "第二段内容" in text
