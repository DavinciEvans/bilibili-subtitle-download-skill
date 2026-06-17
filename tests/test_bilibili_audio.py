"""Unit tests for bilibili_audio. Real B 站 integration requires cookie."""
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from scripts.bilibili_audio import (
    fetch_audio_192k,
    fetch_audio_192k_sync,
    _load_cookie,
    _credential_from_cookie,
    _choose_audio_track,
    BilibiliAudioError,
)

# ---------- _load_cookie ----------
def test_load_cookie_missing_file_raises(tmp_path):
    with pytest.raises(BilibiliAudioError, match="cookie not found"):
        _load_cookie(str(tmp_path / "nope.txt"))

def test_load_cookie_reads_content(tmp_path):
    p = tmp_path / "cookie.txt"
    p.write_text("SESSDATA=abc123; bili_jct=xyz789")
    assert _load_cookie(str(p)) == "SESSDATA=abc123; bili_jct=xyz789"

# ---------- _credential_from_cookie ----------
def test_credential_from_cookie_parses_keys():
    cookie = "SESSDATA=aaa; bili_jct=bbb; buvid3=ccc; DedeUserID=123"
    cred = _credential_from_cookie(cookie)
    assert cred.sessdata == "aaa"
    assert cred.bili_jct == "bbb"
    assert cred.buvid3 == "ccc"
    assert cred.dedeuserid == "123"

def test_credential_from_cookie_empty():
    cred = _credential_from_cookie("")
    assert cred.sessdata == ""
    assert cred.bili_jct == ""

# ---------- _choose_audio_track ----------
def test_choose_audio_track_prefers_192k():
    from bilibili_api.video import AudioQuality
    tracks = [
        {"id": 30216, "baseUrl": "https://a/64k.m4s"},
        {"id": 30280, "baseUrl": "https://a/192k.m4s"},
        {"id": 30232, "baseUrl": "https://a/132k.m4s"},
    ]
    chosen = _choose_audio_track(tracks)
    assert chosen["id"] == AudioQuality._192K.value
    assert "192k" in chosen["baseUrl"]

def test_choose_audio_track_falls_back_to_first():
    tracks = [{"id": 30216, "baseUrl": "https://a/64k.m4s"}]
    chosen = _choose_audio_track(tracks)
    assert chosen["id"] == 30216

def test_choose_audio_track_empty_raises():
    with pytest.raises(BilibiliAudioError, match="no audio tracks"):
        _choose_audio_track([])

# ---------- fetch_audio_192k (async, mocked) ----------
@pytest.mark.asyncio
async def test_fetch_audio_192k_full_flow(tmp_path):
    """端到端 mock：mock video API + ffmpeg"""
    fake_url_info = {
        "dash": {
            "audio": [
                {"id": 30280, "baseUrl": "https://example.com/192k.m4s"},
            ]
        }
    }

    # mock video.Video: get_download_url is async (coroutine) in real bilibili_api
    fake_video = MagicMock()
    fake_video.get_download_url = AsyncMock(return_value=fake_url_info)

    def fake_ffmpeg(*args, **kwargs):
        # 写一个空文件到 output 路径
        cmd = args[0]
        output_path = cmd[-1]
        Path(output_path).write_bytes(b"fake mp3 content here" * 100)
        r = MagicMock()
        r.returncode = 0
        r.stderr = b""
        return r

    with patch("scripts.bilibili_audio.video.Video", return_value=fake_video), \
         patch("subprocess.run", side_effect=fake_ffmpeg):
        cookie_file = tmp_path / "cookie.txt"
        cookie_file.write_text("SESSDATA=test; bili_jct=test")
        out = tmp_path / "out.mp3"
        result = await fetch_audio_192k("BV1xx411c7mD", 0, out, cookie_path=str(cookie_file))

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 100
    fake_video.get_download_url.assert_awaited_once_with(page_index=0)

@pytest.mark.asyncio
async def test_fetch_audio_192k_no_audio_tracks(tmp_path):
    fake_url_info = {"dash": {"audio": []}}
    fake_video = MagicMock()
    fake_video.get_download_url = AsyncMock(return_value=fake_url_info)

    with patch("scripts.bilibili_audio.video.Video", return_value=fake_video):
        cookie_file = tmp_path / "cookie.txt"
        cookie_file.write_text("SESSDATA=test")
        with pytest.raises(BilibiliAudioError, match="no audio tracks"):
            await fetch_audio_192k("BV1xx411c7mD", 0, tmp_path / "out.mp3",
                                   cookie_path=str(cookie_file))

@pytest.mark.asyncio
async def test_fetch_audio_192k_ffmpeg_failure(tmp_path):
    fake_url_info = {
        "dash": {"audio": [{"id": 30280, "baseUrl": "https://x.m4s"}]}
    }
    fake_video = MagicMock()
    fake_video.get_download_url = AsyncMock(return_value=fake_url_info)

    def fake_failed_run(*args, **kwargs):
        r = MagicMock()
        r.returncode = 1
        r.stderr = b"ffmpeg error"
        return r

    with patch("scripts.bilibili_audio.video.Video", return_value=fake_video), \
         patch("subprocess.run", side_effect=fake_failed_run):
        cookie_file = tmp_path / "cookie.txt"
        cookie_file.write_text("SESSDATA=test")
        with pytest.raises(BilibiliAudioError, match="ffmpeg failed"):
            await fetch_audio_192k("BV1xx", 0, tmp_path / "out.mp3",
                                   cookie_path=str(cookie_file))

# ---------- fetch_audio_192k_sync (sync wrapper) ----------
def test_fetch_audio_192k_sync_wrapper(tmp_path):
    """验证 sync wrapper 能用 asyncio.run 调用 async 版本。"""
    fake_url_info = {
        "dash": {"audio": [{"id": 30280, "baseUrl": "https://example.com/192k.m4s"}]}
    }
    fake_video = MagicMock()
    fake_video.get_download_url = AsyncMock(return_value=fake_url_info)

    def fake_ffmpeg(*args, **kwargs):
        cmd = args[0]
        output_path = cmd[-1]
        Path(output_path).write_bytes(b"fake mp3 content here" * 100)
        r = MagicMock()
        r.returncode = 0
        r.stderr = b""
        return r

    with patch("scripts.bilibili_audio.video.Video", return_value=fake_video), \
         patch("subprocess.run", side_effect=fake_ffmpeg):
        cookie_file = tmp_path / "cookie.txt"
        cookie_file.write_text("SESSDATA=test")
        out = tmp_path / "out_sync.mp3"
        result = fetch_audio_192k_sync("BV1xx411c7mD", 0, out, cookie_path=str(cookie_file))

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 100
