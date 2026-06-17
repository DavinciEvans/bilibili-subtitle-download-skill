"""
完整 ASR fallback 流程:
fetch audio → VAD/硬切 → 逐段调 MiMo ASR → 去重 → 写 chunk 文件 → 返回路径列表。
"""
import os
import subprocess
import tempfile
from pathlib import Path
from scripts.mimo_audio import transcribe_wav, MiMoASRError
from scripts.bilibili_audio import fetch_audio_192k_sync
from scripts.vad_segmenter import segment_by_vad
from scripts.text_dedup import merge_with_overlap_dedup

CHARS_PER_CHUNK = 100_000

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
    cookie_path: str = "~/.openclaw/workspace/bilibili_cookie.txt",
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

        # 1) 拉音频
        fetch_audio_192k_sync(bv_id, p_num, audio_path, cookie_path=cookie_path)

        # 2) VAD 分段
        segments = segment_by_vad(
            audio_path,
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
