#!/usr/bin/env python3
"""Render the live profile cards as deterministic SVGs.

Reads ``.profile-build/stats.json`` (written by the update-stats workflow) and
the cached avatar, then rewrites:

- ``assets/profile/card-neofetch.svg`` — neofetch-style terminal snapshot with
  the avatar rendered as coloured ASCII art beside live account stats.
- ``assets/profile/card-contributions.svg`` — the last-year contribution
  heatmap plus a few derived activity signals.
- the ``<!-- STATS-START -->`` badge block in ``README.md``.

Output is byte-stable for identical input, so the daily workflow only commits
when a number actually changed.

Usage:
    python3 scripts/render_profile.py [--build-dir .profile-build]
                                      [--assets-dir assets/profile]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

# --- house palette (keep in sync with assets/profile/card-*.svg) -------------
PEACH_A = "#FFF0E6"
PEACH_B = "#FFD8C3"
PEACH_EDGE = "#E8C6B1"
DOT = "#3F2414"
ORANGE = "#FA9439"
PEACH = "#FAA67C"
BROWN = "#3F2414"
BROWN_SOFT = "#9C4D22"
CREAM = "#FEF9EB"

MONO = "'SFMono-Regular', 'JetBrains Mono', Consolas, 'Liberation Mono', monospace"
SANS = "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif"

PORTRAIT_COLS = 56
PORTRAIT_ROWS = 28
CHAR_ADVANCE = 5.7
LINE_HEIGHT = 13.4
PORTRAIT_RAMP = " .:=+*#"

HEAT_LEVELS = ["#F3E7D3", "#FFD8C3", "#FAA67C", "#FA9439", "#9C4D22"]


def load_stats(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_k(value: int) -> str:
    if value >= 1000:
        text = f"{value / 1000:.1f}k"
        return text.replace(".0k", "k")
    return str(value)


# --- README badge block -----------------------------------------------------

def update_readme(stats: dict, readme_path: Path) -> None:
    """Rewrite the tracked STATS badge block in README.md."""
    profile = f"https://github.com/{stats['user']}"
    badges = "\n".join(
        [
            "<!-- STATS-START -->",
            f"[![Total Stars](https://img.shields.io/badge/Total%20Stars-{fmt_k(stats['stars'])}-FA9439?style=flat&logo=github&logoColor=white)]({profile})",
            f"[![Followers](https://img.shields.io/badge/Followers-{fmt_k(stats['followers'])}-3F2414?style=flat&logo=github&logoColor=white)]({profile}?tab=followers)",
            f"[![Original Repos](https://img.shields.io/badge/Original%20Repos-{stats['repos']}-FAA67C?style=flat&logo=github&logoColor=white)]({profile}?tab=repositories)",
            f"[![Commits](https://img.shields.io/badge/Commits-{fmt_k(stats['commits_total'])}-FA9439?style=flat&logo=github&logoColor=white)]({profile}?tab=overview)",
            f"[![Lines of Code](https://img.shields.io/badge/Lines%20of%20Code-{fmt_k(stats['loc'])}-3F2414?style=flat&logo=github&logoColor=white)]({profile}?tab=repositories)",
            "<!-- STATS-END -->",
        ]
    )
    content = readme_path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"<!-- STATS-START -->.*?<!-- STATS-END -->",
        badges,
        content,
        flags=re.DOTALL,
    )
    if count != 1:
        raise SystemExit(f"expected one stats block in {readme_path}, found {count}")
    readme_path.write_text(updated, encoding="utf-8")


# --- avatar → coloured ASCII -------------------------------------------------

def avatar_to_ascii(image: Image.Image) -> list[list[tuple[str, str]]]:
    """Return a PORTRAIT_ROWS × PORTRAIT_COLS grid of (char, colour) cells."""
    img = ImageOps.exif_transpose(image).convert("RGB")
    # Slight blur keeps flat-colour art from turning into noise when downsampled.
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    img = ImageEnhance.Color(img).enhance(1.12)

    # Flood-fill the flat background away from the corners, so it does not
    # drown the subject as mid-tone noise. Falls through gracefully on
    # full-bleed photos (nothing matches, nothing is removed).
    key = (255, 0, 255)
    w, h = img.size
    flooded = img.copy()
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(flooded, corner, key, thresh=30)

    # Downsample colours from the untouched image and the background-ness from
    # the flooded mask separately, so edge cells neither turn magenta nor
    # vanish. A cell is blank when over half of its area is background.
    samples = img.resize((PORTRAIT_COLS, PORTRAIT_ROWS), Image.Resampling.BOX)
    raw = samples.tobytes()
    pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]

    mask = Image.new("L", img.size)
    fraw = flooded.tobytes()
    mask.putdata([
        255 if (fraw[i] == 255 and fraw[i + 1] == 0 and fraw[i + 2] == 255) else 0
        for i in range(0, len(fraw), 3)
    ])
    mask_small = mask.resize((PORTRAIT_COLS, PORTRAIT_ROWS), Image.Resampling.BOX)
    bg = mask_small.tobytes()

    def luminance(px: tuple[int, int, int]) -> float:
        # Red-weighted luma: the warm palette (red cap, orange clothes) would
        # otherwise collapse into sparse dots under standard luma.
        r, g, b = px
        return (0.5 * r + 0.4 * g + 0.1 * b) / 255.0

    kept = [pixels[i] for i in range(len(pixels)) if bg[i] < 128]
    lum = [luminance(px) for px in kept] or [0.0, 1.0]
    lo, hi = min(lum), max(lum)
    span = (hi - lo) or 1.0

    grid: list[list[tuple[str, str]]] = []
    for row in range(PORTRAIT_ROWS):
        cells: list[tuple[str, str]] = []
        for col in range(PORTRAIT_COLS):
            i = row * PORTRAIT_COLS + col
            if bg[i] >= 128:
                cells.append((" ", "#000000"))
                continue
            px = pixels[i]
            norm = ((luminance(px) - lo) / span) ** 1.15
            char = PORTRAIT_RAMP[min(len(PORTRAIT_RAMP) - 1, int(norm * len(PORTRAIT_RAMP)))]
            cells.append((char, ascii_colour(px, norm)))
        grid.append(cells)
    return grid


def ascii_colour(px: tuple[int, int, int], norm: float) -> str:
    """Colour a cell from the source pixel.

    Near-black cells sink toward the terminal background so eyes and outlines
    read as holes; everything else keeps its hue with a slight lift.
    """
    r, g, b = px
    if norm < 0.16:
        # mix toward the dark terminal brown
        r = int(r * 0.5 + 0x3F * 0.5)
        g = int(g * 0.5 + 0x24 * 0.5)
        b = int(b * 0.5 + 0x14 * 0.5)
    else:
        r, g, b = (min(255, int(v * 1.06 + 8)) for v in px)
    return f"#{r:02X}{g:02X}{b:02X}"


# --- shared SVG frame -------------------------------------------------------

def frame_block(width: int, height: int, pill: str, desc: str, title: str) -> list[str]:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"  <title id=\"title\">{title}</title>",
        f"  <desc id=\"desc\">{desc}</desc>",
        "  <defs>",
        '    <linearGradient id="peach" x1="0" y1="0" x2="1" y2="1">',
        f'      <stop offset="0" stop-color="{PEACH_A}"/>',
        f'      <stop offset="1" stop-color="{PEACH_B}"/>',
        "    </linearGradient>",
        '    <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">',
        f'      <circle cx="2" cy="2" r="1.5" fill="{DOT}" opacity="0.08"/>',
        "    </pattern>",
        "  </defs>",
        f'  <rect x="8" y="8" width="{width - 16}" height="{height - 16}" rx="30" '
        f'fill="url(#peach)" stroke="{PEACH_EDGE}" stroke-width="2"/>',
        f'  <rect x="8" y="8" width="{width - 16}" height="{height - 16}" rx="30" fill="url(#dots)"/>',
    ]
    pill_width = 13.2 * len(pill) + 56
    out += [
        f'  <rect x="54" y="42" width="{pill_width:.0f}" height="34" rx="17" fill="{ORANGE}"/>',
        f'  <text x="{54 + pill_width / 2:.0f}" y="64" fill="{BROWN}" font-family="{SANS}" '
        f'font-size="13" font-weight="900" letter-spacing="1.8" text-anchor="middle">{pill}</text>',
    ]
    return out


def terminal_panel(x: int, y: int, width: int, height: int, label: str) -> list[str]:
    """Terminal chrome; closes its group so later elements use absolute coords."""
    return [
        f'  <g transform="translate({x} {y})">',
        f'    <rect x="0" y="0" width="{width}" height="{height}" rx="26" fill="{BROWN}" '
        f'stroke="{BROWN}" stroke-width="3"/>',
        f'    <circle cx="32" cy="30" r="6" fill="{ORANGE}"/>',
        f'    <circle cx="52" cy="30" r="6" fill="{PEACH}"/>',
        f'    <circle cx="72" cy="30" r="6" fill="{CREAM}"/>',
        f'    <text x="{width / 2:.0f}" y="35" fill="{PEACH}" font-family="{MONO}" '
        f'font-size="14" text-anchor="middle">{label}</text>',
        "  </g>",
    ]


# --- neofetch card ----------------------------------------------------------

def neofetch_rows(stats: dict) -> list[tuple[str, str]]:
    created = stats["created_at"][:7]
    uptime_years = dt.date.today().year - int(stats["created_at"][:4])
    commits = fmt_int(stats["commits_total"])
    return [
        ("OS", "GitHub Actions · ubuntu-latest"),
        ("Host", f"{stats['user']}/{stats['user']}"),
        ("Uptime", f"{uptime_years} years · since {created}"),
        ("Packages", f"{stats['repos']} original public repos"),
        ("Shell", "agent-skills × human judgment"),
        ("Motto", "proof over promises"),
        ("Stars", fmt_int(stats["stars"])),
        ("Followers", fmt_int(stats["followers"])),
        ("Commits", f"{commits} total · {fmt_int(stats['commits_12mo'])} (12mo)"),
        ("LOC", f"{fmt_int(stats['loc'])} lines of code"),
    ]


def render_neofetch(stats: dict, portrait: list[list[tuple[str, str]]]) -> str:
    width, height = 1280, 580
    out = frame_block(
        width,
        height,
        "SYSTEM SNAPSHOT · 系统快照",
        "Neofetch-style terminal card: the avatar as coloured ASCII art beside "
        "live GitHub stats, regenerated daily by GitHub Actions.",
        "Azhou neofetch system snapshot",
    )
    out += terminal_panel(54, 96, 1172, 452, "azhou@github: neofetch")

    # ASCII portrait, one <text> per cell keeps the grid aligned in any font.
    px0, py0 = 88, 156
    for row, cells in enumerate(portrait):
        for col, (char, colour) in enumerate(cells):
            if char == " ":
                continue
            x = px0 + col * CHAR_ADVANCE + CHAR_ADVANCE / 2
            y = py0 + row * LINE_HEIGHT
            out.append(
                f'    <text x="{x:.1f}" y="{y:.1f}" fill="{colour}" font-family="{MONO}" '
                f'font-size="9.5" text-anchor="middle" xml:space="preserve">{char}</text>'
            )

    # Info rows in classic neofetch key/value style.
    ix, iy = 480, 180
    out.append(
        f'    <text x="{ix}" y="{iy}" fill="{ORANGE}" font-family="{MONO}" '
        f'font-size="20" font-weight="700">azhou@github</text>'
    )
    out.append(
        f'    <text x="{ix}" y="{iy + 24}" fill="{PEACH}" font-family="{MONO}" '
        f'font-size="17" xml:space="preserve">{"─" * 24}</text>'
    )
    for i, (key, value) in enumerate(neofetch_rows(stats)):
        y = iy + 58 + i * 26
        out.append(
            f'    <text x="{ix}" y="{y}" fill="{PEACH}" font-family="{MONO}" '
            f'font-size="15" font-weight="700">{key.lower()}</text>'
        )
        out.append(
            f'    <text x="{ix + 148}" y="{y}" fill="{CREAM}" font-family="{MONO}" '
            f'font-size="15">: {value}</text>'
        )

    # Neofetch-style colour swatches.
    swatches = [ORANGE, PEACH, BROWN_SOFT, CREAM, PEACH_B, "#E0761B", "#7A3B1D", "#F4D9C8"]
    sy = iy + 58 + len(neofetch_rows(stats)) * 26 + 12
    for i, colour in enumerate(swatches):
        out.append(
            f'  <rect x="{ix + i * 58}" y="{sy - 14}" width="48" height="18" rx="5" fill="{colour}"/>'
        )
    out += ["</svg>", ""]
    return "\n".join(out)


# --- contribution heatmap card ---------------------------------------------

def heat_level(count: int, thresholds: list[int]) -> int:
    for i, limit in enumerate(thresholds):
        if count <= limit:
            return i
    return len(thresholds)


def calendar_grid(stats: dict) -> tuple[list[tuple[dt.date, int]], dt.date]:
    days = [(dt.date.fromisoformat(d["date"]), d["count"]) for d in stats["calendar"]]
    days.sort(key=lambda item: item[0])
    return days, days[0][0]


def streaks(days: list[tuple[dt.date, int]]) -> tuple[int, int]:
    """Return (longest streak, current streak) of active days."""
    counts = [count for _, count in days]
    longest = run = 0
    for count in counts:
        run = run + 1 if count > 0 else 0
        longest = max(longest, run)
    # A quiet today does not break the streak yet.
    if len(counts) >= 2 and counts[-1] == 0:
        counts = counts[:-1]
    current = 0
    for count in reversed(counts):
        if count == 0:
            break
        current += 1
    return longest, current


def render_contributions(stats: dict) -> str:
    days, first = calendar_grid(stats)
    total = sum(count for _, count in days)
    active = sum(1 for _, count in days if count > 0)
    longest, current = streaks(days)
    best_day, best_count = max(days, key=lambda item: item[1])

    counts = sorted(count for _, count in days if count > 0)
    if counts:
        t1 = counts[int(len(counts) * 0.25)] or 1
        t2 = counts[int(len(counts) * 0.50)] or t1 + 1
        t3 = counts[int(len(counts) * 0.75)] or t2 + 1
        thresholds = [0, t1, t2, t3]
    else:
        thresholds = [0, 1, 2, 3]

    width, height = 1280, 470
    out = frame_block(
        width,
        height,
        "CONTRIBUTION HEATMAP · 贡献热力图",
        "The last year of public contributions as an orange heatmap with "
        "activity signals, regenerated daily by GitHub Actions.",
        "Azhou contribution heatmap",
    )
    out += [
        f'  <rect x="54" y="96" width="1172" height="344" rx="26" fill="{CREAM}" '
        f'stroke="{BROWN}" stroke-width="3"/>',
        f'  <text x="94" y="152" fill="{BROWN}" font-family="{SANS}" font-size="30" '
        f'font-weight="900">{fmt_int(total)} contributions</text>',
        f'  <text x="386" y="152" fill="{BROWN_SOFT}" font-family="{SANS}" font-size="19" '
        f'font-weight="700">in the last 12 months · {days[0][0]} → {days[-1][0]}</text>',
    ]

    # GitHub-style grid: columns are weeks, rows are weekdays Sunday-first.
    cell, gap = 13, 4
    gx, gy = 122, 206
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    col_of: dict[dt.date, int] = {}
    for day, _ in days:
        col_of[day] = (day - first).days // 7

    seen_months: set[tuple[int, int]] = set()
    for day, _ in days:
        key = (day.year, day.month)
        if key in seen_months:
            continue
        seen_months.add(key)
        x = gx + col_of[day] * (cell + gap)
        out.append(
            f'  <text x="{x}" y="{gy - 12}" fill="{BROWN_SOFT}" font-family="{SANS}" '
            f'font-size="13" font-weight="700">{month_names[day.month - 1]}</text>'
        )

    for label, weekday in (("Mon", 1), ("Wed", 3), ("Fri", 5)):
        y = gy + weekday * (cell + gap) + cell - 2
        out.append(
            f'  <text x="86" y="{y}" fill="{BROWN_SOFT}" font-family="{SANS}" '
            f'font-size="12" text-anchor="end">{label}</text>'
        )

    for day, count in days:
        x = gx + col_of[day] * (cell + gap)
        # Rows are Sunday-first, matching GitHub's own graph.
        y = gy + ((day.weekday() + 1) % 7) * (cell + gap)
        level = heat_level(count, thresholds)
        out.append(
            f'  <rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3.5" '
            f'fill="{HEAT_LEVELS[level]}" stroke="{PEACH_EDGE}" stroke-width="0.8"/>'
        )

    # Derived activity chips.
    chips = [
        ("ACTIVE DAYS", f"{active}/{len(days)}"),
        ("LONGEST STREAK", f"{longest} days"),
        ("CURRENT STREAK", f"{current} days"),
        ("BEST DAY", f"{best_count} · {best_day}"),
    ]
    cy = 386
    cx = 94
    for label, value in chips:
        chip_w = 258
        out += [
            f'  <rect x="{cx}" y="{cy}" width="{chip_w}" height="42" rx="12" fill="{PEACH_B}"/>',
            f'  <text x="{cx + 16}" y="{cy + 18}" fill="{BROWN_SOFT}" font-family="{SANS}" '
            f'font-size="11" font-weight="900" letter-spacing="1.2">{label}</text>',
            f'  <text x="{cx + 16}" y="{cy + 35}" fill="{BROWN}" font-family="{SANS}" '
            f'font-size="16" font-weight="800">{value}</text>',
        ]
        cx += chip_w + 18

    # Legend.
    out.append(
        f'  <text x="1010" y="152" fill="{BROWN_SOFT}" font-family="{SANS}" '
        f'font-size="13" font-weight="700">Less</text>'
    )
    for i, colour in enumerate(HEAT_LEVELS):
        out.append(
            f'  <rect x="{1052 + i * 22}" y="139" width="15" height="15" rx="4" fill="{colour}" '
            f'stroke="{PEACH_EDGE}" stroke-width="0.8"/>'
        )
    out.append(
        f'  <text x="1178" y="152" fill="{BROWN_SOFT}" font-family="{SANS}" '
        f'font-size="13" font-weight="700">More</text>'
    )
    out += ["</svg>", ""]
    return "\n".join(out)


# --- entry point ------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", default=".profile-build")
    parser.add_argument("--assets-dir", default="assets/profile")
    parser.add_argument("--readme", default="README.md")
    args = parser.parse_args()

    build = Path(args.build_dir)
    assets = Path(args.assets_dir)
    stats = load_stats(build / "stats.json")

    avatar_path = build / "avatar.png"
    if not avatar_path.exists():
        urllib.request.urlretrieve(stats["avatar_url"], avatar_path)  # noqa: S310
    portrait = avatar_to_ascii(Image.open(avatar_path))

    (assets / "card-neofetch.svg").write_text(render_neofetch(stats, portrait), encoding="utf-8")
    (assets / "card-contributions.svg").write_text(render_contributions(stats), encoding="utf-8")
    update_readme(stats, Path(args.readme))
    print(f"wrote {assets / 'card-neofetch.svg'}")
    print(f"wrote {assets / 'card-contributions.svg'}")
    print(f"updated {args.readme}")


if __name__ == "__main__":
    main()
