"""
从 B 站拉音轨到本地 mp3 192kbps。
复用现有 cookie 凭证。
"""
import asyncio
import os
import subprocess
from pathlib import Path
from bilibili_api import video
from bilibili_api.video import AudioQuality

class BilibiliAudioError(Exception):
    pass

def _load_cookie(cookie_path: str) -> str:
    p = Path(os.path.expanduser(cookie_path))
    if not p.exists():
        raise BilibiliAudioError(f"cookie not found: {p}")
    return p.read_text().strip()

def _credential_from_cookie(cookie_str: str):
    """从 cookie 字符串构造 bilibili-api-python 的 Credential 对象。"""
    from bilibili_api import Credential
    cookies = {}
    for kv in cookie_str.split("; "):
        if "=" in kv:
            k, v = kv.split("=", 1)
            cookies[k.strip()] = v.strip()
    return Credential(
        sessdata=cookies.get("SESSDATA", ""),
        bili_jct=cookies.get("bili_jct", ""),
        buvid3=cookies.get("buvid3", ""),
        buvid4=cookies.get("buvid4", ""),
        dedeuserid=cookies.get("DedeUserID", ""),
    )

def _choose_audio_track(audio_tracks: list[dict]) -> dict:
    """从 dash audio list 选最合适的：优先 192k (id=30280)，否则第一个。"""
    if not audio_tracks:
        raise BilibiliAudioError("no audio tracks in dash data")
    for t in audio_tracks:
        if t.get("id") == AudioQuality._192K.value:
            return t
    return audio_tracks[0]

async def fetch_audio_192k(
    bv_id: str,
    page_index: int,
    output_path: str | Path,
    *,
    cookie_path: str = str(Path(__file__).resolve().parent.parent / "secrets" / "bilibili_cookie.txt"),
) -> Path:
    """拉指定分 P 的 192kbps 音轨到 output_path (mp3)。返回 output_path。async 版本。"""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    cookie_str = _load_cookie(cookie_path)
    cred = _credential_from_cookie(cookie_str)
    v = video.Video(bvid=bv_id, credential=cred)

    try:
        url_info = await v.get_download_url(page_index=page_index)
    except Exception as e:
        raise BilibiliAudioError(f"get_download_url failed: {e}") from e

    dash = url_info.get("dash") or {}
    audio_tracks = dash.get("audio") or []
    chosen = _choose_audio_track(audio_tracks)

    audio_url = chosen.get("baseUrl") or chosen.get("base_url") or chosen.get("url")
    if not audio_url:
        raise BilibiliAudioError(f"no audio url in track: {chosen}")

    headers = f"User-Agent: Mozilla/5.0\r\nReferer: https://www.bilibili.com/\r\nCookie: {cookie_str}"
    cmd = [
        "ffmpeg", "-y", "-headers", headers,
        "-i", audio_url,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "192k",
        str(output),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not output.exists() or output.stat().st_size < 100:
        raise BilibiliAudioError(f"ffmpeg failed: {r.stderr.decode(errors='ignore')[:500]}")

    return output

def fetch_audio_192k_sync(
    bv_id: str,
    page_index: int,
    output_path: str | Path,
    *,
    cookie_path: str = str(Path(__file__).resolve().parent.parent / "secrets" / "bilibili_cookie.txt"),
) -> Path:
    """sync wrapper around fetch_audio_192k."""
    return asyncio.run(fetch_audio_192k(bv_id, page_index, output_path, cookie_path=cookie_path))
