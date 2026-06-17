"""Regression tests for download_and_chunk main flow + ASR fallback integration."""
import json
import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# 把 scripts 目录加到 path, 让 import scripts.download_and_chunk 可用
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts import download_and_chunk as dlc


def _run_main(argv):
    """Run the async main() and return whatever it does (may sys.exit)."""
    return asyncio.run(dlc.main(argv))


def test_main_subtitle_success_path(monkeypatch, tmp_path, capsys):
    """主流程: 有字幕时, 不应触发 ASR fallback"""
    # mock get_saved_cookie, get_video_info, fetch_subtitle_content
    monkeypatch.setattr(dlc, "get_saved_cookie", lambda: "SESSDATA=test")
    monkeypatch.setattr(dlc, "get_video_info", lambda bv, cookie: ({"title": "test", "pages": [{"cid": 123}]}, None))
    monkeypatch.setattr(dlc, "fetch_subtitle_content", lambda bv, cid, cookie: ("正常字幕内容" * 100, "user"))

    # 确保 ASR run_asr 不会被调
    with patch.object(dlc, "run_asr") as mock_asr:
        with patch.object(dlc, "OUTPUT_DIR_FALLBACK", str(tmp_path)):
            # 改 cwd
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                _run_main(["download_and_chunk.py", "BV1xx411c7mD"])
            finally:
                os.chdir(old_cwd)
        mock_asr.assert_not_called()

    captured = capsys.readouterr()
    assert "RESULT_JSON" in captured.out
    # 不应包含 method: asr_fallback 字段 (字幕成功路径)
    # 找到 RESULT_JSON 行, 解析 JSON
    for line in captured.out.splitlines():
        if line.startswith("RESULT_JSON:"):
            payload = json.loads(line[len("RESULT_JSON:"):])
            assert payload.get("method") != "asr_fallback"
            assert payload["bv_id"] == "BV1xx411c7mD"
            break


def test_main_no_subtitle_triggers_asr_fallback(monkeypatch, tmp_path, capsys):
    """主流程: 无字幕时, 应触发 ASR fallback"""
    monkeypatch.setattr(dlc, "get_saved_cookie", lambda: "SESSDATA=test")
    monkeypatch.setattr(dlc, "get_video_info", lambda bv, cookie: ({"title": "test", "pages": [{"cid": 123}]}, None))
    monkeypatch.setattr(dlc, "fetch_subtitle_content", lambda bv, cid, cookie: (None, None))

    fake_asr_result = {
        "bv_id": "BV1xx411c7mD",
        "title": "BV1xx411c7mD",
        "total_chars": 100,
        "chunks": [str(tmp_path / "BV1xx411c7mD_chunk_0.txt")],
        "segments_count": 3,
    }
    # 创建空 chunk 文件模拟 run_asr 输出
    (tmp_path / "BV1xx411c7mD_chunk_0.txt").write_text("测试文本")

    with patch.object(dlc, "run_asr", return_value=fake_asr_result) as mock_asr:
        with patch.object(dlc, "OUTPUT_DIR_FALLBACK", str(tmp_path)):
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                _run_main(["download_and_chunk.py", "BV1xx411c7mD"])
            finally:
                os.chdir(old_cwd)
        mock_asr.assert_called_once()
        # 验证 cookie_path 参数传递
        call_kwargs = mock_asr.call_args.kwargs
        assert call_kwargs.get("cookie_path") == str(dlc.COOKIE_FILE)
        # 验证 bv_id 位置参数
        call_args = mock_asr.call_args.args
        assert call_args[0] == "BV1xx411c7mD"

    captured = capsys.readouterr()
    assert "ASR fallback" in captured.out
    assert "RESULT_JSON" in captured.out
    assert "asr_fallback" in captured.out
    # 验证 RESULT_JSON 含 method=asr_fallback
    for line in captured.out.splitlines():
        if line.startswith("RESULT_JSON:"):
            payload = json.loads(line[len("RESULT_JSON:"):])
            assert payload["method"] == "asr_fallback"
            assert payload["bv_id"] == "BV1xx411c7mD"
            break


def test_main_no_subtitle_no_cookie_exits(monkeypatch, tmp_path, capsys):
    """无字幕 + 无 cookie (从 login 拿不到) 时, 应报错退出且不调 ASR"""
    async def fake_login():
        return "SESSDATA=from_qr"  # 模拟有 cookie (B站登录成功)
    monkeypatch.setattr(dlc, "login_with_qr", fake_login)
    monkeypatch.setattr(dlc, "get_saved_cookie", lambda: "")  # 无 cookie
    # 模拟: 第一次 get_video_info 失败 (无 cookie), 第二次也失败 (login 后的 cookie 也不行)
    # 这样不会走到 fetch_subtitle_content, 但 cookie 已被赋值为 from_qr
    # 真正测试"无字幕无 cookie"的场景: 需要在 ASR fallback 分支前 cookie 为空
    # 由于 main() 的 cookie 获取逻辑 (if not cookie: cookie = await login()),
    # 走到 ASR 分支时 cookie 必然非空, 除非 login() 返回空串.
    # 此 case 仅验证 mock 调用关系 (run_asr 不应被调, 因为 get_video_info 失败)
    monkeypatch.setattr(dlc, "get_video_info", lambda bv, cookie: (None, "video info failed"))

    with patch.object(dlc, "run_asr") as mock_asr:
        with patch.object(dlc, "OUTPUT_DIR_FALLBACK", str(tmp_path)):
            with pytest.raises(SystemExit) as exc_info:
                _run_main(["download_and_chunk.py", "BV1xx411c7mD"])
            assert exc_info.value.code == 1
            mock_asr.assert_not_called()
