
# -*- coding: utf-8 -*-
"""
毎週木曜 9:00 JST に arXiv math.AG の直近 N 日を取得し、
しきい値以上の論文すべてを「タイトル（色付き）・著者（姓のみ）・URL」で列挙。
掲載順はスコア（重み）降順。

【本版のポイント】
- 主定理抽出は廃止（PDF本文ダウンロードなし）
- タイトル行は RGB(232,180,180) に着色
- 著者名は姓のみ（"Last, First"→カンマ前／それ以外→最後の語）
"""

import os, re, time, json, textwrap, datetime as dt
import requests, feedparser, yaml
from zoneinfo import ZoneInfo
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.units import mm
from reportlab.lib.colors import Color

ARXIV_API = "https://export.arxiv.org/api/query"  # 公式API（Atom）
JST = ZoneInfo("Asia/Tokyo")

# User-Agent: arXivへの礼儀として連絡先（メール等）を含める
CONTACT = os.environ.get("ARXIV_CONTACT", "contact@example.com")
HEADERS = {"User-Agent": f"ag-weekly-bot (contact: {CONTACT})"}

TITLE_COLOR = Color(232/255.0, 180/255.0, 180/255.0)  # RGB(232,180,180)

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
        links = {ln.get("title",""): ln["href"] for ln in e.links}
        pdf_url = links.get("pdf") or next((ln["href"] for ln in e.links if ln.get("type")=="application/pdf"), None)
        entries.append({
            "id": e.get("id"),
            "title": e.get("title","").strip(),
            "summary": e.get("summary","").strip(),
            "authors": [a.get("name","") for a in e.get("authors",[])],
            "published": e.get("published"),
            "updated": e.get("updated"),
            "categories": [t.get("term") for t in e.get("tags",[]) if t.get("term")],
            "abs_url": e.get("id"),
            "pdf_url": pdf_url,
        })
    return entries

def in_lookback(e, days):
    def parse_iso(s):
        try:
            return dt.datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception:
            return None
    cand = max([d for d in [parse_iso(e.get("updated","")), parse_iso(e.get("published",""))] if d], default=None)
    if not cand:
        return True
    now = dt.datetime.now(dt.timezone.utc)
    return (now - cand).days <= days

def score_entry(e, cfg):
    score = 0.0
    title = e["title"].lower()
    abstr = e["summary"].lower()
    cats  = " ".join(e["categories"]).lower()
    authors = " ".join(e["authors"]).lower()

    for kw in cfg["profile"].get("keywords", []):
        term = kw["term"].lower()
        w = kw.get("weight",1)
        if term in title:  score += w * cfg["scoring"].get("title_weight",1.0)
        if term in abstr:  score += w * cfg["scoring"].get("abstract_weight",1.0)
    for au in cfg["profile"].get("authors_priority", []):
        if au["name"].lower() in authors:
            score += au.get("weight",1) * cfg["scoring"].get("author_weight",1.0)
    for ms in cfg["profile"].get("msc_terms", []):
        if ms["term"].lower() in cats:
            score += ms.get("weight",1) * cfg["scoring"].get("category_weight",0.5)

    for bad in cfg["profile"].get("exclude", []):
        if bad.lower() in title or bad.lower() in abstr:
            score -= 2.0

    return score

# --- 著者表記（姓のみ）ユーティリティ ------------------------------

def _surname_from_name(name: str) -> str:
    """ 'Last, First Middle' → 'Last' / 'First Middle Last' → 'Last' """
    name = name.strip()
    if not name:
        return ""
    # “Last, First ...” 形式はカンマ前を姓とみなす
    if "," in name:
        last = name.split(",")[0].strip()
    else:
        parts = name.split()
        last = parts[-1] if parts else name
    # 記号の除去（. ,）
    last = re.sub(r"[\\.,]", "", last)
    return last

def surnames_only(authors_list):
    # 著者配列を姓配列に変換（重複はそのまま／順序保持）
    return [_surname_from_name(a) for a in authors_list if a and _surname_from_name(a)]

# --- PDF 出力 -------------------------------------------------------

def build_pdf(filename, title, items):
    os.makedirs("out", exist_ok=True)
    path = os.path.join("out", filename)

    # CJKフォント（CID）
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))

    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(title)
    width, height = A4

    def draw_wrapped(x, y, s, size=12, leading=16, wrap=84, color=None):
        c.setFont('HeiseiKakuGo-W5', size)
        if color:
            c.setFillColor(color)
        else:
            c.setFillColorRGB(0,0,0)
        for line in textwrap.wrap(s, width=wrap):
            c.drawString(x, y, line)
            y -= leading
        # 戻す
        c.setFillColorRGB(0,0,0)
        return y

    margin = 20*mm
    y = height - margin
    y = draw_wrapped(margin, y, title, size=16, leading=20, wrap=60) - 8

    if not items:
        y = draw_wrapped(margin, y, "今週のピックアップは 0件 でした。")
        c.showPage(); c.save(); return path

    for i, e in enumerate(items, 1):
        # タイトル（色付き）
        y = draw_wrapped(margin, y, f"[{i}] {e['title']}", size=13, leading=18, wrap=70, color=TITLE_COLOR) - 2
        # 著者（姓のみ）
        surnames = surnames_only(e["authors"])
        y = draw_wrapped(margin, y, f"著者: {', '.join(surnames)}")
        # URL
        y = draw_wrapped(margin, y, f"URL: {e['abs_url']}")
        y -= 8
        if y < 40*mm:
            c.showPage(); y = height - margin

    c.showPage(); c.save()
    return path

# --- メイン ---------------------------------------------------------

def main():
    cfg = load_config()

    # 1) arXivから取得（最大 max_fetch、最新順）
    xml = arxiv_query_math_ag(max_results=cfg["limits"]["max_fetch"])
    entries = [e for e in parse_atom(xml) if in_lookback(e, cfg["limits"]["lookback_days"])]

    # 2) スコアリング → しきい値以上のみ
    picked = []
    for e in entries:
        s = score_entry(e, cfg)
        if s >= cfg["scoring"]["threshold"]:
            e["score"] = s
            picked.append(e)

    # 3) スコア（重み）降順で掲載
    picked.sort(key=lambda x: x["score"], reverse=True)

    # 4) PDF生成
    today = dt.datetime.now(JST).strftime("%Y-%m-%d")
    fname = f"{cfg['output']['filename_prefix']}_{today}.pdf"
    title = f"math.AG 週次ピックアップ（{today}）"
    path = build_pdf(fname, title, picked)

    # 5) ログ
    print(json.dumps({
        "listed_count": len(picked),
        "pdf": path
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
