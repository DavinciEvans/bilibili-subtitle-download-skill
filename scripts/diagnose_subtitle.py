"""
诊断为什么 download_and_chunk.py 拿不到字幕。
区分三种情况:
  1. UP 主关闭字幕投稿 (allow_submit=false)
  2. AI 字幕还没生成 (排队中)
  3. 脚本/cookie/API 端问题

用法:
  python scripts/diagnose_subtitle.py <BV_ID> [--cid CID]

输出:
  - 4 种 API 组合 (匿名/带cookie × player/v2/player/wbi/v2) 的字幕块
  - 页面 __INITIAL_STATE__.videoData.subtitle (如果是浏览器模式, 见下)
  - 判断结论 + 推荐下一步动作

不依赖浏览器; 如需浏览器嵌入态确认, 手动在 DevTools 读:
  window.__INITIAL_STATE__.videoData.subtitle
"""
import json
import sys
import argparse
from pathlib import Path

import requests

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
REF = 'https://www.bilibili.com/'


def get_cookie():
    """从 skill 安装根目录的 secrets 目录读 cookie"""
    skill_root = Path(__file__).resolve().parent.parent
    cookie_file = skill_root / 'secrets' / 'bilibili_cookie.txt'
    if cookie_file.exists():
        return cookie_file.read_text().strip()
    return ''


def probe(label, cookie, url, params):
    headers = {'User-Agent': UA, 'Referer': REF}
    if cookie:
        headers['Cookie'] = cookie
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        j = r.json()
    except Exception as e:
        return {'label': label, 'error': str(e)}
    sub = (j.get('data') or {}).get('subtitle') or {}
    return {
        'label': label,
        'code': j.get('code'),
        'msg': j.get('message'),
        'lan': sub.get('lan'),
        'allow_submit': sub.get('allow_submit'),
        'count': len(sub.get('subtitles') or []),
        'first_subtitle': (sub.get('subtitles') or [None])[0],
    }


def diagnose(bv_id, cid=None):
    cookie = get_cookie()

    # 1. 拿 cid
    info = requests.get(
        'https://api.bilibili.com/x/web-interface/view',
        params={'bvid': bv_id},
        headers={'User-Agent': UA, 'Referer': REF, 'Cookie': cookie},
        timeout=15,
    ).json()
    if info.get('code') != 0:
        print(f'❌ video info 失败: {info.get("message")}')
        sys.exit(1)

    data = info['data']
    print(f'标题: {data.get("title")}')
    print(f'UP: {data.get("owner", {}).get("name")}')
    print(f'发布时间: {data.get("pubdate")}')
    print(f'cid: {data["pages"][0]["cid"]}')
    if cid is None:
        cid = data['pages'][0]['cid']

    # 2. 4 种组合探测
    print('\n=== API 探测 ===')
    results = []
    for label, has_cookie in [('A: 匿名 player/v2', False),
                               ('B: 带 cookie player/v2', True),
                               ('C: 匿名 player/wbi/v2', False),
                               ('D: 带 cookie player/wbi/v2', True)]:
        _, ck = label.split(': ', 1)
        _, endpoint = ck.split(' ', 1)
        c = cookie if has_cookie else ''
        url = f'https://api.bilibili.com/x/player/{endpoint}'
        r = probe(label, c, url, {'bvid': bv_id, 'cid': cid})
        results.append(r)
        print(f'\n--- {label} ---')
        for k in ('code', 'msg', 'lan', 'allow_submit', 'count'):
            print(f'  {k}: {r.get(k)}')
        if r.get('first_subtitle'):
            print(f'  first: {r["first_subtitle"]}')

    # 3. 判断
    print('\n=== 诊断 ===')
    any_count = any(r.get('count', 0) > 0 for r in results)
    any_allow = any(r.get('allow_submit') for r in results)

    if any_count:
        print('✅ 至少一个 API 返回了字幕列表 → 脚本 bug 或 cookie 失效')
        print('   检查: download_and_chunk.py 是否带 cookie, SESSDATA 是否过期')
        return

    if not any_allow and all(r.get('allow_submit') is False for r in results):
        print('🚫 所有 API 都返回 allow_submit=false, 字幕列表为空')
        print('   → UP 主在投稿设置里关了字幕投稿, B 站不会再生成 AI 字幕')
        print('   → 这是 B 站服务端事实, 不是脚本问题')
        print('   → 如需字幕, 唯一路径是 ASR fallback 或等别人上传野生字幕')
        return

    print('⏳ 字幕列表为空, 但 allow_submit=true')
    print('   → AI 字幕可能还在排队生成 (通常发布后几分钟到几小时)')
    print('   → 建议: 等 30 min ~ 2h 重试 download_and_chunk.py')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('bv_id', help='e.g. BV18Rji6FEc3')
    p.add_argument('--cid', type=int, default=None)
    args = p.parse_args()
    diagnose(args.bv_id, args.cid)


if __name__ == '__main__':
    main()
