import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import json

# ========== 配置区 ==========
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=你的access_token"
KEYWORD = "热点"
TOP_N = 15

# ========== 工具函数 ==========
def clean_title(title):
    """
    清洗标题，去掉 emoji、特殊符号，保留中文、英文、数字、常用标点
    """
    # 保留文字、数字、中文、英文和基本标点
    pattern = re.compile(r'[^\u4e00-\u9fff\w\s.,:()?!-]')
    return pattern.sub('', title).strip()

def send_to_dingtalk(content):
    """
    发送 Markdown 内容到钉钉
    """
    headers = {'Content-Type': 'application/json'}
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": "热点推送",
            "text": content
        },
        "at": {
            "isAtAll": False
        }
    }
    resp = requests.post(DINGTALK_WEBHOOK, headers=headers, data=json.dumps(data))
    print(f"DingTalk send status: {resp.status_code}, response: {resp.text}")
    if resp.status_code == 200:
        result = resp.json()
        if result.get("errcode") != 0:
            print("注意：钉钉可能拦截消息，原因:", result.get("errmsg"))

# ========== 微博热搜 ==========
def fetch_weibo_top(n=TOP_N):
    url = "https://s.weibo.com/top/summary"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    try:
        trs = soup.select("table tbody tr")[0:n]
        for tr in trs:
            a_tag = tr.select_one("td a")
            if a_tag:
                title = clean_title(a_tag.text)
                link = "https://s.weibo.com/weibo?q=" + requests.utils.quote(title)
                items.append((title, link))
    except Exception as e:
        print("微博抓取异常:", e)
    print(f"Fetched weibo items: {len(items)}")
    for i, item in enumerate(items, 1):
        print(f"W{i}. {item[0]} -> {item[1]}")
    return items

# ========== B站热榜 ==========
def fetch_bilibili_top(n=TOP_N):
    url = "https://api.bilibili.com/x/web-interface/popular?ps=50"
    resp = requests.get(url, timeout=10)
    items = []
    try:
        data = resp.json()
        for video in data['data']['list'][:n]:
            title = clean_title(video['title'])
            link = f"https://www.bilibili.com/video/{video['bvid']}"
            items.append((title, link))
    except Exception as e:
        print("B站抓取异常:", e)
    print(f"Fetched bilibili items: {len(items)}")
    for i, item in enumerate(items, 1):
        print(f"B{i}. {item[0]} -> {item[1]}")
    return items

# ========== 构建 Markdown ==========
def build_markdown(weibo_items, bilibili_items):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = f"> 关键字：{KEYWORD}\n\n"

    md += f"# 微博热搜（Top {len(weibo_items)})\n\n"
    for i, (title, link) in enumerate(weibo_items, 1):
        md += f"{i}. [{title}]({link})  \n"

    md += f"\n# B站热榜（Top {len(bilibili_items)})\n\n"
    for i, (title, link) in enumerate(bilibili_items, 1):
        md += f"{i}. [{title}]({link})  \n"

    md += f"\n> 更新时间：{now}"
    return md

# ========== 主流程 ==========
if __name__ == "__main__":
    weibo_items = fetch_weibo_top()
    bilibili_items = fetch_bilibili_top()
    markdown = build_markdown(weibo_items, bilibili_items)
    print("=== Generated Markdown Preview ===")
    print(markdown)

    # 发送到钉钉
    send_to_dingtalk(markdown)
