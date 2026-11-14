"""Builds the README art: the repo banner, the three-beat explainer and the social preview.

    python tools/banner/build.py              # assets/banner-*.svg, assets/explainer-*.svg
    node tools/banner/export_png.mjs          # assets/banner-1280x640.png, with headless Chromium

What the pictures show is the design: what the Council is being built to do. No model is trained yet, and each
picture says so in its own text.

The banner shows the job as a desk. Pieces of agent work queue on the left; one at a time goes to the Council,
which reads it; slop is marked in red pen, stamped and sent back with a note in the owner's words; good work goes
through to the person on the right. The explainer tells one real case (11 November 2026) in three beats.

One accent colour, an editor's red, is kept for the catch and the send-back. Type: JetBrains Mono for what the
agents wrote, Instrument Serif for what the person says, Hanken Grotesk for the labels. Text is outlined to paths
(svgkit), so the files need no fonts and no network.

Motion is CSS keyframes inside the SVG, which GitHub runs when the file is referenced as an image. Every element
is drawn in its finished place, and the animation rules sit inside `prefers-reduced-motion: no-preference`, so the
first frame, the reduced-motion view and any renderer that ignores animation all show the same complete picture.
Each loop begins and ends on that picture. Only transform, opacity and stroke-dashoffset are animated.

The round 1 LinkedIn image (assets/banner-linkedin-1200x627.*) is frozen and no longer built here.
"""
import math
import os

from svgkit import Doc, cr, f, font

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(ROOT, "assets")

# ----------------------------------------------------------------------------------------------------------------
# tokens: GitHub's own page colours as the base, one accent
# ----------------------------------------------------------------------------------------------------------------
THEMES = {
    "dark": dict(name="dark", page="#0d1117", ink="#f0f3f6", dim="#b4bcc6", faint="#8b949e",
                 paper="#161b22", edge="#3d444d", lane="#6e7681", accent="#ff7b54"),
    "light": dict(name="light", page="#ffffff", ink="#1f2328", dim="#4d5661", faint="#656d76",
                  paper="#f6f8fa", edge="#c4ccd4", lane="#8c959f", accent="#c4391a"),
}

EXPO = "cubic-bezier(.16,1,.3,1)"      # arrivals: fast start, long settle
INOUT = "cubic-bezier(.65,0,.35,1)"    # travel between two resting places


def _lum(hx):
    ch = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check_contrast():
    """WCAG AA (4.5:1) for every text colour on every surface it is drawn on. The build stops if one fails."""
    rows = []
    for T in THEMES.values():
        for fg in ("ink", "dim", "faint", "accent"):
            for bg in ("page", "paper"):
                c = contrast(T[fg], T[bg])
                rows.append((T["name"], fg, bg, c))
                assert c >= 4.5, "%s %s on %s is %.2f:1" % (T["name"], fg, bg, c)
    return rows


# ----------------------------------------------------------------------------------------------------------------
# animation: tracks of timed stops on one master loop
# ----------------------------------------------------------------------------------------------------------------
class Track:
    """Stops on a loop of `total` seconds. A stop is (time, declarations, easing towards the next stop)."""

    def __init__(self, total):
        self.total = total
        self.stops = []

    def at(self, t, decl, ease=None):
        self.stops.append((t % self.total, decl, ease))
        return self

    def emit(self, doc):
        s = sorted(self.stops, key=lambda x: x[0])
        assert s[0][1] == s[-1][1] or s[0][0] == 0, "the loop boundary must fall inside a hold: %r" % (s,)
        if s[0][0] > 0:
            s.insert(0, (0.0, s[-1][1], None))
        if s[-1][0] < self.total:
            s.append((self.total, s[0][1], None))
        name = doc.uid("k")
        rows = "".join("%s%%{%s%s}" % (f(100 * t / self.total, 3), d, ";animation-timing-function:" + e if e else "")
                       for t, d, e in s)
        doc.css.append("@keyframes %s{%s}" % (name, rows))
        doc.motion.append(".%s{animation:%s %ss linear infinite both}" % (name, name, f(self.total, 2)))
        return name


def new_doc(w, h, title, desc):
    doc = Doc(w, h, title, desc)
    doc.motion = []
    return doc


def finish(doc):
    """Animation only for people who have not asked for less of it; everyone else gets the finished picture."""
    if doc.motion:
        doc.css.append("@media (prefers-reduced-motion: no-preference){%s}" % "".join(doc.motion))
    return doc


def place(p, s=1.0):
    return "transform:translate(%spx,%spx) scale(%s)" % (f(p[0], 2), f(p[1], 2), f(s, 3))


def g(inner, cls=None, transform=None, extra=""):
    a = ""
    if cls:
        a += ' class="%s"' % cls
    if transform:
        a += ' transform="%s"' % transform
    return "<g%s%s>%s</g>" % (a, extra, inner)


# ----------------------------------------------------------------------------------------------------------------
# the pieces of work
# ----------------------------------------------------------------------------------------------------------------
CW, CH = 200.0, 128.0          # a piece of work at reading size; its centre is the group's origin
CARD_R = 16.0                  # corner radius of a piece of work; the reading frame curves round the same centre
STAMP = "Sent back"
STAMP_AT = "translate(41 39) rotate(-7)"     # lower right of the piece, tilted as a hand stamps
TICK_AT = "translate(76 42)"
NOTES = {"readme": "this is the old version",
         "claim": "where is the source for that number?",
         "diff": "I already said this yesterday"}


def pen_ring(box, seed=0.0):
    """A red-pen ring round a box: a slightly uneven ellipse whose end overshoots its start, as a hand draws it."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2 + 9, (y1 - y0) / 2 + 6.5
    pts = []
    n = 15
    for i in range(n + 1):
        a = math.radians(196 + 392 * i / n)
        k = 1 + 0.035 * math.sin(i * 1.9 + seed) + 0.075 * i / n
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    return cr(pts, closed=False)


def work(doc, T, kind):
    """One piece of agent work, drawn at reading size round (0, 0). Returns (svg, box of the part a pen would ring)."""
    l, t = -CW / 2, -CH / 2
    ink, dim, faint = T["ink"], T["dim"], T["faint"]
    o = ['<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s"/>'
         % (f(l), f(t), f(CW), f(CH), f(CARD_R), T["paper"], T["edge"]),
         '<path d="M%s %sh%s" stroke="%s"/>' % (f(l), f(t + 25), f(CW), T["edge"])]
    name = {"readme": "README.md", "claim": "summary.md", "diff": "release.diff", "good": "fix.md"}[kind]
    o.append(doc.text(name, l + 12, t + 16.5, "mono", 10.5, faint)[0])
    x = l + 12
    box = None
    if kind == "readme":
        tag, tw = doc.text("preview", l + CW - 12, t + 16.5, "mono", 10.5, dim, anchor="end")
        o.append(tag)
        box = (l + CW - 12 - tw, t + 8.5, l + CW - 12, t + 19)
        o.append(doc.text("Project README", x, t + 46, "cap", 13, ink)[0])
        for n, line in enumerate(("Install with one command and run the", "examples. Works on Windows, macOS",
                                  "and Linux. See the docs for more.")):
            o.append(doc.text(line, x, t + 62 + 13 * n, "sans", 9.5, dim)[0])
        o.append('<rect x="%s" y="%s" width="%s" height="19" rx="7" fill="%s" fill-opacity=".45"/>'
                 % (f(x), f(t + 98), f(CW - 24), T["edge"]))
        o.append(doc.text("pip install project", x + 8, t + 111, "mono", 9.5, dim)[0])
    elif kind == "claim":
        o.append(doc.text("Task complete", x, t + 46, "cap", 13, ink)[0])
        pre, hit = "The new build is ", "twice as fast"
        pw = font("sans").width(pre, 10.5)
        hw = font("sans").width(hit, 10.5)
        o.append(doc.text(pre, x, t + 66, "sans", 10.5, dim)[0])
        o.append(doc.text(hit, x + pw, t + 66, "sans", 10.5, ink)[0])
        box = (x + pw, t + 57, x + pw + hw, t + 69)
        o.append(doc.text("as the old one. All checks pass.", x, t + 81, "sans", 10.5, dim)[0])
    elif kind == "diff":
        rows = (("  def release():", dim), ("-     run_tests()", faint), ("+     # skip tests for now", ink),
                ("      publish()", dim))
        for n, (line, col) in enumerate(rows):
            o.append(doc.text(line, x, t + 48 + 17 * n, "mono", 10, col)[0])
        w = font("mono").width(rows[2][0], 10)
        box = (x, t + 73.5, x + w, t + 85.5)
    else:
        o.append(doc.text("Login fix", x, t + 46, "cap", 13, ink)[0])
        for n, line in enumerate(("Tests: all pass, log attached.", "Source: linked in the notes.",
                                  "This is the newest version.")):
            o.append(doc.text(line, x, t + 64 + 15 * n, "sans", 10.5, dim)[0])
    return "".join(o), box


def stamp(doc, T):
    """The verdict, stamped in the accent. Drawn round (0, 0); the caller places and tilts it."""
    label, w = doc.text(STAMP.upper(), 0, 4.3, "cap", 12, T["accent"], tracking=0.14, anchor="middle")
    bw = w + 22
    return ('<rect x="%s" y="-13" width="%s" height="26" rx="9" fill="%s" fill-opacity=".94" stroke="%s" stroke-width="1.6"/>%s'
            % (f(-bw / 2), f(bw), T["paper"], T["accent"], label))


def tick(T, r=11.0):
    return ('<circle r="%s" fill="%s" stroke="%s" stroke-width="1.5"/>' % (f(r), T["paper"], T["ink"]),
            '<path d="M-5.2 .4l3.6 3.8l6.8-8" fill="none" stroke="%s" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round" pathLength="1" stroke-dasharray="1 1.05"' % T["ink"])


def words(doc, s, x, y, key, size, fill, anchor="start"):
    """A line set word by word, so each word can arrive on its own. Returns [svg per word], width."""
    fnt = font(key)
    total = fnt.width(s, size)
    if anchor == "middle":
        x -= total / 2
    elif anchor == "end":
        x -= total
    out, pos = [], 0
    for w in s.split(" "):
        out.append(doc.text(w, x + fnt.width(s[:pos], size), y, key, size, fill)[0])
        pos += len(w) + 1
    return out, total


def arrow(pts, colour, width=1.5, head=6.5, cls=None, dash="1.5 6.5"):
    """A dotted lane with a chevron at its end. pts is a polyline; the lane's dots drift towards the head."""
    d = "M" + "L".join("%s %s" % (f(x), f(y)) for x, y in pts)
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    a = math.atan2(y2 - y1, x2 - x1)
    w1 = (x2 - head * math.cos(a - 0.62), y2 - head * math.sin(a - 0.62))
    w2 = (x2 - head * math.cos(a + 0.62), y2 - head * math.sin(a + 0.62))
    return ('<path d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round" '
            'stroke-dasharray="%s"%s/>' % (d, colour, f(width), dash, ' class="%s"' % cls if cls else "")
            + '<path d="M%s %sL%s %sL%s %s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" '
              'stroke-linejoin="round"/>' % (f(w1[0]), f(w1[1]), f(x2), f(y2), f(w2[0]), f(w2[1]), colour, f(width + 0.2)))


def brackets(B, s, colour, m=10.0, arm=9.0, width=1.5):
    """The Council's reading frame: four rounded corner marks round the place where work is read.

    Each mark is a quarter circle with a short straight tail (arm) at both ends. Its radius is the card's own
    corner radius plus the gap m, so the frame and the card curve round the same centre."""
    hw, hh = CW * s / 2 + m, CH * s / 2 + m
    r = CARD_R * s + m
    d = ""
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        cx, cy = B[0] + sx * hw, B[1] + sy * hh
        d += "M%s %sV%sA%s %s 0 0 %d %s %sH%s" % (
            f(cx), f(cy - sy * (r + arm)), f(cy - sy * r), f(r), f(r), 1 if sx * sy > 0 else 0,
            f(cx - sx * r), f(cy), f(cx - sx * (r + arm)))
    return '<path d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round"' % (
        d, colour, f(width))


# ----------------------------------------------------------------------------------------------------------------
# the banner: the whole job on one desk
# ----------------------------------------------------------------------------------------------------------------
TITLE = "Human LLM Council"
LINE_1 = "A personalised human you run on your own hardware."
LINE_2 = ("It catches the ", "slop", " AI agents hand you, and sends it back with your feedback.")
STATUS = "Preview: this is the design. No model is trained yet."
STATIONS = (("AI agents", "hand in work"),
            ("Your Council", "reads it first, the way you would"),
            ("You", "see only what passes"))
RETURN_LABEL = "sent back with your feedback"

BANNER_ALT = (
    "Human LLM Council. A personalised human you run on your own hardware: it catches the slop AI agents hand you "
    "and sends it back with your feedback. The picture shows the design. Work from AI agents queues on the left. "
    "The Council reads each piece first. A stale README preview is ringed in red, stamped \"sent back\" and returned "
    "with the note \"this is the old version\"; a made-up claim goes back with \"where is the source for that "
    "number?\"; a diff that skips the tests goes back with \"I already said this yesterday\". Only work that passes "
    "reaches the person on the right. Preview: no model is trained yet.")

# timings of one piece of work at the desk, in seconds after it arrives
TRAVEL, SCAN0, SCAN1, RING1, STAMP1, NOTE0, STAY, BACK = 0.8, 0.1, 0.8, 1.15, 1.35, 1.35, 3.7, 0.8
WORD_GAP, WORD_IN = 0.09, 0.4

WIDE = dict(
    W=880, H=440, u=1.0,
    title=(0, 56, 60), lines=((0, 95), (0, 120)), line_size=18, line_split=None,
    status=(880, 30, 13, "end"),
    A=(72, 300), B=(440, 300), C=(808, 300), sT=0.72, sD=1.25,
    labels=((0, 174, "start"), (440, 174, "middle"), (880, 174, "end")), name_size=15, sub_size=13, sub_dy=18,
    fwd=(((166, 300), (290, 300)), ((590, 300), (722, 300))),
    ret=((302, 418), (72, 418), (72, 360)),
    ret_label=(88, 407, 12.5, "start"),
    note=(317, 425, 23, "start"),
)

# Below 768 px the README's <picture> swaps to this one: the same desk, stacked, with type sized for a phone.
PHONE = dict(
    W=600, H=946, u=1.6,
    title=(0, 72, 76), lines=((0, 116), (0, 149), (0, 182)), line_size=25,
    line_split=("A personalised human you run on your own", "hardware. It catches the slop AI agents hand",
                "you, and sends it back with your feedback."),
    status=(0, 932, 20, "start"),
    A=(250, 290), B=(300, 565), C=(88, 830), sT=0.85, sD=1.7,
    labels=((0, 282, "start"), (0, 392, "start"), (196, 824, "start")), name_size=24, sub_size=21, sub_dy=29,
    subs=("hand in work", "reads it first", "see only what passes"),
    fwd=(((250, 356), (250, 430)), ((88, 702), (88, 764))),
    ret=((564, 724), (586, 724), (586, 290), (370, 290)),
    ret_label=(572, 414, 20, "end"),
    note=(554, 736, 30, "end"),
)


def banner_scene(doc, T, L, animated=True):
    """Draws the banner into doc and returns its body. Every element sits in its finished place (the still)."""
    ink, dim, acc = T["ink"], T["dim"], T["accent"]
    A, B, C, sT, sD = L["A"], L["B"], L["C"], L["sT"], L["sD"]
    u = L["u"]
    o = []

    # ---- words at the top: the name, what it is, what it does, and that it is a preview
    tx, ty, ts = L["title"]
    o.append(doc.text(TITLE, tx, ty, "serif", ts, ink)[0])
    size = L["line_size"]
    rows = L["line_split"] or (LINE_1, "".join(LINE_2))
    hit_box = None
    for (lx, ly), row in zip(L["lines"], rows):
        if "slop" in row:
            pre = row[:row.index("slop")]
            post = row[row.index("slop") + 4:]
            pw, sw = font("sans").width(pre, size), font("sansm").width("slop", size)
            o.append(doc.text(pre, lx, ly, "sans", size, dim)[0])
            o.append(doc.text("slop", lx + pw, ly, "sansm", size, ink)[0])
            o.append(doc.text(post, lx + pw + sw, ly, "sans", size, dim)[0])
            hit_box = (lx + pw, ly - size * 0.62, lx + pw + sw, ly + size * 0.2)
        else:
            o.append(doc.text(row, lx, ly, "sans", size, dim)[0])
    ring = '<path d="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" pathLength="1" stroke-dasharray="1 1.05"' % (
        pen_ring(hit_box, 1.0), acc, f(1.8 * u))
    o.append(ring + ' class="pen"/>')
    doc.css.append("@keyframes pen{from{stroke-dashoffset:1.03}to{stroke-dashoffset:0}}")
    doc.motion.append(".pen{animation:pen .7s %s .5s both}" % INOUT)
    sx, sy, ss, sa = L["status"]
    o.append(doc.text(STATUS, sx, sy, "sansm", ss, dim, anchor=sa)[0])

    # ---- the three places, their lanes and the way back
    subs = L.get("subs") or [s[1] for s in STATIONS]
    for (lx, ly, la), (name, _), sub in zip(L["labels"], STATIONS, subs):
        o.append(doc.text(name, lx, ly, "cap", L["name_size"], ink, anchor=la)[0])
        o.append(doc.text(sub, lx, ly + L["sub_dy"], "sans", L["sub_size"], dim, anchor=la)[0])
    for seg in L["fwd"]:
        o.append(arrow(seg, T["lane"], 1.5 * u, 6.5 * u, cls="fl", dash="%s %s" % (f(1.5 * u), f(6.5 * u))))
    o.append(arrow(L["ret"], acc, 1.6 * u, 6.5 * u, cls="fl", dash="%s %s" % (f(1.5 * u), f(6.5 * u))))
    doc.css.append("@keyframes fl{to{stroke-dashoffset:-%s}}" % f(8 * u))
    doc.motion.append(".fl{animation:fl 1.1s linear infinite}")
    rx, ry, rs, ra = L["ret_label"]
    o.append(doc.text(RETURN_LABEL, rx, ry, "sansm", rs, acc, anchor=ra)[0])

    # the queue behind the front piece, and the reading frame
    blank = ('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s"/><path d="M%s %sh%s" stroke="%s"/>'
             % (f(-CW / 2), f(-CH / 2), f(CW), f(CH), f(CARD_R), T["paper"], T["edge"], f(-CW / 2), f(-CH / 2 + 25), f(CW),
                T["edge"]))
    for k in (2, 1):
        o.append(g(blank, transform="translate(%s %s) scale(%s)" % (f(A[0] + 7 * k * u), f(A[1] - 7 * k * u), f(sT, 3))))
    frame = brackets(B, sD, T["lane"], 10 * u, 9 * u, 1.5 * u)
    o.append(frame + "/>")

    # what has already reached the person: one passed piece, resting
    good_svg, _ = work(doc, T, "good")
    tk_disc, tk_path = tick(T)
    rest = good_svg + g(tk_disc + tk_path + "/>", transform=TICK_AT)

    # ---- the loop
    order = ("readme", "claim", "diff")
    step = STAY + BACK + 0.1 + TRAVEL                       # one slop piece's arrival to the next one's
    back0 = 1.5                                             # the first piece (already marked) starts back here
    arrive = {"claim": back0 + BACK + 0.1 + TRAVEL}
    arrive["diff"] = arrive["claim"] + step
    arrive["good"] = arrive["diff"] + step
    leave_good = arrive["good"] + 1.6
    arrive["readme"] = leave_good + 0.1 + TRAVEL
    total = arrive["readme"] + STAY - back0                 # so the first piece's stay matches the others'
    after = {"readme": "claim", "claim": "diff", "diff": "good", "good": "readme"}
    queue_in = {after[k]: arrive[k] - TRAVEL + 0.4 for k in after}   # the next piece steps up once this one has left

    bump = Track(total)
    bump.at(leave_good + TRAVEL - 0.05, "transform:translateY(0px)", EXPO)
    bump.at(leave_good + TRAVEL + 0.12, "transform:translateY(%spx)" % f(-5 * u), INOUT)
    bump.at(leave_good + TRAVEL + 0.6, "transform:translateY(0px)")
    o.append(g(g(rest, transform="translate(%s %s) scale(%s)" % (f(C[0]), f(C[1]), f(sT, 3))),
               cls=bump.emit(doc) if animated else None))

    hot = Track(total)                                      # the reading frame turns red while slop is on the desk
    notes = []
    pieces = []
    back_pos = (A[0], A[1] + 8 * u)
    for kind in order + ("good",):
        a = arrive[kind]
        svg, box = work(doc, T, kind)
        at_desk = kind == "readme"                          # the still: the README is on the desk, already marked
        move, fade = Track(total), Track(total)
        fade.at(queue_in[kind], "opacity:0").at(queue_in[kind] + 0.4, "opacity:1")
        move.at(a - TRAVEL, place(A, sT), INOUT).at(a, place(B, sD))
        scan = Track(total)
        scan.at(a + SCAN0, "transform:translateX(%spx);opacity:0" % f(-CW / 2 + 8))
        scan.at(a + SCAN0 + 0.12, "transform:translateX(%spx);opacity:1" % f(-CW / 2 + 30))
        scan.at(a + SCAN1 - 0.12, "transform:translateX(%spx);opacity:1" % f(CW / 2 - 30))
        scan.at(a + SCAN1, "transform:translateX(%spx);opacity:0" % f(CW / 2 - 8))
        scan.at(a + SCAN1 + 0.05, "transform:translateX(%spx);opacity:0" % f(-CW / 2 + 8))
        inner = svg + ('<path d="M0 %sV%s" stroke="%s" stroke-width="1.3" opacity="0"%s/>'
                       % (f(-CH / 2 + 27), f(CH / 2 - 2), ink, ' class="%s"' % scan.emit(doc) if animated else ""))
        if kind == "good":
            gone = leave_good + TRAVEL
            move.at(leave_good, place(B, sD), INOUT).at(gone, place(C, sT)).at(gone + 0.25, place(C, sT)).at(gone + 0.3, place(A, sT))
            fade.at(gone, "opacity:1").at(gone + 0.2, "opacity:0")
            draw = Track(total)
            draw.at(a + SCAN1, "stroke-dashoffset:1.03", INOUT).at(a + RING1, "stroke-dashoffset:0")
            draw.at(gone + 0.2, "stroke-dashoffset:0").at(gone + 0.25, "stroke-dashoffset:1.03")
            seal = Track(total)
            seal.at(a + SCAN1, "opacity:0").at(a + SCAN1 + 0.15, "opacity:1").at(gone + 0.2, "opacity:1").at(gone + 0.25, "opacity:0")
            inner += g(g(tk_disc + tk_path + ' stroke-dashoffset="1.03"' + (' class="%s"' % draw.emit(doc) if animated else "") + "/>",
                         cls=seal.emit(doc) if animated else None, extra=' opacity="0"'), transform=TICK_AT)
        else:
            back = a + STAY
            gone = back + BACK
            move.at(back, place(B, sD), INOUT).at(gone, place(back_pos, sT * 0.94)).at(gone + 0.05, place(A, sT))
            fade.at(back + 0.3, "opacity:1").at(gone, "opacity:0")
            hot.at(a + SCAN1, "opacity:0").at(a + SCAN1 + 0.25, "opacity:1").at(back, "opacity:1").at(back + 0.4, "opacity:0")
            draw = Track(total)
            draw.at(a + SCAN1, "stroke-dashoffset:1.03", INOUT).at(a + RING1, "stroke-dashoffset:0")
            draw.at(gone, "stroke-dashoffset:0").at(gone + 0.05, "stroke-dashoffset:1.03")
            inner += ('<path d="%s" fill="none" stroke="%s" stroke-width="1.8" stroke-linecap="round" pathLength="1" '
                      'stroke-dasharray="1 1.05"%s%s/>' % (pen_ring(box, len(kind)), acc, "" if at_desk else ' stroke-dashoffset="1.03"',
                                                      ' class="%s"' % draw.emit(doc) if animated else ""))
            hit = Track(total)                               # the stamp lands a little large and settles
            hit.at(a + RING1, "transform:scale(1.22);opacity:0", EXPO).at(a + STAMP1, "transform:scale(1);opacity:1")
            hit.at(gone, "transform:scale(1);opacity:1").at(gone + 0.05, "transform:scale(1.22);opacity:0")
            inner += g(g(stamp(doc, T), cls=hit.emit(doc) if animated else None, extra="" if at_desk else ' opacity="0"'),
                       transform=STAMP_AT)
            # the note in the person's words, arriving word by word, then leaving with the work
            nx, ny, ns, na = L["note"]
            ws, _ = words(doc, "“" + NOTES[kind] + "”", nx, ny, "serif", ns, acc, na)
            parts = []
            for i, w in enumerate(ws):
                t0 = a + NOTE0 + WORD_GAP * i
                wt = Track(total)
                wt.at(t0, "transform:translateY(%spx);opacity:0" % f(7 * u), EXPO).at(t0 + WORD_IN, "transform:translateY(0px);opacity:1")
                wt.at(gone, "transform:translateY(0px);opacity:1").at(gone + 0.05, "transform:translateY(%spx);opacity:0" % f(7 * u))
                parts.append(g(w, cls=wt.emit(doc) if animated else None, extra="" if at_desk else ' opacity="0"'))
            away = Track(total)
            away.at(back, "transform:translateX(0px);opacity:1", INOUT).at(back + 0.6, "transform:translateX(%spx);opacity:0" % f(-70 * u))
            away.at(gone + 0.1, "transform:translateX(0px);opacity:0").at(gone + 0.5, "transform:translateX(0px);opacity:1")
            notes.append(g("".join(parts), cls=away.emit(doc) if animated else None))
        here = B if at_desk else A
        scale = sD if at_desk else sT
        shown = at_desk or kind == "claim"                   # the still: the claim waits at the front of the queue
        pieces.append((kind, g(g(inner, cls=fade.emit(doc) if animated else None, extra="" if shown else ' opacity="0"'),
                               cls=move.emit(doc) if animated else None,
                               transform="translate(%s %s) scale(%s)" % (f(here[0]), f(here[1]), f(scale, 3)))))
    o.append(brackets(B, sD, acc, 10 * u, 9 * u, 1.9 * u) + (' class="%s"' % hot.emit(doc) if animated else "") + "/>")
    # paint order: the piece at the desk goes on top
    for kind in ("good", "diff", "claim", "readme"):
        o.append(dict(pieces)[kind])
    o.extend(notes)
    return "".join(o)


def banner(T, L):
    doc = new_doc(L["W"], L["H"], TITLE, BANNER_ALT)
    doc.pad = (2, 2, 2, 2)
    doc.body.append(banner_scene(doc, T, L))
    return finish(doc)


def social(T):
    """GitHub's social preview, 1280 x 640: the wide banner's still on the page colour."""
    W, H, k = 1280, 640, 1.26
    doc = new_doc(W, H, TITLE, BANNER_ALT)
    L = WIDE
    doc.body.append('<rect width="%d" height="%d" fill="%s"/>' % (W, H, T["page"]))
    doc.body.append(g(banner_scene(doc, T, L, animated=False),
                      transform="translate(%s %s) scale(%s)" % (f((W - L["W"] * k) / 2), f((H - L["H"] * k) / 2), f(k))))
    doc.motion = []
    doc.css = []
    return finish(doc)


# ----------------------------------------------------------------------------------------------------------------
# the explainer: one real case in three beats
# ----------------------------------------------------------------------------------------------------------------
CASE = "One real case, 11 November 2026"
DESIGN = "The design, not a working product. No model is trained yet."
BEATS = ("An agent hands in work", "The Council catches the slop", "It goes back with my feedback")
AGENT_SAYS = ("README preview is ready", "for your review.")
FINDING = ("A newer version had already", "replaced this one.")
REPEATS = "Lines I keep repeating to agents:"
BACK_LABEL = "sent back with my feedback"
PASSES = "Only the fixed work reaches me."
FOOT = ("What happened on 11 November 2026: this preview reached me.",
        "Catching it first is what the Council is being built to do.")

EXPLAINER_ALT = (
    "How the Council is meant to work, on one real case from 11 November 2026. This is the design, not a working "
    "product; no model is trained yet. One: an agent hands in work, saying \"README preview is ready for your "
    "review\". Two: the Council catches the slop: the preview is ringed in red and stamped \"sent back\", because a "
    "newer version had already replaced this one. Three: it goes back with my feedback, \"this is the old version\". "
    "Other lines I keep repeating to agents: \"I already said this yesterday\" and \"where is the source for that "
    "number?\". Only the fixed work reaches me. What happened on 11 November 2026: this preview reached me. Catching "
    "it first is what the Council is being built to do.")

X_WIDE = dict(
    W=880, H=404, u=1.0, side=False,
    head=((CASE, 0, 16, "cap", 14, "ink", "start"), (DESIGN, 880, 16, "sansm", 13, "dim", "end")),
    beats=((0, 40, 1.0), (300, 40, 1.0), (630, 40, 1.0)),
    fwd=(((252, 187), (296, 187)), ((584, 187), (622, 187))),
    ret=((640, 258), (640, 350), (62, 350), (62, 276)),
    ret_label=(78, 339, 12.5, "start"),
    passes=(880, 355, 13, "end"),
    foot=((FOOT[0] + " " + FOOT[1], 0, 394, "sans", 12.5, "faint", "start"),),
)

X_PHONE = dict(
    W=600, H=1178, u=1.6, side=True,
    head=((CASE, 0, 24, "cap", 22, "ink", "start"), (DESIGN, 0, 54, "sansm", 19, "dim", "start")),
    beats=((0, 84, 1.5), (0, 318, 1.45), (0, 760, 1.5)),
    fwd=(),
    ret=((382, 872), (590, 872), (590, 236), (576, 236)),
    ret_label=(578, 852, 20, "end"),
    passes=(0, 1082, 21, "start"),
    foot=((FOOT[0], 0, 1134, "sans", 19, "faint", "start"), (FOOT[1], 0, 1162, "sans", 19, "faint", "start")),
)


def explainer_scene(doc, T, L, animated=True):
    """Three beats, each drawn in its own small coordinate space and placed by L. The still shows all three."""
    ink, dim, faint, acc = T["ink"], T["dim"], T["faint"], T["accent"]
    u = L["u"]
    total, out = 15.0, 2.2        # the finished picture holds, steps back at `out`, then is told again in order
    ghost = "opacity:.24"         # a part that has not happened yet stays faintly in place, so the frame is never empty

    def gate(t_in, dur=0.6):
        """A class for a part that drops back to a ghost with the picture and is inked in again at t_in."""
        if not animated:
            return None
        tr = Track(total)
        tr.at(out, "opacity:1", INOUT).at(out + 0.5, ghost).at(t_in, ghost, EXPO).at(t_in + dur, "opacity:1")
        return tr.emit(doc)

    def once(t0, t1, hidden, shown, ease=INOUT):
        """A class for a mark (ring, stamp, spoken word) that is unmade with the picture and made again at t0."""
        if not animated:
            return ""
        tr = Track(total)
        tr.at(out, shown, INOUT).at(out + 0.5, hidden).at(t0, hidden, ease).at(t1, shown)
        return ' class="%s"' % tr.emit(doc)

    def header(n, title):
        return (doc.text(str(n), 0, 30, "serif", 34, ink)[0] + doc.text(title, 27, 27, "sansm", 15, ink)[0])

    o = []
    for text, x, y, key, size, col, anchor in L["head"] + L["foot"]:
        o.append(doc.text(text, x, y, key, size, T[col], anchor=anchor)[0])

    card, box = work(doc, T, "readme")

    # ---- beat 1: what the agent said, and the piece it handed in
    said = [doc.text("agent", 0, 62, "mono", 11, faint)[0],
            '<rect x="0.5" y="70.5" width="236" height="58" rx="16" fill="%s" stroke="%s"/>' % (T["paper"], T["edge"])]
    for n, line in enumerate(AGENT_SAYS):
        said.append(doc.text(line, 14, 95 + 18 * n, "mono", 12, ink)[0])
    thumb_at = (318, 99) if L["side"] else (62, 186)
    b1 = (header(1, BEATS[0]) + g("".join(said), cls=gate(3.0))
          + g(g(card, transform="translate(%s %s) scale(.62)" % thumb_at), cls=gate(3.3)))

    # ---- beat 2: the Council reads it, rings the stale part and stamps it
    at, s2 = (140, 150), 1.2
    t_card, t_ring, t_stamp = 3.9, 5.2, 5.55
    scan = ""
    if animated:
        tr = Track(total)
        x0, x1 = -CW / 2 + 8, CW / 2 - 8
        tr.at(t_card + 0.7, "transform:translateX(%spx);opacity:0" % f(x0))
        tr.at(t_card + 0.82, "transform:translateX(%spx);opacity:1" % f(x0 + 22))
        tr.at(t_ring - 0.12, "transform:translateX(%spx);opacity:1" % f(x1 - 22))
        tr.at(t_ring, "transform:translateX(%spx);opacity:0" % f(x1))
        tr.at(t_ring + 0.05, "transform:translateX(%spx);opacity:0" % f(x0))
        scan = ' class="%s"' % tr.emit(doc)
    marked = (card + '<path d="M0 %sV%s" stroke="%s" stroke-width="1.3" opacity="0"%s/>' % (f(-CH / 2 + 27), f(CH / 2 - 2), ink, scan)
              + '<path d="%s" fill="none" stroke="%s" stroke-width="1.8" stroke-linecap="round" pathLength="1" stroke-dasharray="1 1.05"%s/>'
              % (pen_ring(box, 6), acc, once(t_ring, t_ring + 0.35, "stroke-dashoffset:1.03", "stroke-dashoffset:0"))
              + g("<g%s>%s</g>" % (once(t_ring + 0.35, t_stamp + 0.2, "transform:scale(1.22);opacity:0", "transform:scale(1);opacity:1", EXPO),
                                   stamp(doc, T)), transform=STAMP_AT))
    b2 = (header(2, BEATS[1]) + brackets(at, s2, T["lane"]) + "/>"
          + brackets(at, s2, acc, width=1.9) + once(t_ring, t_ring + 0.25, "opacity:0", "opacity:1") + "/>"
          + g(g(marked, transform="translate(%s %s) scale(%s)" % (at[0], at[1], s2)), cls=gate(t_card))
          + g("".join(doc.text(line, at[0], 262 + 18 * n, "sans", 13.5, dim, anchor="middle")[0]
                      for n, line in enumerate(FINDING)), cls=gate(6.1)))

    # ---- beat 3: the feedback, in the person's words
    t_say = 6.8
    ws, _ = words(doc, "“" + NOTES["readme"] + "”", 0, 84, "serif", 31, acc)
    say = []
    for i, w in enumerate(ws):
        t0 = t_say + 0.1 * i
        say.append("<g%s>%s</g>" % (once(t0, t0 + 0.45, "transform:translateY(8px);opacity:0", "transform:translateY(0px);opacity:1", EXPO), w))
    b3 = header(3, BEATS[2]) + "".join(say) + g(doc.text(REPEATS, 0, 126, "sans", 12.5, dim)[0], cls=gate(8.2))
    for n, kind in enumerate(("diff", "claim")):
        b3 += g(doc.text("“" + NOTES[kind] + "”", 0, 153 + 26 * n, "serif", 19, ink)[0], cls=gate(8.5 + 0.4 * n))

    for (bx, by, bs), body in zip(L["beats"], (b1, b2, b3)):
        o.append(g(body, transform="translate(%s %s) scale(%s)" % (bx, by, bs)))

    # ---- between and after the beats: the order, the way back, and what reaches the person
    for seg in L["fwd"]:
        o.append(arrow(seg, T["lane"], 1.5 * u, 6.5 * u))
    rx, ry, rs, ra = L["ret_label"]
    o.append(g(arrow(L["ret"], acc, 1.6 * u, 6.5 * u, cls="fl", dash="%s %s" % (f(1.5 * u), f(6.5 * u)))
               + doc.text(BACK_LABEL, rx, ry, "sansm", rs, acc, anchor=ra)[0], cls=gate(9.6)))
    doc.css.append("@keyframes fl{to{stroke-dashoffset:-%s}}" % f(8 * u))
    doc.motion.append(".fl{animation:fl 1.1s linear infinite}")
    px, py, ps, pa = L["passes"]
    label, pw = doc.text(PASSES, px, py, "sansm", ps, ink, anchor=pa)
    k = ps / 13.0
    tx = (px - pw - 14 * k) if pa == "end" else px + 9 * k
    if pa != "end":
        label = doc.text(PASSES, px + 24 * k, py, "sansm", ps, ink)[0]
    disc, mark = tick(T, 9)
    o.append(g(g(disc + mark + "/>", transform="translate(%s %s) scale(%s)" % (f(tx), f(py - 4.5 * k), f(k * 0.82, 3))) + label,
               cls=gate(10.3)))
    return "".join(o)


def explainer(T, L):
    doc = new_doc(L["W"], L["H"], "How the Council is meant to work", EXPLAINER_ALT)
    doc.pad = (2, 2, 2, 2)
    doc.body.append(explainer_scene(doc, T, L))
    return finish(doc)


def write(doc, name):
    path = os.path.join(ASSETS, name)
    os.makedirs(ASSETS, exist_ok=True)
    text = doc.render()
    # Two things must never reach the public art, not even by accident inside a coordinate: a figure the pages
    # no longer print, and a word they no longer use. svgkit.f keeps coordinates clear of the figure.
    for banned in ("71" + ".5", "over" + "r"):
        assert banned not in text.lower(), "%s: found %r in the output" % (name, banned)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("%-40s %6d bytes" % (os.path.relpath(path, ROOT), os.path.getsize(path)))


def main():
    for name, fg, bg, c in check_contrast():
        print("contrast %-5s %-6s on %-5s %5.2f:1" % (name, fg, bg, c))
    for name in ("dark", "light"):
        write(banner(THEMES[name], WIDE), "banner-%s.svg" % name)
        write(banner(THEMES[name], PHONE), "banner-%s-m.svg" % name)
        write(explainer(THEMES[name], X_WIDE), "explainer-%s.svg" % name)
        write(explainer(THEMES[name], X_PHONE), "explainer-%s-m.svg" % name)
    write(social(THEMES["dark"]), "banner-1280x640.svg")


if __name__ == "__main__":
    main()
