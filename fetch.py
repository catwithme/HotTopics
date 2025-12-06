# fetch_split.py
# 修改说明：将微博热搜和B站热榜分开发送钉钉，便于排查钉钉内容安全拦截问题
# 依赖：requests
# 钉钉关键词：热点

import os
import time
import datetime
import re
import requests

DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")
if not DINGTALK_WEBHOOK:
    raise SystemExit("Error: environment variable DINGTALK_WEBHOOK not set")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

def clean_text(text):
    """清洗标题文本，去掉零宽字符、不可见字符等"""
    if not text:
        return ""
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    text = ''.join(c for c in text if c.isprintable())
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def get_beijing_time_str():
    utc_now = datetime.datetime.utcnow()
    bj_now = utc_now + datetime.timedelta(hours=8)
    return bj_now.strftime("%Y-%m-%d %H:%M:%S")

def fetch_weibo_top(n=15):
    url = "https://v2.xxapi.cn/api/weibohot"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 200 or "data" not in j:
            print("Weibo API returned error:", j)
            return []
        data = j.get("data", [])
        items = []
        for it in data:
            title = clean_text(it.get("title"))
            link = it.get("url", "")
            if title and link:
                items.append({"title": title, "url": link.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        print("fetch_weibo_top error:", repr(e))
        return []

def fetch_bilibili_top(n=15):
    api = "https://api.bilibili.com/x/web-interface/popular?ps=50"
    try:
        r = requests.get(api, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        data = j.get("data", {})
        cand = []
        if isinstance(data, list):
            cand = data
        elif isinstance(data, dict):
            cand = data.get("list") or data.get("archives") or data.get("result") or []
        items = []
        for it in cand:
            title = clean_text(it.get("title") or it.get("name"))
            bvid = it.get("bvid") or it.get("bvidStr")
            url = ""
            if bvid:
                url = "https://www.bilibili.com/video/" + bvid
            else:
                url = it.get("arcurl") or it.get("url") or ""
            if title:
                items.append({"title": title, "url": url.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        print("fetch_bilibili_top error:", repr(e))
        return []

def build_markdown(platform_name, items):
    parts = []
    parts.append("关键字：热点\n")
    if items:
        parts.append(f"# {platform_name}（Top {len(items)}）\n")
        for i, it in enumerate(items, 1):
            parts.append(f"{i}. [{it.get('title')}]({it.get('url')})  ")
    else:
        parts.append(f"# {platform_name} — 获取失败或无数据\n")
    parts.append("\n> 更新时间：{}".format(get_beijing_time_str()))
    return "\n\n".join(parts)

def send_to_dingtalk(markdown_text, title="热搜更新"):
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": markdown_text
        }
    }
    try:
        r = requests.post(DINGTALK_WEBHOOK, json=payload, timeout=10)
        print("DingTalk send status:", r.status_code, "response:", r.text)
        return r.status_code == 200
    except Exception as e:
        print("send_to_dingtalk error:", repr(e))
        return False

def main():
    # 微博
    weibo = fetch_weibo_top(15)
    print(f"Fetched weibo items: {len(weibo)}")
    for idx, it in enumerate(weibo[:5], 1):
        print(f"  W{idx}. {it.get('title')} -> {it.get('url')}")
    md_weibo = build_markdown("微博热搜", weibo)
    ok_weibo = send_to_dingtalk(md_weibo, title="微博热搜（Top）")
    if not ok_weibo:
        print("Failed to send Weibo DingTalk message")
    else:
        print("Weibo Send OK.")

    # B站
    bilibili = fetch_bilibili_top(15)
    print(f"Fetched bilibili items: {len(bilibili)}")
    for idx, it in enumerate(bilibili[:5], 1):
        print(f"  B{idx}. {it.get('title')} -> {it.get('url')}")
    md_bilibili = build_markdown("B站热榜", bilibili)
    ok_bilibili = send_to_dingtalk(md_bilibili, title="B站热榜（Top）")
    if not ok_bilibili:
        print("Failed to send Bilibili DingTalk message")
    else:
        print("Bilibili Send OK.")

if __name__ == "__main__":
    main()
