import os
import sys
import json
import re
import asyncio
from pathlib import Path
import requests
from bilibili_api import login_v2, Credential

try:
    from scripts.asr_fallback import run_asr
except ImportError:
    # 当 download_and_chunk.py 被作为 __main__ 直接运行（非 -m scripts.download_and_chunk）时,
    # scripts 包的相对 import 会失败。fallback: 把 scripts/ 父目录加到 sys.path,
    # 这样 scripts 就成了 namespace package, scripts.asr_fallback 等子模块都可正常 import
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from scripts.asr_fallback import run_asr

# Configuration
# 所有凭证/中间产物路径都相对于 skill 安装根目录 (<skill_root>):
#   COOKIE_FILE     = <skill_root>/secrets/bilibili_cookie.txt
#   QR_IMAGE_PATH   = <skill_root>/secrets/bilibili_login_qr.png
SKILL_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = SKILL_ROOT / "secrets"
COOKIE_FILE = str(SECRETS_DIR / "bilibili_cookie.txt")
QR_IMAGE_PATH = str(SECRETS_DIR / "bilibili_login_qr.png")
CHARS_PER_CHUNK = 100000
OUTPUT_DIR_FALLBACK = os.path.join('bili_temp', '{bv_id}')  # 占位符, main() 替换

def clean_filename(title):
    return re.sub(r'[\\/:*?"<>|]', '_', title)

def get_saved_cookie():
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'r') as f:
            return f.read().strip()
    return ""

async def login_with_qr():
    qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
    await qr.generate_qrcode()
    
    # Save QR code image for user to scan
    pic = qr.get_qrcode_picture()
    pic.to_file(QR_IMAGE_PATH)

    print(f"QR_CODE_READY:{QR_IMAGE_PATH}", flush=True)
    print("老大，请扫描这个二维码登录喵！🐾", flush=True)
    
    # Wait for login
    while not qr.has_done():
        state = await qr.check_state()
        if state == login_v2.QrCodeLoginEvents.DONE: # Success
            break
        await asyncio.sleep(2)
    
    credential = qr.get_credential()
    cookies = credential.get_cookies()
    
    # Save cookies to file in string format for general HTTP requests
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    with open(COOKIE_FILE, 'w') as f:
        f.write(cookie_str)
    
    if os.path.exists(QR_IMAGE_PATH):
        os.remove(QR_IMAGE_PATH)
        
    return cookie_str

def get_video_info(bv_id, cookie):
    url = "https://api.bilibili.com/x/web-interface/view"
    params = {'bvid': bv_id}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
        'Cookie': cookie
    }
    resp = requests.get(url, params=params, headers=headers)
    data = resp.json()
    if data['code'] != 0:
        # If cookie invalid, code might be -101
        return None, data['message']
    return data['data'], None

def fetch_subtitle_content(bv_id, cid, cookie):
    """
    Fetch subtitles from Bilibili API. Supports both user-uploaded and AI-generated subtitles.
    - User subtitles: lan='zh' (Chinese)
    - AI subtitles: lan='ai-zh' (AI-generated Chinese)
    Both have signed URLs with auth_key that can be directly accessed.
    """
    subtitle_api = 'https://api.bilibili.com/x/player/wbi/v2'
    headers = {
        'authority': 'api.bilibili.com',
        'accept': 'application/json, text/plain, */*',
        'origin': 'https://www.bilibili.com',
        'referer': 'https://www.bilibili.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Cookie': cookie
    }
    params = {'bvid': bv_id, 'cid': cid}
    resp = requests.get(subtitle_api, headers=headers, params=params)
    data = resp.json()

    if data.get('code') != 0:
        return None, None

    subtitles = data.get('data', {}).get('subtitle', {}).get('subtitles', [])
    if not subtitles:
        return None, None

    # Priority: user Chinese (zh) > AI Chinese (ai-zh) > any first
    target_url = None
    subtitle_type = None  # 'user' or 'ai'

    # First pass: prefer user Chinese subtitle
    for s in subtitles:
        lan = s.get('lan', '')
        if lan == 'zh':
            target_url = s.get('subtitle_url')
            subtitle_type = 'user'
            break

    # Second pass: fallback to AI Chinese subtitle
    if not target_url:
        for s in subtitles:
            lan = s.get('lan', '')
            if lan == 'ai-zh':
                target_url = s.get('subtitle_url')
                subtitle_type = 'ai'
                break

    # Third pass: any available subtitle
    if not target_url and subtitles:
        target_url = subtitles[0].get('subtitle_url')
        subtitle_type = 'user'

    if not target_url:
        return None, None

    if target_url.startswith('//'):
        target_url = 'https:' + target_url

    resp = requests.get(target_url, timeout=30)
    body = resp.json().get('body', [])
    full_text = "\n".join([b.get('content', '') for b in body])
    return full_text, subtitle_type


def fetch_ai_subtitle(bv_id, cid, cookie):
    """
    This function is kept for backward compatibility.
    AI subtitles are now fetched directly in fetch_subtitle_content().
    """
    return None  # Not needed anymore

async def main(argv=None):
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        print("Usage: python3 download_and_chunk.py <BV_ID> [P_NUM]")
        sys.exit(1)

    bv_id = argv[1]
    p_num = int(argv[2]) if len(argv) > 2 else 0

    print(f"[*] Processing {bv_id} (P{p_num})...🐾", flush=True)

    try:
        cookie = get_saved_cookie()
        info = None

        if cookie:
            info, err = get_video_info(bv_id, cookie)

        # If no cookie or cookie expired/invalid
        if not info:
            cookie = await login_with_qr()
            info, err = get_video_info(bv_id, cookie)
            if not info:
                raise Exception(f"Failed to get video info even after login: {err}")

        # Get CID for the requested Part
        pages = info.get('pages', [])
        if p_num >= len(pages):
            raise Exception(f"Invalid P_NUM: video only has {len(pages)} parts.")
        cid = pages[p_num]['cid']

        # Try fetching subtitle (supports both user and AI subtitles)
        full_text, subtitle_type = fetch_subtitle_content(bv_id, cid, cookie)

        if not full_text:
            # 优先检查 cookie (ASR 需要)
            if not cookie:
                print("ERROR: 没找到字幕喵, 且无 cookie 文件, 无法走 ASR fallback...😿")
                print(f"       请先登录以生成 cookie: {COOKIE_FILE}")
                sys.exit(1)

            print("[*] 没找到用户/AI字幕, 尝试 ASR fallback 🐾", flush=True)
            output_dir = os.path.join(os.getcwd(), OUTPUT_DIR_FALLBACK.format(bv_id=bv_id))
            try:
                asr_result = run_asr(bv_id, p_num, output_dir, cookie_path=COOKIE_FILE)
            except Exception as e:
                print(f"ERROR: ASR fallback 失败: {e}")
                sys.exit(1)

            print(f"[*] ASR 完成, 分 {asr_result['segments_count']} 段, 写 {len(asr_result['chunks'])} 个 chunk")
            print("RESULT_JSON:" + json.dumps({
                "bv_id": bv_id,
                "title": info.get('title', bv_id),
                "total_chars": asr_result["total_chars"],
                "chunks": asr_result["chunks"],
                "method": "asr_fallback",
            }))
            return

        if subtitle_type == 'ai':
            print("[*] 检测到AI字幕并获取成功！🐾", flush=True)

        title = info.get('title', bv_id)
        total_chars = len(full_text)

        # Create output dir in workspace using BV_ID
        output_dir = os.path.join(os.getcwd(), OUTPUT_DIR_FALLBACK.format(bv_id=bv_id))
        os.makedirs(output_dir, exist_ok=True)
        
        chunks = []
        for i in range(0, total_chars, CHARS_PER_CHUNK):
            chunk_content = full_text[i : i + CHARS_PER_CHUNK]
            chunk_index = i // CHARS_PER_CHUNK
            chunk_file = os.path.join(output_dir, f"{bv_id}_chunk_{chunk_index}.txt")
            with open(chunk_file, 'w', encoding='utf-8') as f:
                f.write(chunk_content)
            chunks.append(chunk_file)
            
        print(f"[*] Success. Total chunks: {len(chunks)}")
        print("RESULT_JSON:" + json.dumps({
            "bv_id": bv_id,
            "title": title,
            "total_chars": total_chars,
            "chunks": chunks
        }))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
