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


GAME_NAME = "我的花园世界"
ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".garden_code_state.json"
SERVERCHAN_FILE = ROOT / "serverchan_urls.txt"
def find_xhs_upstream():
    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "aione" / "upstreams" / "Spider_XHS")
    candidates.extend([
        Path(platformdirs.user_data_dir("aione")) / "upstreams" / "Spider_XHS",
        Path.home() / ".local" / "share" / "aione" / "upstreams" / "Spider_XHS",
        Path.home() / "AppData" / "Local" / "aione" / "upstreams" / "Spider_XHS",
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


XHS_UPSTREAM = find_xhs_upstream()
NODE_BIN = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin"

KNOWN_CREATORS = [
    "jojomoonX",
    "喵喵嗷呜",
    "我的花园世界-金兰叶序",
    "我的花园世界",
]

SLOT_CONFIG = {
    "20": {
        "label": "20点限时码",
        "keywords": ["20点兑换码", "8点兑换码", "限时码1", "20:00"],
        "include_daily": True,
        "include_weekly": True,
    },
    "21": {
        "label": "21点限时码",
        "keywords": ["21点兑换码", "9点兑换码", "限时码2", "21:30"],
        "include_daily": False,
        "include_weekly": False,
    },
    "22": {
        "label": "22点限时码",
        "keywords": ["22点兑换码", "10点兑换码", "限时码3", "22:00"],
        "include_daily": False,
        "include_weekly": False,
    },
}


def beijing_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def load_state():
    if not STATE_PATH.exists():
        return {"sent_slots": {}, "sent_week_codes": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sent_slots": {}, "sent_week_codes": []}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_aione(args):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if os.environ.get("XHS_COOKIE") and not env.get("AIONE_XHS_COOKIES"):
        env["AIONE_XHS_COOKIES"] = os.environ["XHS_COOKIE"]
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


def clean_code(value):
    value = re.sub(r"\[[^\]]+R\]", "", value)
    value = re.sub(r"#.*$", "", value)
    value = value.strip(" \t:：-—，,。；;）)")
    if "：" in value or ":" in value:
        value = re.split(r"[:：]", value)[-1]
    value = re.sub(r"\s+", "", value)
    return value


def good_code(value):
    if not value:
        return False
    if len(value) < 4 or len(value) > 24:
        return False
    if re.search(r"https?://|领取路径|主界面|兑换码选项|有效|左右|更新", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def extract_codes(desc):
    found = {}
    patterns = [
        ("weekly", r"周码[^:：\n]*[:：]\s*([^\n\r]+)"),
        ("daily", r"(?:今日通用|今日通码|通用码|通码)[^:：\n]*[:：]\s*([^\n\r]+)"),
        ("limited_20", r"(?:限时码\s*1|限时码1|20\s*[:：]\s*00|20点|8点)[^:：\n]*[:：]\s*([^\n\r]+)"),
        ("limited_21", r"(?:限时码\s*2|限时码2|21\s*[:：]\s*30|21点|9点)[^:：\n]*[:：]\s*([^\n\r]+)"),
        ("limited_22", r"(?:限时码\s*3|限时码3|22\s*[:：]\s*00|22点|10点)[^:：\n]*[:：]\s*([^\n\r]+)"),
    ]
    for kind, pattern in patterns:
        match = re.search(pattern, desc, flags=re.I)
        if match:
            code = clean_code(match.group(1))
            if good_code(code):
                found[kind] = code
    return found


def note_summary(item, url):
    card = item.get("note_card") or {}
    user = card.get("user") or {}
    return {
        "title": card.get("title") or card.get("display_title") or "",
        "author": user.get("nickname") or user.get("nick_name") or "",
        "desc": card.get("desc") or "",
        "url": url,
        "time": card.get("time"),
        "last_update_time": card.get("last_update_time"),
    }


def build_queries(today, slot):
    md = f"{today.month}.{today.day}"
    md2 = f"{today.month}月{today.day}日"
    base = [
        f"{GAME_NAME} {md}日兑换码",
        f"{GAME_NAME} {md2}兑换码",
        f"{GAME_NAME} 今日通码",
        f"{GAME_NAME} 今日通用",
        f"{GAME_NAME} {SLOT_CONFIG[slot]['label']}",
    ]
    base.extend(f"{creator} {GAME_NAME} 兑换码" for creator in KNOWN_CREATORS)
    base.extend(f"{GAME_NAME} {kw}" for kw in SLOT_CONFIG[slot]["keywords"])
    return list(dict.fromkeys(base))


def collect_from_xhs(slot, today):
    seen = set()
    details = []
    merged = {}
    sources = {}

    for query in build_queries(today, slot):
        try:
            items = xhs_search(query)
        except Exception as exc:
            print(f"Search failed: {query}: {exc}", file=sys.stderr)
            continue

        for item in items:
            if item.get("model_type") != "note":
                continue
            note_id = item.get("id")
            xsec_token = item.get("xsec_token") or ""
            if not note_id or note_id in seen:
                continue
            seen.add(note_id)

            card = item.get("note_card") or {}
            title = card.get("display_title") or card.get("title") or ""
            if GAME_NAME not in title and "兑换码" not in title and "限时码" not in title:
                continue

            try:
                detail, url = xhs_note_info(note_id, xsec_token)
            except Exception as exc:
                print(f"Detail failed: {note_id}: {exc}", file=sys.stderr)
                continue

            summary = note_summary(detail, url)
            codes = extract_codes(summary["desc"])
            if not codes:
                continue

            details.append({**summary, "codes": codes})
            for kind, code in codes.items():
                if kind not in merged:
                    merged[kind] = code
                    sources[kind] = summary

            target_kind = {"20": "limited_20", "21": "limited_21", "22": "limited_22"}[slot]
            have_target = target_kind in merged
            have_daily = (not SLOT_CONFIG[slot]["include_daily"]) or "daily" in merged
            if have_target and have_daily:
                return merged, sources, details

            if len(details) >= 8:
                return merged, sources, details

    return merged, sources, details


def serverchan_urls():
    urls = [
        os.environ.get("SERVERCHAN_SEND_URL", "").strip(),
        os.environ.get("SERVERCHAN_SEND_URL_2", "").strip(),
    ]
    if SERVERCHAN_FILE.exists():
        urls.extend(
            line.strip()
            for line in SERVERCHAN_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
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
            print(f"ServerChan #{index}: {resp.read().decode('utf-8', errors='replace')}")


def line_for(label, kind, codes, sources):
    if kind not in codes:
        return f"- {label}：未抓到"
    src = sources.get(kind) or {}
    author = src.get("author") or "未知来源"
    return f"- {label}：{codes[kind]}（来源：{author}）"


def build_message(slot, attempt, today, codes, sources, state):
    lines = [f"{GAME_NAME}兑换码 {today.isoformat()} {SLOT_CONFIG[slot]['label']}"]
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
    if any(sources.values()):
        lines.append("")
        lines.append("参考笔记：")
        used = []
        for src in sources.values():
            key = src.get("url")
            if key and key not in used:
                used.append(key)
                lines.append(f"- {src.get('author', '未知来源')}《{src.get('title', '')}》")
                lines.append(f"  {src.get('url')}")
    return "\n".join(lines)


def should_send(slot, attempt, codes):
    target = {"20": "limited_20", "21": "limited_21", "22": "limited_22"}[slot]
    if slot == "20":
        return bool(codes.get(target) or codes.get("daily") or codes.get("weekly")) or attempt >= 3
    return bool(codes.get(target)) or attempt >= 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=["20", "21", "22"], required=True)
    parser.add_argument("--attempt", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = beijing_now()
    today = now.date()
    state = load_state()
    slot_key = f"{today.isoformat()}-{args.slot}"
    if not args.dry_run and state.get("sent_slots", {}).get(slot_key):
        print(f"Already sent {slot_key}; skip.")
        return

    codes, sources, details = collect_from_xhs(args.slot, today)
    print(json.dumps({"codes": codes, "details_found": len(details)}, ensure_ascii=False, indent=2))

    if not should_send(args.slot, args.attempt, codes):
        print("Not enough codes yet; skip push until next attempt.")
        return

    message = build_message(args.slot, args.attempt, today, codes, sources, state)
    title = f"{GAME_NAME}{SLOT_CONFIG[args.slot]['label']}"

    if args.dry_run:
        print("DRY_RUN_MESSAGE_BEGIN")
        print(message)
        print("DRY_RUN_MESSAGE_END")
    else:
        push_serverchan(title, message)

    if not args.dry_run:
        state.setdefault("sent_slots", {})[slot_key] = {
            "sent_at": now.isoformat(),
            "codes": codes,
        }
        weekly_code = codes.get("weekly")
        if args.slot == "20" and weekly_code and weekly_code not in state.get("sent_week_codes", []):
            state.setdefault("sent_week_codes", []).append(weekly_code)
        save_state(state)


if __name__ == "__main__":
    main()
