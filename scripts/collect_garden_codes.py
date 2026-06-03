import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request


GAME_NAME = "我的花园世界"
SERVERCHAN_SEND_URLS = [
    os.environ.get("SERVERCHAN_SEND_URL", "").strip(),
    os.environ.get("SERVERCHAN_SEND_URL_2", "").strip(),
]
SERVERCHAN_SEND_URLS = [url for url in SERVERCHAN_SEND_URLS if url]


def fetch(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def search_duckduckgo(query):
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    text = fetch(url)
    results = []
    for match in re.finditer(
        r'class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        text,
        flags=re.S,
    ):
        href = html.unescape(match.group("href"))
        title = re.sub(r"<.*?>", "", match.group("title"))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        if "uddg=" in href:
            parsed = urllib.parse.urlparse(href)
            href = urllib.parse.parse_qs(parsed.query).get("uddg", [href])[0]
        if title and href:
            results.append({"title": title, "url": href})
    return results


def extract_codes(text):
    candidates = set()
    for token in re.findall(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9_-]{4,24}(?![A-Za-z0-9])", text):
        if re.search(r"\d", token) and re.search(r"[A-Za-z]", token):
            candidates.add(token)
    return sorted(candidates)


def collect():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    date_text = today.strftime("%Y-%m-%d")
    queries = [
        f"{GAME_NAME} 限时码 {date_text}",
        f"{GAME_NAME} 兑换码 {date_text}",
        f"{GAME_NAME} 礼包码 今日",
        f"{GAME_NAME} 博主 限时码",
    ]

    seen_urls = set()
    sources = []
    codes = {}

    for query in queries:
        try:
            results = search_duckduckgo(query)
        except Exception as exc:
            print(f"Search failed for {query}: {exc}", file=sys.stderr)
            continue

        for result in results[:5]:
            url = result["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = result["title"]
            joined = f"{title} {url}"
            found = extract_codes(joined)
            if GAME_NAME in joined or "花园世界" in joined or found:
                sources.append({"title": title, "url": url})
            for code in found:
                codes.setdefault(code, []).append(title)

    message = format_message(date_text, codes, sources)
    return message


def format_message(date_text, codes, sources):
    lines = [f"{GAME_NAME}限时码 {date_text}"]
    if codes:
        lines.append("")
        lines.append("今日收集到的疑似兑换码：")
        for code in sorted(codes):
            lines.append(f"- {code}")
        lines.append("")
        lines.append("提示：限时码可能很快过期，请尽快兑换。")
    else:
        lines.append("")
        lines.append("未找到可靠新码。")
        lines.append("提示：今天公开网页里暂时没有抓到可核对的限时码。")

    if sources:
        lines.append("")
        lines.append("参考来源：")
        for item in sources[:5]:
            lines.append(f"- {item['title']} {item['url']}")

    return "\n".join(lines)


def push_serverchan(message):
    if not SERVERCHAN_SEND_URL:
        print(message)
        raise SystemExit("Missing SERVERCHAN_SEND_URL secret.")

    data = urllib.parse.urlencode({
        "title": f"{GAME_NAME}限时码",
        "desp": message,
    }).encode("utf-8")

    req = urllib.request.Request(
        SERVERCHAN_SEND_URL,
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
        print(body)
        raise

    print(body)


if __name__ == "__main__":
    msg = collect()
    print(msg)
    push_serverchan(msg)
