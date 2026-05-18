import requests
import json
import os
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
today_str   = now.strftime("%Y%m%d")
today_label = now.strftime("%Y年%m月%d日")
month_key   = now.strftime("%Y%m")
month_label = now.strftime("%Y年%m月")

ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
NOTION_KEY     = os.environ["NOTION_API_KEY"]
PARENT_PAGE_ID = os.environ["NOTION_PARENT_PAGE_ID"]

_is_bearer   = NOTION_KEY.startswith(("npt_", "ntn_", "secret_"))
_is_token_v2 = not _is_bearer

def generate_news():
    system_prompt = """你是专业的数字营销行业新闻编辑。严格输出JSON，无多余文字，无代码块标记。
JSON结构：
{
  "page_title": "YYYYMMDD - 最重要新闻的一句话标题（15字以内）",
  "regions": {
    "eu_us":  [新闻数组],
    "china":  [新闻数组],
    "sea":    [新闻数组],
    "japan":  [新闻数组]
  },
  "editorial": "编辑总评（站在数字营销/广告行业从业者视角，点评今日最重要1-2条新闻对行业的实际影响，200字以内）"
}
每条新闻格式：
{"category": "ai" | "ecommerce" | "digital_marketing", "title": "新闻标题", "summary": "100字以内摘要", "url": "信息来源URL"}
每个地区提供2-3条新闻，尽量覆盖三种分类。只输出纯JSON。"""
    user_prompt = f"今天是{today_label}，请生成覆盖欧美、中国、东南亚、日本四个地区的AI行业、电商、数字营销最新新闻简报。"
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01"
        },
        json={
            "model": "claude-3-haiku-20240307",
            "max_tokens": 2000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        },
        timeout=60
    )
    if not resp.ok:
        print("API Error:", resp.status_code, resp.text)
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

if _is_bearer:
    NOTION_HEADERS = {
        "Authorization": f"Bearer {NOTION_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
else:
    NOTION_HEADERS = {
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
        "cookie": f"token_v2={NOTION_KEY}"
    }

def notion_get(url):
    r = requests.get(url, headers=NOTION_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def notion_post(url, data):
    r = requests.post(url, headers=NOTION_HEADERS, json=data, timeout=30)
    r.raise_for_status()
    return r.json()

def heading2(text):
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

def paragraph(parts):
    rich = []
    for p in parts:
        t, bold, color = p if len(p) == 3 else (*p, None)
        ann = {"bold": bold}
        item = {"type": "text", "text": {"content": t}, "annotations": ann}
        if color:
            item["annotations"]["color"] = color
        rich.append(item)
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich}}

def divider():
    return {"object": "block", "type": "divider", "divider": {}}

def callout(text, emoji="✍️"):
    return {
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": "gray_background"
        }
    }

def toggle(summary, children):
    return {
        "object": "block", "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": summary},
                           "annotations": {"bold": True}}],
            "children": children
        }
    }

REGION_META = {
    "eu_us":  "🌎 欧美地区",
    "china":  "🇨🇳 中国地区",
    "sea":    "🌏 东南亚地区",
    "japan":  "🇯🇵 日本地区",
}
CAT_LABEL = {
    "ai":                "🤖 AI",
    "ecommerce":         "📦 E-commerce",
    "digital_marketing": "📣 Digital Marketing",
}

def build_blocks(data):
    blocks = []
    blocks.append(paragraph([("📅 " + today_label, False, "gray")]))
    blocks.append(divider())
    for region_key, region_name in REGION_META.items():
        items = data["regions"].get(region_key, [])
        if not items:
            continue
        blocks.append(heading2(region_name))
        for item in items:
            cat = CAT_LABEL.get(item.get("category", "ai"), "🤖 AI")
            title   = item.get("title", "")
            summary = item.get("summary", "")
            url     = item.get("url", "")
            blocks.append(paragraph([(f"{cat}  ", True, None), (title, True, None)]))
            blocks.append(paragraph([(summary, False, None)]))
            if url:
                blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{
                        "type": "text",
                        "text": {"content": "📎 " + url, "link": {"url": url}},
                        "annotations": {"color": "gray", "italic": True}
                    }]}
                })
            blocks.append(paragraph([("", False, None)]))
    blocks.append(divider())
    editorial = data.get("editorial", "")
    if editorial:
        blocks.append(callout(editorial, "✍️"))
    return blocks

def get_page_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    return notion_get(url).get("results", [])

def find_or_create_month_toggle(page_id, month_key, month_label):
    blocks = get_page_blocks(page_id)
    toggle_title = f"📂 {month_key} — {month_label}"
    for b in blocks:
        if b["type"] == "toggle":
            rich = b["toggle"].get("rich_text", [])
            text = "".join(r["plain_text"] for r in rich)
            if month_key in text:
                return b["id"]
    result = notion_post(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        {"children": [toggle(toggle_title, [])]}
    )
    return result["results"][0]["id"]

def create_news_subpage(parent_page_id, page_title, blocks):
    data = {
        "parent": {"page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "📰"},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": page_title}}]}},
        "children": blocks[:100]
    }
    result = notion_post("https://api.notion.com/v1/pages", data)
    return result["id"], result["url"]

def add_page_link_to_toggle(toggle_id, child_page_id):
    notion_post(
        f"https://api.notion.com/v1/blocks/{toggle_id}/children",
        {"children": [{"object": "block", "type": "link_to_page",
                       "link_to_page": {"type": "page_id", "page_id": child_page_id}}]}
    )

def main():
    print(f"[{today_label}] 开始生成新闻简报...")
    print("→ 调用 Claude API...")
    data = generate_news()
    page_title = data.get("page_title", f"{today_str} - 每日AI简报")
    print(f"→ 生成完成：{page_title}")
    blocks = build_blocks(data)
    print("→ 创建 Notion 子页面...")
    child_id, child_url = create_news_subpage(PARENT_PAGE_ID, page_title, blocks)
    print(f"→ 子页面已创建：{child_url}")
    print("→ 更新月份 Toggle...")
    toggle_id = find_or_create_month_toggle(PARENT_PAGE_ID, month_key, month_label)
    add_page_link_to_toggle(toggle_id, child_id)
    print("→ 链接已添加到 Toggle")
    print("✅ 完成！")

if __name__ == "__main__":
    main()
