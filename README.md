# bilibili-subtitle-download-skill

下载 B 站视频字幕 / 课程字幕，分块输出供 LLM 总结。**视频完全没有字幕时**才触发 ASR 转写（可选，需 MiMo API key）。

## 起源与差异

Fork 自 [DavinciEvans/bilibili-subtitle-download-skill](https://github.com/DavinciEvans/bilibili-subtitle-download-skill)。

相对上游的改动：

1. **依赖包替换**：`bilibili-api` 已停更，改用 `bilibili-api-python`。
2. **AI 字幕支持**：B 站 AI 字幕 (`lan='ai-zh'`) 优先于 fallback，无字幕时不再无解。
3. **ASR fallback**（主要新增）：视频完全无字幕时，自动调用 MiMo-V2.5-ASR 语音识别。流程：拉 192k 音频 → webrtcvad 分段 → 逐段调 ASR → 字符级跨段去重 → 纯文本 chunk 文件。
4. **所有路径相对化**：cookie / API key / 二维码临时图都放在 skill 安装根目录的 `secrets/` 子目录里（git 忽略），不再依赖 `~/.openclaw/workspace/`。

## 支持的字幕来源

| 来源 | 触发条件 | RESULT_JSON `method` |
|------|---------|---------------------|
| 用户上传字幕 | `lan='zh'` | `"subtitle"` |
| AI 字幕 | `lan='ai-zh'` | `"subtitle"` |
| ASR 转写（MiMo-V2.5-ASR） | 上述都没有 **且** 配置了 API key | `"asr_fallback"` |
| 空 chunk 文件 | 上述都没有 **且** 未配置 API key | `"asr_fallback"`（chunk 内容为空） |

**未配置 MiMo API key 不影响字幕主路径**——只会在遇到无字幕视频时输出空 chunk 文件，提示"该视频需要 ASR 才能生成字幕，请配置 MiMo API key"。

## 安装

```bash
git clone git@github.com:hfun2017/bilibili-subtitle-download-skill.git
cd bilibili-subtitle-download-skill
pip install bilibili-api-python webrtcvad openai
```

把整个目录（包含 `SKILL.md`）放到 hermes skill 目录下，例如 `~/.hermes/skills/media/bilibili-subtitle-downloader/`。

## MiMo API Key（可选）

只在你需要 ASR fallback（处理无字幕视频）时才需要。

1. 访问 [MiMo 控制台](https://api.xiaomimimo.com) 注册账号
2. 在控制台 "API Keys" 页面创建一个新 key
3. 把 key 写到 `$SKILL_DIR/secrets/mimo_api_key` 文件（首行，无 BOM 无尾随换行以外的空白）

```bash
mkdir -p "$SKILL_DIR/secrets"
echo "YOUR_MIMO_API_KEY_HERE" > "$SKILL_DIR/secrets/mimo_api_key"
chmod 600 "$SKILL_DIR/secrets/mimo_api_key"
```

**不配置也不影响有字幕的视频**——脚本优先用 B 站字幕 / AI 字幕，ASR 只在两者都拿不到时才启动。

## 快速上手

详细工作流见 [`SKILL.md`](./SKILL.md)。核心命令：

```bash
SKILL_DIR=/path/to/bilibili-subtitle-download-skill
cd "$SKILL_DIR"
PYTHONIOENCODING=utf-8 python scripts/download_and_chunk.py <BV_ID>
```

首次运行会要求扫码登录 B 站（cookie 写入 `$SKILL_DIR/secrets/bilibili_cookie.txt`）。

## 测试

```bash
pip install pytest pytest-asyncio
python3 -m pytest tests/
```

46 个测试，包括 2 个真调 MiMo ASR 的集成测试（需要在 `secrets/mimo_api_key` 放真 key）。
