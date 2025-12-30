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
import sys # 导入 sys 避免在 fetch 失败时继续执行

# --- 配置与常量 ---
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")
DINGTALK_WEBHOOK_TEST = os.environ.get("DINGTALK_WEBHOOK_TEST") # 新增测试 Webhook

# 设置二分法测试之间的延迟（秒），防止触发钉钉的频率限制或消极反应
AUDIT_DELAY_SECONDS = 1 

if not DINGTALK_WEBHOOK:
    raise SystemExit("Error: environment variable DINGTALK_WEBHOOK not set")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# --- 辅助函数 ---

def clean_text(text):
    """清洗标题文本，去掉零宽字符、不可见字符等"""
    if not text:
        return ""
    # 去掉零宽空格、特殊控制符
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    # 去掉其他不可见控制字符
    text = ''.join(c for c in text if c.isprintable())
    # 替换连续空格为一个
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def get_beijing_time_str():
    """获取北京时间字符串"""
    utc_now = datetime.datetime.utcnow()
    bj_now = utc_now + datetime.timedelta(hours=8)
    return bj_now.strftime("%Y-%m-%d %H:%M:%S")

# --- 消息发送核心逻辑 (不变) ---

def _send_request(webhook_url, payload, is_test=False):
    """通用发送请求逻辑，用于生产和测试 Webhook"""
    if not webhook_url:
        return False, {"errcode": -2, "errmsg": "Webhook URL not provided"}

    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        
        try:
            response_json = r.json()
            errcode = response_json.get("errcode")
            errmsg = response_json.get("errmsg")
        except json.JSONDecodeError:
            errcode, errmsg = -1, "Non-JSON response"
        except Exception:
            errcode, errmsg = -3, "Network/Exception Error"
        
        status_msg = f"Status: {r.status_code}, Error: {errcode} - {errmsg}"
        
        if is_test:
            print(f"[AUDIT TEST] {payload['markdown']['title']}: {status_msg}")
        else:
            print(f"[PRODUCTION] {payload['markdown']['title']}: {status_msg}")
            
        return errcode == 0, response_json

    except Exception as e:
        print(f"send_request error ({'TEST' if is_test else 'PROD'}): {repr(e)}")
        return False, {"errcode": -3, "errmsg": f"Network/Exception Error: {repr(e)}"}

def send_to_dingtalk(webhook_url, markdown_text, title="热搜更新", is_test=False):
    """发送 Markdown 消息到指定 Webhook"""
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown_text}
    }
    
    ok, response = _send_request(webhook_url, payload, is_test)
    
    if is_test:
        # 在测试模式下，我们只关心是否为内容安全风险（430104）
        if response.get("errcode") == 430104:
            return False # 明确返回 False，表示内容不安全
        return ok # 其他错误或成功都返回 True（非内容敏感错误）

    return ok # 生产环境只关心是否成功

def send_exception_report(title, error_detail):
    """推送异常报告到生产 Webhook"""
    timestamp = get_beijing_time_str()
    markdown_text = f"## ❌ 爬虫异常报告\n\n"
    markdown_text += f"**时间:** {timestamp}\n\n"
    markdown_text += f"**模块:** {title}\n\n"
    markdown_text += f"**详情:**\n\n> {error_detail}"
    
    # 强制使用生产 webhook 进行异常报告
    return send_to_dingtalk(DINGTALK_WEBHOOK, markdown_text, title=f"⚠️ {title}", is_test=False)

# --- 数据抓取 ---

def fetch_weibo_top(n=15):
    url = "https://v2.xxapi.cn/api/weibohot"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 200 or "data" not in j:
            raise ValueError(f"Weibo API returned error: {j}")
        data = j.get("data", [])
        items = []
        for it in data:
            title = clean_text(it.get("title"))
            link = it.get("url", "")
            if title and link:
                items.append({"title": title, "url": link.strip()})
        return items
    except Exception as e:
        raise Exception(f"fetch_weibo_top error: {repr(e)}")

def fetch_baidu_top(n=15):
    """获取百度热搜榜"""
    url = "https://v2.xxapi.cn/api/baiduhot" 
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 200 or "data" not in j:
            raise ValueError(f"Baidu API returned error: {j}")
        data = j.get("data", [])
        items = []
        for it in data:
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

def _build_platform_section(items, platform_name, mode):
    section_parts = []
    if not items:
        return section_parts

    section_parts.append(f"\n# {platform_name}\n")

    count = 0

    if mode == "weibo":
        for idx, it in enumerate(items, 1):
            title = it["title"]
            if " " in title:
                continue
            url = it["url"]
            safe_title = title.replace('[', '\\[').replace(']', '\\]')
            section_parts.append(f"{idx}. [{safe_title}]({url})\n\n\n")
            count += 1
            if count >= 15:
                break

    elif mode == "baidu":
        for it in items[1:]:
            title = it["title"]
            url = it["url"]
            safe_title = title.replace('[', '\\[').replace(']', '\\]')
            section_parts.append(f"{count + 1}. [{safe_title}]({url})\n")
            count += 1
            if count >= 15:
                break

    return section_parts

def build_final_markdown(weibo, baidu):
    parts = []
    parts.append(f"关键字：热点 | {get_beijing_time_str()}\n")

    parts.extend(_build_platform_section(weibo, "微博热搜", "weibo"))
    parts.extend(_build_platform_section(baidu, "百度热搜", "baidu"))

    parts.append(f"\n> 更新时间：{get_beijing_time_str()}")
    return "\n".join(parts)

# --- 主逻辑 ---

def main():
    try:
        weibo = fetch_weibo_top(50)
        baidu = fetch_baidu_top(50)
    except Exception as e:
        send_exception_report("核心数据抓取失败", repr(e))
        return

    final_md = build_final_markdown(weibo, baidu)

    ok = send_to_dingtalk(
        DINGTALK_WEBHOOK,
        final_md,
        title="微博 + 百度 热搜",
        is_test=False
    )

    if not ok:
        send_exception_report("最终推送失败", "请检查 Webhook")

if __name__ == "__main__":
    main()
