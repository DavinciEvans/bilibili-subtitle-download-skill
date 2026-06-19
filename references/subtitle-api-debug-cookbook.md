# B站字幕 API Debug Cookbook

诊断 "脚本拿到 ASR fallback，但用户说有字幕" 或 "字幕 API 返回空数组" 这类问题的快速参考。基于 2026-06 会话的真实调试记录。

## 1. 四个真相来源，按权威性排序

| # | 来源 | URL / 命令 | 权威性 | 备注 |
|---|---|---|---|---|
| 1 | B站前端嵌入的 SSR initial state | 浏览器打开视频页 → DevTools console: `window.__INITIAL_STATE__.videoData.subtitle` | **最高** | 这是页面渲染时的服务端真值，浏览器 cookie + buvid 都带全 |
| 2 | 浏览器原生 fetch 字幕 API（带完整 buvid/bili_ticket） | `fetch('https://api.bilibili.com/x/player/wbi/v2?bvid=...&cid=...', {credentials:'include'})` | 高 | 同源 + 完整 cookie + 完整 header |
| 3 | 带登录态 SESSDATA 的脚本 HTTP 请求 | Python `requests.get(...)` 带 cookie 文件 | 中 | 取决于 cookie 有效性 + 必要 header 完整性 |
| 4 | 匿名 HTTP 请求 | 不带 cookie | 低 | 部分视频允许匿名取字幕，但不是全部 |

**经验法则**：1 和 2 一致说"没字幕" → 服务端真的没挂；3 和 4 也一致 → 不是脚本问题；1/2 有但 3/4 没有 → **脚本侧的 cookie/header 问题**（最常见就是 cookie 失效，见下文）。

## 2. 字幕 API 的响应字段含义

```json
{
  "code": 0,
  "message": "OK",
  "data": {
    "subtitle": {
      "allow_submit": false,        // UP 主是否允许字幕投稿
      "lan": "",                    // 默认字幕语言（空 = 没有默认）
      "lan_doc": "",
      "subtitles": [                // 可用字幕列表
        {
          "id": 1234567890,
          "lan": "zh",              // 用户字幕
          "lan_doc": "中文",
          "subtitle_url": "//aisubtitle.bilibili.com/...?auth_key=...",
          "type": 0,
          "ai_type": 0,             // 0 = 非 AI, 1 = AI 字幕
          "author": {...}
        },
        {
          "lan": "ai-zh",           // AI 字幕
          "ai_type": 1,
          "subtitle_url": "..."
        }
      ]
    }
  }
}
```

**关键字段判断**：
- `subtitles: []` + `allow_submit: false` → UP 主关字幕（最常见）
- `subtitles: []` + `allow_submit: true` → 视频刚发布，AI 字幕排队生成中（等几分钟到几小时）
- `subtitles: [{lan: "ai-zh", ai_type: 1}]` → 有 AI 字幕，脚本应取这条
- `subtitles: [{lan: "zh", ai_type: 0}]` → 有用户上传字幕

## 3. Cookie 失效的诊断

**症状**：`player/v2` 和 `player/wbi/v2` 都返回 `subtitles: []`，但浏览器前端明明能看到字幕。

**根因**：脚本只看 cookie 文件存在+非空，没验证登录态。

**快速诊断**：
```python
import requests
cookie = open('<skill_root>/secrets/bilibili_cookie.txt').read().strip()
r = requests.get('https://api.bilibili.com/x/web-interface/nav',
                  headers={'Cookie': cookie,
                           'User-Agent': 'Mozilla/5.0 ...',
                           'Referer': 'https://www.bilibili.com/'})
data = r.json()
print(f"code={data['code']}, isLogin={data['data']['isLogin']}")
# code=0 + isLogin=True → 登录态 OK
# code=-101 → 失效
```

**关键观察**：B站对失效 cookie 的处理是**静默**——`player/v2` 和 `player/wbi/v2` 不会返回错误码，而是返回空 `subtitles: []`，跟"UP 主没挂字幕"长得一模一样。只有 `/x/web-interface/nav` 会显式返回 `-101`。

## 4. QR 登录流程的陷阱

**症状**：脚本卡在 QR 等待状态，但 cookie 文件始终没生成。后台脚本 `check_state()` 一直返回 `QrCodeLoginEvents.SCAN`，2-3 分钟后服务端返回 `TIMEOUT`。

**常见原因**：
1. **PTY 超时杀掉进程**：用 `pty=true` + `timeout=90` 调用脚本，到时间 pty 给进程发 SIGTERM，QR 等待循环被打断
2. **二维码被微信压缩/缓存**：发给用户的 PNG 被微信压缩后扫不上
3. **B 站风控**：频繁生成 QR 触发 web 端风控，建议间隔几分钟再试
4. ⭐ **用户只扫了码没在 app 点确认**（最常被忽略！）：B 站 web QR 登录是 **3 步流程**——(a) app 扫码 → (b) **app 弹授权页，用户必须点"登录/确认/授权"按钮** → (c) 服务端返回 DONE。**只有步骤 (a) 完成时，服务端状态是 `SCAN`，2 分钟内无 `CONF` 就会 `TIMEOUT`**。

**正确姿势**：
- 用 `terminal(background=true, notify_on_complete=true)` 跑脚本，不要用 pty + timeout
- 监听 `secrets/bilibili_cookie.txt` 出现作为登录完成的信号
- 二维码始终发**最新生成的那张**，明确告诉用户"之前的不算数"
- 发 QR 时**必须**在消息里写明 3 步流程（参考 SKILL.md pitfall "B 站 web QR 登录是 3 步流程" 的提示模板），用户缺第 2 步是 90% 失败的原因

**验证 QR 状态机（`bilibili-api-python` 17.4.1）**：
```python
from bilibili_api import login_v2
qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
await qr.generate_qrcode()
qr_link = qr._QrCodeLogin__qr_link   # 双下划线 name-mangling 后才能拿
qr_key  = qr._QrCodeLogin__qr_key
# 状态: SCAN (已扫等确认) → CONF (已确认等认证) → DONE (完成) 或 TIMEOUT (2 分钟)
```

**反模式**：看到 `SCAN` 就以为"登录成功了一半，cookie 马上就来"——实际上 `SCAN` 持续 2 分钟无 `CONF` 必然 `TIMEOUT`，必须立刻提醒用户在 app 里点确认。

## 5. 浏览器端 "暂无字幕" 的 DOM 标志

打开视频页后，在 DevTools console 跑：
```js
const nolan = document.querySelector('.bpx-player-ctrl-subtitle-nolan');
console.log(nolan?.innerText);  // "暂无字幕"
const subs = document.querySelectorAll('.bpx-player-ctrl-subtitle-major-content > *');
console.log(`主字幕条数: ${subs.length}`);
```

如果 `nolan` 显示"暂无字幕" + 主字幕条数 = 0 + `__INITIAL_STATE__.videoData.subtitle.list: []` → **服务端真的没挂任何字幕**，**不是脚本问题**。

## 6. ASR fallback 不是"找不到字幕"的唯一解释

ASR fallback 触发的常见原因（按概率排）：

1. **脚本侧 cookie 失效**（最常见，占 50%+）— 见 §3
2. **UP 主关闭字幕投稿** — `allow_submit: false`
3. **视频刚发布，AI 字幕排队中** — 等几小时重试
4. **真的没字幕** — 老视频、UP 主没开 AI

诊断时**必须先排除 1**，因为它会伪装成"没字幕"。直接跑 ASR 是浪费（慢、贵、有幻觉）。

## 7. 用户给 ground truth 时的诊断反模式

**症状**：用户贴截图说"我本地拿到了字幕 (source=subtitle)"，但 agent 仍坚持"我四路证据都说没字幕"。用户挫败 → "你怎么这么犟呢"。

**反模式**：用自己环境的 4 路证据替代用户的真实证据。

**正确做法**：
1. 用户给的截图/log/命令 → **立即承认自己环境的差异**（cookie/IP/buvid/endpoint 都可能不同）
2. 列 agent 能复现的细节
3. 请用户补充 agent 看不到的：脚本路径/源码/commit/API endpoint/header
4. 让用户证据成为新起点（"他的脚本走的是哪个 endpoint 我没试过"），不要继续推自己结论

**经验**：用户的 ground truth 优先级 > agent 的间接证据。agent 自己看到的"4 路证据一致"只覆盖**自己的执行环境**，不是用户的。
