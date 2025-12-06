# fetch_weibo_one_by_one.py
# 修改说明：
# 1. 微博热搜 15 条拆分成 15 次发送，每次 1 条，间隔 5 秒
# 2. 暂停 B 站推送
# 3. 便于排查钉钉内容安全（430104）

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

def build_markdown(item):
    title = item.get("title")
    url = item.get("url")
    md = f"关键字：热点\n\n# 微博热搜单条\n1. [{title}]({url})\n\n> 更新时间：{get_beijing_time_str()}"
    return md

def send_to_dingtalk(markdown_text, title="微博热搜单条"):
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
    weibo_items = fetch_weibo_top(15)
    print(f"Fetched {len(weibo_items)} weibo items")
    for idx, item in enumerate(weibo_items, 1):
        print(f"Sending W{idx}: {item.get('title')}")
        md = build_markdown(item)
        ok = send_to_dingtalk(md)
        if not ok:
            print(f"Failed to send W{idx}: {item.get('title')}")
        else:
            print(f"W{idx} sent OK")
        time.sleep(5)  # 间隔 5 秒

if __name__ == "__main__":
    main()
