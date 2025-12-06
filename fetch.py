# fetch.py
import requests
from bs4 import BeautifulSoup
import urllib.parse
import datetime
import json
import re
import os

# ---------- 配置 ----------
DINGTALK_WEBHOOK = os.environ.get('DINGTALK_WEBHOOK')  # 仓库Secrets中配置
KEYWORD = "热点"
MAX_ITEMS = 15

# ---------- 工具函数 ----------
def fetch_weibo_hot():
    url = "https://s.weibo.com/top/summary"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[微博] 请求失败: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    table = soup.find("table", attrs={"class": "list_table"})
    if not table:
        print("[微博] 未找到热搜表格")
        return []

    rows = table.find_all("tr")[1:]  # 第一行是表头
    for row in rows[:MAX_ITEMS]:
        td = row.find("td", attrs={"class": "td-02"})
        if td and td.a:
            title = td.a.get_text(strip=True)
            url_q = td.a.get("href")
            full_url = urllib.parse.urljoin("https://s.weibo.com", url_q)
            # 只清理钉钉可能报错的特殊符号，保留 emoji 和常用标点
            safe_title = re.sub(r'[<>#\$%&*]', '', title)
            items.append((safe_title, full_url))
    print(f"[微博] 抓取到 {len(items)} 条热搜")
    return items

def fetch_bilibili_hot():
    url = "https://www.bilibili.com/v/popular/rank/all"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[B站] 请求失败: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    for i, li in enumerate(soup.select("li.rank-item")[:MAX_ITEMS]):
        a = li.find("a", class_="title")
        if a:
            title = a.get_text(strip=True)
            href = a.get("href")
            if not href.startswith("http"):
                href = "https:" + href
            items.append((title, href))
    print(f"[B站] 抓取到 {len(items)} 条热榜")
    return items

def generate_markdown(weibo_items, bilibili_items):
    md = f"关键字：{KEYWORD}\n\n"

    # 微博
    md += f"# 微博热搜（Top {len(weibo_items)}）\n\n"
    for i, (title, url) in enumerate(weibo_items, 1):
        md += f"{i}. [{title}]({url})  \n"

    # B站
    md += f"\n# B站热榜（Top {len(bilibili_items)}）\n\n"
    for i, (title, url) in enumerate(bilibili_items, 1):
        md += f"{i}. [{title}]({url})  \n"

    # 更新时间（北京时间）
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    md += f"\n> 更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"

    return md

def send_to_dingtalk(content):
    if not DINGTALK_WEBHOOK:
        print("[钉钉] 未配置Webhook")
        return

    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"{KEYWORD}热榜",
            "text": content
        }
    }

    try:
        resp = requests.post(DINGTALK_WEBHOOK, json=data, timeout=10)
        print(f"[钉钉] 发送状态: {resp.status_code}, 返回: {resp.text}")
    except Exception as e:
        print(f"[钉钉] 发送异常: {e}")

# ---------- 主流程 ----------
def main():
    weibo_items = fetch_weibo_hot()
    bilibili_items = fetch_bilibili_hot()

    if not weibo_items:
        print("[微博] 没有抓到数据，推送内容中会标注0条")
    if not bilibili_items:
        print("[B站] 没有抓到数据")

    md = generate_markdown(weibo_items, bilibili_items)
    print("=== Generated Markdown Preview ===")
    print(md)
    send_to_dingtalk(md)

if __name__ == "__main__":
    main()
