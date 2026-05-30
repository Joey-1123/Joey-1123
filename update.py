import os
import json
import datetime
import time
import requests
from dateutil.relativedelta import relativedelta
from lxml import etree

USERNAME = "Joey-1123"
BIRTHDAY = datetime.date(2005, 5, 1)
CACHE_PATH = "cache/loc_cache.json"

GITHUB_GRAPHQL = "https://api.github.com/graphql"

HEADERS = {}
if os.environ.get("GH_TOKEN"):
    HEADERS["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
elif os.environ.get("ACCESS_TOKEN"):
    HEADERS["Authorization"] = f"token {os.environ['ACCESS_TOKEN']}"


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


def get_total_commits(repo_nodes):
    return sum(node["commits"] for node in repo_nodes)


def fetch_repo_loc(repo_full_name):
    owner, repo = repo_full_name.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/stats/code_frequency"
    for attempt in range(3):
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 202:
            time.sleep(3)
            continue
        if resp.status_code != 200:
            return 0, 0
        additions = deletions = 0
        for week in resp.json():
            additions += week[1]
            deletions += week[2]
        return additions, deletions
    return 0, 0


def get_loc_data(repo_nodes):
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)

    total_additions = total_deletions = 0

    for i, node in enumerate(repo_nodes):
        name = node["name"]
        commits = node["commits"]
        if commits == 0:
            continue

        cached = cache.get(name, {})
        if cached.get("commits") == commits:
            total_additions += cached.get("additions", 0)
            total_deletions += cached.get("deletions", 0)
            continue

        if i > 0 and i % 5 == 0:
            time.sleep(1)

        additions, deletions = fetch_repo_loc(name)
        cache[name] = {"commits": commits, "additions": additions, "deletions": deletions}
        total_additions += additions
        total_deletions += deletions
        print(f"  -> {name}: +{additions:,} / -{deletions:,}")

    os.makedirs("cache", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)

    return total_additions, total_deletions, total_additions - total_deletions


def calculate_age():
    today = datetime.date.today()
    diff = relativedelta(today, BIRTHDAY)
    parts = []
    if diff.years:
        parts.append(f"{diff.years} year{'s' if diff.years != 1 else ''}")
    if diff.months:
        parts.append(f"{diff.months} month{'s' if diff.months != 1 else ''}")
    if diff.days:
        parts.append(f"{diff.days} day{'s' if diff.days != 1 else ''}")
    is_birthday = diff.months == 0 and diff.days == 0
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

    print("Fetching contribution count...")
    contributed = get_contrib_count()

    print("Counting commits...")
    total_commits = get_total_commits(repos["nodes"])

    print("Calculating LOC...")
    additions, deletions, net_loc = get_loc_data(repos["nodes"])
    print(f"  -> +{additions:,} / -{deletions:,} = {format_loc(net_loc)} net")

    print("Calculating age...")
    age_str, is_birthday = calculate_age()
    age_display = f"{age_str}{'  🎂' if is_birthday else ''}"

    stats = {
        "age_display": age_display,
        "repos": repos["count"],
        "stars": repos["stars"],
        "commits": total_commits,
        "contributed": contributed,
        "followers": user["followers"],
        "following": user["following"],
        "loc": format_loc(net_loc),
        "loc_add": additions,
        "loc_del": deletions,
    }

    print("Updating SVGs...")
    for theme in ["light", "dark"]:
        filename = f"{theme}_mode.svg"
        update_svg(filename, stats)
        print(f"  -> {filename} updated")

    print("Done!")


if __name__ == "__main__":
    main()
