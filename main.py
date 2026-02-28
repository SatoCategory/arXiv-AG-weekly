# -*- coding: utf-8 -*-
"""
毎週木曜 9:00 JST に arXiv math.AG の直近 N 日を取得し、
関心に近い論文を抽出 → 主定理候補を抽出 → 日本語PDFで要約。
要件：
- 詳細は最大3件、4件目以降はタイトルのみ
- 0件なら「0件でした」とPDFに明記
"""
import os, io, re, time, json, textwrap, datetime as dt
import requests, feedparser, yaml
from zoneinfo import ZoneInfo
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.units import mm
from pdfminer.high_level import extract_text

ARXIV_API = "https://export.arxiv.org/api/query"  # 公式API（Atom）
JST = ZoneInfo("Asia/Tokyo")

# User-Agent: arXivへの礼儀として連絡先（メール等）を含める
CONTACT = os.environ.get("ARXIV_CONTACT", "contact@example.com")
HEADERS = {"User-Agent": f"ag-weekly-bot (contact: {CONTACT})"}

_DEF_THEOREM_PATTERNS = [
    r"\bMain\s+Theorem\b.*",
    r"\bTheorem\s+\d+[^:]*:.*",
    r"\bTheorem\b[^:]*:.*",
    r"\bmain result\b.*",
    r"\bwe (prove|show|establish) that\b.*",
    r"(主定理|主結果|本論文の主結果)[^。\n]*[。．\n].*",
    r"(定理\s*\d*[^：]*：.*)"
]


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def arxiv_query_math_ag(max_results=2000, start=0, sortBy="submittedDate", sortOrder="descending"):
    params = {
        "search_query": "cat:math.AG",
        "start": start,
        "max_results": max_results,
        "sortBy": sortBy,
        "sortOrder": sortOrder,
    }
    r = requests.get(ARXIV_API, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text  # XML(Atom)


def parse_atom(xml_text):
    feed = feedparser.parse(xml_text)
    entries = []
    for e in feed.entries:
        links = {ln.get("title", ""): ln["href"] for ln in e.links}
        pdf_url = links.get("pdf") or next((ln["href"] for ln in e.links if ln.get("type") == "application/pdf"), None)
        entries.append({
            "id": e.get("id"),
            "title": e.get("title", "").strip(),
            "summary": e.get("summary", "").strip(),
            "authors": [a.get("name", "") for a in e.get("authors", [])],
            "published": e.get("published"),
            "updated": e.get("updated"),
            "categories": [t.get("term") for t in e.get("tags", []) if t.get("term")],
            "abs_url": e.get("id"),
            "pdf_url": pdf_url,
        })
    return entries


def in_lookback(e, days):
    def parse_iso(s):
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    cand = max([d for d in [parse_iso(e.get("updated", "")), parse_iso(e.get("published", ""))] if d], default=None)
    if not cand:
        return True
    now = dt.datetime.now(dt.timezone.utc)
    return (now - cand).days <= days


def score_entry(e, cfg):
    score = 0.0
    title = e["title"].lower()
    abstr = e["summary"].lower()
    cats = " ".join(e["categories"]).lower()
    authors = " ".join(e["authors"]).lower()

    for kw in cfg["profile"].get("keywords", []):
        term = kw["term"].lower()
        w = kw.get("weight", 1)
        if term in title:
            score += w * cfg["scoring"].get("title_weight", 1.0)
        if term in abstr:
            score += w * cfg["scoring"].get("abstract_weight", 1.0)
    for au in cfg["profile"].get("authors_priority", []):
        if au["name"].lower() in authors:
            score += au.get("weight", 1) * cfg["scoring"].get("author_weight", 1.0)
    for ms in cfg["profile"].get("msc_terms", []):
        if ms["term"].lower() in cats:
            score += ms.get("weight", 1) * cfg["scoring"].get("category_weight", 0.5)

    for bad in cfg["profile"].get("exclude", []):
        if bad.lower() in title or bad.lower() in abstr:
            score -= 2.0

    return score


def extract_main_theorem_from_text(text, max_chars=700):
    text = re.sub(r"\s+\n", "\n", text)
    for pat in _DEF_THEOREM_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            chunk = text[m.start(): m.start() + 2000]
            sentences = re.split(r"(?<=[\.!?。．\n])\s+", chunk)
            out = " ".join(sentences[:3])
            out = re.sub(r"\s+", " ", out).strip()
            return (out[:max_chars] + "…") if len(out) > max_chars else out
    return ""


def extract_main_theorem(pdf_url):
    if not pdf_url:
        return ""
    try:
        r = requests.get(pdf_url, headers=HEADERS, timeout=120)
        r.raise_for_status()
        with open("tmp.pdf", "wb") as f:
            f.write(r.content)
        text = extract_text("tmp.pdf") or ""
        if len(text) > 20000:
            text = text[:20000]
        theorem = extract_main_theorem_from_text(text)
        return theorem
    except Exception:
        return ""
    finally:
        try:
            os.remove("tmp.pdf")
        except Exception:
            pass


def ensure_out_dir():
    os.makedirs("out", exist_ok=True)


def build_pdf(filename, title, top_details, other_titles):
    ensure_out_dir()
    path = os.path.join("out", filename)

    # CJKフォント（CID）
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))

    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(title)
    width, height = A4

    def draw_text(x, y, s, size=12, leading=16, wrap=84):
        c.setFont('HeiseiKakuGo-W5', size)
        for line in textwrap.wrap(s, width=wrap):
            c.drawString(x, y, line)
            y -= leading
        return y

    margin = 20 * mm
    y = height - margin
    y = draw_text(margin, y, title, size=16, leading=20, wrap=60) - 8

    if not top_details and not other_titles:
        y = draw_text(margin, y, "今週のピックアップは 0件 でした。")
        c.showPage(); c.save(); return path

    # 詳細（最大3件）
    for i, item in enumerate(top_details, 1):
        y = draw_text(margin, y, f"[{i}] {item['title']}", size=13, leading=18, wrap=70) - 2
        y = draw_text(margin, y, f"著者: {', '.join(item['authors'])}")
        y = draw_text(margin, y, f"URL: {item['abs_url']}")
        if item["theorem"]:
            y = draw_text(margin, y, "主定理（自動抽出）:", size=12, leading=16)
            y = draw_text(margin + 8, y, item["theorem"], wrap=80)
        else:
            y = draw_text(margin, y, "主定理（自動抽出）: 見つかりませんでした。")
        y -= 6
        if y < 40 * mm:
            c.showPage(); y = height - margin

    # 4件目以降はタイトルのみ
    if other_titles:
        y -= 8
        y = draw_text(margin, y, "その他の候補（タイトルのみ）:", size=13, leading=18)
        for t in other_titles:
            y = draw_text(margin + 8, y, f"- {t}", wrap=85)
            if y < 30 * mm:
                c.showPage(); y = height - margin

    c.showPage(); c.save()
    return path


def main():
    cfg = load_config()

    # 1) arXivから取得（最大 max_fetch、最新順）
    xml = arxiv_query_math_ag(max_results=cfg["limits"]["max_fetch"])

    entries = [e for e in parse_atom(xml) if in_lookback(e, cfg["limits"]["lookback_days"])]

    # 2) スコアリング
    items = []
    for e in entries:
        s = score_entry(e, cfg)
        if s >= cfg["scoring"]["threshold"]:
            e["score"] = s
            items.append(e)
    items.sort(key=lambda x: x["score"], reverse=True)

    # 3) 上位max_details件は主定理抽出
    top = items[:cfg["limits"]["max_details"]]
    others = items[cfg["limits"]["max_details"]:]

    detailed = []
    for e in top:
        theorem = extract_main_theorem(e["pdf_url"])
        time.sleep(3)  # polite: 連続PDF取得は3秒間隔
        detailed.append({
            "title": e["title"],
            "authors": e["authors"],
            "abs_url": e["abs_url"],
            "theorem": theorem
        })

    other_titles = [e["title"] for e in others] if cfg["output"]["include_others_titles"] else []

    # 4) PDF生成
    today = dt.datetime.now(JST).strftime("%Y-%m-%d")
    fname = f"{cfg['output']['filename_prefix']}_{today}.pdf"
    title = f"math.AG 週次ピックアップ（{today}）"
    path = build_pdf(fname, title, detailed, other_titles)

    print(json.dumps({
        "picked_count": len(items),
        "detailed_count": len(detailed),
        "others_count": len(other_titles),
        "pdf": path
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
