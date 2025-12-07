# fetch.py
# 使用 XXAPI 获取微博热搜 + B站热门 → 推送钉钉  
# 钉钉关键词：热点  
# 依赖：requests, time
# --- 核心改进：二分法审查、双 Webhook、异常推送、延迟控制、Markdown 健壮性 ---

import os
import time
import datetime
import re
import requests
import json # 确保导入 json 用于解析钉钉响应

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
    """
    清洗标题文本，去掉零宽字符、不可见字符等，并确保最终首尾无空格。
    **已优化**：替换连续空格为单个空格。
    """
    if not text:
        return ""
    # 去掉零宽空格、特殊控制符
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    # 去掉其他不可见控制字符
    text = ''.join(c for c in text if c.isprintable())
    # 替换连续空格为一个（保留内容中的必要空格）
    text = re.sub(r'\s+', ' ', text)
    # 最终移除首尾空格
    return text.strip()

def get_beijing_time_str():
    """获取北京时间字符串"""
    utc_now = datetime.datetime.utcnow()
    bj_now = utc_now + datetime.timedelta(hours=8)
    return bj_now.strftime("%Y-%m-%d %H:%M:%S")

# --- 消息发送核心逻辑 ---

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

# --- 数据抓取 (保持不变) ---

def fetch_weibo_top(n=15):
    # ... (您的 fetch_weibo_top 代码)
    url = "https://v2.xxapi.cn/api/weibohot"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 200 or "data" not in j:
            # 捕获 API 返回的业务错误
            raise ValueError(f"Weibo API returned error: {j}")
        data = j.get("data", [])
        items = []
        for it in data:
            title = clean_text(it.get("title"))
            link = it.get("url", "")
            if title and link:
                # 抓取时使用 clean_text 确保标题干净
                items.append({"title": title, "url": link.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        # 将异常抛出到 main 函数中统一处理
        raise Exception(f"fetch_weibo_top error: {repr(e)}")

def fetch_bilibili_top(n=15):
    # ... (您的 fetch_bilibili_top 代码)
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
                # 抓取时使用 clean_text 确保标题干净
                items.append({"title": title, "url": url.strip()})
            if len(items) >= n:
                break
        return items
    except Exception as e:
        # 将异常抛出到 main 函数中统一处理
        raise Exception(f"fetch_bilibili_top error: {repr(e)}")


# --- Markdown 构建器 (已增强健壮性，新增转义和优化换行) ---

def build_final_markdown(weibo, bilibili):
    """构建最终发送的合并 Markdown 报告（增强数据健壮性，并对标题进行转义）"""
    parts = []
    parts.append("关键字：热点\n")
    
    # 微博部分
    if weibo:
        parts.append("# 微博热搜（Top {}）\n".format(len(weibo)))
        for i, it in enumerate(weibo, 1):
            title = it.get('title')
            url = it.get('url')
            
            # --- 核心健壮性检查 ---
            if not title or not url:
                print(f"Warning: Weibo item {i} skipped due to missing title/URL: {it}")
                continue
            
            # --- Markdown 字符转义 ---
            # 转义 Markdown 敏感字符 [ ] *，防止标题内容破坏链接结构
            title = title.replace('[', '\[').replace(']', '\]').replace('*', '\*')
            
            # --- 优化换行：确保链接紧凑，使用 \n 确保解析一致性 ---
            # 移除行末多余空格，并以 \n 结束
            parts.append(f"{i}. [{title}]({url})\n") 
    
    # B站部分
    if bilibili:
        parts.append("\n# B站热榜（Top {}）\n".format(len(bilibili)))
        for i, it in enumerate(bilibili, 1):
            title = it.get('title')
            url = it.get('url')
            
            # --- 核心健壮性检查 ---
            if not title or not url:
                print(f"Warning: Bilibili item {i} skipped due to missing title/URL: {it}")
                continue
                
            # --- Markdown 字符转义 ---
            # 转义 Markdown 敏感字符 [ ] *，防止标题内容破坏链接结构
            title = title.replace('[', '\[').replace(']', '\]').replace('*', '\*')

            # --- 优化换行：确保链接紧凑，使用 \n 确保解析一致性 ---
            # 移除行末多余空格，并以 \n 结束
            parts.append(f"{i}. [{title}]({url})\n")
    
    parts.append("\n> 更新时间：{}".format(get_beijing_time_str()))
    # 最终使用 \n\n.join 确保大的块之间有分隔
    return "\n\n".join(parts)


def build_audit_markdown(items, platform_name):
    """为二分法测试构建 Markdown，只包含当前批次的标题"""
    parts = [f"## [AUDIT] {platform_name} ({len(items)} 条)"]
    for idx, it in enumerate(items, 1):
        # 仅显示标题，不显示序号，保持简洁
        parts.append(f"- {it['title']}") 
    return "\n".join(parts)

# --- 核心审查：二分法逻辑 ---

def test_content_audit(items, platform_name, test_webhook_url):
    
    def audit_recursive(subitems, depth=0):
        if not subitems:
            return []
        
        # --- 延迟设置：避免触发钉钉消极反应 ---
        time.sleep(AUDIT_DELAY_SECONDS) 
        
        # 构建当前子集消息
        title = f"[Audit] {platform_name} D{depth} ({len(subitems)} 条)"
        text_md = build_audit_markdown(subitems, platform_name)
        
        # 使用 TEST Webhook 真实发送测试
        is_safe = send_to_dingtalk(test_webhook_url, text_md, title=title, is_test=True)

        if is_safe:
            # 全部安全，返回整个子集
            return subitems
            
        if len(subitems) == 1:
            # 单条触发审查（430104），剔除
            print(f"  [AUDIT REMOVED] Sensitive item: {subitems[0]['title']}")
            return []
            
        # 失败，继续二分法查找
        mid = len(subitems) // 2
        
        print(f"  [AUDIT FAILED] Splitting {len(subitems)} items into left ({mid}) and right ({len(subitems)-mid})")
        
        # 递归查找左右两部分
        left = audit_recursive(subitems[:mid], depth + 1)
        right = audit_recursive(subitems[mid:], depth + 1)
        
        return left + right

    if not test_webhook_url:
        print(f"Warning: Audit skipped for {platform_name} due to missing DINGTALK_WEBHOOK_TEST.")
        return items
        
    print(f"\n--- 开始对 {platform_name} 进行二分法内容审查 ({len(items)} 条) ---")
    safe_items = audit_recursive(items)
    print(f"--- {platform_name} 审查完成：保留 {len(safe_items)} 条 ---")
    return safe_items

# --- 主逻辑 ---

def main():
    
    # 1. 数据抓取与异常处理
    try:
        weibo = fetch_weibo_top(15)
        bilibili = fetch_bilibili_top(15)
    except Exception as e:
        # 抓取阶段发生严重异常
        error_msg = f"数据抓取失败: {repr(e)}"
        print(f"❌ {error_msg}")
        send_exception_report("核心数据抓取失败", error_msg)
        return # 停止后续流程
    
    total_fetched = len(weibo) + len(bilibili)
    print(f"Fetched weibo items: {len(weibo)}")
    print(f"Fetched bilibili items: {len(bilibili)}")
    
    if total_fetched == 0:
        # 没有数据，推送报告并停止
        report_msg = "本次运行未抓取到任何有效热搜数据。"
        print(f"⚠️ {report_msg}")
        send_exception_report("热搜数据缺失", report_msg)
        return

    # 2. 内容审查（二分法）
    
    # 检查测试 Webhook 是否存在
    if DINGTALK_WEBHOOK_TEST:
        safe_weibo = test_content_audit(weibo, "微博热搜", DINGTALK_WEBHOOK_TEST)
        safe_bilibili = test_content_audit(bilibili, "B站热榜", DINGTALK_WEBHOOK_TEST)
    else:
        # 如果没有测试 Webhook，则跳过审查，使用原始数据 (存在安全风险)
        print("Warning: DINGTALK_WEBHOOK_TEST is missing. Skipping content audit.")
        safe_weibo = weibo
        safe_bilibili = bilibili
        
    total_safe = len(safe_weibo) + len(safe_bilibili)
    print(f"\nFinal safe items: {total_safe} (Weibo: {len(safe_weibo)}, Bili: {len(safe_bilibili)})")
    
    if total_safe == 0:
        # 抓到数据但全部被审查剔除
        report_msg = f"本次抓取 {total_fetched} 条，但全部被内容审查系统剔除。请检查敏感词汇。"
        print(f"⚠️ {report_msg}")
        send_exception_report("内容审查失败", report_msg)
        return

    # 3. 最终合并与推送
    final_md = build_final_markdown(safe_weibo, safe_bilibili)
    print("\n=== Generated FINAL Markdown Preview ===")
    print(final_md[:3000])

    print("\n--- 开始最终推送（使用生产 Webhook）---")
    ok = send_to_dingtalk(DINGTALK_WEBHOOK, final_md, title="微博 + B站 热搜（Top）", is_test=False)
    
    if not ok:
        print("❌ Failed to send final DingTalk message")
        send_exception_report("最终推送失败", "请检查生产 Webhook 配置或网络连接。")
    else:
        print("✅ Send OK.")

if __name__ == "__main__":
    main()
