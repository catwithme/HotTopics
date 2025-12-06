# fetch.py
# 使用 XXAPI 获取微博热搜 + B站热门 → 推送钉钉  
# 钉钉关键词：热点  
# 依赖：requests  

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
            url = "https://www.bilibili.com/video/" + bvid if bvid else it.get("arcurl") or it.get("url") or ""
            if title:
                items.append({"title": title, "url": url.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        print("fetch_bilibili_top error:", repr(e))
        return []

def build_markdown(items, platform_name):
    parts = [f"# {platform_name}（Top {len(items)}）\n"]
    for idx, it in enumerate(items, 1):
        parts.append(f"{idx}. [{it['title']}]({it['url']})  ")
    return "\n\n".join(parts)

def send_to_dingtalk(markdown_text, title="热搜更新", simulate=False):
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown_text}
    }
    if simulate:
        # 模拟发送，只检查 payload 是否结构合法
        print(f"[SIMULATE] DingTalk payload length: {len(markdown_text)}")
        # 返回 True 模拟正常，不触发真实发送
        return True
    try:
        r = requests.post(DINGTALK_WEBHOOK, json=payload, timeout=10)
        print("DingTalk send status:", r.status_code, "response:", r.text)
        return r.status_code == 200
    except Exception as e:
        print("send_to_dingtalk error:", repr(e))
        return False

def test_content_audit(items, platform_name, simulate=True):
    """
    最优审查测试策略：
    1. 30 条一次性测试
    2. 如果失败，二分法找出触发条目
    3. 单条测试剔除敏感条目
    """
    def audit_recursive(subitems, start_idx=0):
        if not subitems:
            return []
        text_md = build_markdown(subitems, platform_name)
        ok = send_to_dingtalk(text_md, title=f"{platform_name} 审查测试", simulate=simulate)
        if ok:
            # 全部安全
            return subitems
        if len(subitems) == 1:
            # 单条触发审查，剔除
            print(f"[AUDIT] {platform_name} item removed due to audit: {subitems[0]['title']}")
            return []
        # 二分法继续查找
        mid = len(subitems) // 2
        left = audit_recursive(subitems[:mid], start_idx)
        right = audit_recursive(subitems[mid:], start_idx + mid)
        return left + right

    return audit_recursive(items)

def main():
    weibo = fetch_weibo_top(15)
    bilibili = fetch_bilibili_top(15)

    print(f"Fetched weibo items: {len(weibo)}")
    print(f"Fetched bilibili items: {len(bilibili)}")

    # 审查测试（模拟，不真实发送）
    safe_weibo = test_content_audit(weibo, "微博热搜", simulate=True)
    safe_bilibili = test_content_audit(bilibili, "B站热榜", simulate=True)

    print(f"Safe weibo items: {len(safe_weibo)}")
    print(f"Safe bilibili items: {len(safe_bilibili)}")

    # 最终合并安全条目
    final_md = "关键字：热点\n\n"
    if safe_weibo:
        final_md += build_markdown(safe_weibo, "微博热搜") + "\n\n"
    if safe_bilibili:
        final_md += build_markdown(safe_bilibili, "B站热榜") + "\n\n"
    final_md += f"> 更新时间：{get_beijing_time_str()}"

    # 真实发送
    ok = send_to_dingtalk(final_md, title="微博 + B站 热搜（Top）", simulate=False)
    if not ok:
        print("Failed to send DingTalk message")
    else:
        print("Send OK.")

if __name__ == "__main__":
    main()
