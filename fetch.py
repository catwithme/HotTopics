# fetch.py
# 作用：抓取微博热搜（Top 15）和 B站热门（Top 15），生成 Markdown，然后推送到钉钉机器人 webhook。
# 钉钉关键词：热点
# 依赖：requests, beautifulsoup4

import os
import time
import json
import re
import requests
from bs4 import BeautifulSoup

DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")
if not DINGTALK_WEBHOOK:
    raise SystemExit("Error: environment variable DINGTALK_WEBHOOK not set")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

def fetch_weibo_top(n=15):
    url = "https://s.weibo.com/top/summary"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        scripts = soup.find_all("script")
        json_data = None
        for s in scripts:
            if "var $CONFIG" in s.text or "STK && STK.pageletM && STK.pageletM.view" in s.text:
                match = re.search(r'\{.*\}', s.text, re.S)
                if match:
                    try:
                        json_data = json.loads(match.group())
                        break
                    except:
                        continue
        items = []
        # 如果没解析到 JSON，则尝试传统方式抓 a 标签
        if not json_data:
            anchors = soup.select("a[href*='/weibo?q=']")
            for a in anchors:
                text = a.get_text(strip=True)
                href = a.get("href", "")
                if text and href:
                    full = href if href.startswith("http") else "https://s.weibo.com" + href
                    items.append({"title": text, "url": full})
                    if len(items) >= n:
                        break
            return items[:n]

        # 从 JSON 中提取前 n 条
        if isinstance(json_data, dict):
            try:
                list_data = json_data.get("mods", {}).get("html", "")
                soup2 = BeautifulSoup(list_data, "html.parser")
                anchors = soup2.select("td.td-02 a")
                for a in anchors:
                    title = a.get_text(strip=True)
                    href = a.get("href", "")
                    full = href if href.startswith("http") else "https://s.weibo.com" + href
                    items.append({"title": title, "url": full})
                    if len(items) >= n:
                        break
            except:
                pass
        return items[:n]
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
            title = None
            url = None
            if isinstance(it, dict):
                title = it.get("title") or it.get("name") or (it.get("desc") if it.get("desc") else None)
                bvid = it.get("bvid") or it.get("bvidStr")
                arcurl = it.get("arcurl") or it.get("short_link") or it.get("url")
                if not title:
                    for k in ("title", "name", "desc"):
                        v = it.get(k)
                        if isinstance(v, str) and v.strip():
                            title = v.strip()
                            break
                if bvid:
                    url = "https://www.bilibili.com/video/" + bvid
                elif arcurl:
                    url = arcurl
                else:
                    nested_bvid = None
                    if "param" in it and isinstance(it["param"], dict):
                        nested_bvid = it["param"].get("bvid") or it["param"].get("bvidStr")
                        nested_url = it["param"].get("uri") or it["param"].get("url")
                        if nested_bvid:
                            url = "https://www.bilibili.com/video/" + nested_bvid
                        elif nested_url:
                            url = nested_url
                if not url and title:
                    url = "https://search.bilibili.com/all?keyword=" + requests.utils.requote_uri(title)
            else:
                continue
            if not title:
                continue
            items.append({"title": title.strip(), "url": url or ""})
            if len(items) >= n:
                break
        return items[:n]
    except Exception as e:
        print("fetch_bilibili_top error:", repr(e))
        return []

def build_markdown(weibo, bilibili):
    parts = []
    # 钉钉关键词固定行，确保通过“热点”验证
    parts.append("关键字：热点\n")
    parts.append("# 微博热搜（Top {}）\n".format(len(weibo)))
    for i, it in enumerate(weibo, 1):
        title = (it.get("title") or "").replace("\n", " ").strip()
        url = it.get("url", "").strip()
        if url:
            parts.append(f"{i}. [{title}]({url})  ")
        else:
            parts.append(f"{i}. {title}  ")
    parts.append("\n# B站热榜（Top {}）\n".format(len(bilibili)))
    for i, it in enumerate(bilibili, 1):
        title = (it.get("title") or "").replace("\n", " ").strip()
        url = it.get("url", "").strip()
        if url:
            parts.append(f"{i}. [{title}]({url})  ")
        else:
            parts.append(f"{i}. {title}  ")
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
    for idx, it in enumerate(weibo[:5], 1):
        print(f"  W{idx}. {it.get('title')} -> {it.get('url')}")
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
