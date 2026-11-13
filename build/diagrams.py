"""SVG diagram engine.

Each anti-pattern carries a compact flow spec:

    diagram:
      bad:  ["User query", "Embed", "!Top-k vector only", "LLM"]
      bad_note: "What goes wrong"
      good: ["User query", "+Rewrite", "+BM25 | Dense", "+Rerank", "LLM"]
      good_note: "Why it holds up"
      good_loop: "Optional feedback-loop label"

Node prefixes:  "!" = failure point,  "+" = component introduced by the fix.
A " | " inside a node stacks parallel components vertically.
"""
from html import escape

W = 960
PAD = 24
NODE_H = 46
STACK_GAP = 8
GAP = 34


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]


def _kind(label):
    if label.startswith("!"):
        return "bad", label[1:].strip()
    if label.startswith("+"):
        return "new", label[1:].strip()
    return "std", label.strip()


def _row(nodes, y0, uid):
    cols = [[_kind(p.strip()) for p in n.split(" | ")] for n in nodes]
    n = len(cols)
    node_w = (W - 2 * PAD - 60 - GAP * (n - 1)) / n
    x0 = PAD + 60
    max_stack = max(len(c) for c in cols)
    row_h = max_stack * NODE_H + (max_stack - 1) * STACK_GAP
    chars = max(9, int(node_w / 7.4))
    out = []
    centers = []
    for i, col in enumerate(cols):
        x = x0 + i * (node_w + GAP)
        col_h = len(col) * NODE_H + (len(col) - 1) * STACK_GAP
        cy0 = y0 + (row_h - col_h) / 2
        for j, (kind, text) in enumerate(col):
            y = cy0 + j * (NODE_H + STACK_GAP)
            out.append(f'<rect class="dg-node dg-{kind}" x="{x:.1f}" y="{y:.1f}" width="{node_w:.1f}" height="{NODE_H}" rx="8"/>')
            lines = _wrap(text, chars)
            fs = 12.5 if len(lines) < 3 else 11
            lh = fs + 2
            ty = y + NODE_H / 2 - (len(lines) - 1) * lh / 2 + fs * 0.35
            for k, ln in enumerate(lines):
                out.append(f'<text class="dg-t dg-t-{kind}" x="{x + node_w / 2:.1f}" y="{ty + k * lh:.1f}" font-size="{fs}" text-anchor="middle">{escape(ln)}</text>')
            if kind == "bad":
                out.append(f'<circle class="dg-badge-bad" cx="{x + node_w - 4:.1f}" cy="{y + 4:.1f}" r="8"/><text class="dg-badge-t" x="{x + node_w - 4:.1f}" y="{y + 8:.1f}" text-anchor="middle" font-size="11">!</text>')
            if kind == "new":
                out.append(f'<circle class="dg-badge-new" cx="{x + node_w - 4:.1f}" cy="{y + 4:.1f}" r="8"/><text class="dg-badge-t" x="{x + node_w - 4:.1f}" y="{y + 8:.1f}" text-anchor="middle" font-size="12">+</text>')
        centers.append((x, x + node_w, y0 + row_h / 2))
    for i in range(n - 1):
        x1 = centers[i][1] + 3
        x2 = centers[i + 1][0] - 4
        cy = centers[i][2]
        out.append(f'<line class="dg-edge" x1="{x1:.1f}" y1="{cy:.1f}" x2="{x2:.1f}" y2="{cy:.1f}" marker-end="url(#ah-{uid})"/>')
    return out, row_h, centers


def render(spec, uid):
    if not spec:
        return ""
    parts = []
    y = PAD
    body = []
    for key, label, cls in (("bad", "ANTI-PATTERN", "bad"), ("good", "RECOMMENDED", "good")):
        if key not in spec:
            continue
        band_top = y
        rows, rh, centers = _row(spec[key], y + 30, uid)
        note = spec.get(f"{key}_note", "")
        loop = spec.get(f"{key}_loop")
        extra = 0
        if loop:
            extra = 34
        band_h = 30 + rh + extra + (34 if note else 16)
        body.append(f'<rect class="dg-band dg-band-{cls}" x="8" y="{band_top:.1f}" width="{W - 16}" height="{band_h:.1f}" rx="12"/>')
        body.append(f'<text class="dg-lbl dg-lbl-{cls}" x="{PAD + 4}" y="{band_top + 20:.1f}" font-size="11.5" letter-spacing="1.4">{label}</text>')
        body.extend(rows)
        if loop:
            xs = centers[-1][0] + (centers[-1][1] - centers[-1][0]) / 2
            xe = centers[0][0] + (centers[0][1] - centers[0][0]) / 2
            yb = y + 30 + rh
            ly = yb + 22
            body.append(f'<path class="dg-loop" d="M{xs:.1f},{yb + 2:.1f} V{ly:.1f} H{xe:.1f} V{yb + 6:.1f}" marker-end="url(#ah-{uid})"/>')
            body.append(f'<text class="dg-loop-t" x="{(xs + xe) / 2:.1f}" y="{ly - 5:.1f}" text-anchor="middle" font-size="11.5">{escape(loop)}</text>')
        if note:
            body.append(f'<text class="dg-note dg-note-{cls}" x="{PAD + 4}" y="{band_top + band_h - 13:.1f}" font-size="12.5">{escape(note)}</text>')
        y = band_top + band_h + 14
    h = y + 4
    parts.append(f'<svg class="dg" viewBox="0 0 {W} {h:.0f}" role="img" xmlns="http://www.w3.org/2000/svg">')
    parts.append(f'<defs><marker id="ah-{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="dg-ah" d="M0,0 L10,5 L0,10 z"/></marker></defs>')
    parts.extend(body)
    parts.append("</svg>")
    return "\n".join(parts)


def layers(spec, uid):
    """Stacked layer diagram for reference architectures.

    spec: {title, layers: [{name, items: [..], kind: std|new|bad}], side: [..]}
    """
    names = spec["layers"]
    side = spec.get("side", [])
    side_w = 170 if side else 0
    lw = W - 2 * PAD - side_w - (16 if side else 0)
    lh = 56
    gap = 10
    y = PAD
    out = []
    for L in names:
        kind = L.get("kind", "std")
        out.append(f'<rect class="dg-layer dg-layer-{kind}" x="{PAD}" y="{y}" width="{lw}" height="{lh}" rx="10"/>')
        out.append(f'<text class="dg-layer-name" x="{PAD + 14}" y="{y + lh / 2 + 4}" font-size="12.5">{escape(L["name"])}</text>')
        items = L.get("items", [])
        if items:
            ix0 = PAD + 190
            iw = (lw - 190 - 10 - 8 * (len(items) - 1)) / len(items)
            for i, it in enumerate(items):
                ix = ix0 + i * (iw + 8)
                out.append(f'<rect class="dg-chip" x="{ix:.1f}" y="{y + 10}" width="{iw:.1f}" height="{lh - 20}" rx="6"/>')
                lines = _wrap(it, max(8, int(iw / 6.6)))
                fs = 11.5 if len(lines) == 1 else 10.5
                ty = y + lh / 2 - (len(lines) - 1) * (fs + 1) / 2 + 4
                for k, ln in enumerate(lines[:2]):
                    out.append(f'<text class="dg-chip-t" x="{ix + iw / 2:.1f}" y="{ty + k * (fs + 1):.1f}" font-size="{fs}" text-anchor="middle">{escape(ln)}</text>')
        y += lh + gap
    total = y - gap - PAD
    if side:
        sx = PAD + lw + 16
        sh = (total - 8 * (len(side) - 1)) / len(side)
        for i, s in enumerate(side):
            sy = PAD + i * (sh + 8)
            out.append(f'<rect class="dg-side" x="{sx}" y="{sy:.1f}" width="{side_w}" height="{sh:.1f}" rx="10"/>')
            lines = _wrap(s, 20)
            for k, ln in enumerate(lines):
                out.append(f'<text class="dg-side-t" x="{sx + side_w / 2}" y="{sy + sh / 2 - (len(lines) - 1) * 7 + k * 14 + 4:.1f}" font-size="12" text-anchor="middle">{escape(ln)}</text>')
    h = y - gap + PAD
    return f'<svg class="dg" viewBox="0 0 {W} {h:.0f}" role="img" xmlns="http://www.w3.org/2000/svg">' + "\n".join(out) + "</svg>"


def tco_chart(uid):
    """Illustrative monthly cost vs. volume: managed API vs. self-hosted GPU."""
    w, h = W, 400
    l, r, t, b = 80, 40, 30, 60
    pw, ph = w - l - r, h - t - b
    vols = [i * 0.05 for i in range(0, 201)]  # billions of tokens / month
    api = lambda v: v * 3200          # ~$3.2 per 1M blended tokens
    gpu = lambda v: 14000 + 4000 * int(v // 3) + v * 300  # fixed cluster + step scale + power
    hyb = lambda v: min(api(v), gpu(v)) * 0.8   # routing + caching discount
    ymax = 36000
    X = lambda v: l + v / 10 * pw
    Y = lambda c: t + ph - min(c, ymax) / ymax * ph
    def path(f):
        return "M" + " L".join(f"{X(v):.1f},{Y(f(v)):.1f}" for v in vols)
    out = [f'<svg class="dg" viewBox="0 0 {w} {h}" role="img" xmlns="http://www.w3.org/2000/svg">']
    for c in range(0, ymax + 1, 9000):
        out.append(f'<line class="dg-grid" x1="{l}" x2="{w - r}" y1="{Y(c):.1f}" y2="{Y(c):.1f}"/>')
        out.append(f'<text class="dg-axis" x="{l - 10}" y="{Y(c) + 4:.1f}" text-anchor="end" font-size="11">${c // 1000}k</text>')
    for v in range(0, 11, 2):
        out.append(f'<text class="dg-axis" x="{X(v):.1f}" y="{h - b + 20}" text-anchor="middle" font-size="11">{v}B</text>')
    out.append(f'<text class="dg-axis" x="{l + pw / 2}" y="{h - 14}" text-anchor="middle" font-size="12">Monthly token volume (billions)</text>')
    out.append(f'<text class="dg-axis" x="18" y="{t + ph / 2}" text-anchor="middle" font-size="12" transform="rotate(-90 18 {t + ph / 2})">Monthly cost (illustrative)</text>')
    out.append(f'<path class="dg-line dg-line-a" d="{path(api)}"/>')
    out.append(f'<path class="dg-line dg-line-b" d="{path(gpu)}"/>')
    out.append(f'<path class="dg-line dg-line-c" d="{path(hyb)}"/>')
    be = next(v for v in vols if gpu(v) <= api(v))
    out.append(f'<line class="dg-be" x1="{X(be):.1f}" x2="{X(be):.1f}" y1="{t}" y2="{t + ph}"/>')
    out.append(f'<text class="dg-be-t" x="{X(be) + 6:.1f}" y="{t + 14}" font-size="11.5">Break-even zone</text>')
    lx = l + 16
    for i, (cls, lab) in enumerate((("a", "Managed API (pay per token)"), ("b", "Self-hosted GPU (fixed + step scale)"), ("c", "Hybrid routing + caching"))):
        yy = t + 16 + i * 18
        out.append(f'<line class="dg-line dg-line-{cls}" x1="{lx}" x2="{lx + 22}" y1="{yy}" y2="{yy}"/>')
        out.append(f'<text class="dg-axis" x="{lx + 30}" y="{yy + 4}" font-size="11.5">{lab}</text>')
    out.append("</svg>")
    return "\n".join(out)
