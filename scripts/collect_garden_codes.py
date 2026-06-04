import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


GAME_NAME = "我的花园世界"
STATE_FILE = ".github/state/garden-sent.json"
SERVERCHAN_SEND_URLS = [
    os.environ.get("SERVERCHAN_SEND_URL", "").strip(),
    os.environ.get("SERVERCHAN_SEND_URL_2", "").strip(),
]
SERVERCHAN_SEND_URLS = [url for url in SERVERCHAN_SEND_URLS if url]

BLOGGERS = [
    {"platform": "小红书", "name": "我的花园世界-金兰叶序", "red_id": "26453463813", "focus": "今日通码"},
    {"platform": "小红书", "name": "喵喵嗷呜", "red_id": "4278304669", "focus": "兑换码"},
]

TARGETS = [
    {"id": "daily", "label": "今日通码", "keywords": ["今日通码", "通码", "今天通码"], "hour": 19, "minute": 0},
    {"id": "20", "label": "8点兑换码", "keywords": ["8点兑换码", "八点兑换码", "8点限时码", "八点限时码"], "hour": 20, "minute": 6},
    {"id": "21", "label": "9点兑换码", "keywords": ["9点兑换码", "九点兑换码", "9点限时码", "九点限时码"], "hour": 21, "minute": 25},
    {"id": "22", "label": "10点兑换码", "keywords": ["10点兑换码", "十点兑换码", "10点限时码", "十点限时码"], "hour": 22, "minute": 25},
]


def now_bj():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def fetch(url, timeout=4):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def clean_text(text):
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<.*?>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def search_bing_rss(query):
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
    text = fetch(url)
    results = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return results
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title") or "")
        href = item.findtext("link") or ""
        description = clean_text(item.findtext("description") or "")
        if title and href:
            results.append({"title": title, "url": href, "text": f"{title} {description}", "source": "Bing"})
    return results


def dedupe(items):
    seen = set()
    output = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def today_terms(today):
    return [
        today.strftime("%Y-%m-%d"),
        today.strftime("%Y/%m/%d"),
        f"{today.month}.{today.day}",
        f"{today.month}月{today.day}日",
        "今天",
        "今日",
        "今晚",
    ]


def queries_for_target(target, today):
    queries = []
    relevant_bloggers = BLOGGERS
    if target["id"] == "daily":
        relevant_bloggers = [b for b in BLOGGERS if b["focus"] == "今日通码"]
    elif target["id"] in ("20", "21", "22"):
        relevant_bloggers = [b for b in BLOGGERS if b["focus"] == "兑换码"]

    for blogger in relevant_bloggers:
        queries.append(f"{blogger['name']} {blogger['red_id']} {GAME_NAME} {today.month}月{today.day}日 {target['label']}")

    queries.append(f"{GAME_NAME} {today.month}月{today.day}日 {target['label']} 小红书")

    return dedupe(queries)


def target_is_due(target, now):
    release_time = now.replace(hour=target["hour"], minute=target["minute"], second=0, microsecond=0)
    return now >= release_time


def is_today_text(text, today):
    return any(term in text for term in today_terms(today)) or any(term in text for term in ["刚刚", "分钟前", "小时前"])


def source_name(text):
    for blogger in BLOGGERS:
        if blogger["name"] in text or blogger["red_id"] in text:
            return f"{blogger['platform']} {blogger['name']}({blogger['red_id']})"
    if "xiaohongshu.com" in text or "小红书" in text:
        return "小红书同类型公开来源"
    if "weibo.com" in text or "微博" in text:
        return "微博同类型公开来源"
    return "公开搜索来源"


def text_matches_target(text, target, today):
    if GAME_NAME not in text and "花园世界" not in text:
        return False
    if not is_today_text(text, today):
        return False
    return any(keyword in text for keyword in target["keywords"])


def extract_codes(text, target):
    codes = []
    words = ["通码"] if target["id"] == "daily" else ["兑换码", "限时码"]
    for keyword in target["keywords"] + words:
        patterns = [
            rf"{re.escape(keyword)}[：:\s]*([一-龥A-Za-z0-9_-]{{2,24}})",
            rf"{re.escape(keyword)}.*?[：:\s]([一-龥A-Za-z0-9_-]{{2,24}})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                code = normalize_code(match.group(1))
                if code:
                    codes.append(code)
    return dedupe(codes)


def normalize_code(candidate):
    candidate = candidate.strip(" ：:，,。.;；、[]【】（）()《》<>\"'“”‘’")
    if not (2 <= len(candidate) <= 24):
        return ""
    noise = {
        "兑换",
        "复制",
        "领取",
        "攻略",
        "最新",
        "今日",
        "今天",
        "今晚",
        "通码",
        "兑换码",
        "限时码",
        "小红书",
        "我的花园世界",
    }
    if candidate in noise:
        return ""
    if re.fullmatch(r"\d{1,2}([:.月-])\d{1,2}日?", candidate):
        return ""
    return candidate


def collect_target(target, today):
    found = []
    seen_urls = set()
    for query in queries_for_target(target, today):
        try:
            results = search_bing_rss(query)[:3]
        except Exception as exc:
            print(f"Bing search failed for {query}: {exc}", file=sys.stderr)
            continue
        for result in results:
            if result["url"] in seen_urls:
                continue
            seen_urls.add(result["url"])
            text = f"{result['title']} {result.get('text', '')} {result['url']}"
            if not text_matches_target(text, target, today):
                continue
            codes = extract_codes(text, target)
            for code in codes:
                found.append(
                    {
                        "target_id": target["id"],
                        "target": target["label"],
                        "code": code,
                        "source": source_name(text),
                        "title": result["title"],
                        "url": result["url"],
                    }
                )
    return unique_found(found)


def unique_found(found):
    seen = set()
    output = []
    for item in found:
        key = (item["target_id"], item["code"], item["source"])
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def format_message(date_text, item):
    lines = [
        f"{GAME_NAME}{item['target']} {date_text}",
        f"兑换码：{item['code']}",
        f"来源：{item['source']}",
    ]
    if item.get("title"):
        lines.append(f"标题：{item['title']}")
    if item.get("url"):
        lines.append(f"链接：{item['url']}")
    lines.append("提示：兑换码可能很快过期，请尽快兑换。")
    return "\n".join(lines)


def push_serverchan(message):
    if not SERVERCHAN_SEND_URLS:
        print(message)
        raise SystemExit("Missing SERVERCHAN_SEND_URL secret.")
    data = urllib.parse.urlencode({"title": f"{GAME_NAME}兑换码", "desp": message}).encode("utf-8")
    for index, url in enumerate(SERVERCHAN_SEND_URLS, start=1):
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"ServerChan #{index} failed:")
            print(body)
            raise
        print(f"ServerChan #{index} response:")
        print(body)


def main():
    now = now_bj()
    today = now.date()
    date_text = today.strftime("%Y-%m-%d")
    state = load_state()
    sent_any = False

    searches_used = 0
    max_searches = int(os.environ.get("GARDEN_MAX_SEARCHES", "6"))

    for target in TARGETS:
        if not target_is_due(target, now):
            continue
        state_key = f"{date_text}-{target['id']}"
        if state.get(state_key, {}).get("sent"):
            continue
        if searches_used >= max_searches:
            print("Search budget exhausted for this run.")
            break
        searches_used += len(queries_for_target(target, today))
        found = collect_target(target, today)
        if not found:
            print(f"{target['label']} not found yet.")
            continue

        item = found[0]
        message = format_message(date_text, item)
        print(message)
        push_serverchan(message)
        state[state_key] = {
            "sent": True,
            "sent_at": now.isoformat(),
            "target": target["label"],
            "code": item["code"],
            "source": item["source"],
            "url": item["url"],
        }
        sent_any = True

    if sent_any:
        save_state(state)
    else:
        print("No new code found; no push sent.")


if __name__ == "__main__":
    main()
