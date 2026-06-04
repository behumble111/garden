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
    {"platform": "小红书", "name": "我的花园世界-金兰叶序", "red_id": "26453463813", "kind": "通码"},
    {"platform": "小红书", "name": "喵喵嗷呜", "red_id": "4278304669", "kind": "限时码"},
]

SLOTS = {
    "20": {"hour": 20, "label": "20点推送", "targets": ["7点今日通码", "8点限时码"]},
    "21": {"hour": 21, "label": "21点推送", "targets": ["9点限时码"]},
    "22": {"hour": 22, "label": "22点推送", "targets": ["10点限时码"]},
}


def now_bj():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def current_slot(now):
    forced = os.environ.get("GARDEN_SLOT", "").strip()
    if forced in SLOTS:
        return forced, SLOTS[forced], True
    for slot_id, slot in SLOTS.items():
        if now.hour == slot["hour"] and now.minute in (0, 5, 10):
            return slot_id, slot, now.minute == 10
    return "", None, False


def fetch(url, timeout=6):
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


def search_queries(slot, today):
    queries = []
    for target in slot["targets"]:
        for blogger in BLOGGERS:
            if target.endswith("通码") and blogger["kind"] != "通码":
                continue
            if target.endswith("限时码") and blogger["kind"] != "限时码":
                continue
            queries.append(f"{blogger['name']} {blogger['red_id']} {GAME_NAME} {today.month}月{today.day}日 {target}")
            queries.append(f"site:xiaohongshu.com {blogger['name']} {GAME_NAME} {target}")
        queries.append(f"{GAME_NAME} {today.month}月{today.day}日 {target} 小红书")
        queries.append(f"{GAME_NAME} 今日 {target} 小红书")
    return dedupe(queries)


def dedupe(items):
    seen = set()
    output = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def today_markers(today):
    return [
        today.strftime("%Y-%m-%d"),
        today.strftime("%Y/%m/%d"),
        f"{today.month}.{today.day}",
        f"{today.month}月{today.day}日",
        "今天",
        "今日",
        "今晚",
        "刚刚",
        "小时前",
        "分钟前",
    ]


def known_blogger(text):
    for blogger in BLOGGERS:
        if blogger["name"] in text or blogger["red_id"] in text:
            return f"{blogger['platform']} {blogger['name']}({blogger['red_id']})"
    return "同类型公开来源"


def relevant_to_slot(text, slot, today):
    if GAME_NAME not in text and "花园世界" not in text:
        return False
    if not any(marker in text for marker in today_markers(today)):
        return False
    return any(target in text or target.replace("点", ":00") in text for target in slot["targets"])


def extract_codes(text, slot):
    codes = []
    for target in slot["targets"]:
        code_words = ["通码"] if target.endswith("通码") else ["限时码"]
        for word in code_words:
            patterns = [
                rf"{re.escape(target)}[：:\s]*([一-龥A-Za-z0-9_-]{{2,20}})",
                rf"{word}[：:\s]*([一-龥A-Za-z0-9_-]{{2,20}})",
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, text):
                    code = normalize_code(match.group(1))
                    if code:
                        codes.append({"target": target, "code": code})
    return unique_codes(codes)


def normalize_code(candidate):
    candidate = candidate.strip(" ：:，,。.;；、[]【】（）()《》<>\"'“”‘’")
    if not (2 <= len(candidate) <= 20):
        return ""
    noise = {"兑换", "复制", "领取", "攻略", "最新", "今日", "今天", "今晚", "通码", "限时码", "小红书"}
    if candidate in noise:
        return ""
    if re.fullmatch(r"\d{1,2}([:.月-])\d{1,2}日?", candidate):
        return ""
    return candidate


def unique_codes(codes):
    seen = set()
    output = []
    for item in codes:
        key = (item["target"], item["code"])
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def collect(slot, today):
    found = []
    sources = []
    seen_urls = set()
    for query in search_queries(slot, today):
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
            if not relevant_to_slot(text, slot, today):
                continue
            codes = extract_codes(text, slot)
            source_name = known_blogger(text)
            sources.append({"source": source_name, "title": result["title"], "url": result["url"], "codes": codes})
            for item in codes:
                item = dict(item)
                item["source"] = source_name
                item["url"] = result["url"]
                found.append(item)
    return unique_found(found), sources


def unique_found(found):
    seen = set()
    output = []
    for item in found:
        key = (item["target"], item["code"], item["source"])
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


def format_message(date_text, slot, found, sources, final_attempt):
    lines = [f"{GAME_NAME}{slot['label']} {date_text}", f"本次目标：{'、'.join(slot['targets'])}"]
    if found:
        lines.append("")
        lines.append("抓到的码：")
        for item in found:
            lines.append(f"- {item['target']}：{item['code']}")
            lines.append(f"  来源：{item['source']}")
    else:
        lines.append("")
        lines.append("没抓到。")
        if final_attempt:
            lines.append("这已经是本时间点延长 10 分钟后的结果。")
        else:
            lines.append("还在 10 分钟窗口内，5 分钟后会继续尝试。")

    if sources:
        lines.append("")
        lines.append("参考来源：")
        for item in sources[:8]:
            lines.append(f"- {item['source']}：{item['title']} {item['url']}")
    return "\n".join(lines)


def push_serverchan(message):
    if not SERVERCHAN_SEND_URLS:
        print(message)
        raise SystemExit("Missing SERVERCHAN_SEND_URL secret.")
    data = urllib.parse.urlencode({"title": f"{GAME_NAME}每日码推送", "desp": message}).encode("utf-8")
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
    slot_id, slot, final_attempt = current_slot(now)
    if not slot:
        print(f"No active push window at {now.isoformat()}.")
        return

    date_text = now.date().strftime("%Y-%m-%d")
    state_key = f"{date_text}-{slot_id}"
    state = load_state()
    if state.get(state_key, {}).get("sent"):
        print(f"{state_key} already sent; skipping duplicate.")
        return

    found, sources = collect(slot, now.date())
    if not found and not final_attempt:
        print(format_message(date_text, slot, found, sources, final_attempt))
        return

    message = format_message(date_text, slot, found, sources, final_attempt)
    print(message)
    push_serverchan(message)
    state[state_key] = {"sent": True, "sent_at": now.isoformat(), "found": bool(found)}
    save_state(state)


if __name__ == "__main__":
    main()
