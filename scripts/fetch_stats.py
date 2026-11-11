#!/usr/bin/env python3
"""Fetch the account's public GitHub stats into .profile-build/stats.json.

Data source is the GraphQL API (same surface the profile page itself renders).
Authentication: the GH_TOKEN environment variable, falling back to the local
``gh auth token`` so the script can run unchanged in CI and on a dev machine.

Everything downstream (count_loc.py, render_profile.py) reads only this file,
so local previews match what the daily workflow will publish.

Usage:
    python3 scripts/fetch_stats.py [--user TeFuirnever] [--out .profile-build/stats.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import urllib.request
from pathlib import Path

GRAPHQL = "https://api.github.com/graphql"

MAIN_QUERY = """
query ($login: String!) {
  user(login: $login) {
    createdAt
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      privacy: PUBLIC
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
      totalCount
      nodes { name stargazerCount url }
    }
    followers { totalCount }
  }
}
"""

YEAR_QUERY = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
    }
  }
}
"""


def token() -> str:
    env = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if env:
        return env
    return subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    ).stdout.strip()


def gql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310
        GRAPHQL,
        data=body,
        headers={
            "Authorization": f"bearer {token()}",
            "Content-Type": "application/json",
            "User-Agent": "azhou-profile-stats",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        payload = json.load(response)
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


def total_commits(login: str, created_at: dt.datetime) -> int:
    """Sum yearly commit contributions since the account was created.

    contributionsCollection windows cap at one year, so ask per calendar year.
    """
    total = 0
    year = created_at.year
    now = dt.datetime.now(dt.timezone.utc)
    while year <= now.year:
        start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        end = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        data = gql(YEAR_QUERY, {"login": login, "from": start.isoformat(), "to": end.isoformat()})
        total += data["user"]["contributionsCollection"]["totalCommitContributions"]
        year += 1
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="TeFuirnever")
    parser.add_argument("--out", default=".profile-build/stats.json")
    args = parser.parse_args()

    data = gql(MAIN_QUERY, {"login": args.user})["user"]
    created = dt.datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))

    calendar = [
        {"date": day["date"], "count": day["contributionCount"]}
        for week in data["contributionsCollection"]["contributionCalendar"]["weeks"]
        for day in week["contributionDays"]
    ]
    repos = data["repositories"]["nodes"]

    stats = {
        "user": args.user,
        "created_at": data["createdAt"],
        "avatar_url": f"https://github.com/{args.user}.png?size=460",
        "followers": data["followers"]["totalCount"],
        "stars": sum(repo["stargazerCount"] for repo in repos),
        "repos": data["repositories"]["totalCount"],
        "commits_12mo": data["contributionsCollection"]["totalCommitContributions"],
        "commits_total": total_commits(args.user, created),
        "loc": 0,
        "repo_list": [{"name": repo["name"], "url": repo["url"]} for repo in repos],
        "calendar": calendar,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {out} — stars={stats['stars']} followers={stats['followers']} "
        f"repos={stats['repos']} commits_12mo={stats['commits_12mo']} "
        f"commits_total={stats['commits_total']} calendar_days={len(calendar)}"
    )


if __name__ == "__main__":
    main()
