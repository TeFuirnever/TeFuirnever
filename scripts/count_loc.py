#!/usr/bin/env python3
"""Count total lines of code across the account's original public repos.

Shallow-clones every repo listed in ``stats.json``, counts code lines with a
pure-Python counter (no cloc dependency, same numbers everywhere), and writes
the total back into ``stats.json`` as ``loc``.

Counting rules — deliberately simple and documented:
- only files with a known code extension are counted (markup/data like
  Markdown, JSON, YAML, SVG is excluded);
- blank lines are excluded;
- comment-only lines are excluded (line comments and block comments).

Usage:
    python3 scripts/count_loc.py [--stats .profile-build/stats.json]
                                 [--workdir .profile-build/loc-work]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "out",
    "target", "__pycache__", "site-packages", ".next", "coverage", ".turbo",
    "Pods", "DerivedData", ".obsidian",
}

# extension → (language, line comments, block comment pairs)
CODE_LANGS: dict[str, tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]] = {
    ".py": ("Python", ("#",), (('"""', '"""'), ("'''", "'''"))),
    ".sh": ("Shell", ("#",), ()),
    ".bash": ("Shell", ("#",), ()),
    ".zsh": ("Shell", ("#",), ()),
    ".rb": ("Ruby", ("#",), ()),
    ".pl": ("Perl", ("#",), ()),
    ".lua": ("Lua", ("--",), ()),
    ".sql": ("SQL", ("--",), (("/*", "*/"),)),
    ".hs": ("Haskell", ("--",), ()),
    ".js": ("JavaScript", ("//",), (("/*", "*/"),)),
    ".jsx": ("JavaScript", ("//",), (("/*", "*/"),)),
    ".mjs": ("JavaScript", ("//",), (("/*", "*/"),)),
    ".cjs": ("JavaScript", ("//",), (("/*", "*/"),)),
    ".ts": ("TypeScript", ("//",), (("/*", "*/"),)),
    ".tsx": ("TypeScript", ("//",), (("/*", "*/"),)),
    ".java": ("Java", ("//",), (("/*", "*/"),)),
    ".c": ("C", ("//",), (("/*", "*/"),)),
    ".h": ("C", ("//",), (("/*", "*/"),)),
    ".cc": ("C++", ("//",), (("/*", "*/"),)),
    ".cpp": ("C++", ("//",), (("/*", "*/"),)),
    ".hpp": ("C++", ("//",), (("/*", "*/"),)),
    ".go": ("Go", ("//",), (("/*", "*/"),)),
    ".rs": ("Rust", ("//",), (("/*", "*/"),)),
    ".swift": ("Swift", ("//",), (("/*", "*/"),)),
    ".kt": ("Kotlin", ("//",), (("/*", "*/"),)),
    ".scala": ("Scala", ("//",), (("/*", "*/"),)),
    ".php": ("PHP", ("//", "#"), (("/*", "*/"),)),
    ".css": ("CSS", (), (("/*", "*/"),)),
    ".scss": ("SCSS", ("//",), (("/*", "*/"),)),
    ".sass": ("Sass", ("//",), ()),
    ".less": ("Less", ("//",), (("/*", "*/"),)),
    ".vue": ("Vue", ("//",), (("/*", "*/"),)),
    ".svelte": ("Svelte", ("//",), (("/*", "*/"),)),
    ".dart": ("Dart", ("//",), (("/*", "*/"),)),
    ".ex": ("Elixir", ("#",), ()),
    ".exs": ("Elixir", ("#",), ()),
    ".erl": ("Erlang", ("%",), ()),
    ".r": ("R", ("#",), ()),
    ".jl": ("Julia", ("#",), (("#=", "=#"),)),
    ".zig": ("Zig", ("//",), ()),
    ".html": ("HTML", (), (("<!--", "-->"),)),
    ".htm": ("HTML", (), (("<!--", "-->"),)),
    ".xml": ("XML", (), (("<!--", "-->"),)),
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "poetry.lock", "Gemfile.lock", "composer.lock", "go.sum",
}


def iter_code_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILENAMES or ".min." in path.name:
            continue
        if path.suffix.lower() in CODE_LANGS:
            yield path


def count_file(path: Path, line_comments: tuple[str, ...],
               blocks: tuple[tuple[str, str], ...]) -> int:
    code = 0
    open_block: str | None = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    for raw in text.splitlines():
        line = raw.strip()
        if open_block:
            if open_block in line:
                open_block = None
            continue
        if not line:
            continue
        started_block = False
        for opener, closer in blocks:
            if line.startswith(opener):
                if closer not in line[len(opener):]:
                    open_block = closer
                started_block = True
                break
        if started_block:
            continue
        if any(line.startswith(prefix) for prefix in line_comments):
            continue
        code += 1
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", default=".profile-build/stats.json")
    parser.add_argument("--workdir", default=".profile-build/loc-work")
    args = parser.parse_args()

    stats_path = Path(args.stats)
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for stale in workdir.glob(".tmp-*"):
        shutil.rmtree(stale, ignore_errors=True)

    failed: list[str] = []
    by_lang: dict[str, int] = {}
    total = 0
    for repo in stats["repo_list"]:
        name, url = repo["name"], repo["url"]
        target = workdir / name
        if not target.exists():
            # Clone into a temp dir and rename on success, so an interrupted
            # clone can never masquerade as a finished one on the next run.
            tmp = workdir / f".tmp-{name}"
            ok = False
            for attempt in range(1, 4):
                shutil.rmtree(tmp, ignore_errors=True)
                clone = subprocess.run(
                    ["git", "clone", "--depth", "1", "--quiet", url, str(tmp)],
                    capture_output=True, text=True,
                )
                if clone.returncode == 0:
                    tmp.rename(target)
                    ok = True
                    break
                print(f"{name}: clone attempt {attempt} failed ({clone.stderr.strip()})",
                      file=sys.stderr)
                time.sleep(3 * attempt)
            if not ok:
                failed.append(name)
                continue
        repo_total = 0
        for path in iter_code_files(target):
            lang, line_comments, blocks = CODE_LANGS[path.suffix.lower()]
            lines = count_file(path, line_comments, blocks)
            by_lang[lang] = by_lang.get(lang, 0) + lines
            repo_total += lines
        total += repo_total
        print(f"{name}: {repo_total:,}")

    stats["loc"] = total
    stats["loc_by_lang"] = dict(sorted(by_lang.items(), key=lambda kv: -kv[1]))
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"total LOC: {total:,}")
    if failed:
        # Never publish a silently-incomplete number; fail the run loudly.
        print(f"clone failed after retries: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
