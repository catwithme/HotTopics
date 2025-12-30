import os
import time
import datetime
import re
import requests
import json 
import sys

# --- 配置与常量 ---
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")
DINGTALK_WEBHOOK_TEST = os.environ.get("DINGTALK_WEBHOOK_TEST")

AUDIT_DELAY_SECONDS = 1 

if not DINGTALK_WEBHOOK:
    raise SystemExit("Error: environment variable DINGTALK_WEBHOOK not set")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# --- 辅助函数 ---

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

# --- 消息发送核心逻辑 ---

def _send_request(webhook_url, payload, is_test=False):
    if not webhook_url:
        return False, {"errcode": -2, "errmsg": "Webhook URL not provided"}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        response_json = r.json()
        errcode = response_json.get("errcode")
        print(f"[{'TEST' if is_test else 'PROD'}] {payload['markdown']['title']}: {errcode}")
        return errcode == 0, response_json
    except Exception as e:
        return False, {"errcode": -3, "errmsg": repr(e)}

def send_to_dingtalk(webhook_url, markdown_text, title="热搜更新", is_test=False):
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown_text}
    }
    ok, response = _send_request(webhook_url, payload, is_test)
    if is_test and response.get("errcode") == 430104:
        return False
    return ok

def send_exception_report(title, error_detail):
    timestamp = get_beijing_time_str()
    markdown_text = f"## ❌ 爬虫异常报告\n\n**时间:** {timestamp}\n\n**详情:**\n\n> {error_detail}"
    return send_to_dingtalk(DINGTALK_WEBHOOK, markdown_text, title=f"⚠️ {title}")

# --- 数据抓取 ---

def fetch_weibo_top(n=15):
    url = "https://v2.xxapi.cn/api/weibohot"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json().get("data", [])
        items = []
        for it in data:
            title = clean_text(it.get("title"))
            link = it.get("url", "")
            # 修改点 1：标题含空格则跳过，并补齐 15 条
            if not title or ' ' in title:
                continue
            if title and link:
                items.append({"title": title, "url": link.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        raise Exception(f"fetch_weibo_top error: {repr(e)}")

def fetch_baidu_top(n=15):
    url = "https://v2.xxapi.cn/api/baiduhot" 
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json().get("data", [])
        # 修改点 2：去掉第一条置顶，取后续 15 条
        target_data = data[1:n+1] 
        items = []
        for it in target_data:
            title = clean_text(it.get("title") or it.get("keyword")) 
            link = it.get("url", "") 
            if not link and it.get("keyword"):
                 link = f"https://www.baidu.com/s?wd={requests.utils.quote(it['keyword'])}"
            if title and link:
                items.append({"title": title, "url": link.strip()})
        return items
    except Exception as e:
        raise Exception(f"fetch_baidu_top error: {repr(e)}")

# --- Markdown 构建器 ---

def _build_platform_section(items, platform_name):
    section_parts = []
    if items:
        section_parts.append(f"\n### {platform_name}\n")
        for i, it in enumerate(items, 1):
            title = it.get('title', '').replace('[', '\\[').replace(']', '\\]')
            url = it.get('url', '').strip()
            # 修改点 3：取消加粗，并在行尾加双换行以增大间距
            if title and url:
                line = f"{i}. [{title}]({url}) \n\n"
                section_parts.append(line)
    return section_parts

def build_final_markdown(weibo, baidu):
    parts = []
    curr_time = get_beijing_time_str()
    # 修改点 4：头部保留关键字并增加时间
    parts.append(f"关键字：热点 | 更新时间：{curr_time}\n")
    
    parts.extend(_build_platform_section(weibo, "微博热搜"))
    parts.extend(_build_platform_section(baidu, "百度热搜"))
    
    parts.append(f"\n---\n> 最后更新：{curr_time}")
    return "".join(parts)

# --- 核心审查：二分法逻辑 ---

def test_content_audit(items, platform_name, test_webhook_url):
    def audit_recursive(subitems, depth=0):
        if not subitems: return []
        time.sleep(AUDIT_DELAY_SECONDS) 
        title = f"[Audit] {platform_name} D{depth}"
        text_md = f"## Audit {platform_name}\n" + "\n".join([f"- {x['title']}" for x in subitems])
        is_safe = send_to_dingtalk(test_webhook_url, text_md, title=title, is_test=True)
        if is_safe: return subitems
        if len(subitems) == 1: return []
        mid = len(subitems) // 2
        return audit_recursive(subitems[:mid], depth + 1) + audit_recursive(subitems[mid:], depth + 1)

    if not test_webhook_url: return items
    print(f"审查 {platform_name}...")
    return audit_recursive(items)

# --- 主逻辑 ---

def main():
    try:
        weibo = fetch_weibo_top(15)
        baidu = fetch_baidu_top(15)
    except Exception as e:
        send_exception_report("数据抓取失败", repr(e))
        return

    if DINGTALK_WEBHOOK_TEST:
        safe_weibo = test_content_audit(weibo, "微博热搜", DINGTALK_WEBHOOK_TEST)
        safe_baidu = test_content_audit(baidu, "百度热搜", DINGTALK_WEBHOOK_TEST)
    else:
        safe_weibo, safe_baidu = weibo, baidu
        
    if safe_weibo or safe_baidu:
        final_md = build_final_markdown(safe_weibo, safe_baidu)
        send_to_dingtalk(DINGTALK_WEBHOOK, final_md, title="微博 + 百度 热搜") 

if __name__ == "__main__":
    main()
