# fetch.py
# 作用：每次运行抓取微博热搜（Top 15）和 B 站热门（Top 15），生成 Markdown，然后推送到钉钉机器人 webhook。
# 说明：在 GitHub Actions 中运行时会从环境变量 DINGTALK_WEBHOOK 读取 webhook。
# 依赖：requests, beautifulsoup4

import os
import time
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
    """
    抓取微博热搜（s.weibo.com/top/summary），返回 list of {"title","url"}，最多 n 条。
    如果页面结构变更可能需要调整解析逻辑（查看 Actions 日志中的错误信息）。
    """
    url = "https://s.weibo.com/top/summary"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        # 兼容常见结构，优先抓 td.td-02 下的 a
        tds = soup.find_all("td", class_="td-02")
        if not tds:
            # 备用：一些版本可能用 div 或其他标签
            anchors = soup.select("a[href*='/weibo?q='], a[href*='s.weibo.com']")
            for a in anchors:
                text = a.get_text(strip=True)
                href = a.get("href", "")
                if text and href:
                    full = href if href.startswith("http") else ("https://s.weibo.com" + href if href.startswith("/") else href)
                    items.append({"title": text, "url": full})
                    if len(items) >= n:
                        break
            return items[:n]

        for td in tds:
            a = td.find("a")
            if a and a.text and a.text.strip():
                title = a.text.strip()
                href = a.get("href", "")
                if href.startswith("/"):
                    full = "https://s.weibo.com" + href
                elif href.startswith("http"):
                    full = href
                else:
                    full = href
                items.append({"title": title, "url": full})
                if len(items) >= n:
                    break
        return items[:n]
    except Exception as e:
        print("fetch_weibo_top error:", repr(e))
        return []

def fetch_bilibili_top(n=15):
    """
    抓取 B 站热门（使用公开接口），返回 list of {"title","url"}，最多 n 条。
    如果官方接口返回结构不同，也有容错尝试。
    """
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
            # 常见字段：list / archives / result 等
            cand = data.get("list") or data.get("archives") or data.get("result") or []
        items = []
        for it in cand:
            # 支持多种字段名
            title = None
            url = None
            # title 字段可能在不同层级
            if isinstance(it, dict):
                title = it.get("title") or it.get("name") or (it.get("desc") if it.get("desc") else None)
                bvid = it.get("bvid") or it.get("bvidStr")
                arcurl = it.get("arcurl") or it.get("short_link") or it.get("url")
                # 有时候 item 是更深一层的 dict（如 {'param': {...}}），尝试展开
                if not title:
                    # 深度尝试
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
                    # 一些条目可能包含 'aid' 或 'bvid' 在 nested
                    nested_bvid = None
                    if "param" in it and isinstance(it["param"], dict):
                        nested_bvid = it["param"].get("bvid") or it["param"].get("bvidStr")
                        nested_url = it["param"].get("uri") or it["param"].get("url")
                        if nested_bvid:
                            url = "https://www.bilibili.com/video/" + nested_bvid
                        elif nested_url:
                            url = nested_url
                # 兜底：构造一个可用的 url（若 title 存在但 url 为空）
                if not url and title:
                    # 尝试使用搜索链接作为 fallback
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
        # 钉钉返回 200 且 body 中包含 success 表示成功；我们打印全部响应便于排查
        print("DingTalk send status:", r.status_code, "response:", r.text)
        return r.status_code == 200
    except Exception as e:
        print("send_to_dingtalk error:", repr(e))
        return False

def main():
    # 抓取 15 条（你要求）
    weibo = fetch_weibo_top(15)
    bilibili = fetch_bilibili_top(15)

    # 日志：打印抓取到的条目数量与前几项，便于在 Actions logs 查看
    print(f"Fetched weibo items: {len(weibo)}")
    for idx, it in enumerate(weibo[:5], 1):
        print(f"  W{idx}. {it.get('title')} -> {it.get('url')}")
    print(f"Fetched bilibili items: {len(bilibili)}")
    for idx, it in enumerate(bilibili[:5], 1):
        print(f"  B{idx}. {it.get('title')} -> {it.get('url')}")

    md = build_markdown(weibo, bilibili)
    # 打印前 3000 字到 Actions 日志供排查（通常足够）
    print("=== Generated Markdown Preview ===")
    print(md[:3000])

    ok = send_to_dingtalk(md, title="微博 + B站 热搜（Top）")
    if not ok:
        raise SystemExit("Failed to send DingTalk message")
    else:
        print("Send OK.")

if __name__ == "__main__":
    main()
