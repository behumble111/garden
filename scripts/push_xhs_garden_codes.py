import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import platformdirs


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

GAME_NAME = "我的花园世界"
ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".garden_code_state.json"
SERVERCHAN_FILE = ROOT / "serverchan_urls.txt"
XHS_COOKIE_FILE = ROOT / "xhs_cookie.txt"

KNOWN_CREATORS = [
    "草莓熊崽",
    "若水",
    "jojomoonX",
    "时光机无心",
    "喵喵嗷呜",
    "我的花园世界-金兰叶序",
    "唐僧给块肉呗",
    "我的花园世界",
]

TRUSTED_CREATORS = ["草莓熊崽", "若水", "jojomoonX", "时光机无心", "我的花园世界-金兰叶序"]
OFFICIAL_WORDS = ["官服", "微信", "微信小游戏", "小程序"]
NON_OFFICIAL_WORDS = [
    "渠道服",
    "抖音服",
    "抖服",
    "斗服",
    "快手服",
    "小游戏中心",
    "吱吱宝服",
    "支吱宝服",
    "支付宝服",
    "蓝服",
    "九游",
    "TapTap",
    "taptap",
    "华为服",
    "小米服",
    "vivo服",
    "oppo服",
]

SLOT_CONFIG = {
    "20": {
        "label": "20点限时码",
        "target": "limited_20",
        "keywords": ["20点兑换码", "8点兑换码", "八点兑换码", "限时码1", "20:00", "20点限时码"],
        "include_daily": True,
        "include_weekly": True,
        "window": "20:05-20:20 左右",
    },
    "21": {
        "label": "21点限时码",
        "target": "limited_21",
        "keywords": ["21点兑换码", "9点兑换码", "九点兑换码", "限时码2", "21:10", "21点限时码"],
        "include_daily": False,
        "include_weekly": False,
        "window": "21:23-21:38 左右",
    },
    "22": {
        "label": "22点限时码",
        "target": "limited_22",
        "keywords": ["22点兑换码", "10点兑换码", "十点兑换码", "限时码3", "22:10", "22点限时码"],
        "include_daily": False,
        "include_weekly": False,
        "window": "22:00-22:20 左右",
    },
}


def beijing_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def find_xhs_upstream():
    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "aione" / "upstreams" / "Spider_XHS")
    candidates.extend(
        [
            Path(platformdirs.user_data_dir("aione")) / "upstreams" / "Spider_XHS",
            Path.home() / ".local" / "share" / "aione" / "upstreams" / "Spider_XHS",
            Path.home() / "AppData" / "Local" / "aione" / "upstreams" / "Spider_XHS",
        ]
    )
    for candidate in candidates:
        try:
            exists = candidate.exists()
        except OSError:
            exists = False
        if exists:
            return candidate
    return candidates[0]


XHS_UPSTREAM = find_xhs_upstream()
NODE_BIN = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin"
AUTH_FAILED = False


def clean_env_text(value):
    return (value or "").lstrip("\ufeff").strip()


def run_source_label():
    return clean_env_text(os.environ.get("GARDEN_RUN_SOURCE")) or "本地 Windows"


def load_state():
    if not STATE_PATH.exists():
        return {"sent_slots": {}, "sent_week_codes": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sent_slots": {}, "sent_week_codes": []}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_xhs_cookie():
    if os.environ.get("XHS_COOKIE"):
        return clean_env_text(os.environ["XHS_COOKIE"])
    if XHS_COOKIE_FILE.exists():
        return clean_env_text(XHS_COOKIE_FILE.read_text(encoding="utf-8"))
    return ""


def run_aione(args):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cookie = load_xhs_cookie()
    if cookie and not env.get("AIONE_XHS_COOKIES"):
        env["AIONE_XHS_COOKIES"] = cookie
    if NODE_BIN.exists():
        env["PATH"] = str(NODE_BIN) + os.pathsep + env.get("PATH", "")

    proc = subprocess.run(
        ["aione", *args],
        cwd=str(XHS_UPSTREAM),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=70,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout)


def xhs_search(query, page=1):
    result = run_aione(["xhs", "note", "search", "--query", query, "--page", str(page), "--output", "json"])
    ok, msg, payload = result
    if not ok:
        raise RuntimeError(msg)
    return (payload.get("data") or {}).get("items") or []


def xhs_note_info(note_id, xsec_token):
    url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={urllib.parse.quote(xsec_token)}&xsec_source=pc_search"
    result = run_aione(["xhs", "note", "info", "--url", url, "--output", "json"])
    ok, msg, payload = result
    if not ok:
        raise RuntimeError(msg)
    items = ((payload.get("data") or {}).get("items") or [])
    if not items:
        raise RuntimeError("empty note detail")
    return items[0], url


def normalize_text(value):
    if value is None:
        return ""
    return str(value)


def note_summary(item, url):
    card = item.get("note_card") or {}
    user = card.get("user") or {}
    desc = normalize_text(card.get("desc"))
    title = normalize_text(card.get("title") or card.get("display_title"))
    return {
        "title": title,
        "author": normalize_text(user.get("nickname") or user.get("nick_name")),
        "desc": desc,
        "url": url,
        "time": card.get("time"),
        "last_update_time": card.get("last_update_time"),
    }


def xhs_time_to_beijing_date(value):
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return dt.datetime.fromtimestamp(timestamp, dt.timezone(dt.timedelta(hours=8))).date()


def note_is_today(summary, today):
    dates = [
        xhs_time_to_beijing_date(summary.get("time")),
        xhs_time_to_beijing_date(summary.get("last_update_time")),
    ]
    return today in dates


def clean_code(value):
    value = re.sub(r"\[[^\]]+R\]", "", value)
    value = re.sub(r"#.*$", "", value)
    value = value.strip(" \t:：,，。；;、-—|")
    if ":" in value or "：" in value:
        value = re.split(r"[:：]", value)[-1]
    value = re.sub(r"\s+", "", value)
    value = re.split(r"[，,。；;、\s]", value)[0]
    return value.strip(" \t:：,，。；;、-—|")


def good_code(value):
    if not value:
        return False
    if len(value) < 4 or len(value) > 24:
        return False
    if re.search(r"https?://|领取路径|主界面|兑换码选项|有效|左右|更新|搜索|关注|评论|复制", value):
        return False
    if re.search(r"兑换码|限时码|通码|周码|日码|官服|微信|版本|花园世界|攻略|全部|今日|本周", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def official_score(text):
    score = 0
    for word in OFFICIAL_WORDS:
        if word in text:
            score += 2
    for word in NON_OFFICIAL_WORDS:
        if word in text:
            score -= 8
    return score


def is_excluded_source(text):
    return any(word in text for word in NON_OFFICIAL_WORDS)


def trusted_author(author):
    return any(name in author for name in TRUSTED_CREATORS)


def official_note_text(desc):
    lines = re.split(r"[\n\r]+", normalize_text(desc))
    selected = []
    in_official = True
    seen_section = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if selected and selected[-1]:
                selected.append("")
            continue

        if any(word in line for word in NON_OFFICIAL_WORDS):
            in_official = False
            seen_section = True
            continue
        if any(word in line for word in OFFICIAL_WORDS) or re.search(r"官服ID|ys开头", line, flags=re.I):
            in_official = True
            seen_section = True

        if in_official or not seen_section:
            selected.append(line)
    return "\n".join(selected)


def extract_by_labels(desc):
    found = {}
    patterns = [
        ("weekly", r"(?:周码|本周码|每周码)[^：:\n\r]{0,16}[：:\s]+([^\n\r]+)"),
        ("daily", r"(?:今日通码|今日通用|今日通用码|日码|通码|通用码)[^：:\n\r]{0,16}[：:\s]+([^\n\r]+)"),
        ("limited_20", r"(?:20点|20\s*[:：]\s*00|8点|八点|限时码\s*1|第一个限时码)[^：:\n\r]{0,20}[：:\s]+([^\n\r]+)"),
        ("limited_21", r"(?:21点|21\s*[:：]\s*10|9点|九点|限时码\s*2|第二个限时码)[^：:\n\r]{0,20}[：:\s]+([^\n\r]+)"),
        ("limited_22", r"(?:22点|22\s*[:：]\s*10|10点|十点|限时码\s*3|第三个限时码)[^：:\n\r]{0,20}[：:\s]+([^\n\r]+)"),
    ]
    for kind, pattern in patterns:
        match = re.search(pattern, desc, flags=re.I)
        if match:
            code = clean_code(match.group(1))
            if good_code(code):
                found[kind] = code
    return found


def extract_line_candidates(desc):
    candidates = []
    for raw_line in re.split(r"[\n\r]+", desc):
        line = raw_line.strip()
        if not line:
            continue
        search_text = line
        if ":" in line or "：" in line:
            search_text = re.split(r"[:：]", line, maxsplit=1)[-1]
        for match in re.finditer(r"[\u4e00-\u9fff]{4,16}", search_text):
            code = clean_code(match.group(0))
            if good_code(code):
                candidates.append((line, code))
    return candidates


def infer_code_kind(line, slot):
    if re.search(r"周码|本周|每周", line):
        return "weekly"
    if re.search(r"今日通码|今日通用|日码|通码|通用码", line):
        return "daily"
    if re.search(r"20点|20\s*[:：]\s*00|8点|八点|限时码\s*1|第一个", line):
        return "limited_20"
    if re.search(r"21点|21\s*[:：]\s*10|9点|九点|限时码\s*2|第二个", line):
        return "limited_21"
    if re.search(r"22点|22\s*[:：]\s*10|10点|十点|限时码\s*3|第三个", line):
        return "limited_22"
    return ""


def extract_codes(desc, slot):
    official_text = official_note_text(desc)
    found = extract_by_labels(official_text)
    for line, code in extract_line_candidates(official_text):
        kind = infer_code_kind(line, slot)
        if kind and kind not in found:
            found[kind] = code
    return found


def aggregate_candidates(candidates):
    grouped = {}
    for item in candidates:
        grouped.setdefault(item["kind"], {}).setdefault(
            item["code"],
            {"score": 0, "sources": [], "authors": set(), "trusted": 0},
        )
        bucket = grouped[item["kind"]][item["code"]]
        source = item["source"]
        author = source.get("author") or "未知来源"
        author_key = author.lower()
        if author_key not in bucket["authors"]:
            bucket["authors"].add(author_key)
            bucket["sources"].append(source)
            bucket["score"] += 10
            if trusted_author(author):
                bucket["score"] += 8
                bucket["trusted"] += 1
        bucket["score"] += max(0, item.get("score", 0))

    codes = {}
    evidence = {}
    for kind, by_code in grouped.items():
        code, data = sorted(
            by_code.items(),
            key=lambda pair: (pair[1]["score"], len(pair[1]["authors"]), pair[1]["trusted"]),
            reverse=True,
        )[0]
        codes[kind] = code
        evidence[kind] = {
            "sources": data["sources"],
            "source_count": len(data["authors"]),
            "trusted_count": data["trusted"],
            "score": data["score"],
        }
    return codes, evidence


def build_queries(today, slot):
    md = f"{today.month}.{today.day}"
    md2 = f"{today.month}月{today.day}日"
    config = SLOT_CONFIG[slot]
    base = []
    base.extend(f"{creator} {GAME_NAME} 官服 {md}兑换码" for creator in TRUSTED_CREATORS)
    base.extend(f"{creator} {GAME_NAME} {config['label']}" for creator in TRUSTED_CREATORS)
    base.extend(f"{creator} {GAME_NAME} 官服 兑换码" for creator in TRUSTED_CREATORS)
    base.extend(f"{creator} {GAME_NAME} 兑换码" for creator in TRUSTED_CREATORS)
    base.extend([
        f"{GAME_NAME} 官服 {md}兑换码",
        f"{GAME_NAME} {md}兑换码",
        f"{GAME_NAME} 微信 {md2}兑换码",
        f"{GAME_NAME} 微信小游戏 {md2}兑换码",
        f"{GAME_NAME} {md2}兑换码",
        f"{GAME_NAME} 官服 今日通码",
        f"{GAME_NAME} 微信 今日通用码",
        f"{GAME_NAME} 今日通码",
        f"{GAME_NAME} 官服 {config['label']}",
        f"{GAME_NAME} {config['label']}",
    ])
    base.extend(f"{creator} {GAME_NAME} 官服 兑换码" for creator in KNOWN_CREATORS)
    base.extend(f"{creator} {GAME_NAME} 兑换码" for creator in KNOWN_CREATORS)
    base.extend(f"{GAME_NAME} 官服 {kw}" for kw in config["keywords"])
    base.extend(f"{GAME_NAME} 微信 {kw}" for kw in config["keywords"])
    base.extend(f"{GAME_NAME} {kw}" for kw in config["keywords"])
    return list(dict.fromkeys(base))


def search_card_text(item):
    card = item.get("note_card") or {}
    user = card.get("user") or {}
    parts = [
        card.get("display_title"),
        card.get("title"),
        card.get("desc"),
        user.get("nickname"),
        user.get("nick_name"),
    ]
    return " ".join(normalize_text(part) for part in parts if part)


def relevant_search_result(item):
    text = search_card_text(item)
    return GAME_NAME in text or "花园世界" in text or "兑换码" in text or "限时码" in text


def slot_text_matches(text, slot):
    patterns = {
        "20": r"20点|20\s*[:：]\s*00|8点|八点|限时码\s*1|第一个限时码|限时码一",
        "21": r"21点|21\s*[:：]\s*10|9点|九点|限时码\s*2|第二个限时码|限时码二",
        "22": r"22点|22\s*[:：]\s*10|10点|十点|限时码\s*3|第三个限时码|限时码三",
    }
    return bool(re.search(patterns[slot], text, flags=re.I))


def relevant_note_text(text, slot):
    return (
        slot_text_matches(text, slot)
        or "兑换码" in text
        or "限时码" in text
        or "通码" in text
        or "周码" in text
    )


def collect_from_xhs(slot, today):
    global AUTH_FAILED
    seen = set()
    details = []
    candidates = []
    auth_failures = 0

    for query in build_queries(today, slot):
        if auth_failures >= 3:
            print("Stop search after repeated XHS auth failures.", file=sys.stderr)
            break
        print(f"Search query: {query}", file=sys.stderr)
        try:
            items = xhs_search(query)
        except Exception as exc:
            if any(marker in str(exc) for marker in ["登录已过期", "login", "cookie", "Cookie", "unauthorized"]):
                AUTH_FAILED = True
                auth_failures += 1
            print(f"Search failed: {query}: {exc}", file=sys.stderr)
            continue
        auth_failures = 0
        print(f"Search returned {len(items)} items: {query}", file=sys.stderr)
        if items:
            samples = []
            for sample in items[:3]:
                card = sample.get("note_card") or {}
                user = card.get("user") or {}
                samples.append(
                    {
                        "title": card.get("display_title") or card.get("title") or "",
                        "author": user.get("nickname") or user.get("nick_name") or "",
                        "type": sample.get("model_type"),
                    }
                )
            print(json.dumps({"samples": samples}, ensure_ascii=False), file=sys.stderr)

        for item in items:
            if item.get("model_type") != "note":
                continue
            note_id = item.get("id")
            xsec_token = item.get("xsec_token") or ""
            if not note_id or note_id in seen:
                continue
            seen.add(note_id)
            if not relevant_search_result(item):
                continue

            try:
                detail, url = xhs_note_info(note_id, xsec_token)
            except Exception as exc:
                print(f"Detail failed: {note_id}: {exc}", file=sys.stderr)
                continue

            summary = note_summary(detail, url)
            full_text = f"{summary['title']} {summary['author']} {summary['desc']}"
            if not note_is_today(summary, today):
                print(f"Skip old note: {summary['author']} {summary['title']}", file=sys.stderr)
                continue
            if not relevant_note_text(full_text, slot):
                print(f"Skip note without code marker: {summary['author']} {summary['title']}", file=sys.stderr)
                continue

            codes = extract_codes(summary["desc"], slot)
            summary = {**summary, "codes": codes, "official_score": official_score(full_text)}
            details.append(summary)
            for kind, code in codes.items():
                candidates.append(
                    {
                        "kind": kind,
                        "code": code,
                        "source": summary,
                        "score": summary["official_score"] + (3 if kind == SLOT_CONFIG[slot]["target"] else 0),
                    }
                )

            if len(details) >= 8:
                break
        if len(details) >= 8:
            break

    codes, evidence = aggregate_candidates(candidates)
    return codes, evidence, details


def normalize_serverchan_url(value):
    value = value.strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.lower().startswith(("sct", "sctp")):
        return f"https://sctapi.ftqq.com/{value}.send"
    return value


def serverchan_urls():
    values = [
        os.environ.get("SERVERCHAN_SEND_URL", "").strip(),
        os.environ.get("SERVERCHAN_SEND_URL_2", "").strip(),
    ]
    if SERVERCHAN_FILE.exists():
        values.extend(
            line.strip()
            for line in SERVERCHAN_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    urls = [normalize_serverchan_url(value) for value in values]
    return list(dict.fromkeys(url for url in urls if url))


def push_serverchan(title, message):
    urls = serverchan_urls()
    if not urls:
        print(message)
        raise SystemExit(f"Missing ServerChan URL. Put URLs in {SERVERCHAN_FILE}")

    data = urllib.parse.urlencode({"title": title, "desp": message}).encode("utf-8")
    for index, url in enumerate(urls, start=1):
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(f"ServerChan #{index}: {body}")


def line_for(label, kind, codes, sources):
    if kind not in codes:
        return f"- {label}：未抓到"
    src = sources.get(kind) or {}
    author = src.get("author") or "未知来源"
    return f"- {label}：{codes[kind]}（来源：{author}）"


def compact_note_text(text, limit=1800):
    text = normalize_text(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n……（正文较长，已截断）"


def evidence_line(kind, evidence):
    data = evidence.get(kind) or {}
    sources = data.get("sources") or []
    names = []
    for src in sources[:4]:
        author = src.get("author") or "未知来源"
        if author not in names:
            names.append(author)
    if not names:
        return "佐证：暂无稳定来源"
    if data.get("source_count", 0) >= 2:
        return f"佐证：{data['source_count']} 个来源一致（{'、'.join(names)}）"
    return f"佐证：单来源（{names[0]}）"


def code_block(label, code, kind, evidence):
    lines = [f"### **{label}**", f"## **{code}**", f"复制：`{code}`", evidence_line(kind, evidence)]
    return lines


def build_summary_message(slot, attempt, today, codes, evidence, details, source_label):
    config = SLOT_CONFIG[slot]
    lines = [f"{GAME_NAME}官服/微信版本兑换码 {today.isoformat()}"]
    lines.append("")
    lines.append(f"来源：{source_label}")
    lines.append("")
    lines.append(f"检查次数：第 {attempt}/3 次")
    lines.append("")

    if slot == "20":
        if codes.get("weekly"):
            lines.extend(code_block("本周周码", codes["weekly"], "weekly", evidence))
            lines.append("")
        if codes.get("daily"):
            lines.extend(code_block("今日通码（官服）", codes["daily"], "daily", evidence))
            lines.append("")
        if codes.get("limited_20"):
            lines.extend(code_block(f"官服 20点限时码（{SLOT_CONFIG['20']['window']}）", codes["limited_20"], "limited_20", evidence))
    elif slot == "21" and codes.get("limited_21"):
        lines.extend(code_block(f"官服 21点限时码（{SLOT_CONFIG['21']['window']}）", codes["limited_21"], "limited_21", evidence))
    elif slot == "22" and codes.get("limited_22"):
        lines.extend(code_block(f"官服 22点限时码（{SLOT_CONFIG['22']['window']}）", codes["limited_22"], "limited_22", evidence))
    else:
        lines.append(f"未确认到 {config['label']}。")

    lines.append("")
    lines.append("来源笔记：")
    used = set()
    for data in evidence.values():
        for src in (data.get("sources") or []):
            key = src.get("url") or f"{src.get('author')}:{src.get('title')}"
            if key in used:
                continue
            used.add(key)
            lines.append(f"- {src.get('author', '未知来源')}《{src.get('title', '')}》")
            if src.get("url"):
                lines.append(f"  {src['url']}")
            if len(used) >= 5:
                break
        if len(used) >= 5:
            break

    if details and not used:
        lines.append(f"- 已找到 {len(details)} 条相关笔记，但未形成可发送的官服码。")

    return "\n".join(lines).rstrip()


def build_raw_note_message(slot, attempt, today, details, source_label):
    lines = [f"{GAME_NAME}兑换码原文转发 {today.isoformat()} {SLOT_CONFIG[slot]['label']}"]
    lines.append("")
    lines.append(f"来源：{source_label}")
    lines.append("")
    lines.append("说明：本次直接转发相关博主当天兑换码笔记正文，请你自行摘取。")
    lines.append("")

    if not details:
        lines.append("未抓到今天相关兑换码笔记。")
        lines.append("")
        lines.append(f"检查次数：第 {attempt}/3 次")
        return "\n".join(lines)

    for index, note in enumerate(details[:3], start=1):
        title = note.get("title") or "无标题"
        author = note.get("author") or "未知博主"
        url = note.get("url") or ""
        desc = compact_note_text(note.get("desc") or title)
        lines.append(f"来源 {index}：{author}《{title}》")
        if url:
            lines.append(url)
        lines.append("")
        lines.append(desc)
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(f"检查次数：第 {attempt}/3 次")
    return "\n".join(lines).rstrip()


def build_message(slot, attempt, today, codes, sources, state, source_label):
    lines = [f"{GAME_NAME}官服/微信版本兑换码 {today.isoformat()} {SLOT_CONFIG[slot]['label']}"]
    lines.append("")
    lines.append(f"来源：{source_label}")
    lines.append("")

    if slot == "20":
        weekly_code = codes.get("weekly")
        if weekly_code and weekly_code not in state.get("sent_week_codes", []):
            lines.append(line_for("周码", "weekly", codes, sources))
        elif SLOT_CONFIG[slot]["include_weekly"]:
            lines.append("- 周码：未发现新的周码")
        lines.append(line_for("今日通码", "daily", codes, sources))
        lines.append(line_for("20点限时码", "limited_20", codes, sources))
    elif slot == "21":
        lines.append(line_for("21点限时码", "limited_21", codes, sources))
    else:
        lines.append(line_for("22点限时码", "limited_22", codes, sources))

    lines.append("")
    lines.append(f"检查次数：第 {attempt}/3 次")
    lines.append("服区限制：官服 / 微信版本")
    if any(sources.values()):
        lines.append("")
        lines.append("参考笔记：")
        used = set()
        for src in sources.values():
            key = src.get("url")
            if key and key not in used:
                used.add(key)
                lines.append(f"- {src.get('author', '未知来源')}《{src.get('title', '')}》")
                lines.append(f"  {src.get('url')}")
    return "\n".join(lines)


def build_auth_failed_message(today, source_label):
    return "\n".join(
        [
            f"{GAME_NAME}官服/微信版本兑换码 {today.isoformat()}",
            "",
            f"来源：{source_label}",
            "",
            "小红书登录已过期，无法搜索兑换码。",
            "",
            "请更新 GitHub Secret 里的 XHS_COOKIE；如果本地也要继续抓取，也需要更新本地 xhs_cookie.txt 或 aione 的小红书 cookie。",
            "",
            "这不是“未抓到兑换码”，而是搜索权限失效。",
        ]
    )


def should_send(slot, attempt, codes):
    target = SLOT_CONFIG[slot]["target"]
    if slot == "20":
        return bool(codes.get(target) or codes.get("daily") or codes.get("weekly")) or attempt >= 3
    return bool(codes.get(target)) or attempt >= 3


def should_send_raw_notes(attempt, details):
    return bool(details) or attempt >= 3


def should_send_codes(slot, codes):
    target = SLOT_CONFIG[slot]["target"]
    if slot == "20":
        return bool(codes.get(target) or codes.get("daily") or codes.get("weekly"))
    return bool(codes.get(target))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=["20", "21", "22"], required=True)
    parser.add_argument("--attempt", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--date", help="Beijing date to search, YYYY-MM-DD. Defaults to today's Beijing date.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-message", action="store_true")
    args = parser.parse_args()
    source_label = run_source_label()

    if args.test_message:
        push_serverchan(
            f"{GAME_NAME}官服推送测试",
            f"{GAME_NAME}官服/微信版本推送测试\n\n来源：{source_label}\n\n如果两个手机都收到，说明本地双 Server 酱配置正常。",
        )
        return

    now = beijing_now()
    today = dt.date.fromisoformat(args.date) if args.date else now.date()
    state = load_state()
    slot_key = f"{today.isoformat()}-{args.slot}"
    if not args.dry_run and state.get("sent_slots", {}).get(slot_key):
        print(f"Already sent {slot_key}; skip.")
        return

    codes, evidence, details = collect_from_xhs(args.slot, today)
    print(json.dumps({"codes": codes, "details_found": len(details)}, ensure_ascii=False, indent=2))

    if os.environ.get("GARDEN_SKIP_EMPTY_PUSH") == "1" and not codes and not details and not AUTH_FAILED:
        print("No XHS details found; skip empty cloud push.")
        return

    if AUTH_FAILED and not codes:
        alert_key = f"{today.isoformat()}-xhs-auth-failed"
        if not args.dry_run and state.get("sent_slots", {}).get(alert_key):
            print(f"Already sent {alert_key}; skip.")
            return
        message = build_auth_failed_message(today, source_label)
        title = f"{GAME_NAME}小红书登录已过期"
        if args.dry_run:
            print("DRY_RUN_MESSAGE_BEGIN")
            print(message)
            print("DRY_RUN_MESSAGE_END")
            return
        push_serverchan(title, message)
        state.setdefault("sent_slots", {})[alert_key] = {
            "sent_at": now.isoformat(),
            "source": source_label,
            "codes": {},
        }
        save_state(state)
        return

    if not should_send_codes(args.slot, codes):
        print("No confirmed official code yet; skip push until next attempt.")
        return

    message = build_summary_message(args.slot, args.attempt, today, codes, evidence, details, source_label)
    title = f"{GAME_NAME}{SLOT_CONFIG[args.slot]['label']}官服"

    if args.dry_run:
        print("DRY_RUN_MESSAGE_BEGIN")
        print(message)
        print("DRY_RUN_MESSAGE_END")
        return

    push_serverchan(title, message)
    state.setdefault("sent_slots", {})[slot_key] = {
        "sent_at": now.isoformat(),
        "source": source_label,
        "codes": codes,
        "evidence": {
            kind: {
                "source_count": data.get("source_count", 0),
                "trusted_count": data.get("trusted_count", 0),
                "sources": [
                    {
                        "author": source.get("author"),
                        "title": source.get("title"),
                        "url": source.get("url"),
                    }
                    for source in (data.get("sources") or [])[:5]
                ],
            }
            for kind, data in evidence.items()
        },
        "notes": [
            {
                "author": note.get("author"),
                "title": note.get("title"),
                "url": note.get("url"),
            }
            for note in details[:3]
        ],
    }
    weekly_code = codes.get("weekly")
    if args.slot == "20" and weekly_code and weekly_code not in state.get("sent_week_codes", []):
        state.setdefault("sent_week_codes", []).append(weekly_code)
    save_state(state)


if __name__ == "__main__":
    main()
