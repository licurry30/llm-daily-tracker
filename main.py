import os, json, re, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests, feedparser, yaml
from dateutil import parser as dtparser
from urllib.parse import quote_plus

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.getenv("CONFIG", os.path.join(BASE_DIR, "config.yaml"))
STATE_PATH = os.path.join(BASE_DIR, "data", "state.json")

UA = "llm-daily-tracker/1.0 (+https://github.com/; contact: you@example.com)"  # 可改

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "arena_prev": []}

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def strip_html(x, limit=300):
    if not x: return ""
    x = re.sub(r"<[^>]+>", "", x)
    x = re.sub(r"\s+", " ", x).strip()
    return (x[:limit] + "…") if len(x) > limit else x

def parse_entry_time(e):
    # 尽量从 RSS/Atom 提供的字段解析时间
    for key in ["published", "updated", "created", "date"]:
        if key in e and e[key]:
            try:
                return dtparser.parse(e[key])
            except Exception:
                pass
    for key in ["published_parsed", "updated_parsed"]:
        if key in e and e[key]:
            try:
                return datetime(*e[key][:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def fmt_local(dt, tz):
    if not dt: return ""
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")

def fetch_feed(source, since_dt, per_feed_limit, tz):
    out = []
    url = source["url"]
    name = source["name"]
    category = source.get("category", "misc")
    try:
        d = feedparser.parse(url, request_headers={"User-Agent": UA})
        for e in d.entries:
            eid = e.get("id") or e.get("link") or f"{name}:{e.get('title','')}"
            t = parse_entry_time(e)
            # 若无时间，保守纳入一次，后续靠 seen 去重
            if t and t < since_dt:
                continue
            item = {
                "id": eid,
                "title": e.get("title", "").strip(),
                "link": e.get("link", ""),
                "source": name,
                "category": category,
                "published": fmt_local(t, tz),
                "summary": strip_html(e.get("summary") or e.get("description") or ""),
            }
            out.append(item)
            if len(out) >= per_feed_limit:
                break
    except Exception as ex:
        print(f"[feed:error] {name} -> {ex}", file=sys.stderr)
    return out

def fetch_arxiv(topic, since_dt, per_topic_limit, tz):
    # arXiv API（Atom）
    q = topic["query"]
    max_results = topic.get("max_results", 25)
    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query={quote_plus(q)}&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )
    items = []
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        d = feedparser.parse(r.text)
        for e in d.entries:
            t = parse_entry_time(e)
            if t and t < since_dt:
                continue
            link = e.get("link", "")
            title = e.get("title", "").replace("\n", " ").strip()
            authors = ", ".join(a.get("name","") for a in e.get("authors", [])) if "authors" in e else ""
            summary = strip_html(e.get("summary", ""))
            items.append({
                "id": e.get("id", link or title),
                "title": title,
                "link": link,
                "source": f"arXiv · {topic['name']}",
                "category": "arxiv",
                "published": fmt_local(t, tz),
                "summary": summary,
                "authors": authors,
            })
            if len(items) >= per_topic_limit:
                break
    except Exception as ex:
        print(f"[arxiv:error] {topic['name']} -> {ex}", file=sys.stderr)
    return items

def prune_seen(seen, days_to_keep):
    now = datetime.now(timezone.utc)
    to_del = []
    for k, ts in seen.items():
        try:
            t = dtparser.parse(ts)
            if (now - t).days > days_to_keep:
                to_del.append(k)
        except Exception:
            to_del.append(k)
    for k in to_del:
        seen.pop(k, None)

def render_markdown(date_str, tz, items, config):
    def section(title):
        return f"\n## {title}\n"

    # 构建分类索引
    by_cat = {}
    for it in items:
        cat = it.get("category") or "misc"
        by_cat.setdefault(cat, []).append(it)

    # 各分区内按时间倒序
    for lst in by_cat.values():
        lst.sort(key=lambda x: x.get("published", ""), reverse=True)

    lines = []
    lines.append(f"# LLM Daily Brief — {date_str}")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now(ZoneInfo(config['timezone'])).strftime('%Y-%m-%d %H:%M')} ({config['timezone']})")
    lines.append(f"- 抓取窗口：{config.get('since_hours', 24)}h · 源数：{len(config.get('feeds', []))}")
    lines.append("")

    sections = config.get("sections", [])
    if sections:
        for sec in sections:
            title = sec.get("title") or sec.get("key")
            includes = sec.get("includes", [])
            # 汇总该分区内的条目
            sec_items = []
            for c in includes:
                sec_items.extend(by_cat.get(c, []))
            if not sec_items:
                continue
            lines.append(section(title))
            for it in sec_items:
                lines.append(f"- [{it['title']}]({it['link']}) — {it['source']} · {it.get('published','')}")
            lines.append("")
    else:
        # 回退：老的固定分组（避免 config 未更新时报错）
        for title, cats in [
            ("官方 / 厂商", ["vendor-cn", "vendor-global", "vendor"]),
            ("中文资讯", ["zh-media"]),
            ("英文资讯", ["en-news", "en-depth", "newsletter"]),
            ("研究机构 / 开源社区", ["research-lab", "open-source"]),
            ("论文 · arXiv", ["arxiv"]),
        ]:
            sec_items = []
            for c in cats:
                sec_items.extend(by_cat.get(c, []))
            if sec_items:
                lines.append(section(title))
                for it in sec_items:
                    lines.append(f"- [{it['title']}]({it['link']}) — {it['source']} · {it.get('published','')}")
                lines.append("")

    lines.append("---")
    lines.append("数据源与分组在 config.yaml → sections / feeds 中可自定义。")
    return "\n".join(lines)
  


def update_index(latest_date, out_dir):
    index_path = os.path.join(BASE_DIR, "docs", "index.md")
    rel = f"./daily/{latest_date}.md"
    content = f"""# LLM Daily Brief

- 最新日报：[{latest_date}]({rel})
- 所有历史：docs/daily/
- 使用说明见仓库 README.md
"""
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)

def main():
    config = load_yaml(CONFIG_PATH)
    tz = ZoneInfo(config.get("timezone", "UTC"))
    since_hours = int(config.get("since_hours", 24))
    since_dt = datetime.now(tz) - timedelta(hours=since_hours)
    # 将 since_dt 统一到 UTC 比较
    since_dt = since_dt.astimezone(timezone.utc)

    state = load_state()
    seen = state.get("seen", {})
    prune_seen(seen, int(config.get("days_to_keep_seen", 30)))

    per_feed_limit = int(config["max_items"]["per_feed"])
    per_arxiv_limit = int(config["max_items"]["per_arxiv"])


    all_news = []
    # RSS 源
    for src in config.get("feeds", []):
        items = fetch_feed(src, since_dt, per_feed_limit, tz)
        for it in items:
            if it["id"] in seen:
                continue
            seen[it["id"]] = datetime.now(timezone.utc).isoformat()
            all_news.append(it)

    # arXiv
    all_arxiv = []
    for topic in config.get("arxiv", []):
        itms = fetch_arxiv(topic, since_dt, per_arxiv_limit, tz)
        for it in itms:
            if it["id"] in seen:
                continue
            seen[it["id"]] = datetime.now(timezone.utc).isoformat()
            all_arxiv.append(it)

    combined_items = all_news + all_arxiv

    today = datetime.now(tz).strftime("%Y-%m-%d")
    out_dir = os.path.join(BASE_DIR, config.get("output_dir", "docs/daily"))
    ensure_dir(out_dir)
    out_path = os.path.join(out_dir, f"{today}.md")
    report = render_markdown(today, tz, combined_items, arena_rows, config)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    # 首页
    ensure_dir(os.path.join(BASE_DIR, "docs"))
    update_index(today, out_dir)

    # 保存状态
    state["seen"] = seen
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"Generated: {out_path}")

if __name__ == "__main__":
    main()
