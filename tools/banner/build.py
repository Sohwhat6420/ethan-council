"""Builds the README banner and its two social images.

    python tools/banner/build.py              # assets/banner-{dark,light}.svg and the social SVGs
    node tools/banner/export_png.mjs          # renders the social SVGs to PNG with headless Chromium

The banner is the council card from the profile README (five seats round an oval table, in the profile's ghost glass),
widened into a hero. Motion is CSS and SMIL inside the SVG, the same technique as the profile's typed "now focused on"
line: each phrase is clipped by a rect whose width steps with calcMode="discrete", and the caret follows it. GitHub
strips <style> and <script> from README HTML but runs both inside an SVG served as an image. With reduced motion
the motion layer is hidden and a still frame shows instead.

Every claim on these images is also in README.md, with its source there.
"""
import math
import os

from fontTools.ttLib import TTFont  # noqa: F401  (svgkit needs it; fail early with a clear import error)

from svgkit import Doc, THEMES, REDUCED, GLASS_PAD, f, font, glass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets")

# the four members, clockwise from the right-hand seat; the top seat is the person, who always decides
MEMBERS = [("Scrutiniser", "being built first"), ("Designer", "planned"), ("Coder", "planned"),
           ("Orchestrator", "planned")]
PHASE = 3.0                       # seconds each member is lit
CYCLE = PHASE * len(MEMBERS)

PHRASES = ["learns from my real answers to AI agents",
           "scored on the times I overrule the agent",
           "built for a 6 GB laptop GPU; data stays home",
           "it suggests, and I still make the call"]

GOAL = ("An LLM that thinks and decides like one person,", "and runs on consumer-grade hardware.")


def caps(doc, s, x, y, size, colour, anchor="start", tracking=0.14):
    return doc.text(s.upper(), x, y, "cap", size, colour, tracking=tracking, anchor=anchor)


def seats(cx, cy, k):
    rx, ry = 80.5 * k, 48.3 * k
    out = []
    for j in range(5):
        a = math.radians(-90 + 72 * j)
        out.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return out   # [0] is the person; [1:] are the members, clockwise


def constellation(doc, T, cx, cy, k, animated=True, lit=0):
    """The council: an oval table, the person at the head, four members round it. Returns (base, motion, still)."""
    S = seats(cx, cy, k)
    gold, acc = T["gold"], T["accent"]
    r = 11 * k
    base = ['<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="none" stroke="%s" stroke-opacity=".5" stroke-width="1.6"/>'
            % (f(cx), f(cy), f(40 * k), f(24 * k), gold)]
    for j, (x, y) in enumerate(S):
        base.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-opacity=".25" stroke-width="1"/>'
                    % (f(cx), f(cy), f(x), f(y), gold))
        if j == 0:
            # the person: a solid seat, always lit
            base.append('<circle cx="%s" cy="%s" r="%s" fill="%s" fill-opacity=".16" stroke="%s" stroke-width="1.8"/>'
                        % (f(x), f(y), f(r), gold, gold))
            base.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (f(x), f(y), f(3.2 * k), gold))
        else:
            base.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-opacity=".45" stroke-width="1.8"/>'
                        % (f(x), f(y), f(r), gold))
    base.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (f(cx), f(cy), f(5 * k), gold))
    # labels: the person above, members below their seats
    lab = 9.5 * k
    x0, y0 = S[0]
    t, _ = caps(doc, "You decide", x0, y0 - r - 8 * k, lab, T["text"], anchor="middle")
    base.append(t)
    def label_y(i):
        # side seats carry their label above, clear of the table; the two lower seats below
        y = S[i + 1][1]
        return y - r - 8 * k if i in (0, 3) else y + r + 15 * k

    for i, (name, _) in enumerate(MEMBERS):
        x, y = S[i + 1]
        t, _ = caps(doc, name, x, label_y(i), lab, T["faint"], anchor="middle", tracking=0.1)
        base.append(t)

    def highlight(i, cls, style):
        x, y = S[i + 1]
        name, state = MEMBERS[i]
        g = ['<g class="%s"%s>' % (cls, style)]
        g.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-opacity=".8" stroke-width="1.4"/>'
                 % (f(cx), f(cy), f(x), f(y), acc))
        g.append('<circle cx="%s" cy="%s" r="%s" fill="%s" fill-opacity=".14" stroke="%s" stroke-width="2.2"/>'
                 % (f(x), f(y), f(r), acc, acc))
        g.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (f(x), f(y), f(3.2 * k), acc))
        t, _ = caps(doc, name, x, label_y(i), lab, acc, anchor="middle", tracking=0.1)
        g.append(t)
        g.append("</g>")
        return "".join(g)

    still = highlight(lit, "", "")
    if not animated:
        return "".join(base), "", still
    motion = []
    for i in range(len(MEMBERS)):
        x, y = S[i + 1]
        motion.append(highlight(i, "hl", ' style="animation-delay:%ss"' % f(i * PHASE, 1)))
        # a vote travels from the member to the table, then the table's suggestion goes up to the person
        motion.append('<g class="v%d" style="animation-delay:%ss"><circle cx="%s" cy="%s" r="%s" fill="%s"/></g>'
                      % (i, f(i * PHASE, 1), f(cx), f(cy), f(2.8 * k), acc))
        doc.css.append("@keyframes v%d{0%%{transform:translate(%spx,%spx);opacity:0}4%%{opacity:1}"
                       "13%%{transform:translate(0,0);opacity:1}15%%{transform:translate(0,0);opacity:1}"
                       "23%%{transform:translate(%spx,%spx);opacity:1}25%%,100%%{transform:translate(%spx,%spx);opacity:0}}"
                       ".v%d{opacity:0;animation:v%d %ss cubic-bezier(.45,0,.3,1) infinite both}"
                       % (i, f(x - cx), f(y - cy), f(x0 - cx), f(y0 - cy + r), f(x0 - cx), f(y0 - cy + r),
                          i, i, f(CYCLE, 1)))
    # the table answers each vote with a ring
    motion.append('<g transform="translate(%s %s)"><circle r="%s" fill="none" stroke="%s" stroke-width="1.4" class="tp"/></g>'
                  % (f(cx), f(cy), f(5 * k), gold))
    doc.css.append(".tp{transform-box:fill-box;transform-origin:center;opacity:0;animation:tp %ss ease-out infinite .4s}"
                   "@keyframes tp{0%%{transform:scale(1);opacity:0}1%%{opacity:.9}30%%,100%%{transform:scale(5.5);opacity:0}}"
                   % f(PHASE, 1))
    doc.css.append(".hl{opacity:0;animation:hl %ss ease-in-out infinite both}"
                   "@keyframes hl{0%%{opacity:0}3%%,22%%{opacity:1}25%%,100%%{opacity:0}}" % f(CYCLE, 1))
    return "".join(base), "".join(motion), still


def typed(doc, T, x, y, size):
    """The profile's typed rotation: each phrase is revealed by a clip whose width steps letter by letter."""
    mono = font("mono")
    cw = mono.adv(mono.glyph("a")) * size / mono.upm
    prefix = "› "
    pre, _ = doc.text(prefix, x, y, "mono", size, T["faint"])
    xt = x + len(prefix) * cw
    type_s, del_s, hold, gap = 0.05, 0.022, 2.6, 0.5
    events, t = [], 0.3
    for i, p in enumerate(PHRASES):
        for kk in range(1, len(p) + 1):
            events.append((t, i, kk))
            t += type_s
        t += hold
        for kk in range(len(p) - 1, -1, -1):
            events.append((t, i, kk))
            t += del_s
        t += gap
    cycle = t
    clips, motion = [], ['<g class="motion">']
    for i, p in enumerate(PHRASES):
        kt, vals = ["0"], ["0"]
        for (te, pi, kk) in events:
            if pi == i:
                kt.append(f(te / cycle, 5))
                vals.append(f(kk * cw + (2 if kk else 0), 2))
        cid = doc.uid("tc")
        clips.append('<clipPath id="%s"><rect x="%s" y="%s" height="%s" width="0"><animate attributeName="width" '
                     'dur="%ss" repeatCount="indefinite" calcMode="discrete" keyTimes="%s" values="%s"/></rect></clipPath>'
                     % (cid, f(xt, 2), f(y - size * 1.1, 1), f(size * 1.6, 1), f(cycle, 3), ";".join(kt), ";".join(vals)))
        tx, _ = doc.text(p, xt, y, "mono", size, T["text"] if i % 2 == 0 else T["accent"])
        motion.append('<g clip-path="url(#%s)">%s</g>' % (cid, tx))
    kt, vals = ["0"], [f(xt + 1, 2)]
    for (te, pi, kk) in events:
        kt.append(f(te / cycle, 5))
        vals.append(f(xt + kk * cw + 1, 2))
    motion.append('<rect y="%s" width="%s" height="%s" fill="%s" class="blink"><animate attributeName="x" dur="%ss" '
                  'repeatCount="indefinite" calcMode="discrete" keyTimes="%s" values="%s"/></rect>'
                  % (f(y - size * 0.82, 1), f(size * 0.12, 2), f(size * 1.05, 1), T["accent"], f(cycle, 3),
                     ";".join(kt), ";".join(vals)))
    motion.append("</g>")
    doc.defs.extend(clips)
    doc.css.append(".blink{animation:blink 1.05s steps(1) infinite}@keyframes blink{50%{opacity:0}}")
    st, stw = doc.text(PHRASES[0], xt, y, "mono", size, T["text"])
    still = '<g class="still">%s<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/></g>' % (
        st, f(xt + stw + 2, 2), f(y - size * 0.82, 1), f(size * 0.12, 2), f(size * 1.05, 1), T["accent"])
    return pre + "".join(motion) + still


def window(doc, T, x, y, w, h, sweep=True):
    """The card's inner window: a faint gold wash, a hairline and the slow light sweep."""
    k = doc.uid("w")
    doc.defs.append('<clipPath id="%sc"><rect x="%s" y="%s" width="%s" height="%s" rx="11"/></clipPath>'
                    % (k, f(x), f(y), f(w), f(h)))
    doc.defs.append('<linearGradient id="%sg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                    '<stop offset=".5" stop-color="#fff" stop-opacity="%s"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>'
                    '</linearGradient>' % (k, ".05" if T["name"] == "dark" else ".35"))
    under = '<rect x="%s" y="%s" width="%s" height="%s" rx="11" fill="%s" fill-opacity=".05"/>' % (
        f(x), f(y), f(w), f(h), T["gold"])
    over = ""
    if sweep:
        over += '<g clip-path="url(#%sc)"><g class="sw"><rect x="%s" y="%s" width="%s" height="%s" fill="url(#%sg)"/></g></g>' % (
            k, f(x), f(y), f(w / 2), f(h), k)
        doc.css.append(".sw{animation:sw 7s ease-in-out infinite}"
                       "@keyframes sw{0%,35%{transform:translateX(-120%)}65%,100%{transform:translateX(240%)}}")
    over += '<rect x="%s" y="%s" width="%s" height="%s" rx="11" fill="none" stroke="%s" stroke-opacity="%s"/>' % (
        f(x + 0.5), f(y + 0.5), f(w - 1), f(h - 1), "#ffffff" if T["name"] == "dark" else "#14161a",
        ".22" if T["name"] == "dark" else ".12")
    return under, over


FRAME_CSS = """
.rise{animation:rise 1.2s cubic-bezier(.2,.7,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
"""


def hero(T):
    W, H = 880, 300
    alt = ("Human LLM Council. An LLM that thinks and decides like one person, and runs on consumer-grade hardware. "
           "Four members sit round a table: the Scrutiniser, being built first, and the planned Designer, Coder and "
           "Orchestrator. Each lights in turn and passes a suggestion to the person at the head of the table, who "
           "decides. A typed line cycles: " + "; ".join(PHRASES) + ". Preview: no model is trained on real data yet.")
    doc = Doc(W, H, "Human LLM Council", alt)
    doc.pad = GLASS_PAD
    doc.css.append(FRAME_CSS)
    doc.body.append(glass(doc, T, 0, 0, W, H, 18))
    # left: what it is for
    x = 40
    eb, _ = caps(doc, "Open source  ·  local-first  ·  preview", x, 56, 11, T["gold"])
    ti, _ = doc.text("Human LLM Council", x - 2, 116, "serif", 56, T["text"])
    g1, _ = doc.text(GOAL[0], x, 156, "sans", 18, T["text"])
    g2, _ = doc.text(GOAL[1], x, 181, "sans", 18, T["text"])
    doc.body.append('<g class="rise" style="animation-delay:.1s">%s</g>' % eb)
    doc.body.append('<g class="rise" style="animation-delay:.22s">%s</g>' % ti)
    doc.body.append('<g class="rise" style="animation-delay:.38s">%s%s</g>' % (g1, g2))
    doc.body.append('<g class="rise" style="animation-delay:.55s">%s</g>' % typed(doc, T, x, 232, 14))
    nb, _ = caps(doc, "Benchmark built  ·  no model trained on real data yet", x, 270, 9.5, T["faint"], tracking=0.12)
    doc.body.append('<g class="rise" style="animation-delay:.7s">%s</g>' % nb)
    # right: the council
    wx, wy, ww, wh = 506, 22, 352, 256
    under, over = window(doc, T, wx, wy, ww, wh)
    base, motion, still = constellation(doc, T, wx + ww / 2, wy + wh / 2 + 4, 1.28)
    doc.body.append('<g class="rise" style="animation-delay:.3s">%s%s<g class="motion">%s</g>'
                    '<g class="still">%s</g>%s</g>' % (under, base, motion, still, over))
    doc.css.append(REDUCED)
    return doc


def social(T, W, H):
    """A still card for LinkedIn project media (1200 x 627) and GitHub's social preview (1280 x 640)."""
    alt = "Human LLM Council: " + " ".join(GOAL)
    doc = Doc(W, H, "Human LLM Council", alt)
    s = H / 627.0
    bg = "#0d1117" if T["name"] == "dark" else "#f6f8fa"
    doc.defs.append('<radialGradient id="bgg" cx=".78" cy=".42" r=".7"><stop offset="0" stop-color="%s" stop-opacity=".10"/>'
                    '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>' % (T["gold"], T["gold"]))
    doc.body.append('<rect width="%d" height="%d" fill="%s"/><rect width="%d" height="%d" fill="url(#bgg)"/>' % (W, H, bg, W, H))
    m = 44 * s
    doc.body.append(glass(doc, T, m, m, W - 2 * m, H - 2 * m, 26 * s, sd=14 * s))
    x = m + 56 * s
    eb, _ = caps(doc, "Open source  ·  local-first  ·  preview", x, m + 84 * s, 15 * s, T["gold"])
    ti, _ = doc.text("Human LLM", x - 3 * s, m + 178 * s, "serif", 86 * s, T["text"])
    ti2, _ = doc.text("Council", x - 3 * s, m + 262 * s, "serif", 86 * s, T["text"])
    g1, _ = doc.text("An LLM that thinks and decides", x, m + 330 * s, "sans", 27 * s, T["text"])
    g2, _ = doc.text("like one person, and runs on", x, m + 366 * s, "sans", 27 * s, T["text"])
    g3, _ = doc.text("consumer-grade hardware.", x, m + 402 * s, "sans", 27 * s, T["text"])
    url, _ = doc.text("github.com/Sohwhat6420/human-llm-council", x, H - m - 52 * s, "mono", 17 * s, T["dim"])
    doc.body.append(eb + ti + ti2 + g1 + g2 + g3 + url)
    ww, wh = 470 * s, 400 * s
    wx, wy = W - m - 50 * s - ww, (H - wh) / 2
    under, over = window(doc, T, wx, wy, ww, wh, sweep=False)
    base, _, still = constellation(doc, T, wx + ww / 2, wy + wh / 2 + 6 * s, 1.95 * s, animated=False)
    doc.body.append(under + base + still + over)
    return doc


def write(doc, name):
    path = os.path.join(ASSETS, name)
    os.makedirs(ASSETS, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc.render())
    print("%-40s %6d bytes" % (os.path.relpath(path, ROOT), os.path.getsize(path)))


def main():
    for name in ("dark", "light"):
        write(hero(THEMES[name]), "banner-%s.svg" % name)
    # sources for the PNGs (rendered by export_png.mjs), kept so the PNGs can be rebuilt
    write(social(THEMES["dark"], 1200, 627), "banner-linkedin-1200x627.svg")
    write(social(THEMES["dark"], 1280, 640), "banner-1280x640.svg")


if __name__ == "__main__":
    main()
