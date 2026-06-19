---
name: bilibili-subtitle-downloader
description: 下载 Bilibili 视频字幕，将其进行分块以供 LLM（大语言模型）处理，并生成高质量的总结。当用户提供 Bilibili BV 号或 URL，并希望获取视频内容的总结、核心要点或详细的分解时使用。
---

# Bilibili 字幕下载器技能

此技能通过使用专用的 Python 脚本和子智能体 (sub-agent) 编排，自动化提取和总结 Bilibili 视频字幕的流程。

## 前置依赖

首次使用需安装依赖：
```bash
pip install bilibili-api-python
```

## 支持的字幕类型

| 字幕类型 | 字段 | 支持状态 |
|----------|------|----------|
| 用户上传字幕 | `lan='zh'` | ✅ 完全支持 |
| AI 自动字幕 | `lan='ai-zh'` | ✅ 完全支持 |
| 无字幕 → ASR 语音识别 | — | ✅ 自动 fallback (MiMo-V2.5-ASR) |

## 工作流程

> **路径解析**：本 skill 的所有脚本、cookie、key、二维码临时图都位于同一个目录树下——skill 的**安装根目录**（即 `SKILL.md` 所在的目录）。**你（LLM）执行命令前请先确定这个根目录的绝对路径**，把它设成 `SKILL_DIR` 环境变量再 `cd` 进去——例如 `SKILL_DIR=/home/hfun/.hermes/skills/media/bilibili-subtitle-downloader`（路径以实际安装位置为准）。
>
> 一种自解析方式：把下方命令保存为脚本文件并 `bash` 执行时，`$0` 会指向脚本自身，进而推出 skill 根：
> ```bash
> SKILL_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
> ```
> 或者更简单：你直接根据当前会话上下文知道 skill 安装在哪，把绝对路径写进 `SKILL_DIR` 即可。

1.  **提取字幕**: 运行脚本来下载并分块字幕。普通视频均为 BV 号开头
    ```bash
    SKILL_DIR=<绝对路径，到 SKILL.md 所在目录>   # 例如 /home/hfun/.hermes/skills/media/bilibili-subtitle-downloader
    cd "$SKILL_DIR"
    PYTHONIOENCODING=utf-8 python scripts/download_and_chunk.py <BV_ID>
    ```
    * **登录检查**: 如果脚本输出 `QR_CODE_READY:<PATH>`，需要扫码登录。Cookie 保存到 `$SKILL_DIR/secrets/bilibili_cookie.txt`
    * **字幕检测**: 脚本优先获取用户字幕（`zh`），若无则获取 AI 字幕（`ai-zh`）

2.  **处理输出**: 解析脚本输出的 `RESULT_JSON`，分块文件命名格式：
    * 普通视频 (BV号): `bili_temp/<BV_ID>/<BV_ID>_chunk_0.txt`
    * 课程剧集 (EP号): `bili_temp/<EP_ID>/chunk_0.txt`

## Bilibili 课程 (Cheese) 工作流程

1.  **提取课程/剧集信息**: 使用课程专属脚本
    ```bash
    SKILL_DIR=<绝对路径，到 SKILL.md 所在目录>
    cd "$SKILL_DIR"
    PYTHONIOENCODING=utf-8 python scripts/cheese_downloader.py <SS_ID or EP_ID>
    ```
    * **登录**: 脚本将生成 `bilibili_login_qr.png` 二维码
    * **SS_ID 模式**: 打印课程信息和剧集列表，需用 EP_ID 获取字幕
    * **EP_ID 模式**: 下载字幕并切分保存到 `bili_temp/ep456/` 目录

## 无字幕视频的 ASR Fallback

当视频没有用户字幕（`zh`）也没有 AI 字幕（`ai-zh`）时，`download_and_chunk.py` 会自动调用 MiMo-V2.5-ASR 进行语音识别。

### 流程
1. 下载 192kbps 音轨到临时目录
2. VAD 分段（webrtcvad，失败降级硬切）
3. 逐段调 MiMo ASR（base64 后必须 ≤ 10MB，所以 1-3 min/段）
4. 段间去重（最长公共子串）
5. 输出**纯识别文本** chunk 文件（无时间戳，段间换行）

### 前置条件
- 已登录（cookie 文件 `$SKILL_DIR/secrets/bilibili_cookie.txt` 存在）

### 配置
- **API key 解析优先级**（从高到低）：
  1. `transcribe_wav(api_key=...)` 函数参数
  2. 环境变量 `MIMO_API_KEY`
  3. key 文件 `$SKILL_DIR/secrets/mimo_api_key`（首行非空内容，自动 strip）
- cookie 文件：`$SKILL_DIR/secrets/bilibili_cookie.txt`
- 输出文件名前缀 `<BV_ID>_chunk_N.txt`，内容为各段去重后的纯识别文本，段间用换行分隔（**无时间戳**）

### RESULT_JSON method 字段
- `"subtitle"` — 来自 B 站字幕 API（用户或 AI 字幕）
- `"asr_fallback"` — 来自 ASR 语音识别

### 注意事项
- MiMo ASR 在静音/纯音输入上会返回幻觉中文文本（无语音时的占位行为）。生产场景（真实语音）不会触发。
- 跨段去重只去字符级重叠，不处理同义复述。
- ASR 调用当前串行；如遇 429 限流可改并发。

## ⚠️ Pitfall: 用户说"应该有字幕"但脚本 fallback 到 ASR

脚本看不到字幕 ≠ 脚本有 bug。B 站字幕接口的常见空响应原因，按出现概率排：

| 场景 | 信号 | 解释 |
|---|---|---|
| UP 主关闭字幕投稿 | `data.subtitle.allow_submit: false` + `data.subtitle.list: []`（页面 `__INITIAL_STATE__.videoData.subtitle` 也有这个字段） | UP 主在投稿设置里关了"允许字幕投稿"，AI 字幕通常也不会再生成 |
| 视频刚发布，AI 字幕排队中 | `allow_submit` 未关、但 `subtitles: []`，发布时间 < 1 小时 | B 站 AI 字幕是异步生成，发布后可能要等几分钟到几小时 |
| 用户记忆错误 | 上述两种信号都没有 | 用户可能把别的视频记混了，或误把野生字幕当作官方 AI 字幕 |

**判断步骤**（用户质疑时跑一遍，不要直接重跑脚本）：
1. 浏览器打开视频页 `https://www.bilibili.com/video/<BV>/`，DevTools console 读 `window.__INITIAL_STATE__.videoData.subtitle`：
   - `list: []` 且 `allow_submit: false` → **UP 主关了**，告诉用户
   - `list: []` 但 `allow_submit: true` → **排队中**，建议等几小时重试
   - `list` 非空 → 走 step 2 排查脚本
2. 直接 fetch `https://api.bilibili.com/x/player/v2?bvid=<BV>&cid=<CID>`（带登录 cookie）：
   - `data.subtitle.subtitles` 非空 → 脚本 bug，提交 issue
   - 仍然空 → B 站服务端确认无字幕，回报用户即可

**快捷探针**：见 `scripts/diagnose_subtitle.py`，一次性输出 4 种 API 组合 + 页面 initial_state 的字幕状况，区分"脚本没找到"vs"B站真没挂"vs"UP主关了"。

**反模式**：脚本输出"没找到字幕，尝试 ASR fallback"就直接报告给用户。要先排除上面 3 种情况再决定是否走 ASR——ASR 慢、贵、有幻觉，对其实有 AI 字幕的视频是浪费。

## ⚠️ Pitfall: cookie 文件存在 ≠ 登录态有效 → 字幕 API 静默返回空

**症状**：用户说"这个视频应该有 AI 字幕，我本地能拿到"，但脚本 fallback 到 ASR。手动跑 `player/v2` 或 `player/wbi/v2` 也都返回 `subtitles: []`。

**根因**：脚本原本只看 `if cookie:`（cookie 文件存在 + 非空字符串），就认为登录态 OK，直接拿失效 cookie 调 API。B 站对失效 cookie 的处理：

- `player/v2` 和 `player/wbi/v2` **不会**返回错误码，而是**静默返回空 `subtitles: []`** —— 跟"UP 主没挂字幕"长一样
- 只有 `/x/web-interface/nav` 会返回 `-101 账号未登录` 这个明确错误码
- 这导致脚本流程走到 fallback 而不是 QR 登录，用户"扫了码也没用"——因为脚本根本没进 QR 流程

**诊断命令**（怀疑 cookie 失效时第一时间跑）：
```python
import requests
r = requests.get('https://api.bilibili.com/x/web-interface/nav',
                  headers={'Cookie': '<从 secrets/bilibili_cookie.txt 读>',
                           'User-Agent': 'Mozilla/5.0 ...'})
print(r.json())  # 看 code: 0 = 登录态 OK; code: -101 = 失效
```

**修复**（已合入 main）：`scripts/download_and_chunk.py` 加 `check_login(cookie)` 函数，调用 `/x/web-interface/nav` 校验 `code==0 and isLogin==True`，失效则删除 cookie 文件并强制重新 QR 登录。修复后入口逻辑：

```python
if cookie:
    info, err = get_video_info(bv_id, cookie)
    if check_login(cookie):
        cookie_is_fresh = True
    else:
        os.remove(COOKIE_FILE)  # 失效就删, 别让下次也踩坑

if not cookie or not cookie_is_fresh or not info:
    cookie = await login_with_qr()  # 真的会等扫码
```

**给用户的诊断流程**（用户质疑"应该有字幕"时）：
1. **第一步先看 nav**：cookie 失效是最常见的原因，不要直接相信脚本输出
2. 失效 → 删 cookie 文件 → 让脚本重扫 → 拿新 cookie 重跑
3. 仍然空 → 才进入上面"UP 主关了 / 排队中"的判断

**反模式**：cookie 文件存在就跳过去分析脚本逻辑。SESSDATA 即使没到期，也会被风控/IP 变更/风控指纹等判定为失效，**唯一可靠的真值来源是 `/nav` 接口**。

## ⚠️ Pitfall: 扫码登录流程被 pty 超时打断 → 二维码反复刷新误导用户

**症状**：脚本首次发现 cookie 失效，生成 QR 二维码等用户扫；但因为用 pty/前台 `timeout` 命令调用（默认 30-120s），扫码窗口还没来得及完成 cookie 写入，进程就被 kill。脚本下次重跑又重新生成 QR，**用户看到的"新二维码"其实是脚本被重启后生成的，跟上次扫的完全不一样**。用户原话："扫了！扫了！"但 cookie 文件从未生成。

**根因**：`login_with_qr()` 是个 `async` 循环 `await qr.check_state()`，依赖外部（用户扫手机）触发状态变更。pty/前台超时把循环直接砍断，QR 流程没机会走到 `qr.has_done() == True` 分支。

**修复**：QR 登录流程必须用 `terminal(background=true, notify_on_complete=true)` 跑，**不要用 pty=true + timeout**：

```bash
# 错（前台 pty 超时会杀掉 QR 等待循环）
PYTHONIOENCODING=utf-8 timeout 90 python scripts/download_and_chunk.py <BV>

# 对（后台跑，cookie 文件出现后再 poll 或 notify）
PYTHONIOENCODING=utf-8 python -u scripts/download_and_chunk.py <BV> > /tmp/login.log 2>&1
# 然后用 process(action='wait') 或监听 secrets/bilibili_cookie.txt 出现
```

或者把 QR 流程拆成独立子命令 `scripts/login_qr.py`，跑完立刻写 cookie，不混入字幕流程。

**用户感知反模式**：连续发 4-5 张不同时间戳的二维码给用户 → 用户不知道哪张才是有效的 → 扫码确认也匹配不上。**始终只发最新生成的那一张，并明确告诉用户 "扫这张，之前的已过期"**。

**给 LLM 自己的反模式**：cookie 文件不存在的连续多轮里，**不要反复重跑主流程脚本**（每次都会生成新 QR）。应该：
1. 一次后台拉起脚本
2. 监控 `secrets/bilibili_cookie.txt` 是否出现
3. 出现后立即用新 cookie 跑字幕验证

## ⚠️ Pitfall: B 站 web QR 登录是 3 步流程，扫码 ≠ 完成

**症状**：用户说"扫了！扫了！"但 cookie 文件一直没生成。后台脚本状态停在 `QrCodeLoginEvents.SCAN` 长达 3 分钟，最后服务端返回 `TIMEOUT`。

**根因**：B 站 web 端 QR 登录是**完整 3 步流程**：
1. ✅ B 站 app 扫码 → 服务端从无状态变 `SCAN`
2. ⭐ **app 弹授权页，必须在 app 上点"登录/确认/授权"按钮** → 服务端从 `SCAN` 变 `CONF`
3. 服务端变 `DONE` → 脚本写 cookie 文件

**agent 的盲区**：只看服务端 `SCAN` 状态就以为"扫码成功了"，没意识到这其实是**半完成状态**。`SCAN` 持续 2 分钟无 `CONF`，B 站服务端自动 `TIMEOUT`，二维码作废。

**判定状态的 `bilibili-api-python` 接口**（lib 17.4.1）：
```python
from bilibili_api import login_v2
qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
await qr.generate_qrcode()
qr_link = qr._QrCodeLogin__qr_link  # 双下划线私有, name-mangling 后才能拿
qr_key = qr._QrCodeLogin__qr_key

# 状态枚举（按顺序）
# QrCodeLoginEvents.SCAN    = 已扫码, 等用户点确认 (常见卡点!)
# QrCodeLoginEvents.CONF    = 用户已点确认, 等服务端认证
# QrCodeLoginEvents.DONE    = 完成, 可 get_credential()
# QrCodeLoginEvents.TIMEOUT = 2 分钟无动作, 二维码作废
```

**给用户的提示模板**（发 QR 时必须说清楚）：
```
登录流程（3 步，别漏第 2 步）：
1. 用 B 站 app 扫下面的图
2. 扫完后 app 会弹出"是否登录 bilibili.com 网页版"的授权页
   ⭐ 必须在这个页面点 "登录" / "授权" / "确认" 按钮
3. 脚本自动写 cookie 继续
```

**反模式**：只说"扫码登录"，用户只扫了码没点确认 → 永远卡在 `SCAN` 状态 → 二维码 2 分钟后 `TIMEOUT` → 用户挫败感拉满。

## ⚠️ Pitfall: 用户给 ground truth（截图/本地日志）时立即放弃自己的诊断

**症状**：用户贴出截图证明 "我本地用 `summarize_video.py` 拿到了字幕 (source=subtitle)"，但 agent 仍坚持"四路证据（API/initial_state/DOM/UI）都说没字幕"。这是 confirmation bias。

**根因**：agent 收集到的"四路证据"只覆盖**自己**的执行环境（mac/linux cookie 文件、匿名 fetch、浏览器无痕），但**用户的执行环境不同**：
- 用户可能是 Windows、不同的 cookie、不同 IP/buvid 指纹
- 用户的脚本可能调的是 agent 没尝试的 endpoint
- 用户的脚本可能加签名 `w_rid` 等 agent 漏掉的 header

**规则**（写下来以免下次再犯）：
1. 用户提供截图/log/复现命令 → **立即承认差异** + 列出我能复现的细节 + 请用户补充我无法看到的（脚本路径/源码/commit/API endpoint）
2. **不要先解释自己为啥对**——用户的 ground truth 优先级永远高于 agent 的间接证据
3. 让用户的证据成为新的诊断起点（"他/她的脚本走的是哪个 endpoint？我没试过这个"），而不是继续推自己之前的结论

**反模式**：收到用户反驳后回复"但是我有 4 路证据..."。Falsification-first：假设自己错了，然后找差异点。

## 子智能体指令

在生成总结的子智能体时，请使用以下 prompt 模式：

> 请阅读以下 Bilibili 视频字幕分块，并提供全面、准确的总结。
>
> **要求：**
> - 捕获所有关键的技术细节、具体的数据点和逻辑步骤
> - 使用标题保持清晰的结构
> - 明确主旨和可执行的要点
> - 风格：专业，信息丰富且详细
>
> **字幕文件：** [PATH_TO_CHUNK]

## 资源

- **脚本**: `scripts/download_and_chunk.py` - 处理 Bilibili API 交互和基于 Token 的安全分块
- **诊断脚本**: `scripts/diagnose_subtitle.py` - 当用户质疑"应该有字幕但脚本没拿到"时跑这个，4 种 API 组合 + 浏览器 initial_state 诊断，区分"UP 主关了 / 排队中 / 脚本 bug"
- **API Debug Cookbook**: `references/subtitle-api-debug-cookbook.md` - 4 路真相来源的权威性排序 + 响应字段含义 + cookie 失效诊断 + QR 流程陷阱 + DOM "暂无字幕" 标志 + ASR fallback 触发原因
- **依赖**: `bilibili-api-python` (包名变更，原 `bilibili-api` 已停更)
