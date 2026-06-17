"""
跨段文本去重。
VAD 切分时相邻段会共享 ~1-2s 音频；硬切时显式 padding 1s 也产生重叠。
策略：检测 segment[i] 末尾 N 字 与 segment[i+1] 开头 N 字 的最长公共子串，去掉 i+1 前缀重复。
"""
import re


def _longest_tail_head_overlap(a: str, b: str, min_chars: int = 2, max_chars: int = 50) -> int:
    """返回 b 开头与 a 末尾的最长公共子串长度（字符数）。"""
    a = a.strip()
    b = b.strip()
    if not a or not b:
        return 0
    max_check = min(max_chars, len(a), len(b))
    for n in range(max_check, min_chars - 1, -1):
        if a[-n:] == b[:n]:
            return n
    return 0


def merge_with_overlap_dedup(
    segments: list[str], *, min_overlap_chars: int = 2, max_overlap_chars: int = 50,
) -> list[str]:
    """
    输入各段原始 ASR 文本。返回去重后的纯文本列表（去掉空段）。
    """
    # 过滤空段
    out: list[str] = []
    for seg in segments:
        cleaned = seg.strip()
        if cleaned:
            out.append(cleaned)
    if len(out) <= 1:
        return out

    merged = [out[0]]
    for nxt in out[1:]:
        ov = _longest_tail_head_overlap(merged[-1], nxt, min_overlap_chars, max_overlap_chars)
        if ov > 0:
            merged.append(nxt[ov:])
        else:
            merged.append(nxt)
    return merged
