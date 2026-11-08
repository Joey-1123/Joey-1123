# Port `main` fixes to `feat/profile-improvements`

`main` was patched directly. These changes still need to be reapplied on top of
`feat/profile-improvements` before that branch is merged back.

## update.py

- [ ] `INCLUDED_FORKS` + `in_scope()`; stars counted from scoped nodes only.
- [ ] `fetch_repo_loc` returns `None` on failure (never `(0, 0)`).
- [ ] `load_cache` tolerates corrupt JSON; `save_cache` writes atomically.
- [ ] `get_loc_data` does not cache failures and skips failed repos.
- [ ] Per-user LOC is used only when every fetched repo was attributed.
- [ ] `calculate_age` uses `calendar.monthrange` (feat still has the month-13 path).
- [ ] GraphQL retry helper kept in sync.
- [ ] `get_contributions` uses `totalRepositoriesWithContributedCommits`.

## Workflows

- [ ] `update.yml`: `actions/cache` for `cache/`.
- [ ] `update.yml`: `concurrency` group and `timeout-minutes`.
- [ ] `update.yml`: `GH_TOKEN` falls back to `github.token`.
- [ ] `ci.yml`: pytest workflow.

## Assets / docs

- [ ] Both SVGs: `viewBox`, `role="img"`, `<title>`, `<desc>`.
- [ ] Row label "Lines of Code" (not "…on GitHub").
- [ ] `LICENSE` (MIT), `requirements-dev.txt`.
- [ ] `tests/test_update.py` adapted to feat's 4-tuple `get_loc_data` API.
