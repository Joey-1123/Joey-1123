import os
import json
import hashlib
import datetime
import requests
from dateutil.relativedelta import relativedelta
from pathlib import Path

USERNAME = "Joey-1123"
BIRTHDAY = datetime.date(2005, 5, 1)
ASCII_ART_PATH = "ascii/logo.txt"
CACHE_PATH = "cache/loc_cache.json"
CONFIG_PATH = "config.json"
TARGET_ART_WIDTH = 38

GITHUB_GRAPHQL = "https://api.github.com/graphql"

HEADERS = {}
if os.environ.get("GH_TOKEN"):
    HEADERS["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
elif os.environ.get("ACCESS_TOKEN"):
    HEADERS["Authorization"] = f"token {os.environ['ACCESS_TOKEN']}"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def graphql_query(query, variables=None):
    resp = requests.post(
        GITHUB_GRAPHQL,
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
    )
    if resp.status_code != 200:
        raise Exception(f"GraphQL query failed: {resp.status_code} {resp.text}")
    return resp.json()


def get_user_stats():
    query = """
    query($login: String!) {
        user(login: $login) {
            name
            login
            followers { totalCount }
            following { totalCount }
            createdAt
        }
    }"""
    data = graphql_query(query, {"login": USERNAME})
    user = data["data"]["user"]
    return {
        "name": user["name"] or USERNAME,
        "login": user["login"],
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "created_at": user["createdAt"],
    }


def get_repo_stats():
    query = """
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
                totalCount
                edges {
                    node {
                        nameWithOwner
                        stargazers { totalCount }
                        defaultBranchRef {
                            target { ... on Commit { history { totalCount } } }
                        }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }"""

    repos = {"count": 0, "stars": 0, "nodes": []}
    cursor = None
    while True:
        data = graphql_query(query, {"login": USERNAME, "cursor": cursor})
        repos_data = data["data"]["user"]["repositories"]
        repos["count"] = repos_data["totalCount"]
        for edge in repos_data["edges"]:
            node = edge["node"]
            repos["stars"] += node["stargazers"]["totalCount"]
            commit_count = 0
            if node.get("defaultBranchRef") and node["defaultBranchRef"]["target"]:
                commit_count = node["defaultBranchRef"]["target"]["history"]["totalCount"]
            repos["nodes"].append({
                "name": node["nameWithOwner"],
                "commits": commit_count,
            })
        if repos_data["pageInfo"]["hasNextPage"]:
            cursor = repos_data["pageInfo"]["endCursor"]
        else:
            break
    return repos


def get_contrib_count():
    query = """
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
                totalCount
                pageInfo { endCursor hasNextPage }
            }
        }
    }"""
    data = graphql_query(query, {"login": USERNAME, "cursor": None})
    return data["data"]["user"]["repositories"]["totalCount"]


def get_loc_data(repo_nodes):
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)

    total_additions = 0
    total_deletions = 0

    for node in repo_nodes:
        name = node["name"]
        commits = node["commits"]
        if commits == 0:
            continue

        cached = cache.get(name, {})
        if cached.get("commits") == commits:
            total_additions += cached.get("additions", 0)
            total_deletions += cached.get("deletions", 0)
            continue

        additions, deletions = fetch_repo_loc(name)
        cache[name] = {
            "commits": commits,
            "additions": additions,
            "deletions": deletions,
        }
        total_additions += additions
        total_deletions += deletions
        print(f"  -> {name}: +{additions} / -{deletions}")

    os.makedirs("cache", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)

    return total_additions, total_deletions, total_additions - total_deletions


def fetch_repo_loc(repo_full_name):
    owner, repo = repo_full_name.split("/")
    query = """
    query($owner: String!, $repo: String!, $cursor: String) {
        repository(name: $repo, owner: $owner) {
            defaultBranchRef {
                target { ... on Commit { history(first: 100, after: $cursor) {
                    totalCount
                    edges { node { additions deletions } }
                    pageInfo { endCursor hasNextPage }
                }}}
            }
        }
    }"""

    additions = 0
    deletions = 0
    cursor = None

    while True:
        data = graphql_query(query, {"owner": owner, "repo": repo, "cursor": cursor})
        history = (
            data.get("data", {})
            .get("repository", {})
            .get("defaultBranchRef", {})
            .get("target", {})
            .get("history", {})
        )
        if not history or not history.get("edges"):
            break
        for edge in history["edges"]:
            if edge and edge.get("node"):
                additions += edge["node"].get("additions", 0)
                deletions += edge["node"].get("deletions", 0)
        if history["pageInfo"]["hasNextPage"]:
            cursor = history["pageInfo"]["endCursor"]
        else:
            break

    return additions, deletions


def calculate_age():
    today = datetime.date.today()
    diff = relativedelta(today, BIRTHDAY)
    parts = []
    if diff.years:
        parts.append(f"{diff.years}y")
    if diff.months:
        parts.append(f"{diff.months}m")
    if diff.days:
        parts.append(f"{diff.days}d")
    is_birthday = diff.months == 0 and diff.days == 0
    return " ".join(parts) if parts else "0d", is_birthday


def resize_ascii(art_lines, target_width):
    resized = []
    for line in art_lines:
        line = line.rstrip("\n").rstrip()
        if not line:
            resized.append(" " * target_width)
            continue
        if len(line) <= target_width:
            resized.append(line.ljust(target_width))
        else:
            step = len(line) / target_width
            new_line = ""
            for i in range(target_width):
                idx = min(int(i * step + step / 2), len(line) - 1)
                new_line += line[idx]
            resized.append(new_line)
    return resized


def read_ascii_art():
    with open(ASCII_ART_PATH) as f:
        lines = f.readlines()
    return resize_ascii(lines, TARGET_ART_WIDTH)


def generate_svg(ascii_lines, stats, theme):
    is_dark = theme == "dark"

    if is_dark:
        bg = "#0d1117"
        art_color = "#58a6ff"
        title_color = "#58a6ff"
        sep_color = "#30363d"
        key_color = "#8b949e"
        val_color = "#f0f6fc"
    else:
        bg = "#ffffff"
        art_color = "#0969da"
        title_color = "#0969da"
        sep_color = "#d0d7de"
        key_color = "#656d76"
        val_color = "#1f2328"

    font_size = 11
    line_height = font_size + 3
    char_width = 6.6
    art_height = len(ascii_lines) * line_height + 40
    art_width_px = TARGET_ART_WIDTH * char_width

    stats_lines = [
        ("Name", stats["name"]),
    ]

    age_str, is_birthday = stats["age"]
    age_display = f"{age_str}{'  🎂' if is_birthday else ''}"
    stats_lines.append(("Age", age_display))
    stats_lines.extend([
        ("Repos", str(stats["repos"])),
        ("Stars", str(stats["stars"])),
        ("LOC", stats["loc"]),
        ("Contributed", f"{stats['contributed']} repos"),
        ("Followers", str(stats["followers"])),
        ("Following", str(stats["following"])),
    ])

    max_key_len = max(len(k) for k, _ in stats_lines)
    max_val_len = max(len(v) for _, v in stats_lines)

    stats_x = int(art_width_px + 50)
    key_col_width = 16
    dot_width_px = 7

    top_line_y = 30
    svg_height = max(art_height, top_line_y + 50 + len(stats_lines) * (line_height + 3))
    svg_width = max(stats_x + key_col_width * char_width + max_val_len * char_width + 40, 780)

    lines_xml = ""
    for i, line in enumerate(ascii_lines):
        y = top_line_y + i * line_height
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        lines_xml += f'    <text class="art" x="30" y="{y}" xml:space="preserve">{escaped}</text>\n'

    stats_xml = f'    <text class="title" x="{stats_x}" y="{top_line_y}">shubham@joey</text>\n'
    stats_xml += f'    <text class="sep" x="{stats_x}" y="{top_line_y + 16}">{"─" * 42}</text>\n'

    stat_y = top_line_y + 40
    for key, val in stats_lines:
        dots_count = max(key_col_width - len(key) - 1, 1)
        dots_str = "." * dots_count
        stats_xml += f'    <text class="key" x="{stats_x}" y="{stat_y}">{key}{dots_str}</text>\n'
        stats_xml += f'    <text class="val" x="{stats_x + int(key_col_width * char_width) + 20}" y="{stat_y}">{val}</text>\n'
        stat_y += line_height + 3

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{int(svg_width)}" height="{int(svg_height)}" viewBox="0 0 {int(svg_width)} {int(svg_height)}">
  <defs>
    <style>
      .bg {{ fill: {bg}; }}
      .art {{ font-family: 'Courier New', Consolas, monospace; font-size: {font_size}px; fill: {art_color}; white-space: pre; }}
      .title {{ font-family: 'Courier New', Consolas, monospace; font-size: 15px; font-weight: bold; fill: {title_color}; }}
      .sep {{ font-family: 'Courier New', Consolas, monospace; font-size: 11px; fill: {sep_color}; }}
      .key {{ font-family: 'Courier New', Consolas, monospace; font-size: 13px; fill: {key_color}; white-space: pre; }}
      .val {{ font-family: 'Courier New', Consolas, monospace; font-size: 13px; font-weight: bold; fill: {val_color}; }}
    </style>
  </defs>
  <rect class="bg" width="100%" height="100%" rx="10" />
{lines_xml}{stats_xml}</svg>'''

    return svg


def format_loc(num):
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    return f"{num:,}"


def main():
    load_config()

    print("Fetching user info...")
    user = get_user_stats()

    print("Fetching repo stats...")
    repos = get_repo_stats()
    print(f"  -> {repos['count']} repos, {repos['stars']} stars")

    print("Fetching contribution count...")
    contributed = get_contrib_count()
    print(f"  -> {contributed} contributed repos")

    print("Calculating LOC...")
    additions, deletions, net_loc = get_loc_data(repos["nodes"])
    print(f"  -> +{additions:,} / -{deletions:,} = {format_loc(net_loc)} net")

    print("Calculating age...")
    age_str, is_birthday = calculate_age()

    print("Reading & resizing ASCII art...")
    ascii_lines = read_ascii_art()
    print(f"  -> {len(ascii_lines)} lines, {TARGET_ART_WIDTH} chars wide")

    stats = {
        "name": user["name"],
        "age": (age_str, is_birthday),
        "repos": repos["count"],
        "stars": repos["stars"],
        "loc": format_loc(net_loc),
        "contributed": contributed,
        "followers": user["followers"],
        "following": user["following"],
    }

    print("Generating SVGs...")
    for theme in ["light", "dark"]:
        svg = generate_svg(ascii_lines, stats, theme)
        filename = f"{theme}_mode.svg"
        with open(filename, "w") as f:
            f.write(svg)
        print(f"  -> {filename}")

    print("Done!")


if __name__ == "__main__":
    main()
