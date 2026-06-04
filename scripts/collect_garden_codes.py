import datetime as dt
import html
import os
import re
import sys
import urllib.error
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
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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
            results.append({"title": title, "url": href, "source": "DuckDuckGo"})
    return results


def search_bing(query):
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
    text = fetch(url)
    results = []
    for match in re.finditer(
        r'<li class="b_algo".*?<h2.*?><a href="(?P<href>[^"]+)".*?>(?P<title>.*?)</a>',
        text,
        flags=re.S,
    ):
        title = re.sub(r"<.*?>", "", match.group("title"))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        href = html.unescape(match.group("href"))
        if title and href:
            results.append({"title": title, "url": href, "source": "Bing"})
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
        title = re.sub(r"<.*?>", "", match.group("title"))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        if not href or not title:
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = f"https://{domain}" + href
        if domain in href:
            results.append({"title": title, "url": href, "source": source})
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
    direct_queries = [
        f"{GAME_NAME} 限时码",
        f"{GAME_NAME} 兑换码",
    ]
    fallback_queries = [
        f"{GAME_NAME} 限时码 {date_text}",
        f"{GAME_NAME} 兑换码 {date_text}",
        f"{GAME_NAME} 礼包码 今日",
        f"{GAME_NAME} 博主 限时码",
        f"{GAME_NAME} 限时码 小红书",
        f"{GAME_NAME} 兑换码 小红书",
        f"{GAME_NAME} 限时码 微博",
        f"{GAME_NAME} 兑换码 微博",
        f"site:xiaohongshu.com {GAME_NAME} 限时码",
        f"site:weibo.com {GAME_NAME} 限时码",
    ]

    seen_urls = set()
    sources = []
    codes = {}

    for query in direct_queries:
        for search_name, search_fn in (("微博", search_weibo_public), ("小红书", search_xiaohongshu_public)):
            try:
                add_results(search_fn(query)[:5], seen_urls, sources, codes)
            except Exception as exc:
                print(f"{search_name} public search failed for {query}: {exc}", file=sys.stderr)

    for query in fallback_queries:
        for search_name, search_fn in (("DuckDuckGo", search_duckduckgo), ("Bing", search_bing)):
            try:
                add_results(search_fn(query)[:5], seen_urls, sources, codes)
            except Exception as exc:
                print(f"{search_name} search failed for {query}: {exc}", file=sys.stderr)

    return format_message(date_text, codes, sources)


def add_results(results, seen_urls, sources, codes):
    for result in results:
        url = result["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = result["title"]
        source = result.get("source", "公开网页")
        joined = f"{title} {url}"
        found = extract_codes(joined)
        if GAME_NAME in joined or "花园世界" in joined or found:
            sources.append({"title": title, "url": url, "source": source})
        for code in found:
            codes.setdefault(code, []).append(title)


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
        for item in sources[:8]:
            lines.append(f"- [{item['source']}] {item['title']} {item['url']}")

    return "\n".join(lines)


def push_serverchan(message):
    if not SERVERCHAN_SEND_URLS:
        print(message)
        raise SystemExit("Missing SERVERCHAN_SEND_URL secret.")

    data = urllib.parse.urlencode({
        "title": f"{GAME_NAME}限时码",
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
