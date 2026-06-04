import datetime as dt
import html
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


GAME_NAME = "我的花园世界"
TARGET_BLOGGERS = [
    {
        "platform": "小红书",
        "name": "喵喵嗷呜",
        "red_id": "4278304669",
    }
]
SERVERCHAN_SEND_URLS = [
    os.environ.get("SERVERCHAN_SEND_URL", "").strip(),
    os.environ.get("SERVERCHAN_SEND_URL_2", "").strip(),
]
SERVERCHAN_SEND_URLS = [url for url in SERVERCHAN_SEND_URLS if url]


def fetch(url, timeout=10):
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


def search_duckduckgo(query):
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    text = fetch(url)
    results = []
    for match in re.finditer(r'<div class="result.*?</div>\s*</div>', text, flags=re.S):
        block = match.group(0)
        link = re.search(r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', block, flags=re.S)
        if not link:
            continue
        href = html.unescape(link.group("href"))
        title = clean_text(link.group("title"))
        if "uddg=" in href:
            parsed = urllib.parse.urlparse(href)
            href = urllib.parse.parse_qs(parsed.query).get("uddg", [href])[0]
        snippet = clean_text(block)
        if title and href:
            results.append({"title": title, "url": href, "text": snippet, "source": "DuckDuckGo"})
    return results


def search_bing(query):
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
    text = fetch(url)
    results = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return results
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        href = item.findtext("link") or ""
        description = item.findtext("description") or ""
        title = clean_text(title)
        description = clean_text(description)
        if not title or not href:
            continue
        results.append({"title": title, "url": href, "text": f"{title} {description}", "source": "Bing"})
    return results


def search_weibo_public(query):
    url = "https://s.weibo.com/weibo?" + urllib.parse.urlencode({"q": query})
    text = fetch(url)
    if any(marker in text for marker in ["passport.weibo.com", "登录", "verifybypass"]):
        raise RuntimeError("微博公开搜索需要登录或被验证拦截")
    return parse_public_links(text, "weibo.com", "微博")


def search_xiaohongshu_public(query):
    url = "https://www.xiaohongshu.com/search_result?" + urllib.parse.urlencode({"keyword": query})
    text = fetch(url)
    if any(marker in text for marker in ["登录", "login", "captcha", "验证"]):
        raise RuntimeError("小红书公开搜索需要登录或被验证拦截")
    return parse_public_links(text, "xiaohongshu.com", "小红书")


def parse_public_links(text, domain, source):
    results = []
    for match in re.finditer(r'href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', text, flags=re.S):
        href = html.unescape(match.group("href"))
        title = clean_text(match.group("title"))
        if not href or not title:
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = f"https://{domain}" + href
        if domain in href:
            results.append({"title": title, "url": href, "text": title, "source": source})
    return results


def today_markers(today):
    return [
        today.strftime("%Y-%m-%d"),
        today.strftime("%Y/%m/%d"),
        f"{today.month}.{today.day}",
        f"{today.month}月{today.day}日",
        f"{today.month}-{today.day}",
        "今天",
        "今日",
        "今晚",
        "刚刚",
        "小时前",
        "分钟前",
    ]


def targeted_queries(today):
    queries = []
    for blogger in TARGET_BLOGGERS:
        queries.extend([
            f"{blogger['name']} {GAME_NAME} {today.month}月{today.day}日 限时码",
            f"{blogger['name']} {GAME_NAME} 今晚 限时码",
            f"{blogger['red_id']} {GAME_NAME} 限时码",
            f"site:xiaohongshu.com {blogger['name']} {GAME_NAME} 限时码",
        ])
    return dedupe(queries)


def dedupe(items):
    seen = set()
    output = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def is_target_source(text):
    for blogger in TARGET_BLOGGERS:
        if blogger["name"] in text or blogger["red_id"] in text:
            return True
    return False


def is_today_relevant(text, today):
    return any(marker in text for marker in today_markers(today))


def extract_limited_codes(text):
    codes = set()
    patterns = [
        r"限时码[：:\s]*([一-龥A-Za-z0-9_-]{2,16})",
        r"今日限时码[：:\s]*([一-龥A-Za-z0-9_-]{2,16})",
        r"今天限时码[：:\s]*([一-龥A-Za-z0-9_-]{2,16})",
        r"今晚限时码[：:\s]*([一-龥A-Za-z0-9_-]{2,16})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = normalize_code(match.group(1))
            if candidate:
                codes.add(candidate)
    return sorted(codes)


def normalize_code(candidate):
    candidate = candidate.strip(" ：:，,。.;；、[]【】（）()《》<>\"'“”‘’")
    if not (2 <= len(candidate) <= 16):
        return ""
    noise = ["兑换", "复制", "领取", "攻略", "最新", "今日", "今天", "今晚", "限时码"]
    if candidate in noise:
        return ""
    if re.fullmatch(r"\d{1,2}[.月-]\d{1,2}日?", candidate):
        return ""
    return candidate


def collect():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    date_text = today.strftime("%Y-%m-%d")
    seen_urls = set()
    sources = []
    codes = {}

    for query in targeted_queries(today):
        search_plan = [
            ("Bing", search_bing),
        ]
        for search_name, search_fn in search_plan:
            try:
                results = search_fn(query)[:4]
            except Exception as exc:
                print(f"{search_name} search failed for {query}: {exc}", file=sys.stderr)
                continue
            add_results(results, today, seen_urls, sources, codes)

    return format_message(date_text, codes, sources)


def add_results(results, today, seen_urls, sources, codes):
    for result in results:
        url = result["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = result["title"]
        source = result.get("source", "公开网页")
        joined = f"{title} {result.get('text', '')} {url}"

        if not is_target_source(joined):
            continue
        if "限时码" not in joined:
            continue
        if not is_today_relevant(joined, today):
            continue

        found = extract_limited_codes(joined)
        sources.append({"title": title, "url": url, "source": source, "codes": found})
        for code in found:
            codes.setdefault(code, []).append(title)


def format_message(date_text, codes, sources):
    blogger_text = "、".join(f"{item['platform']} {item['name']}({item['red_id']})" for item in TARGET_BLOGGERS)
    lines = [f"{GAME_NAME}今日限时码 {date_text}", f"目标博主：{blogger_text}"]
    if codes:
        lines.append("")
        lines.append("今日收集到的限时码：")
        for code in sorted(codes):
            lines.append(f"- {code}")
        lines.append("")
        lines.append("提示：限时码可能很快过期，请尽快兑换。")
    else:
        lines.append("")
        lines.append("未抓到指定博主今日限时码。")
        lines.append("提示：小红书/微博公开网页可能需要登录或前端接口加载；脚本不会发送泛攻略码或旧兑换码。")

    if sources:
        lines.append("")
        lines.append("参考来源：")
        for item in sources[:8]:
            code_text = f"；识别：{', '.join(item['codes'])}" if item["codes"] else ""
            lines.append(f"- [{item['source']}] {item['title']} {item['url']}{code_text}")

    return "\n".join(lines)


def push_serverchan(message):
    if not SERVERCHAN_SEND_URLS:
        print(message)
        raise SystemExit("Missing SERVERCHAN_SEND_URL secret.")

    data = urllib.parse.urlencode({
        "title": f"{GAME_NAME}今日限时码",
        "desp": message,
    }).encode("utf-8")

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


if __name__ == "__main__":
    msg = collect()
    print(msg)
    push_serverchan(msg)
