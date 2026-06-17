"""Tests for text_dedup."""
import pytest
from scripts.text_dedup import (
    merge_with_overlap_dedup,
    _longest_tail_head_overlap,
)


# ---------- _longest_tail_head_overlap ----------
def test_overlap_basic():
    assert _longest_tail_head_overlap("今天天气真好", "真好适合出门", min_chars=2) == 2


def test_overlap_no_match():
    assert _longest_tail_head_overlap("今天", "明天", min_chars=2) == 0


def test_overlap_empty():
    assert _longest_tail_head_overlap("", "abc") == 0
    assert _longest_tail_head_overlap("abc", "") == 0
    assert _longest_tail_head_overlap("", "") == 0


def test_overlap_respects_min_chars():
    # 仅 1 字符重叠，但 min_chars=2，应返回 0
    assert _longest_tail_head_overlap("今天", "天好", min_chars=2) == 0


def test_overlap_longest_wins():
    # "大家好" 长度 3, "家好" 长度 2, "好" 长度 1; min_chars=2, 应返回 3
    a = "今天天气大家好"
    b = "大家好适合出门"
    assert _longest_tail_head_overlap(a, b, min_chars=2) == 3


def test_overlap_max_chars_cap():
    # 5 字符重叠, max_chars=2 限制最大匹配为 2; 但 min_chars=2 也会被应用
    # 期望：返回 0 因为 max_chars=2 时只能找 2 字符匹配 (b="一二三四五世界", a[-2:]="四五" != b[:2]="一二")
    a = "一二三四五"
    b = "一二三四五世界"
    assert _longest_tail_head_overlap(a, b, min_chars=2, max_chars=2) == 0
    # 若 max_chars=5, 应找到 5 字符匹配
    assert _longest_tail_head_overlap(a, b, min_chars=2, max_chars=5) == 5


# ---------- merge_with_overlap_dedup ----------
def test_no_overlap_passthrough():
    segs = ["你好世界", "今天天气好", "再见"]
    out = merge_with_overlap_dedup(segs)
    assert out == segs


def test_simple_overlap_dedup():
    segs = ["今天天气真好适合出门", "适合出门散步", "散步很舒服"]
    out = merge_with_overlap_dedup(segs, min_overlap_chars=2)
    # "适合出门" 重复
    assert out[0] == "今天天气真好适合出门"
    # seg 2: 去与 out[0] 尾部 "适合出门" 重叠的前缀 → "散步"
    assert out[1] == "散步"
    # seg 3: 去与 out[1] (累积的 "散步") 尾部 "散步" 重叠的前缀 → "很舒服"
    assert out[2] == "很舒服"


def test_empty_segment_handled():
    segs = ["第一段内容", "", "第二段内容"]
    out = merge_with_overlap_dedup(segs)
    assert "第一段内容" in out
    assert "第二段内容" in out
    # 空段被过滤
    assert len(out) == 2


def test_all_empty_returns_empty():
    out = merge_with_overlap_dedup(["", "", ""])
    assert out == []


def test_single_segment_passthrough():
    out = merge_with_overlap_dedup(["单段内容"])
    assert out == ["单段内容"]


def test_chained_overlap():
    # 段1: "...abc"
    # 段2: "abcdef"
    # 段3: "defghi"
    # 期望: [...abc, def, ghi]  (每段去前一个的尾部)
    segs = ["xyzabc", "abcdef", "defghi"]
    out = merge_with_overlap_dedup(segs, min_overlap_chars=2)
    assert out[0] == "xyzabc"
    assert out[1] == "def"  # 去 "abc"
    assert out[2] == "ghi"  # 去 "def"


def test_overlap_below_min_chars_not_deduped():
    # 1 字符重叠, min_chars=2, 应不去重
    segs = ["今天天", "天气好"]
    out = merge_with_overlap_dedup(segs, min_overlap_chars=2)
    assert out == segs
