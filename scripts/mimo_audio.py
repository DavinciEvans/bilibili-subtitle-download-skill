"""
MiMo-V2.5-ASR 客户端封装。

限制:
- base64 后 ≤ 10 MB
- 支持 wav / mp3
- 仅返回识别文本（不含时间戳/分段时间信息）
"""
import os
import base64
from pathlib import Path
from openai import OpenAI

DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5-asr"
MAX_BASE64_MB = 10  # 文档硬限制

class MiMoASRError(Exception):
    pass

def _client(api_key: str | None = None, base_url: str = DEFAULT_BASE_URL) -> OpenAI:
    key = api_key or os.environ.get("MIMO_API_KEY")
    if not key:
        raise MiMoASRError("MIMO_API_KEY not set")
    return OpenAI(api_key=key, base_url=base_url)

def _assert_within_size_limit(path: Path, max_mb: int = MAX_BASE64_MB) -> None:
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        raise MiMoASRError(
            f"file {path} is {size_mb:.1f}MB; exceeds size limit "
            f"(ASR base64 limit is {max_mb}MB). Re-chunk into smaller segments."
        )

def transcribe_wav(
    audio_path: str | Path,
    *,
    api_key: str | None = None,
    language: str = "zh",
    timeout: int = 120,
) -> str:
    """
    同步调用 MiMo ASR。返回识别文本（纯文本，不含时间戳）。
    Raises MiMoASRError on failure.
    """
    path = Path(audio_path)
    if not path.exists():
        raise MiMoASRError(f"file not found: {path}")
    _assert_within_size_limit(path)

    suffix = path.suffix.lower()
    mime = "audio/wav" if suffix == ".wav" else "audio/mpeg"

    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    c = _client(api_key)
    resp = c.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": data_url},
            }],
        }],
        extra_body={"asr_options": {"language": language}},
        timeout=timeout,
    )
    if not resp.choices:
        raise MiMoASRError("empty choices in response")
    return resp.choices[0].message.content or ""
