"""
完整 ASR fallback 流程:
fetch audio → VAD/硬切 → 逐段调 MiMo ASR → 去重 → 写 chunk 文件 → 返回路径列表。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from scripts.mimo_audio import transcribe_wav, MiMoASRError
# 注意: 不要直接 import fetch_audio_192k_sync; 它内部 asyncio.run() 在
# download_and_chunk 的顶层 event loop 里会报 "cannot be called from a running
# event loop". 我们用子进程隔离.
from scripts.vad_segmenter import segment_by_vad
from scripts.text_dedup import merge_with_overlap_dedup

CHARS_PER_CHUNK = 100_000

# 默认 cookie 路径: <skill_root>/secrets/bilibili_cookie.txt
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COOKIE_FILE = SKILL_ROOT / "secrets" / "bilibili_cookie.txt"

def _fetch_audio_in_subprocess(bv_id: str, p_num: int, out_path: Path, cookie_path: str) -> None:
    """在干净子进程里跑 fetch_audio_192k, 避免嵌套 event loop."""
    # 把项目根加到 sys.path, 让子进程能 import scripts.bilibili_audio
    project_root = str(Path(__file__).resolve().parent.parent)
    runner = (
        "import sys, asyncio\n"
        f"sys.path.insert(0, {project_root!r})\n"
        "from scripts.bilibili_audio import fetch_audio_192k\n"
        f"asyncio.run(fetch_audio_192k({bv_id!r}, {p_num}, {str(out_path)!r}, "
        f"cookie_path={cookie_path!r}))\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", runner],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 100:
        raise RuntimeError(
            f"audio fetch subprocess failed (rc={r.returncode}).\n"
            f"stdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}"
        )

def _slice_audio(audio_path: Path, start: float, end: float, out_path: Path) -> None:
    """用 ffmpeg 切音频段。"""
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",  # mp3 64k 降低 payload
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg slice failed: {r.stderr.decode(errors='ignore')[:200]}")


def run_asr(
    bv_id: str,
    p_num: int,
    output_dir: str | Path,
    *,
    cookie_path: str = str(DEFAULT_COOKIE_FILE),
    api_key: str | None = None,
    language: str = "zh",
    target_min_sec: float = 60.0,
    target_max_sec: float = 180.0,
    padding_sec: float = 1.0,
) -> dict:
    """
    完整流程。返回 dict 形如:
    {
      "bv_id": str,
      "title": str,
      "total_chars": int,
      "chunks": [str, ...],  # chunk 文件路径
      "segments_count": int,
    }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bili_asr_") as tmp:
        tmp_path = Path(tmp)
        audio_path = tmp_path / f"{bv_id}_p{p_num}.mp3"

        # 1) 拉音频 (在子进程跑, 避开主 event loop)
        _fetch_audio_in_subprocess(bv_id, p_num, audio_path, cookie_path)

        # 1.5) 转 wav 16k/mono 供 VAD 用 (mp3 B 站 16kHz/160kbps 巧合
        #      避开 vad_segmenter 内部 ffmpeg 路径, 但 mp3 不是 RIFF, wave.open
        #      仍会失败 → 在外层显式转, 错误信息更清楚)
        wav_path = tmp_path / f"{bv_id}_p{p_num}.wav"
        r = subprocess.run([
            "ffmpeg", "-y", "-i", str(audio_path),
            "-ar", "16000", "-ac", "1", "-f", "wav",
            str(wav_path),
        ], capture_output=True)
        if r.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size < 100:
            raise RuntimeError(
                f"ffmpeg wav convert failed: {r.stderr.decode(errors='ignore')[:300]}"
            )

        # 2) VAD 分段
        segments = segment_by_vad(
            wav_path,
            target_min_sec=target_min_sec,
            target_max_sec=target_max_sec,
            padding_sec=padding_sec,
        )

        # 3) 逐段 ASR
        seg_texts: list[str] = []
        for i, seg in enumerate(segments):
            seg_file = tmp_path / f"seg_{i:04d}.mp3"
            _slice_audio(audio_path, seg.start, seg.end, seg_file)
            try:
                txt = transcribe_wav(seg_file, api_key=api_key, language=language)
            except MiMoASRError as e:
                # 单段失败不阻断, 记录空段
                print(f"[warn] seg {i} ({seg.start:.1f}-{seg.end:.1f}s) failed: {e}")
                txt = ""
            seg_texts.append(txt)

        # 4) 跨段去重
        deduped = merge_with_overlap_dedup(seg_texts)

    # 5) 拼纯文本（无时间戳, 段间换行），按 100K 字符切 chunk
    deduped_lines = [t for t in deduped if t]
    full_text = "\n".join(deduped_lines)

    chunks: list[str] = []
    if full_text:
        for i in range(0, len(full_text), CHARS_PER_CHUNK):
            chunk_content = full_text[i : i + CHARS_PER_CHUNK]
            chunk_file = output_dir / f"{bv_id}_chunk_{i // CHARS_PER_CHUNK}.txt"
            chunk_file.write_text(chunk_content, encoding="utf-8")
            chunks.append(str(chunk_file))
    else:
        # 无任何文本: 写空 chunk 文件标记
        chunk_file = output_dir / f"{bv_id}_chunk_0.txt"
        chunk_file.write_text("", encoding="utf-8")
        chunks.append(str(chunk_file))

    return {
        "bv_id": bv_id,
        "title": bv_id,  # 标题未知; 调用方可后置刷新
        "total_chars": len(full_text),
        "chunks": chunks,
        "segments_count": len(segments),
    }
