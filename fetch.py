# fetch.py
# 使用 XXAPI 获取微博热搜 + 百度热搜 → 推送钉钉 
# 20251229 最终优化版：微博去空格补齐、百度去首条、间距优化、头部时间化

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
    """清洗标题文本，去掉零宽字符等"""
    if not text:
        return ""
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    text = ''.join(c for c in text if c.isprintable())
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def get_beijing_time_str():
    """获取北京时间字符串"""
    bj_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    return bj_now.strftime("%Y-%m-%d %H:%M:%S")

# --- 消息发送核心逻辑 ---

def _send_request(webhook_url, payload, is_test=False):
    if not webhook_url:
        return False, {"errcode": -2, "errmsg": "Webhook URL not provided"}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        response_json = r.json()
        errcode = response_json.get("errcode")
        status_msg = f"Status: {r.status_code}, Error: {errcode} - {response_json.get('errmsg')}"
        print(f"[{'TEST' if is_test else 'PROD'}] {payload['markdown']['title']}: {status_msg}")
        return errcode == 0, response_json
    except Exception as e:
        print(f"send_request error: {repr(e)}")
        return False, {"errcode": -3, "errmsg": f"Network Error: {repr(e)}"}

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
    """获取微博热搜：跳过含空格标题并补齐至 n 条"""
    url = "https://v2.xxapi.cn/api/weibohot"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        data = j.get("data", [])
        items = []
        for it in data:
            title = clean_text(it.get("title"))
            link = it.get("url", "")
            # 逻辑优化：标题含空格则跳过，序号顺延
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
    """获取百度热搜：去掉第一条置顶，取后续 15 条"""
    url = "https://v2.xxapi.cn/api/baiduhot" 
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        data = j.get("data", [])
        # 逻辑优化：跳过第一条，截取后续 n 条
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
    """构建板块列表，增加行间距防止误触"""
    section_parts = []
    if items:
        section_parts.append(f"\n### {platform_name}\n")
        for i, it in enumerate(items, 1):
            title = it.get('title', '')
            url = it.get('url', '').strip()
            safe_title = title.replace('[', '\\[').replace(']', '\\]')

            # 优化点：使用 \n\n 增大行间距，取消标题加粗
            if safe_title and url:
                line = f"{i}. [{safe_title}]({url}) \n\n"
            elif safe_title:
                line = f"{i}. {safe_title} \n\n"
            else:
                continue
            section_parts.append(line)
    return section_parts

def build_final_markdown(weibo, baidu):
    """构建最终报告，头部改时间"""
    parts = []
    # 头部：取消“关键字：热点”，改为时间（确保包含关键词“热搜”以适配机器人设置）
    now_time = get_beijing_time_str()
    parts.append(f"#### 📅 实时热搜监控\n**更新时间：{now_time}**\n")
    
    parts.extend(_build_platform_section(weibo, "微博热搜"))
    parts.extend(_build_platform_section(baidu, "百度热搜"))
    
    parts.append(f"\n---\n> 数据更新时间：{now_time}")
    return "".join(parts)

# --- 审查逻辑 (保留) ---

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
    print(f"开始审查 {platform_name}...")
    return audit_recursive(items)

# --- 主逻辑 ---

def main():
    print("--- 启动抓取任务 ---")
    try:
        # 1. 抓取微博(补齐15)和百度(去首取15)
        weibo = fetch_weibo_top(15)
        baidu = fetch_baidu_top(15)
        print(f"抓取成功: 微博 {len(weibo)}条, 百度 {len(baidu)}条")
    except Exception as e:
        error_msg = f"抓取失败: {repr(e)}"
        print(f"❌ {error_msg}")
        send_exception_report("核心抓取异常", error_msg)
        return

    # 2. 内容审查
    if DINGTALK_WEBHOOK_TEST:
        safe_weibo = test_content_audit(weibo, "微博热搜", DINGTALK_WEBHOOK_TEST)
        safe_baidu = test_content_audit(baidu, "百度热搜", DINGTALK_WEBHOOK_TEST)
    else:
        safe_weibo, safe_baidu = weibo, baidu
        
    # 3. 推送
    if safe_weibo or safe_baidu:
        final_md = build_final_markdown(safe_weibo, safe_baidu)
        # title 也要包含关键词以防万一
        ok = send_to_dingtalk(DINGTALK_WEBHOOK, final_md, title="微博 + 百度 热搜") 
        if ok:
            print("✅ 消息推送成功")
        else:
            print("❌ 消息推送失败，请检查机器人关键词设置（需包含“热搜”）")
    else:
        print("⚠️ 无安全数据可推送")

if __name__ == "__main__":
    main()
