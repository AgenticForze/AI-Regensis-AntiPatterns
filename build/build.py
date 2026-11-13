#!/usr/bin/env python3
"""Static site builder: content/*.yaml -> docs/ (GitHub Pages ready)."""
import json
import re
import shutil
import sys
from html import escape
from pathlib import Path

import markdown
import yaml
from pygments.formatters import HtmlFormatter

sys.path.insert(0, str(Path(__file__).parent))
import diagrams  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
OUT = ROOT / "docs"
ASSETS = ROOT / "assets"

MD_EXT = ["fenced_code", "tables", "codehilite", "sane_lists", "attr_list"]
MD_CFG = {"codehilite": {"guess_lang": False, "css_class": "hl"}}


def md(text):
    if not text:
        return ""
    return markdown.markdown(str(text), extensions=MD_EXT, extension_configs=MD_CFG)


def code_block(code, lang="python"):
    return md(f"```{lang}\n{code.rstrip()}\n```")


def load():
    site = yaml.safe_load((CONTENT / "site.yaml").read_text())
    sections = []
    for part in site["parts"]:
        for fname in part["sections"]:
            sec = yaml.safe_load((CONTENT / fname).read_text())
            sec["part"] = part
            sec["patterns"] = list(sec.get("patterns") or [])
            for imp in sorted((CONTENT / "imported").glob(f"*-{sec['id']}.yaml")):
                sec["patterns"] += yaml.safe_load(imp.read_text()).get("patterns", [])
            sections.append(sec)
    return site, sections


def blocks_html(blocks, uid):
    out = []
    for i, b in enumerate(blocks or []):
        if "md" in b:
            out.append(f'<div class="prose">{md(b["md"])}</div>')
        elif "layers" in b:
            cap = b.get("caption", "")
            out.append(f'<figure class="fig">{diagrams.layers(b["layers"], f"{uid}-l{i}")}'
                       + (f"<figcaption>{escape(cap)}</figcaption>" if cap else "") + "</figure>")
        elif "flow" in b:
            cap = b.get("caption", "")
            out.append(f'<figure class="fig">{diagrams.render(b["flow"], f"{uid}-f{i}")}'
                       + (f"<figcaption>{escape(cap)}</figcaption>" if cap else "") + "</figure>")
        elif b.get("chart") == "tco":
            out.append(f'<figure class="fig">{diagrams.tco_chart(uid)}<figcaption>{escape(b.get("caption", ""))}</figcaption></figure>')
        elif "code" in b:
            if b.get("title"):
                out.append(f'<h3 class="blk-h">{escape(b["title"])}</h3>')
            out.append(code_block(b["code"], b.get("lang", "python")))
    return "\n".join(out)


TAG_CLASS = {"Telco": "t-telco", "FinTech": "t-fin", "Critical": "t-crit", "Leadership": "t-lead", "Cost": "t-cost", "Quality": "t-quality", "Security": "t-sec", "Compliance": "t-comp",
             "Reliability": "t-rel", "Latency": "t-lat", "Adoption": "t-adopt", "Scale": "t-scale"}


def tags_html(tags):
    return "".join(f'<span class="tag {TAG_CLASS.get(t, "")}">{escape(t)}</span>' for t in tags or [])


REL = {}


def pattern_html(sec, idx, p):
    pid = p["id"]
    num = f'{sec["num"]}.{idx + 1}'
    d = diagrams.render(p.get("diagram"), f"{sec['id']}-{pid}")
    code = code_block(p["code"], p.get("lang", "python")) if p.get("code") else ""
    return f"""
<article class="ap" id="{pid}">
  <header class="ap-h">
    <div class="ap-num">{num}</div>
    <div>
      <h2><a href="#{pid}">{escape(p['title'])}</a></h2>
      <div class="tags">{tags_html(p.get('tags'))}</div>
    </div>
  </header>
  <div class="grid2">
    <section class="card c-problem"><h3>Problem statement</h3>{md(p['scenario'])}</section>
    <section class="card c-anti"><h3>The anti-pattern</h3>{md(p['antipattern'])}</section>
  </div>
  <section class="card c-fail"><h3>Why the current design fails</h3>{md(p['fails'])}</section>
  <figure class="fig">{d}</figure>
  <section class="card c-sol"><h3>Recommended solution</h3>{md(p['solution'])}</section>
  <section class="card c-why"><h3>Why it succeeds</h3>{md(p['works'])}</section>
  {f'<section class="code"><h3>Reference implementation</h3>{code}</section>' if code else ''}
  <section class="takeaway">
    <div><span class="k">Key takeaway</span><p>{escape(p['takeaway'])}</p></div>
    {f'<div><span class="k">Follow-up to expect</span><p>{escape(p["followup"])}</p></div>' if p.get('followup') else ''}
    {f'<div><span class="k">General rule</span><p>{escape(p["generic"])}</p></div>' if p.get('generic') else ''}
  </section>
  {related_html(p)}
</article>"""


def related_html(p):
    links = [REL[r] for r in p.get("related", []) if r in REL]
    if not links:
        return ""
    items = "".join(f'<a href="{u}"><span>{n}</span>{escape(t)}</a>' for u, n, t in links)
    return f'<div class="related"><span class="k">Related</span>{items}</div>'


def nav_html(site, sections, current):
    out = ['<nav class="nav">']
    for part in site["parts"]:
        out.append(f'<div class="nav-part">{escape(part["label"])}</div>')
        for s in sections:
            if s["part"] is part:
                cls = "active" if s["id"] == current else ""
                out.append(f'<a class="{cls}" href="{s["id"]}.html"><span class="nn">{s["num"]}</span>{escape(s["short"])}</a>')
    out.append("</nav>")
    return "\n".join(out)


def page(site, sections, title, body, current=None, depth=""):
    nav = nav_html(site, sections, current)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {escape(site['title'])}</title>
<meta name="description" content="{escape(site['tagline'])}">
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="assets/code.css">
<script>try{{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
</head>
<body>
<header class="top">
  <button class="menu" aria-label="Menu" onclick="document.body.classList.toggle('nav-open')">☰</button>
  <a class="brand" href="index.html"><span class="logo">◆</span>{escape(site['title'])}</a>
  <div class="search"><input id="q" type="search" placeholder="Search anti-patterns…" autocomplete="off"><div id="qr" class="qr"></div></div>
  <a class="toplink" href="catalog.html">Catalog</a>
  <button class="theme" aria-label="Toggle theme" onclick="toggleTheme()"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/></svg></button>
</header>
<div class="layout">
  <aside class="side">{nav}</aside>
  <main class="main">{body}
  <footer class="foot">{escape(site['footer'])}</footer>
  </main>
</div>
<script src="assets/search-index.js"></script>
<script src="assets/app.js"></script>
</body>
</html>"""


def section_page(site, sections, i):
    s = sections[i]
    prev_s = sections[i - 1] if i > 0 else None
    next_s = sections[i + 1] if i < len(sections) - 1 else None
    toc = "".join(f'<a href="#{p["id"]}"><span>{s["num"]}.{k + 1}</span>{escape(p["title"])}</a>' for k, p in enumerate(s["patterns"]))
    pats = "\n".join(pattern_html(s, k, p) for k, p in enumerate(s["patterns"]))
    pn = '<div class="pn">'
    pn += f'<a class="prev" href="{prev_s["id"]}.html">← {prev_s["num"]}. {escape(prev_s["short"])}</a>' if prev_s else "<span></span>"
    pn += f'<a class="next" href="{next_s["id"]}.html">{next_s["num"]}. {escape(next_s["short"])} →</a>' if next_s else "<span></span>"
    pn += "</div>"
    count = f'<span class="pill">{len(s["patterns"])} anti-patterns</span>' if s["patterns"] else ""
    body = f"""
<div class="hero-s">
  <div class="crumb">{escape(s['part']['label'])}</div>
  <h1><span class="sn">{s['num']}</span>{escape(s['title'])}</h1>
  <p class="lede">{escape(s['summary'])}</p>
  {count}
</div>
{blocks_html(s.get('intro'), s['id'] + '-i')}
{f'<div class="toc"><div class="toc-h">In this section</div>{toc}</div>' if toc else ''}
{pats}
{blocks_html(s.get('outro'), s['id'] + '-o')}
{pn}"""
    return page(site, sections, s["title"], body, s["id"])


def index_page(site, sections):
    total = sum(len(s["patterns"]) for s in sections)
    cards = []
    for part in site["parts"]:
        items = "".join(
            f'<a href="{s["id"]}.html"><span class="nn">{s["num"]}</span><span class="t">{escape(s["title"])}</span><span class="c">{len(s["patterns"]) or ""}</span></a>'
            for s in sections if s["part"] is part)
        cards.append(f'<div class="part-card"><div class="pl">{escape(part["label"])}</div><p>{escape(part["blurb"])}</p><div class="plist">{items}</div></div>')
    anatomy = "".join(f'<div class="an"><span>{i + 1}</span>{escape(a)}</div>' for i, a in enumerate(site["anatomy"]))
    body = f"""
<section class="hero">
  <div class="eyebrow">{escape(site['eyebrow'])}</div>
  <h1>{escape(site['headline'])}</h1>
  <p class="lede">{escape(site['tagline'])}</p>
  <div class="stats">
    <div><b>{total}</b><span>anti-patterns</span></div>
    <div><b>{len(sections)}</b><span>sections</span></div>
    <div><b>{len(site['parts'])}</b><span>parts</span></div>
    <div><b>3</b><span>hyperscalers compared</span></div>
  </div>
  <div class="cta"><a class="btn" href="{sections[0]['id']}.html">Start reading →</a><a class="btn ghost" href="catalog.html">Browse the catalog</a></div>
</section>
<div class="prose">{md(site['intro'])}</div>
<h2 class="h2">Anatomy of every entry</h2>
<div class="anatomy">{anatomy}</div>
<h2 class="h2">Contents</h2>
<div class="parts">{''.join(cards)}</div>
"""
    return page(site, sections, "Home", body)


def catalog_page(site, sections):
    rows = []
    for s in sections:
        for k, p in enumerate(s["patterns"]):
            rows.append(f'<tr data-tags="{" ".join(p.get("tags", []))}"><td class="mono">{s["num"]}.{k + 1}</td>'
                        f'<td><a href="{s["id"]}.html#{p["id"]}">{escape(p["title"])}</a></td>'
                        f'<td>{escape(s["short"])}</td><td>{tags_html(p.get("tags"))}</td></tr>')
    alltags = sorted({t for s in sections for p in s["patterns"] for t in p.get("tags", [])})
    chips = '<button class="chip on" data-t="">All</button>' + "".join(f'<button class="chip" data-t="{t}">{t}</button>' for t in alltags)
    body = f"""
<div class="hero-s"><div class="crumb">Index</div><h1>Anti-pattern catalog</h1>
<p class="lede">Every anti-pattern in one table. Filter by the business risk it creates.</p></div>
<div class="chips" id="chips">{chips}</div>
<table class="cat" id="cat"><thead><tr><th>#</th><th>Anti-pattern</th><th>Section</th><th>Risk</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"""
    return page(site, sections, "Catalog", body, "catalog")


def search_index(sections):
    idx = []
    for s in sections:
        idx.append({"t": f'{s["num"]}. {s["title"]}', "u": f'{s["id"]}.html', "s": "Section"})
        for k, p in enumerate(s["patterns"]):
            idx.append({"t": f'{s["num"]}.{k + 1} {p["title"]}', "u": f'{s["id"]}.html#{p["id"]}', "s": s["short"],
                        "k": " ".join(p.get("tags", [])) + " " + re.sub(r"[^\w ]", " ", str(p.get("takeaway", "")))[:200]})
    return "window.SEARCH=" + json.dumps(idx, ensure_ascii=False) + ";"


def main():
    site, sections = load()
    for s_ in sections:
        for k, p in enumerate(s_["patterns"]):
            REL[p["id"]] = (f'{s_["id"]}.html#{p["id"]}', f'{s_["num"]}.{k + 1}', p["title"])
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in ASSETS.iterdir():
        shutil.copy(f, OUT / "assets" / f.name)
    light = HtmlFormatter(style="github-dark").get_style_defs(".hl")
    (OUT / "assets" / "code.css").write_text(light)
    (OUT / "assets" / "search-index.js").write_text(search_index(sections))
    (OUT / "index.html").write_text(index_page(site, sections))
    (OUT / "catalog.html").write_text(catalog_page(site, sections))
    for i, s in enumerate(sections):
        (OUT / f'{s["id"]}.html').write_text(section_page(site, sections, i))
    (OUT / ".nojekyll").write_text("")
    total = sum(len(s["patterns"]) for s in sections)
    print(f"Built {len(sections)} sections, {total} anti-patterns -> {OUT}")


if __name__ == "__main__":
    main()
