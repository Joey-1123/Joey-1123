# Originally created by Joey-1123 (https://github.com/Joey-1123)
# Inspired by Andrew6rant (https://github.com/Andrew6rant/Andrew6rant)
# If you're reading this, this profile stats generator was made by Joey-1123.
# Please keep this credit if you use or modify this code.

import os
import json
import calendar
import datetime
import time
import xml.etree.ElementTree as etree
import requests

etree.register_namespace("", "http://www.w3.org/2000/svg")

USERNAME = "Joey-1123"
BIRTHDAY = datetime.date(2005, 5, 1)
CACHE_PATH = "cache/loc_cache.json"
CACHE_VERSION = 2
# fork repos that still count for stars/commits/LOC
INCLUDED_FORKS: set[str] = {"Joey-1123/FlickerX", "Joey-1123/Vibe-Trading"}
# kept as an alias for older callers
INCLUDED_REPOS: set[str] = INCLUDED_FORKS

GITHUB_GRAPHQL = "https://api.github.com/graphql"

HEADERS = {}
if os.environ.get("GH_TOKEN"):
    HEADERS["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
elif os.environ.get("ACCESS_TOKEN"):
    HEADERS["Authorization"] = f"token {os.environ['ACCESS_TOKEN']}"


def in_scope(node):
    return (not node["isFork"]) or (node["name"] in INCLUDED_FORKS)


def _retry_wait(resp, attempt, base=2):
    wait = base * (attempt + 1)
    try:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            wait = max(wait, int(float(retry_after)))
    except (ValueError, TypeError):
        pass
    return wait


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
        if resp.status_code in (429, 502, 503):
            last_err = Exception(f"GraphQL retryable: {resp.status_code}")
            time.sleep(_retry_wait(resp, attempt))
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
            if (not node["isFork"]) or (node["nameWithOwner"] in INCLUDED_FORKS):
                repos["stars"] += node["stargazers"]["totalCount"]
            commit_count = 0
            if node.get("defaultBranchRef") and node["defaultBranchRef"]["target"]:
                commit_count = node["defaultBranchRef"]["target"]["history"]["totalCount"]
            repos["nodes"].append({
                "name": node["nameWithOwner"],
                "commits": commit_count,
                "isFork": node["isFork"],
            })
        if repos_data["pageInfo"]["hasNextPage"]:
            cursor = repos_data["pageInfo"]["endCursor"]
        else:
            break
    return repos


def get_contributions():
    query = """
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                totalRepositoriesWithContributedCommits
                totalCommitContributions
                totalPullRequestContributions
                totalIssueContributions
            }
        }
    }"""
    data = graphql_query(query, {"login": USERNAME})
    contributions = data["data"]["user"]["contributionsCollection"]
    return {
        "contributed_repos": contributions["totalRepositoriesWithContributedCommits"],
        "commits_last_year": contributions["totalCommitContributions"],
        "prs": contributions["totalPullRequestContributions"],
        "issues": contributions["totalIssueContributions"],
    }


def get_accessible_repo_count():
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


# back-compat alias
get_contrib_count = get_accessible_repo_count


def _sleep_for_response(resp, attempt, base=3, cap=9):
    wait = min(base * (attempt + 1), cap)
    try:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            wait = max(wait, min(int(float(retry_after)), cap))
    except (ValueError, TypeError):
        pass
    time.sleep(wait)


def fetch_repo_loc(repo_full_name):
    """Repo-wide additions/deletions (all contributors). None when unavailable."""
    owner, repo = repo_full_name.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/code_frequency"
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(3)
            continue
        if resp.status_code in (202, 429, 502, 503):
            _sleep_for_response(resp, attempt)
            continue
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, list):
            return None
        additions = deletions = 0
        for week in data:
            if len(week) >= 3:
                additions += week[1]
                deletions += abs(week[2])
        return additions, deletions
    return None


def fetch_user_loc(repo_full_name, username=USERNAME):
    """Per-user additions/deletions. None when GitHub has not computed stats yet."""
    owner, repo = repo_full_name.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/contributors"
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(3)
            continue
        if resp.status_code in (202, 429, 502, 503):
            _sleep_for_response(resp, attempt, base=3, cap=6)
            continue
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, list):
            return None
        for contributor in data:
            author = (contributor.get("author") or {}).get("login", "")
            if author.lower() != username.lower():
                continue
            additions = deletions = 0
            for week in contributor.get("weeks", []):
                additions += week.get("a", 0)
                deletions += abs(week.get("d", 0))
            return additions, deletions
        return 0, 0
    return None


def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        print(f"  Warning: corrupt cache at {CACHE_PATH} ({e}); rebuilding")
        return {}
    if not isinstance(data, dict) or data.get("_version") != CACHE_VERSION:
        print(f"  Warning: stale cache at {CACHE_PATH}; rebuilding")
        return {}
    return data


def save_cache(cache):
    cache["_version"] = CACHE_VERSION
    directory = os.path.dirname(CACHE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, CACHE_PATH)


def get_loc_data(repo_nodes, use_cache=True, attribute_to_user=True):
    cache = load_cache() if use_cache else {}

    total_additions = total_deletions = 0
    user_add = user_del = 0
    fetched = attributed = 0
    failed = []

    eligible = [n for n in repo_nodes if n["commits"] > 0]

    for i, node in enumerate(eligible):
        name = node["name"]
        commits = node["commits"]

        cached = cache.get(name)
        if use_cache and cached and cached.get("commits") == commits and "additions" in cached:
            total_additions += cached.get("additions", 0)
            total_deletions += cached.get("deletions", 0)
            if attribute_to_user and "user_add" in cached:
                user_add += cached["user_add"]
                user_del += cached["user_del"]
                attributed += 1
            fetched += 1
            continue

        if i > 0 and i % 5 == 0:
            time.sleep(1)

        loc = fetch_repo_loc(name)
        if loc is None:
            failed.append(name)
            continue
        additions, deletions = loc

        entry = {"commits": commits, "additions": additions, "deletions": deletions}
        if attribute_to_user:
            user_loc = fetch_user_loc(name)
            if user_loc is not None:
                ua, ud = user_loc
                entry["user_add"] = ua
                entry["user_del"] = ud
                user_add += ua
                user_del += ud
                attributed += 1

        cache[name] = entry
        total_additions += additions
        total_deletions += deletions
        fetched += 1
        print(f"  -> {name}: +{additions:,} / -{deletions:,}")

    if use_cache:
        save_cache(cache)

    if failed:
        print(f"  Warning: LOC unavailable for {len(failed)} repo(s): {', '.join(failed)}")

    net = total_additions - total_deletions
    user_net = (
        user_add - user_del
        if attribute_to_user and fetched and attributed == fetched
        else None
    )
    return total_additions, total_deletions, net, (user_add, user_del, user_net)


def calculate_age(today=None):
    today = today or datetime.date.today()
    years = today.year - BIRTHDAY.year
    months = today.month - BIRTHDAY.month
    days = today.day - BIRTHDAY.day
    if days < 0:
        months -= 1
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month > 1 else today.year - 1
        days += calendar.monthrange(prev_year, prev_month)[1]
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
    set_text("follower_data", str(stats["followers"]))
    set_text("loc_data", stats["loc"])
    set_text("loc_add", f"{stats['loc_add']:,}")
    set_text("loc_del", f"{stats['loc_del']:,}")

    tree.write(filename, encoding="utf-8", xml_declaration=True)


def main():
    print("Fetching user info...")
    user = get_user_stats()

    print("Fetching repo stats...")
    repos = get_repo_stats()
    print(f"  -> {repos['count']} repos, {repos['stars']} stars")

    print("Fetching contributed repos...")
    try:
        contributions = get_contributions()
        contributed = contributions["contributed_repos"]
    except Exception as e:
        print(f"  Warning: contributionsCollection failed ({e}); using repo access count")
        contributions = None
        contributed = get_accessible_repo_count()

    own_nodes = [n for n in repos["nodes"] if in_scope(n)]

    print("Counting commits...")
    total_commits = sum(n["commits"] for n in own_nodes)

    print("Calculating LOC...")
    additions, deletions, repo_net, (user_add, user_del, user_net) = get_loc_data(own_nodes)
    if user_net is not None:
        net_loc, loc_add, loc_del, loc_scope = user_net, user_add, user_del, "you"
    else:
        net_loc, loc_add, loc_del, loc_scope = repo_net, additions, deletions, "repo-wide"
    print(f"  -> +{loc_add:,} / -{loc_del:,} = {format_loc(net_loc)} net ({loc_scope})")

    print("Calculating age...")
    age_str, is_birthday = calculate_age()
    age_display = f"{age_str}{'  Birthday!' if is_birthday else ''}"

    stats = {
        "age_display": age_display,
        "repos": repos["count"],
        "stars": repos["stars"],
        "commits": total_commits,
        "contributed": contributed,
        "followers": user["followers"],
        "following": user["following"],
        "loc": format_loc(net_loc),
        "loc_add": loc_add,
        "loc_del": loc_del,
    }

    print("Updating SVGs...")
    for theme in ["light", "dark"]:
        filename = f"{theme}_mode.svg"
        update_svg(filename, stats)
        print(f"  -> {filename} updated")

    print("Done!")


if __name__ == "__main__":
    main()
