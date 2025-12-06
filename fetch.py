# fetch.py
# 使用 XXAPI 获取微博热搜 + B站热门 → 推送钉钉  
# 钉钉关键词：热点  
# 依赖：requests  

import os
import time
import requests

DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")
if not DINGTALK_WEBHOOK:
    raise SystemExit("Error: environment variable DINGTALK_WEBHOOK not set")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

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
            title = it.get("title")
            link = it.get("url")
            if title and link:
                items.append({"title": title.strip(), "url": link.strip()})
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
            title = it.get("title") or it.get("name")
            bvid = it.get("bvid") or it.get("bvidStr")
            url = ""
            if bvid:
                url = "https://www.bilibili.com/video/" + bvid
            else:
                url = it.get("arcurl") or it.get("url") or ""
            if title:
                items.append({"title": title.strip(), "url": url.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        print("fetch_bilibili_top error:", repr(e))
        return []

def build_markdown(weibo, bilibili):
    parts = []
    parts.append("关键字：热点\n")
    # 微博部分
    if weibo:
        parts.append("# 微博热搜（Top {}）\n".format(len(weibo)))
        for i, it in enumerate(weibo, 1):
            title = it.get("title", "").replace("\n", " ").strip()
            url = it.get("url", "").strip()
            parts.append(f"{i}. [{title}]({url})  ")
    else:
        parts.append("# 微博热搜（Top） — 获取失败 或 无数据\n")
    # B站部分
    parts.append("\n# B站热榜（Top {}）\n".format(len(bilibili)))
    for i, it in enumerate(bilibili, 1):
        title = it.get("title", "").replace("\n", " ").strip()
        url = it.get("url", "").strip()
        parts.append(f"{i}. [{title}]({url})  ")
    parts.append("\n> 更新时间：{}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
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
    weibo = fetch_weibo_top(15)
    bilibili = fetch_bilibili_top(15)

    print(f"Fetched weibo items: {len(weibo)}")
    if weibo:
        for idx, it in enumerate(weibo[:5], 1):
            print(f"  W{idx}. {it.get('title')} -> {it.get('url')}")
    else:
        print("  No weibo items.")

    print(f"Fetched bilibili items: {len(bilibili)}")
    for idx, it in enumerate(bilibili[:5], 1):
        print(f"  B{idx}. {it.get('title')} -> {it.get('url')}")

    md = build_markdown(weibo, bilibili)
    print("=== Generated Markdown Preview ===")
    print(md[:3000])

    ok = send_to_dingtalk(md, title="微博 + B站 热搜（Top）")
    if not ok:
        raise SystemExit("Failed to send DingTalk message")
    else:
        print("Send OK.")

if __name__ == "__main__":
    main()
