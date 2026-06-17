"""
MiMo-V2.5-ASR 客户端封装。

限制:
- base64 后 ≤ 10 MB
- 支持 wav / mp3
- 仅返回识别文本（不含时间戳/分段时间信息）

API key 解析优先级（从高到低）:
1. 函数参数 `api_key`
2. 环境变量 `MIMO_API_KEY`
3. key 文件 `~/.openclaw/workspace/mimo_api_key` (首行, 自动 strip)
"""
import os
import base64
from pathlib import Path
from openai import OpenAI, OpenAIError

DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5-asr"
MAX_BASE64_MB = 10  # 文档硬限制
DEFAULT_KEY_FILE = Path.home() / ".openclaw" / "workspace" / "mimo_api_key"

class MiMoASRError(Exception):
    pass

def _read_key_file(path: Path) -> str | None:
    """读 key 文件首行非空内容。文件不存在或空则返回 None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise MiMoASRError(f"cannot read key file {path}: {e}") from e
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None

def _resolve_api_key(api_key: str | None) -> str | None:
    """
    按优先级解析 API key。
    Returns key string or None if no source provided.
    Raises MiMoASRError only if explicit key file path provided and unreadable.
    """
    if api_key:
        return api_key
    env_key = os.environ.get("MIMO_API_KEY")
    if env_key:
        return env_key
    return _read_key_file(DEFAULT_KEY_FILE)

def _client(api_key: str | None = None, base_url: str = DEFAULT_BASE_URL) -> OpenAI:
    key = _resolve_api_key(api_key)
    if not key:
        raise MiMoASRError(
            "MIMO API key not found. Provide via: "
            "(1) transcribe_wav(api_key=...) argument, "
            "(2) env var MIMO_API_KEY, "
            f"(3) key file {DEFAULT_KEY_FILE}"
        )
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
    try:
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
    except OpenAIError as e:
        raise MiMoASRError(f"ASR API error: {e}") from e
    if not resp.choices:
        raise MiMoASRError("empty choices in response")
    return resp.choices[0].message.content or ""
