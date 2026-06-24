"""
VAD 分段。
- 优先 webrtcvad（轻量、Google、CPU 友好）
- 失败/无有效段时降级到硬切（按固定时长 + padding）
"""
import wave
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds

def _read_wav_pcm16k_mono(path: Path) -> tuple[bytes, int]:
    """读 wav，转 16k/mono/int16。返回 (raw_bytes, sample_rate)。"""
    import audioop
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())

    if nch > 1:
        raw = audioop.tomono(raw, sw, 1, 1)
    if sr != 16000 or sw != 2:
        # ffmpeg 转
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(path),
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16le",
                str(tmp_path),
            ], check=True, capture_output=True)
            with wave.open(str(tmp_path), "rb") as wf:
                sr = wf.getframerate()
                sw = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
        finally:
            tmp_path.unlink(missing_ok=True)
    if sw != 2:
        raw = audioop.lin2lin(raw, sw, 2)
    return raw, sr

def _webrtc_vad_segments(pcm: bytes, sr: int, padding_sec: float, target_min: float, target_max: float) -> list[Segment] | None:
    """webrtcvad 检测 speech run，合并为 1-3min 段。Returns None if webrtcvad 不可用或无 speech。"""
    try:
        import webrtcvad
    except ImportError:
        return None

    vad = webrtcvad.Vad(2)  # 0=aggressive, 3=most aggressive; 2 平衡
    frame_ms = 20
    frame_bytes = int(sr * frame_ms / 1000) * 2  # 16-bit
    if len(pcm) < frame_bytes:
        return None

    speech_runs: list[tuple[int, int]] = []
    in_speech = False
    run_start = 0
    for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        is_speech = vad.is_speech(pcm[i:i+frame_bytes], sr)
        idx = i // frame_bytes
        if is_speech and not in_speech:
            in_speech = True
            run_start = idx
        elif not is_speech and in_speech:
            speech_runs.append((run_start, idx))
            in_speech = False
    if in_speech:
        speech_runs.append((run_start, len(pcm) // frame_bytes))

    if not speech_runs:
        return None

    # 合并相邻 runs，目标每段 1-3 分钟
    segments: list[Segment] = []
    cur_start_f = speech_runs[0][0]
    cur_end_f = speech_runs[0][1]
    for s, e in speech_runs[1:]:
        merged = (cur_end_f - cur_start_f) * frame_ms / 1000
        gap = (s - cur_end_f) * frame_ms / 1000
        if merged < target_min and gap < 2.0:
            cur_end_f = e
        else:
            segments.append(Segment(
                cur_start_f * frame_ms / 1000,
                cur_end_f * frame_ms / 1000,
            ))
            cur_start_f = s
            cur_end_f = e
    segments.append(Segment(
        cur_start_f * frame_ms / 1000,
        cur_end_f * frame_ms / 1000,
    ))

    # 加 padding
    return [
        Segment(max(0, s.start - padding_sec), s.end + padding_sec)
        for s in segments
    ]


def segment_by_vad(
    audio_path: str | Path,
    *,
    target_min_sec: float = 60.0,
    target_max_sec: float = 180.0,
    padding_sec: float = 1.0,
) -> list[Segment]:
    """主入口。优先 VAD，失败/无效时降级硬切。"""
    path = Path(audio_path)
    pcm, sr = _read_wav_pcm16k_mono(path)

    segs = _webrtc_vad_segments(pcm, sr, padding_sec, target_min_sec, target_max_sec)
    if segs:
        # clamp 到 target_max
        for s in segs:
            if s.end - s.start > target_max_sec + padding_sec * 2:
                s.end = s.start + target_max_sec
        return segs

    # 降级：硬切
    import wave as _w
    with _w.open(str(path), "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
    return fallback_hard_split(
        duration_sec=dur, chunk_sec=target_min_sec, padding_sec=padding_sec,
    )


def fallback_hard_split(
    duration_sec: float, *, chunk_sec: float = 60.0, padding_sec: float = 1.0,
) -> list[Segment]:
    """按时长硬切。每段 chunk_sec + padding（前 padding 仅对非首段，与下段重叠 padding_sec 用于去重）。"""
    if duration_sec <= chunk_sec + padding_sec:
        return [Segment(0.0, duration_sec)]
    segs: list[Segment] = []
    t = 0.0
    while t < duration_sec:
        end = min(t + chunk_sec + padding_sec, duration_sec)
        segs.append(Segment(t, end))
        if end >= duration_sec:
            break
        t = end - padding_sec  # 下段起点 = 本段终点 - padding
    return segs
