# fetch.py
# 使用 XXAPI 获取微博热搜 + 百度热搜 → 推送钉钉  
# 钉钉关键词：热点  
# 20251207最终版本，已修复偶发格式问题，并暂停 B站 推送
# --- 核心改进：二分法审查、双 Webhook、异常推送、延迟控制、Markdown 健壮性 ---

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
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

# --- 发送逻辑 ---

def _send_request(webhook_url, payload, is_test=False):
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        resp = r.json()
        return resp.get("errcode") == 0, resp
    except Exception as e:
        return False, {"errcode": -1, "errmsg": repr(e)}

def send_to_dingtalk(webhook_url, markdown_text, title="热搜更新", is_test=False):
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown_text}
    }
    ok, resp = _send_request(webhook_url, payload, is_test)
    if is_test and resp.get("errcode") == 430104:
        return False
    return ok

def send_exception_report(title, error_detail):
    markdown = (
        f"## ❌ 爬虫异常报告\n\n"
        f"**时间:** {get_beijing_time_str()}\n\n"
        f"**模块:** {title}\n\n"
        f"> {error_detail}"
    )
    send_to_dingtalk(DINGTALK_WEBHOOK, markdown, title=f"⚠️ {title}")

# --- 数据抓取 ---

def fetch_weibo_top():
    url = "https://v2.xxapi.cn/api/weibohot"
    r = requests.get(url, headers=HEADERS, timeout=15)
    j = r.json()
    items = []
    for it in j.get("data", []):
        title = clean_text(it.get("title"))
        url = it.get("url")
        if title and url:
            items.append({"title": title, "url": url})
    return items

def fetch_baidu_top():
    url = "https://v2.xxapi.cn/api/baiduhot"
    r = requests.get(url, headers=HEADERS, timeout=15)
    j = r.json()
    items = []
    for it in j.get("data", []):
        title = clean_text(it.get("title") or it.get("keyword"))
        link = it.get("url") or f"https://www.baidu.com/s?wd={requests.utils.quote(title)}"
        if title:
            items.append({"title": title, "url": link})
    return items

# --- Markdown 构建 ---

def _build_platform_section(items, platform_name, keep_original_index=False):
    section = []
    section.append(f
