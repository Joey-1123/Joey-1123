# Originally created by Joey-1123 (https://github.com/Joey-1123)
# Inspired by Andrew6rant (https://github.com/Andrew6rant/Andrew6rant)
# If you're reading this, this profile stats generator was made by Joey-1123.
# Please keep this credit if you use or modify this code.

import argparse
import os
import json
import datetime
import time
import xml.etree.ElementTree as etree
import requests

etree.register_namespace("", "http://www.w3.org/2000/svg")

USERNAME = os.environ.get("PROFILE_USERNAME", "Joey-1123")
BIRTHDAY = datetime.date(2005, 5, 1)
CACHE_PATH = "cache/loc_cache.json"
# Scope: all non-fork owned repos are counted, plus these forks.
# (Previous comment claimed this was an allowlist; it is a fork-allowlist.)
INCLUDED_FORKS: set[str] = {"Joey-1123/FlickerX", "Joey-1123/Vibe-Trading"}
# Back-compat alias (deprecated, will be removed)
INCLUDED_REPOS: set[str] = INCLUDED_FORKS
# Repos to always skip (noisy mirrors, etc.)
EXCLUDED_REPOS: set[str] = set()


def in_scope(node) -> bool:
    name = node["name"]
    if name in EXCLUDED_REPOS:
        return False
    return (not node["isFork"]) or (name in INCLUDED_FORKS)

GITHUB_GRAPHQL = "https://api.github.com/graphql"

HEADERS = {}
if os.environ.get("GH_TOKEN"):
    HEADERS["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
elif os.environ.get("ACCESS_TOKEN"):
    HEADERS["Authorization"] = f"token {os.environ['ACCESS_TOKEN']}"


def graphql_query(query, variables=None, attempts=4):
    last_err = None
    for attempt in range(attempts):
        try:
            resp = requests.post(
                GITHUB_GRAPHQL,
                json={"query": query, "variables": variables or {}},
                headers=HEADERS,
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code in (502, 503, 429):
            wait = 2 * (attempt + 1)
            try:
                ra = resp.headers.get("Retry-After")
                if ra:
                    wait = max(wait, int(float(ra)))
            except (ValueError, TypeError):
                pass
            time.sleep(wait)
            last_err = Exception(f"GraphQL retryable: {resp.status_code}")
            continue
        if resp.status_code != 200:
            raise Exception(f"GraphQL query failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")
        return data
    raise Exception(f"GraphQL query failed after {attempts} attempts: {last_err}")


def get_user_stats():
    query = """
    query($login: String!) {
        user(login: $login) {
            name
            login
            followers { totalCount }
            following { totalCount }
        }
    }"""
    data = graphql_query(query, {"login": USERNAME})
    user = data["data"]["user"]
    return {
        "name": user["name"] or USERNAME,
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
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
                        isFork
                        stargazers { totalCount }
                        languages(first: 5, orderBy: {field: SIZE, direction: DESC}) {
                            edges { size node { name } }
                        }
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
        if repos["count"] == 0:
            repos["count"] = repos_data["totalCount"]
        for edge in repos_data["edges"]:
            node = edge["node"]
            stars = node["stargazers"]["totalCount"]
            commit_count = 0
            if node.get("defaultBranchRef") and node["defaultBranchRef"]["target"]:
                commit_count = node["defaultBranchRef"]["target"]["history"]["totalCount"]
            repos["nodes"].append({
                "name": node["nameWithOwner"],
                "commits": commit_count,
                "stars": stars,
                "isFork": node["isFork"],
                "languages": [
                    (e["node"]["name"], e["size"])
                    for e in (node.get("languages") or {}).get("edges", [])
                    if e.get("node") and e.get("size")
                ],
            })
        if repos_data["pageInfo"]["hasNextPage"]:
            cursor = repos_data["pageInfo"]["endCursor"]
        else:
            break
    # NOTE: repos["stars"] is the raw owned-total (incl. forks/excluded).
    # Callers must recompute stars over in_scope() nodes for display.
    repos["stars"] = sum(n["stars"] for n in repos["nodes"])
    return repos


def language_shares(nodes, top_n=4):
    """Size-weighted (name, percent) ranking across repos. Pure function."""
    totals: dict[str, int] = {}
    for n in nodes:
        for name, size in n.get("languages", []):
            totals[name] = totals.get(name, 0) + size
    grand = sum(totals.values())
    if grand <= 0:
        return []
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [(name, round(100 * size / grand)) for name, size in ranked]


def top_repos(nodes, top_n=5, max_name=24):
    """Top scoped repos by stars. Pure function. Names owner-stripped + truncated."""
    ranked = sorted(nodes, key=lambda n: n.get("stars", 0), reverse=True)[:top_n]
    out = []
    for n in ranked:
        full = n.get("name", "?")
        short = full.split("/", 1)[-1] if "/" in full else full
        if len(short) > max_name:
            short = short[: max_name - 1] + "…"
        langs = n.get("languages", [])
        out.append({"name": short, "stars": n.get("stars", 0),
                    "lang": langs[0][0] if langs else "—"})
    return out


def format_top_repo(i, repo):
    return f"{i}. {repo['name']} ★{repo['stars']} · {repo['lang']}"


def aggregate_languages(nodes, top_n=4):
    """Size-weighted top language names. Pure function (testable)."""
    return [name for name, _ in language_shares(nodes, top_n)]


def get_contributions():
    """User-authored activity (default: last year per GitHub API)."""
    query = """
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                totalCommitContributions
                totalPullRequestContributions
                totalIssueContributions
                totalRepositoriesWithContributedCommits
            }
            repositories(first: 1, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
                totalCount
            }
        }
    }"""
    data = graphql_query(query, {"login": USERNAME})
    user = data["data"]["user"]
    cc = user["contributionsCollection"]
    return {
        "commits_last_year": cc["totalCommitContributions"],
        "prs": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"],
        "contributed_repos": cc["totalRepositoriesWithContributedCommits"],
        "repos_with_access": user["repositories"]["totalCount"],
    }


def get_contrib_count():
    # Kept for back-compat. Prefer get_contributions()["contributed_repos"].
    query = """
    query($login: String!) {
        user(login: $login) {
            repositories(first: 100, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
                totalCount
            }
        }
    }"""
    data = graphql_query(query, {"login": USERNAME})
    return data["data"]["user"]["repositories"]["totalCount"]


def _sleep_for_response(resp, attempt):
    wait = 2 * (attempt + 1)
    try:
        ra = resp.headers.get("Retry-After")
        if ra:
            wait = max(wait, int(float(ra)))
    except (ValueError, TypeError):
        pass
    time.sleep(wait)


def fetch_repo_loc(repo_full_name):
    """Repo-wide additions/deletions (all contributors). See fetch_user_loc for per-user."""
    owner, repo = repo_full_name.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/code_frequency"
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code in (202, 429, 502, 503):
            _sleep_for_response(resp, attempt)
            continue
        if resp.status_code != 200:
            return 0, 0
        data = resp.json()
        if not isinstance(data, list):
            return 0, 0
        additions = deletions = 0
        for week in data:
            if len(week) >= 3:
                additions += week[1]
                deletions += abs(week[2])
        return additions, deletions
    return 0, 0


def fetch_user_loc(repo_full_name, username=USERNAME):
    """Per-user additions/deletions via /stats/contributors. Falls back to (None, None)."""
    owner, repo = repo_full_name.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/contributors"
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code in (202, 429, 502, 503):
            _sleep_for_response(resp, attempt)
            continue
        if resp.status_code != 200:
            return None, None
        try:
            data = resp.json()
        except ValueError:
            return None, None
        if not isinstance(data, list):
            return None, None
        for c in data:
            author = (c.get("author") or {}).get("login", "")
            if author.lower() == username.lower():
                adds = dels = 0
                for w in c.get("weeks", []):
                    adds += w.get("a", 0)
                    dels += w.get("d", 0)
                return adds, dels
        return 0, 0
    return None, None


def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError) as e:
        print(f"  Warning: corrupt cache at {CACHE_PATH} ({e}); rebuilding")
        return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, CACHE_PATH)


def get_loc_data(repo_nodes, use_cache=True, attribute_to_user=True):
    cache = load_cache() if use_cache else {}

    os.makedirs("cache", exist_ok=True)

    total_additions = total_deletions = 0
    user_add = user_del = 0
    user_attributed = False

    for i, node in enumerate(repo_nodes):
        name = node["name"]
        commits = node["commits"]
        if commits == 0:
            continue

        cached = cache.get(name, {})
        if use_cache and cached.get("commits") == commits and "additions" in cached:
            total_additions += cached.get("additions", 0)
            total_deletions += cached.get("deletions", 0)
            if "user_add" in cached:
                user_attributed = True
                user_add += cached.get("user_add", 0)
                user_del += cached.get("user_del", 0)
            continue

        if i > 0 and i % 5 == 0:
            time.sleep(1)

        additions, deletions = fetch_repo_loc(name)
        entry = {"commits": commits, "additions": additions, "deletions": deletions}
        if attribute_to_user:
            ua, ud = fetch_user_loc(name)
            if ua is not None:
                user_attributed = True
                user_add += ua
                user_del += ud
                entry["user_add"] = ua
                entry["user_del"] = ud
        cache[name] = entry
        total_additions += additions
        total_deletions += deletions
        print(f"  -> {name}: +{additions:,} / -{deletions:,}")

    if use_cache:
        save_cache(cache)

    net = total_additions - total_deletions
    user_net = (user_add - user_del) if user_attributed else None
    return total_additions, total_deletions, net, (user_add, user_del, user_net)


def calculate_age():
    today = datetime.date.today()
    years = today.year - BIRTHDAY.year
    months = today.month - BIRTHDAY.month
    days = today.day - BIRTHDAY.day
    if days < 0:
        months -= 1
        prev = today.month - 1 or 12
        y = today.year if prev != 12 else today.year - 1
        days += (datetime.date(y, prev + 1, 1) - datetime.date(y, prev, 1)).days
    if months < 0:
        years -= 1
        months += 12
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    is_birthday = months == 0 and days == 0
    return ", ".join(parts) if parts else "0 days", is_birthday


def format_loc(num):
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    return f"{num:,}"


def update_svg(filename, stats):
    tree = etree.parse(filename)
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}

    def set_text(elem_id, text):
        el = root.find(f".//svg:*[@id='{elem_id}']", ns)
        if el is not None:
            el.text = str(text)
        else:
            print(f"  Warning: element #{elem_id} not found in {filename}")

    set_text("age_data", stats["age_display"])
    set_text("repo_data", str(stats["repos"]))
    set_text("star_data", str(stats["stars"]))
    set_text("contrib_data", str(stats["contributed"]))
    set_text("commit_data", str(stats["commits"]))
    set_text("pr_data", str(stats.get("prs", "?")))
    set_text("issue_data", str(stats.get("issues", "?")))
    set_text("lang_data", str(stats.get("top_langs", "—")))
    for i in range(1, 6):
        rows = stats.get("top_repos", [])
        set_text(f"top{i}", rows[i - 1] if i <= len(rows) else "—")
    set_text("follower_data", str(stats["followers"]))
    set_text("loc_data", stats["loc"])
    set_text("loc_add", f"{stats['loc_add']:,}")
    set_text("loc_del", f"{stats['loc_del']:,}")

    tree.write(filename, encoding="utf-8", xml_declaration=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate profile stat SVGs")
    parser.add_argument("--dry-run", action="store_true", help="fetch and print, do not write SVGs")
    parser.add_argument("--no-cache", action="store_true", help="ignore and overwrite LOC cache")
    parser.add_argument("--no-user-loc", action="store_true", help="skip per-user LOC attribution")
    args = parser.parse_args(argv)

    if not HEADERS:
        print("  Warning: no GH_TOKEN/ACCESS_TOKEN; API rate limits will be low")

    print("Fetching user info...")
    user = get_user_stats()

    print("Fetching repo stats...")
    repos = get_repo_stats()

    print("Fetching user contributions...")
    try:
        contrib = get_contributions()
        contributed = contrib["contributed_repos"]
        print(f"  -> {contributed} contributed repos, "
              f"{contrib['commits_last_year']} commits (last year), "
              f"{contrib['prs']} PRs, {contrib['issues']} issues")
    except Exception as e:
        print(f"  Warning: contributionsCollection failed ({e}); falling back to repo access count")
        contributed = get_contrib_count()
        contrib = None

    scoped_nodes = [n for n in repos["nodes"] if in_scope(n)]
    scoped_stars = sum(n["stars"] for n in scoped_nodes)
    print(f"  -> {repos['count']} owned repos, {len(scoped_nodes)} in scope, {scoped_stars} stars (scoped)")

    print("Counting commits (default-branch lifetime, scoped repos)...")
    total_commits = sum(n["commits"] for n in scoped_nodes)

    print("Calculating LOC (repo-wide; per-user when available)...")
    additions, deletions, net_loc, (u_add, u_del, u_net) = get_loc_data(
        scoped_nodes,
        use_cache=not args.no_cache,
        attribute_to_user=not args.no_user_loc,
    )
    if u_net is not None:
        print(f"  -> repo +{additions:,} / -{deletions:,} = {format_loc(net_loc)} net; "
              f"you +{u_add:,} / -{u_del:,} = {format_loc(u_net)} net")
        disp_add, disp_del, disp_net = u_add, u_del, u_net
    else:
        print(f"  -> +{additions:,} / -{deletions:,} = {format_loc(net_loc)} net (repo-wide)")
        disp_add, disp_del, disp_net = additions, deletions, net_loc

    print("Aggregating top languages (scoped repos)...")
    shares = language_shares(scoped_nodes)
    lang_display = " · ".join(f"{n} {p}%" for n, p in shares) if shares else "—"
    print(f"  -> {lang_display}")

    print("Ranking top repos (scoped, by stars)...")
    top = top_repos(scoped_nodes)
    top_display = [format_top_repo(i, r) for i, r in enumerate(top, 1)]
    while len(top_display) < 5:
        top_display.append("—")
    for row in top_display:
        print(f"  -> {row}")

    print("Calculating age...")
    age_str, is_birthday = calculate_age()
    age_display = f"{age_str}{'  Birthday!' if is_birthday else ''}"

    stats = {
        "age_display": age_display,
        "repos": repos["count"],
        "stars": scoped_stars,
        "commits": total_commits,
        "contributed": contributed,
        "prs": contrib["prs"] if contrib else "?",
        "issues": contrib["issues"] if contrib else "?",
        "top_langs": lang_display,
        "top_repos": top_display,
        "followers": user["followers"],
        "following": user["following"],
        "loc": format_loc(disp_net),
        "loc_add": disp_add,
        "loc_del": disp_del,
    }

    if args.dry_run:
        print("Dry run; stats would be:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print("Done!")
        return

    print("Updating SVGs...")
    for theme in ["light", "dark"]:
        filename = f"{theme}_mode.svg"
        update_svg(filename, stats)
        print(f"  -> {filename} updated")

    print("Done!")


if __name__ == "__main__":
    main()
