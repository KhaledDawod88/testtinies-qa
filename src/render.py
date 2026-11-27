#!/usr/bin/env python3
"""Card renderer: content.json -> 1080x1920 SVG -> PNG (headless Chrome) -> MP4 (ffmpeg).
Standard library only. PNG and video steps are optional and skipped when the tool is missing."""
import math
import argparse, datetime, html, json, os, re, shutil, subprocess, sys, tempfile

W, H = 1080, 1920
SANS = "Inter, 'Segoe UI', Helvetica, Arial, 'Noto Sans', sans-serif"
MONO = "'JetBrains Mono', Consolas, Menlo, 'DejaVu Sans Mono', monospace"
AR = "'Noto Naskh Arabic', Amiri, 'Noto Sans Arabic', Tahoma, serif"


def esc(s):
    return html.escape(str(s), quote=True)


def wrap(text, width):
    out, cur = [], ""
    for word in str(text).split():
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        out.append(cur)
    return out


def text(x, y, s, size=40, fill="#fff", weight=400, anchor="start", family=SANS, extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>')


def para(x, y, s, width, size=40, fill="#fff", weight=400, anchor="start", lh=1.35, family=SANS):
    """Wrapped paragraph. Returns (svg, next_y)."""
    parts = []
    for i, line in enumerate(wrap(s, width)):
        parts.append(text(x, int(y + i * size * lh), line, size, fill, weight, anchor, family))
    n = max(1, len(wrap(s, width)))
    return "".join(parts), int(y + n * size * lh)


def rect(x, y, w, h, fill, rx=24, stroke=None, sw=2, opacity=1):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" opacity="{opacity}"{st}/>'


def pill(x, y, label, fill, color="#fff", size=30, pad=28):
    w = int(len(label) * size * 0.58 + pad * 2)
    return rect(x, y, w, size + 28, fill, rx=(size + 28) // 2) + text(x + pad, y + size + 6, label, size, color, 700), w


def svg_doc(body, c1, c2, extra_defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient>{extra_defs}</defs>'
            f'<rect width="{W}" height="{H}" fill="url(#bg)"/>{body}</svg>')


def header(brand, tagline, accent, n, total):
    s = text(60, 120, brand, 46, "#fff", 800, family=SANS, extra='letter-spacing="2"')
    s += text(60, 170, tagline, 28, accent, 600)
    s += text(W - 60, 120, f"#{n:02d}", 46, accent, 800, "end")
    return s


def footer(repo, accent):
    return (rect(60, H - 150, W - 120, 2, accent, rx=1, opacity=0.5)
            + text(60, H - 90, "github.com/KhaledDawod88/" + repo, 28, "#ffffffaa", 500)
            + text(W - 60, H - 90, "by Khaled Dawod", 28, accent, 700, "end"))


def title_block(s, y, size=78, fill="#fff", width=20, anchor="start", x=60):
    return para(x if anchor == "start" else W // 2, y, s, width, size, fill, 800, anchor, 1.15)


def highlight(line, kws, accent):
    """Tiny syntax colouring: comments, strings, numbers, keywords."""
    toks = re.findall(r"--.*$|#.*$|//.*$|'[^']*'|\"[^\"]*\"|\w+|\s+|.", line)
    out = []
    for t in toks:
        if t.startswith(("--", "#", "//")):
            col = "#7d8590"
        elif t[:1] in "'\"":
            col = "#a5d6a7"
        elif t.isdigit():
            col = "#ffb86b"
        elif t.upper() in kws:
            col = accent
        else:
            col = "#e6edf3"
        out.append((t, col))
    return "".join(f'<tspan fill="{c}">{esc(t)}</tspan>' for t, c in out)


def code_window(y, lines, kws, accent, size=36, label="query.sql"):
    lh = int(size * 1.62)
    h = len(lines) * lh + 120
    s = rect(60, y, W - 120, h, "#0d1117", 28, "#30363d", 3)
    for i, col in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        s += f'<circle cx="{110 + i * 38}" cy="{y + 46}" r="12" fill="{col}"/>'
    s += text(W - 100, y + 54, label, 26, "#7d8590", 500, "end", MONO)
    for i, ln in enumerate(lines):
        yy = y + 120 + i * lh
        s += (f'<text x="100" y="{yy}" font-family="{MONO}" font-size="{size}" xml:space="preserve">'
              f'{highlight(ln, kws, accent)}</text>')
    return s, y + h


def table(y, head, rows, accent, size=34, title="Result"):
    s = text(60, y, title.upper(), 26, accent, 700, extra='letter-spacing="3"')
    y += 24
    n = len(head)
    cw = (W - 120) // n
    rh = int(size * 1.9)
    total = rh * (len(rows) + 1)
    s += rect(60, y, W - 120, total, "#ffffff14", 20, "#ffffff30", 2)
    s += rect(60, y, W - 120, rh, accent, 20, opacity=0.9)
    for j, hd in enumerate(head):
        s += text(90 + j * cw, y + int(rh * 0.68), hd, size - 4, "#0b1020", 800)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            s += text(90 + j * cw, y + rh * (i + 1) + int(rh * 0.68), v, size - 2, "#fff", 500, family=MONO)
    return s, y + total


def tip_box(y, label, s_text, accent, width=36, size=36):
    body, ny = para(100, y + 110, s_text, width, size, "#fff", 500)
    h = ny - y - 50 + 30
    s = rect(60, y, W - 120, h, "#ffffff14", 28, accent, 3)
    s += text(100, y + 62, label.upper(), 28, accent, 800, extra='letter-spacing="3"')
    return s + body, y + h


def pick(items, index=None):
    if index is None:
        index = (datetime.date.today() - datetime.date(2026, 1, 1)).days
    return index % len(items), items[index % len(items)]


# ---------------------------------------------------------------- output steps
def to_png(svg_path, png_path):
    chrome = next((shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser", "chrome") if shutil.which(c)), None)
    if not chrome:
        print("  (no Chrome found, PNG skipped)")
        return False
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--user-data-dir={td}", f"--window-size={W},{H}", f"--screenshot={os.path.abspath(png_path)}",
                        "file://" + os.path.abspath(svg_path)], capture_output=True, timeout=90)
    return os.path.exists(png_path)


def to_video(png_path, mp4_path, secs=8):
    if not shutil.which("ffmpeg"):
        print("  (no ffmpeg found, video skipped)")
        return False
    vf = (f"scale=1188:2112,zoompan=z='1+0.0007*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={secs*30}:s={W}x{H}:fps=30,"
          "fade=t=in:st=0:d=0.5,format=yuv420p")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", png_path, "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=stereo", "-t", str(secs), "-vf", vf, "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", mp4_path], capture_output=True)
    return r.returncode == 0


import math

# ---- layout: code ---------------------------------------------------------
def L_code(it, n, total, c):
    s = header(c["brand"], c["tagline"], c["accent"], n, total)
    t, y = title_block(it["title"], 300, 74, width=22)
    s += t
    w, y = code_window(y + 10, it["code"], c["kws"], c["accent"], 36, c.get("file", "query.sql"))
    s += w
    t, y = table(y + 70, it["head"], it["rows"], c["accent"], title=c.get("result", "Result"))
    s += t
    t, y = tip_box(y + 60, c.get("tiplabel", "Tip"), it["tip"], c["accent"])
    return svg_doc(s + t + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


# ---- layout: mistake / fix -----------------------------------------------
def L_mistake(it, n, total, c):
    s = header(c["brand"], c["tagline"], c["accent"], n, total)
    t, y = title_block(it["title"], 310, 74, width=22)
    s += t
    y += 20
    for label, key, res, col in (("The mistake", "bad", "bad_result", "#ff6b6b"), ("The fix", "fix", "fix_result", "#4ade80")):
        body, ny = para(100, y + 120, it[key], 34, 40, "#fff", 600, family=MONO)
        h = ny - y + 20 + 70
        s += rect(60, y, W - 120, h, col, 28, opacity=0.14) + rect(60, y, W - 120, h, "none", 28, col, 4)
        s += text(100, y + 62, label.upper(), 28, col, 800, extra='letter-spacing="3"')
        s += body
        s += text(100, ny + 20, "-> " + it[res], 32, col, 700)
        y += h + 40
    t, y = tip_box(y + 10, "Why it happens", it["why"], c["accent"])
    return svg_doc(s + t + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


# ---- layout: checklist (QA) ----------------------------------------------
def L_qa(it, n, total, c):
    s = header(c["brand"], c["tagline"], c["accent"], n, total)
    t, y = title_block(it["title"], 310, 74, width=22)
    s += t
    t, y = para(60, y + 20, it["scenario"], 38, 38, "#ffffffcc", 500)
    s += t
    y += 20
    for val, ok, note in it["cases"]:
        col = "#4ade80" if ok else "#ff6b6b"
        s += rect(60, y, W - 120, 118, "#ffffff12", 24, col, 2)
        s += f'<circle cx="125" cy="{y + 59}" r="30" fill="{col}"/>'
        if ok:
            s += f'<path d="M110 {y+60} L121 {y+72} L142 {y+46}" stroke="#0b1020" stroke-width="8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        else:
            s += f'<path d="M111 {y+45} L139 {y+73} M139 {y+45} L111 {y+73}" stroke="#0b1020" stroke-width="8" fill="none" stroke-linecap="round"/>'
        s += text(185, y + 54, val, 38, "#fff", 700, family=MONO)
        s += text(185, y + 94, note, 28, "#ffffffb0", 500)
        y += 140
    t, y = tip_box(y + 20, "Tester's tip", it["tip"], c["accent"])
    return svg_doc(s + t + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


# ---- layout: bilingual phrase --------------------------------------------
def L_phrase(it, n, total, c):
    s = header(c["brand"], c["tagline"], c["accent"], n, total)
    p, w = pill(60, 280, it["context"], c["accent"], "#0b1020", 30)
    s += p
    t, y = para(60, 470, it["en"], 22, 70, "#fff", 800, lh=1.2)
    s += t
    s += rect(60, y + 10, 200, 8, c["accent"], 4)
    y += 120
    for i, line in enumerate(wrap(it["ar"], 22)):
        s += text(W - 60, y + i * 100, line, 74, "#ffe9a8", 700, "start", AR, 'direction="rtl" unicode-bidi="plaintext"')
    y += len(wrap(it["ar"], 22)) * 100 + 40
    body, ny = para(100, y + 120, it["example"], 36, 38, "#fff", 500)
    h = ny - y + 20 + 60
    s += rect(60, y, W - 120, h, "#ffffff14", 28, c["accent"], 3) + text(100, y + 64, "IN CONTEXT", 28, c["accent"], 800, extra='letter-spacing="3"') + body
    y += h + 40
    for i, line in enumerate(wrap(it["example_ar"], 30)):
        s += text(W - 80, y + 60 + i * 70, line, 46, "#ffffffcc", 500, "start", AR, 'direction="rtl" unicode-bidi="plaintext"')
    return svg_doc(s + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


# ---- layout: interview ----------------------------------------------------
def L_interview(it, n, total, c):
    s = header(c["brand"], c["tagline"], c["accent"], n, total)
    s += text(60, 290, "THE QUESTION", 28, c["accent"], 800, extra='letter-spacing="3"')
    t, y = title_block('"' + it["q"] + '"', 360, 70, width=23)
    s += t
    y += 20
    for label, key, col in (("Weak answer", "weak", "#ff6b6b"), ("Strong answer", "strong", "#4ade80")):
        body, ny = para(100, y + 125, it[key], 40, 36, "#fff", 500)
        h = ny - y + 10 + 50
        s += rect(60, y, W - 120, h, col, 28, opacity=0.13) + rect(60, y, W - 120, h, "none", 28, col, 4)
        s += text(100, y + 66, label.upper(), 28, col, 800, extra='letter-spacing="3"') + body
        y += h + 36
    t, y = tip_box(y + 10, "Formula", it["formula"], c["accent"])
    return svg_doc(s + t + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


# ---- layout: calm word (no figures, landscape only) -----------------------
def L_noor(it, n, total, c):
    s = ""
    stars = [(140, 330, 4), (300, 250, 3), (520, 380, 5), (760, 300, 3), (930, 420, 4), (200, 520, 3), (880, 560, 3), (620, 220, 3)]
    for x, y, r in stars:
        s += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity="0.8"/>'
    mask = '<mask id="m"><rect width="1080" height="1920" fill="#fff"/><circle cx="905" cy="230" r="72" fill="#000"/></mask>'
    s += '<circle cx="860" cy="230" r="84" fill="#f6e3a1" mask="url(#m)"/>'
    s += header(c["brand"], c["tagline"], c["accent"], n, total).replace("#fff", "#fff")
    s += text(W // 2, 640, it["word"], 230, "#ffe9a8", 700, "middle", AR, 'direction="rtl"')
    s += text(W // 2, 730, f'{it["translit"]}  ·  {it["meaning"]}', 44, "#fff", 600, "middle")
    # soft hills
    s += f'<path d="M0 1500 Q270 1340 540 1450 T1080 1400 L1080 1920 L0 1920Z" fill="#1c5d6b" opacity="0.55"/>'
    s += f'<path d="M0 1620 Q300 1480 620 1580 T1080 1540 L1080 1920 L0 1920Z" fill="#15485a" opacity="0.8"/>'
    s += f'<path d="M0 1740 Q340 1650 700 1720 T1080 1690 L1080 1920 L0 1920Z" fill="#0e3347"/>'
    ar_lines = wrap(it["text_ar"], 26)
    en_body, ny = para(W // 2, 0, it["text_en"], 34, 36, "#fff", 500, "middle")
    h = 150 + len(ar_lines) * 88 + len(wrap(it["text_en"], 34)) * 50 + 110
    y0 = 830
    s += rect(60, y0, W - 120, h, "#0b2230", 36, "#ffffff40", 2, 0.72)
    for i, line in enumerate(ar_lines):
        s += text(W // 2, y0 + 120 + i * 88, line, 62, "#fff", 600, "middle", AR, 'direction="rtl" unicode-bidi="plaintext"')
    ty = y0 + 120 + len(ar_lines) * 88 + 10
    t, _ = para(W // 2, ty, it["text_en"], 34, 36, "#ffffffdd", 500, "middle")
    s += t
    p, pw = pill((W - int(len(it["ref"]) * 30 * 0.58 + 56)) // 2, y0 + h - 100, it["ref"], c["accent"], "#0b1020", 30)
    s += p
    s += text(W // 2, H - 140, "by Khaled Dawod", 30, "#f6e3a1", 700, "middle")
    s += text(W // 2, H - 90, it.get("note", "English is a meaning of the text, not a word-for-word translation."), 24, "#ffffffb0", 500, "middle")
    return svg_doc(s, c["c1"], c["c2"], mask)


# ---- layout: arabic word fact ---------------------------------------------
def L_fact(it, n, total, c):
    s = ""
    for k in range(6):  # geometric 2D motif
        s += f'<rect x="760" y="250" width="260" height="260" fill="none" stroke="{c["accent"]}" stroke-width="3" opacity="0.35" transform="rotate({k*15} 890 380)"/>'
    s += header(c["brand"], c["tagline"], c["accent"], n, total)
    s += text(W // 2, 760, it["ar"], 280, "#fff", 700, "middle", AR, 'direction="rtl"')
    s += text(W // 2, 850, it["translit"], 54, c["accent"], 700, "middle")
    p, pw = pill((W - int(len(it["en"]) * 34 * 0.58 + 56 + 330)) // 2, 920, "became English: " + it["en"], c["accent"], "#0b1020", 34)
    s += p
    body, ny = para(100, 1130, it["fact"], 34, 44, "#fff", 500)
    h = ny - 1030 + 20
    s += rect(60, 1010, W - 120, h, "#ffffff14", 30, c["accent"], 3) + body
    t, y = tip_box(1010 + h + 50, "Try it", it["try"], c["accent"])
    return svg_doc(s + t + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


# ---- layout: recipe --------------------------------------------------------
def L_recipe(it, n, total, c):
    s = header(c["brand"], c["tagline"], c["accent"], n, total)
    cx, cy = W // 2, 470
    s += f'<circle cx="{cx}" cy="{cy}" r="200" fill="#ffffff" opacity="0.95"/><circle cx="{cx}" cy="{cy}" r="168" fill="#f4efe6"/>'
    pal = it["palette"]
    for i in range(14):
        a = i * 2.399
        r = 24 + (i * 37) % 100
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        s += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{34 + (i*7)%26}" fill="{pal[i % len(pal)]}"/>'
    t, y = title_block(it["title"], 770, 70, width=22, anchor="middle")
    s += t
    p1, w1 = pill(60, y + 10, it["time"], c["accent"], "#0b1020", 30)
    p2, w2 = pill(60 + w1 + 24, y + 10, it["kcal"], "#ffffff", "#0b1020", 30)
    s += p1 + p2
    y += 120
    s += text(60, y, "INGREDIENTS", 28, c["accent"], 800, extra='letter-spacing="3"')
    y += 20
    for i, ing in enumerate(it["ingredients"]):
        s += f'<circle cx="{78}" cy="{y + 40 + i*56}" r="9" fill="{c["accent"]}"/>' + text(105, y + 52 + i * 56, ing, 36, "#fff", 500)
    y += len(it["ingredients"]) * 56 + 50
    s += text(60, y, "STEPS", 28, c["accent"], 800, extra='letter-spacing="3"')
    y += 14
    for i, st in enumerate(it["steps"]):
        body, ny = para(130, y + 56, st, 38, 34, "#fff", 500)
        s += f'<circle cx="84" cy="{y + 42}" r="24" fill="{c["accent"]}"/>' + text(84, y + 52, str(i + 1), 30, "#0b1020", 800, "middle") + body
        y = ny + 6
    return svg_doc(s + footer(c["repo"], c["accent"]), c["c1"], c["c2"])


SLUG = "testtinies"
CFG = {
 "brand": "TESTTINIES",
 "tagline": "QA in 30 seconds: software testing basics",
 "c1": "#0b1a1a",
 "c2": "#0f3a3a",
 "accent": "#2dd4bf",
 "repo": "testtinies-qa"
}


def render(item, n, total):
    return L_qa(item, n, total, CFG)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=os.path.join(here, "..", "data", "content.json"))
    ap.add_argument("--out", default=os.path.join(here, "..", "out"))
    ap.add_argument("--index", type=int, help="item index (default: today's item)")
    ap.add_argument("--all", action="store_true", help="render every item")
    ap.add_argument("--png", action="store_true", help="also render PNG with headless Chrome")
    ap.add_argument("--video", action="store_true", help="also make an 8 s MP4 with ffmpeg (implies --png)")
    a = ap.parse_args()
    items = json.load(open(a.data, encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    chosen = list(enumerate(items)) if a.all else [pick(items, a.index)]
    for i, item in chosen:
        base = os.path.join(a.out, f"{SLUG}-{i + 1:02d}")
        svg = render(item, i + 1, len(items))
        open(base + ".svg", "w", encoding="utf-8").write(svg)
        print("wrote", base + ".svg")
        if a.png or a.video:
            if to_png(base + ".svg", base + ".png"):
                print("wrote", base + ".png")
                if a.video and to_video(base + ".png", base + ".mp4"):
                    print("wrote", base + ".mp4")


if __name__ == "__main__":
    main()
