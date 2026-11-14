"""Builds the README banner (wide and phone versions, light and dark) and its two social images.

    python tools/banner/build.py              # assets/banner-*.svg
    node tools/banner/export_png.mjs          # renders the two social SVGs to PNG with headless Chromium

The banner is the council card from the profile README (five seats round an oval table, in the profile's ghost glass),
widened into a hero. Motion is CSS and SMIL inside the SVG, the profile's technique: text is outlined to paths, and
the typed line is revealed by clips whose width steps with calcMode="discrete". GitHub strips <style> and <script>
from README HTML but runs both inside an SVG served as an image.

The still frame is the default; the motion layer turns on only under prefers-reduced-motion: no-preference, because
SMIL ignores CSS's animation:none and would otherwise keep typing for people who asked for less motion.

One master loop of 32 s: each member is lit for 4 s (16 s round the table, twice per loop) and each typed phrase
gets 8 s. In each member's 4 s its vote goes to the table, the table answers, and the suggestion goes up to the
person, whose seat brightens: the person decides. Every claim on these images is also in README.md, with its source.
"""
import math
import os
import random

from svgkit import Doc, THEMES, GLASS_PAD, f, font, glass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets")

MEMBERS = ["Scrutiniser", "Designer", "Coder", "Orchestrator"]   # clockwise from the right-hand seat
SEAT_S = 4.0
SEATS_CYCLE = SEAT_S * len(MEMBERS)                               # 16 s
PHRASE_S = 8.0
PHRASES = ["tested on my latest 375 real decisions",
           "also scored on the 53 times I overrode it",
           "pass mark fixed before any training",
           "built for a laptop GPU; my data stays home"]
MASTER = PHRASE_S * len(PHRASES)                                  # 32 s, two rounds of the table

EYEBROW = "Local models  ·  preview  ·  Apache-2.0"               # the profile card's own eyebrow
GOAL = ("An LLM that thinks and decides like one person,", "and runs on consumer-grade hardware.")

# keyframe moments inside one member's 4 s, as fractions of the 16 s seat cycle
T_LEAVE, T_HUB, T_UP, T_YOU = 0.02, 0.08, 0.10, 0.16

STILL_FIRST = """
.motion{display:none}
@media (prefers-reduced-motion: no-preference){.motion{display:inline}.still{display:none}}
@media (prefers-reduced-motion: reduce){*{animation:none!important}}
.rise{animation:rise 1.2s cubic-bezier(.2,.7,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
"""


def caps(doc, s, x, y, size, colour, anchor="start", tracking=0.14):
    return doc.text(s.upper(), x, y, "cap", size, colour, tracking=tracking, anchor=anchor)[0]


def toward(a, b, d):
    """The point d along the line from a towards b."""
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
    return (a[0] + (b[0] - a[0]) * d / L, a[1] + (b[1] - a[1]) * d / L)


def constellation(doc, T, cx, cy, k, lab, animated=True):
    """The council: an oval table, the person at the head, four members round it. Returns (base, motion, still)."""
    rx, ry = 80.5 * k, 48.3 * k
    S = [(cx + rx * math.cos(math.radians(-90 + 72 * j)), cy + ry * math.sin(math.radians(-90 + 72 * j)))
         for j in range(5)]                     # [0] the person; [1:] the members
    gold, acc = T["gold"], T["accent"]
    light = T["name"] == "light"
    r, hub = 11 * k, 5 * k
    idle = ".7" if light else ".45"
    C = (cx, cy)
    base = ['<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="none" stroke="%s" stroke-opacity=".5" stroke-width="1.6"/>'
            % (f(cx), f(cy), f(40 * k), f(24 * k), gold)]
    for j, p in enumerate(S):
        e = toward(p, C, r + 3)
        base.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-opacity="%s" stroke-width="1"/>'
                    % (f(cx), f(cy), f(e[0]), f(e[1]), gold, ".4" if light else ".25"))
        if j == 0:
            base.append('<circle cx="%s" cy="%s" r="%s" fill="%s" fill-opacity=".16" stroke="%s" stroke-width="1.8"/>'
                        '<circle cx="%s" cy="%s" r="%s" fill="%s"/>'
                        % (f(p[0]), f(p[1]), f(r), gold, gold, f(p[0]), f(p[1]), f(3.2 * k), gold))
        else:
            base.append('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-opacity="%s" stroke-width="1.8"/>'
                        % (f(p[0]), f(p[1]), f(r), gold, idle))
    base.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (f(cx), f(cy), f(hub), gold))
    base.append(caps(doc, "You decide", S[0][0], S[0][1] - r - 0.75 * lab, lab, T["text"], anchor="middle"))

    def label_y(i):
        y = S[i + 1][1]
        return y - r - 0.75 * lab if i in (0, 3) else y + r + 1.45 * lab   # side seats above, lower seats below

    for i, name in enumerate(MEMBERS):
        base.append(caps(doc, name, S[i + 1][0], label_y(i), lab, T["faint"], anchor="middle", tracking=0.1))

    def lit(i, attrs=""):
        p = S[i + 1]
        e = toward(p, C, r + 3)
        return ('<g%s><line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-opacity=".85" stroke-width="1.4"/>'
                '<circle cx="%s" cy="%s" r="%s" fill="%s" fill-opacity=".14" stroke="%s" stroke-width="2.2"/>'
                '<circle cx="%s" cy="%s" r="%s" fill="%s"/>%s</g>'
                % (attrs, f(cx), f(cy), f(e[0]), f(e[1]), acc, f(p[0]), f(p[1]), f(r), acc, acc, f(p[0]), f(p[1]),
                   f(3.2 * k), acc, caps(doc, MEMBERS[i], p[0], label_y(i), lab, acc, anchor="middle", tracking=0.1)))

    still = lit(0)
    if not animated:
        return "".join(base), "", still

    cyc = f(SEATS_CYCLE, 0)
    you = S[0]
    you_in = toward(you, C, r + 2)                 # where the suggestion arrives, at the person's ring
    hub_in = lambda p: toward(C, p, hub + 3)       # noqa: E731  (a dot stops just short of the hub)
    pct = lambda t: f(100 * t, 2) + "%"            # noqa: E731
    motion = []
    for i in range(len(MEMBERS)):
        p = S[i + 1]
        start = toward(p, C, r + 3)
        h1, h2 = hub_in(p), hub_in(you)
        d = f(i * SEAT_S, 0)
        motion.append(lit(i, ' class="hl" style="animation-delay:%ss"' % d))
        # the vote: seat edge -> hub (fades in the hub's halo) -> up the person's spoke -> the person's ring
        motion.append('<circle r="%s" fill="%s" class="v%d" style="animation-delay:%ss"/>' % (f(2.6 * k), acc, i, d))
        doc.css.append(
            ".v%d{opacity:0;animation:v%d %ss cubic-bezier(.45,0,.3,1) infinite both}"
            "@keyframes v%d{0%%{transform:translate(%spx,%spx);opacity:0}%s{transform:translate(%spx,%spx);opacity:0}"
            "%s{opacity:1}%s{transform:translate(%spx,%spx);opacity:1}%s{transform:translate(%spx,%spx);opacity:0}"
            "%s{transform:translate(%spx,%spx);opacity:0}%s{opacity:1}%s{transform:translate(%spx,%spx);opacity:1}"
            "%s,100%%{transform:translate(%spx,%spx);opacity:0}}"
            % (i, i, cyc, i, f(start[0]), f(start[1]), pct(T_LEAVE), f(start[0]), f(start[1]), pct(T_LEAVE + 0.01),
               pct(T_HUB - 0.01), f(h1[0]), f(h1[1]), pct(T_HUB), f(h1[0]), f(h1[1]), pct(T_UP), f(h2[0]), f(h2[1]),
               pct(T_UP + 0.01), pct(T_YOU), f(you_in[0]), f(you_in[1]), pct(T_YOU + 0.01), f(you_in[0]),
               f(you_in[1])))
    # the table answers each vote: the oval itself swells and fades
    motion.append('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="none" stroke="%s" stroke-width="1.6" class="tp"/>'
                  % (f(cx), f(cy), f(40 * k), f(24 * k), gold))
    doc.css.append(".tp{transform-box:fill-box;transform-origin:center;opacity:0;animation:tp %ss ease-out infinite %ss both}"
                   "@keyframes tp{0%%{transform:scale(1);opacity:.8}22%%,100%%{transform:scale(1.14);opacity:0}}"
                   % (f(SEAT_S, 0), f(T_HUB * SEATS_CYCLE, 2)))
    # the person's seat brightens as each suggestion arrives
    motion.append('<circle cx="%s" cy="%s" r="%s" fill="%s" fill-opacity=".28" stroke="%s" stroke-width="2.4" class="yo"/>'
                  % (f(you[0]), f(you[1]), f(r + 1.5), gold, gold))
    doc.css.append(".yo{opacity:0;animation:yo %ss ease-out infinite %ss both}"
                   "@keyframes yo{0%%{opacity:0}2%%,9%%{opacity:1}22%%,100%%{opacity:0}}"
                   % (f(SEAT_S, 0), f(T_YOU * SEATS_CYCLE, 2)))
    doc.css.append(".hl{opacity:0;animation:hl %ss ease-in-out infinite both}"
                   "@keyframes hl{0%%{opacity:0}2%%,22%%{opacity:1}25%%,100%%{opacity:0}}" % cyc)
    return "".join(base), "".join(motion), still


def typed(doc, T, x, y, size):
    """The profile's typed rotation, one phrase per 8 s, phase-locked to the table (two seats per phrase)."""
    mono = font("mono")
    cw = mono.adv(mono.glyph("a")) * size / mono.upm
    pre = doc.text("› ", x, y, "mono", size, T["faint"])[0]
    xt = x + 2 * cw
    rng = random.Random(7)                  # a human typing rhythm, the same on every build
    events = []
    for i, p in enumerate(PHRASES):
        t = i * PHRASE_S + 0.3
        for kk in range(1, len(p) + 1):
            events.append((t, i, kk))
            t += rng.uniform(0.04, 0.07)
        t = (i + 1) * PHRASE_S - 0.3 - 0.018 * len(p)
        for kk in range(len(p) - 1, -1, -1):
            events.append((t, i, kk))
            t += 0.018
    clips, motion = [], ['<g class="motion">']
    for i, p in enumerate(PHRASES):
        kt, vals = ["0"], ["0"]
        for (te, pi, kk) in events:
            if pi == i:
                kt.append(f(te / MASTER, 5))
                vals.append(f(kk * cw + (2 if kk else 0), 2))
        cid = doc.uid("tc")
        clips.append('<clipPath id="%s"><rect x="%s" y="%s" height="%s" width="0"><animate attributeName="width" '
                     'dur="%ss" repeatCount="indefinite" calcMode="discrete" keyTimes="%s" values="%s"/></rect></clipPath>'
                     % (cid, f(xt, 2), f(y - size * 1.1, 1), f(size * 1.6, 1), f(MASTER, 0), ";".join(kt), ";".join(vals)))
        motion.append('<g clip-path="url(#%s)">%s</g>' % (cid, doc.text(p, xt, y, "mono", size, T["dim"])[0]))
    kt, vals = ["0"], [f(xt + 1, 2)]
    for (te, _, kk) in events:
        kt.append(f(te / MASTER, 5))
        vals.append(f(xt + kk * cw + 1, 2))
    motion.append('<rect y="%s" width="%s" height="%s" fill="%s" opacity=".8"><animate attributeName="x" dur="%ss" '
                  'repeatCount="indefinite" calcMode="discrete" keyTimes="%s" values="%s"/></rect>'
                  % (f(y - size * 0.82, 1), f(size * 0.12, 2), f(size * 1.05, 1), T["dim"], f(MASTER, 0),
                     ";".join(kt), ";".join(vals)))
    motion.append("</g>")
    doc.defs.extend(clips)
    st = doc.text(PHRASES[0], xt, y, "mono", size, T["dim"])[0]
    return pre + "".join(motion) + '<g class="still">%s</g>' % st


def window(T, x, y, w, h):
    """The card's inner window: a faint wash and a hairline (gold in dark, neutral in light)."""
    dark = T["name"] == "dark"
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="11" fill="%s" fill-opacity="%s"/>'
            % (f(x), f(y), f(w), f(h), T["gold"] if dark else "#14161a", ".05" if dark else ".03"),
            '<rect x="%s" y="%s" width="%s" height="%s" rx="11" fill="none" stroke="%s" stroke-opacity="%s"/>'
            % (f(x + 0.5), f(y + 0.5), f(w - 1), f(h - 1), "#ffffff" if dark else "#14161a", ".22" if dark else ".12"))


ALT = ("Human LLM Council. An LLM that thinks and decides like one person, and runs on consumer-grade hardware. "
       "Four members sit round a table: the Scrutiniser, being built first, and the planned Designer, Coder and "
       "Orchestrator. Each in turn passes its suggestion to the person at the head of the table, who decides. ")


def hero(T):
    W, H = 880, 300
    doc = Doc(W, H, "Human LLM Council", ALT + "A typed line cycles: " + "; ".join(PHRASES) + ".")
    doc.pad = GLASS_PAD
    doc.css.append(STILL_FIRST)
    doc.body.append(glass(doc, T, 0, 0, W, H, 18))
    x = 40
    rise = lambda d, s: '<g class="rise" style="animation-delay:%ss">%s</g>' % (d, s)   # noqa: E731
    doc.body.append(rise(".1", caps(doc, EYEBROW, x, 70, 11, T["gold"])))
    doc.body.append(rise(".22", doc.text("Human LLM Council", x - 2, 128, "serif", 54, T["text"])[0]))
    doc.body.append(rise(".38", doc.text(GOAL[0], x, 168, "sans", 18, T["dim"])[0]
                         + doc.text(GOAL[1], x, 193, "sans", 18, T["dim"])[0]))
    doc.body.append(rise(".55", typed(doc, T, x, 240, 14)))
    wx, wy, ww, wh = 506, 22, 352, 256
    under, over = window(T, wx, wy, ww, wh)
    base, motion, still = constellation(doc, T, wx + ww / 2, wy + wh / 2 + 4, 1.28, 12.2)
    doc.body.append(rise(".3", '%s%s<g class="motion">%s</g><g class="still">%s</g>%s' % (under, base, motion, still, over)))
    return doc


def hero_phone(T):
    """Stacked for narrow screens (the README's <picture> picks it below 768 px): title, goal and the table."""
    W, H = 600, 560
    doc = Doc(W, H, "Human LLM Council", ALT)
    doc.pad = GLASS_PAD
    doc.css.append(STILL_FIRST)
    doc.body.append(glass(doc, T, 0, 0, W, H, 22))
    x = 36
    doc.body.append(caps(doc, EYEBROW, x, 62, 16, T["gold"]))
    doc.body.append(doc.text("Human LLM Council", x - 2, 130, "serif", 66, T["text"])[0])
    doc.body.append(doc.text("An LLM that thinks and decides like", x, 178, "sans", 25, T["dim"])[0])
    doc.body.append(doc.text("one person, on consumer-grade hardware.", x, 211, "sans", 25, T["dim"])[0])
    wx, wy, ww, wh = 24, 244, W - 48, 292
    under, over = window(T, wx, wy, ww, wh)
    base, motion, still = constellation(doc, T, W / 2, wy + wh / 2 + 8, 1.5, 17)
    doc.body.append('%s%s<g class="motion">%s</g><g class="still">%s</g>%s' % (under, base, motion, still, over))
    return doc


def social(T, W, H):
    """A still card for LinkedIn project media (1200 x 627) and GitHub's social preview (1280 x 640)."""
    doc = Doc(W, H, "Human LLM Council", "Human LLM Council: " + " ".join(GOAL))
    s = H / 627.0
    bg = "#0d1117" if T["name"] == "dark" else "#f6f8fa"
    doc.defs.append('<radialGradient id="bgg" cx=".78" cy=".42" r=".7"><stop offset="0" stop-color="%s" stop-opacity=".10"/>'
                    '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>' % (T["gold"], T["gold"]))
    doc.body.append('<rect width="%d" height="%d" fill="%s"/><rect width="%d" height="%d" fill="url(#bgg)"/>' % (W, H, bg, W, H))
    m = 40 * s
    doc.body.append(glass(doc, T, m, m, W - 2 * m, H - 2 * m, 26 * s, sd=14 * s))
    ww, wh = 500 * s, 420 * s
    wx, wy = W - m - 36 * s - ww, (H - wh) / 2
    x = m + 56 * s
    doc.body.append(caps(doc, EYEBROW, x, wy + 40 * s, 18 * s, T["gold"], tracking=0.12))
    doc.body.append(doc.text("Human LLM", x - 3 * s, wy + 142 * s, "serif", 92 * s, T["text"])[0])
    doc.body.append(doc.text("Council", x - 3 * s, wy + 232 * s, "serif", 92 * s, T["text"])[0])
    for n, line in enumerate(("An LLM that thinks and decides", "like one person, and runs on", "consumer-grade hardware.")):
        doc.body.append(doc.text(line, x, wy + (308 + 40 * n) * s, "sans", 30 * s, T["dim"])[0])
    under, over = window(T, wx, wy, ww, wh)
    base, _, still = constellation(doc, T, wx + ww / 2, wy + wh / 2 + 10 * s, 1.72 * s, 21 * s, animated=False)
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
        write(hero_phone(THEMES[name]), "banner-%s-m.svg" % name)
    write(social(THEMES["dark"], 1200, 627), "banner-linkedin-1200x627.svg")
    write(social(THEMES["dark"], 1280, 640), "banner-1280x640.svg")


if __name__ == "__main__":
    main()
