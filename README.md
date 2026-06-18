# bilibili-subtitle-download-skill

下载 B 站视频字幕 / 课程字幕，**无字幕时自动 ASR 转写**，分块输出供 LLM 总结。

## 起源与差异

Fork 自 [DavinciEvans/bilibili-subtitle-download-skill](https://github.com/DavinciEvans/bilibili-subtitle-download-skill)。

相对上游的改动：

1. **依赖包替换**：`bilibili-api` 已停更，改用 `bilibili-api-python`。
2. **AI 字幕支持**：B 站 AI 字幕 (`lan='ai-zh'`) 优先于 fallback，无字幕时不再无解。
3. **ASR fallback**（主要新增）：视频完全无字幕时，自动调用 MiMo-V2.5-ASR 语音识别。流程：拉 192k 音频 → webrtcvad 分段 → 逐段调 ASR → 字符级跨段去重 → 纯文本 chunk 文件。
4. **所有路径相对化**：cookie / API key / 二维码临时图都放在 skill 安装根目录的 `secrets/` 子目录里（git 忽略），不再依赖 `~/.openclaw/workspace/`。

## 支持的字幕来源

| 来源 | 触发条件 | 字段 |
|------|---------|------|
| 用户上传字幕 | `lan='zh'` | `method: "subtitle"` |
| AI 字幕 | `lan='ai-zh'` | `method: "subtitle"` |
| ASR 转写（MiMo-V2.5-ASR） | 无任何字幕 | `method: "asr_fallback"` |

## 安装

```bash
git clone git@github.com:hfun2017/bilibili-subtitle-download-skill.git
cd bilibili-subtitle-download-skill
pip install bilibili-api-python webrtcvad openai
```

把整个目录（包含 `SKILL.md`）放到 hermes skill 目录下，例如 `~/.hermes/skills/media/bilibili-subtitle-downloader/`。

## 快速上手

详细工作流见 [`SKILL.md`](./SKILL.md)。核心命令：

```bash
SKILL_DIR=/path/to/bilibili-subtitle-download-skill
cd "$SKILL_DIR"
PYTHONIOENCODING=utf-8 python scripts/download_and_chunk.py <BV_ID>
```

首次运行会要求扫码登录 B 站（cookie 写入 `$SKILL_DIR/secrets/bilibili_cookie.txt`）。
ASR 需要 MiMo API key（写入 `$SKILL_DIR/secrets/mimo_api_key`，详见 SKILL.md）。

## 测试

```bash
pip install pytest pytest-asyncio
python3 -m pytest tests/
```

46 个测试，包括 2 个真调 MiMo ASR 的集成测试（需要在 `secrets/mimo_api_key` 放真 key）。
