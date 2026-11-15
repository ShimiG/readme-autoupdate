#!/usr/bin/env python3
"""Decide which repositories the portfolio page has to be checked against.

Two commands, both pure functions of the JSON files they are given, so they
can be run and tested without GitHub:

  candidates  Pick the repositories that may appear on the portfolio.
  decide      Compare their READMEs with the ones the page was last checked
              against, and write the list of work for Claude.
"""

import argparse
import datetime
import hashlib
import json
import re
import sys

SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")
OPT_OUT_TOPIC = "no-portfolio"


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def names(text):
    """A comma or space separated list, lower-cased. "none" means empty."""
    return {n for n in re.split(r"[,\s]+", (text or "").lower()) if n and n != "none"}


def listed(repo, wanted):
    return repo["full_name"].lower() in wanted or repo["name"].lower() in wanted


def candidates(args):
    repos = load(args.repos, [])
    exclude = names(args.exclude) | {args.portfolio_repo.lower()}
    private_ok = names(args.private)
    out = []
    for repo in sorted(repos, key=lambda r: r["full_name"].lower()):
        if repo.get("fork") or repo.get("archived") or repo.get("disabled"):
            continue
        if not repo.get("size"):
            continue
        if OPT_OUT_TOPIC in (repo.get("topics") or []):
            continue
        if listed(repo, exclude):
            continue
        # The page is public. A private repository is only described on it
        # when the owner has named that repository.
        if repo.get("private") and not listed(repo, private_ok):
            continue
        if not SAFE_NAME.match(repo["name"]):
            print(f"::warning::Skipping {repo['full_name']}: unsupported name.", file=sys.stderr)
            continue
        spdx = (repo.get("license") or {}).get("spdx_id")
        out.append(
            {
                "repo": repo["full_name"],
                "name": repo["name"],
                "private": bool(repo.get("private")),
                "description": repo.get("description") or "",
                "language": repo.get("language") or "",
                "license": spdx if spdx and spdx != "NOASSERTION" else "",
                "topics": repo.get("topics") or [],
                "homepage": repo.get("homepage") or "",
                "default_branch": repo["default_branch"],
            }
        )
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


def fingerprint(candidate, readme):
    """Changes when something the page says about the project may have changed."""
    basis = json.dumps(
        [readme["sha"], candidate["description"], candidate["private"]],
        ensure_ascii=False,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def decide(args):
    cands = load(args.candidates, [])
    readmes = load(args.readmes, {})
    main_state = (load(args.state, {}) or {}).get("projects", {})
    pending = load(args.pending)
    pending_state = pending.get("projects", {}) if isinstance(pending, dict) else None
    force = args.force == "true"

    current = {}
    no_readme = []
    for cand in cands:
        readme = readmes.get(cand["repo"])
        if not readme:
            no_readme.append(cand["repo"])
            continue
        current[cand["repo"]] = fingerprint(cand, readme)

    if force:
        run, reason = True, "A full recheck was asked for."
    elif current == main_state:
        run, reason = False, "The page was already checked against the current READMEs."
    elif pending_state is not None and current == pending_state:
        run, reason = False, (
            "A proposal for the current READMEs already exists on the update branch "
            "(open, or closed by the owner)."
        )
    else:
        run, reason = True, "At least one README changed, or a repository was added or removed."

    projects = []
    for cand in cands:
        if cand["repo"] not in current:
            continue
        changed = force or current[cand["repo"]] != main_state.get(cand["repo"])
        entry = dict(cand)
        entry["status"] = "check" if changed else "unchanged"
        entry["readme"] = readmes[cand["repo"]]["path"]
        if changed:
            entry["source_dir"] = f"{args.sources}/{cand['name']}"
        projects.append(entry)
    removed = sorted(repo for repo in main_state if repo not in current)

    today = datetime.datetime.now(datetime.timezone.utc)
    manifest = {
        "today": today.strftime("%Y-%m-%d"),
        "page": args.page,
        "owner": args.portfolio_repo.split("/")[0],
        "projects": projects,
        "removed": removed,
    }
    with open(args.manifest, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    state = {
        "about": (
            "Written by the portfolio auto-update workflow. It records which README "
            "version of each repository the page was last checked against."
        ),
        "projects": dict(sorted(current.items())),
    }
    with open(args.new_state, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")

    to_check = [p["repo"] for p in projects if p["status"] == "check"]
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write("### Portfolio check\n\n")
            handle.write(f"{reason}\n\n")
            if run:
                for repo in to_check:
                    handle.write(f"- check `{repo}`\n")
                for repo in removed:
                    handle.write(f"- remove `{repo}` (no longer listed)\n")
                same = len(projects) - len(to_check)
                if same:
                    handle.write(f"- {same} unchanged, left alone\n")
            for repo in no_readme:
                handle.write(f"- `{repo}` has no README and is skipped\n")
            handle.write("\n")

    print(f"run={'true' if run else 'false'}")
    print(f"checks={len(to_check)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    cand = sub.add_parser("candidates")
    cand.add_argument("--repos", required=True)
    cand.add_argument("--portfolio-repo", required=True)
    cand.add_argument("--exclude", default="")
    cand.add_argument("--private", default="")
    cand.set_defaults(func=candidates)

    dec = sub.add_parser("decide")
    dec.add_argument("--candidates", required=True)
    dec.add_argument("--readmes", required=True)
    dec.add_argument("--state", required=True)
    dec.add_argument("--pending", required=True)
    dec.add_argument("--force", default="false")
    dec.add_argument("--page", required=True)
    dec.add_argument("--portfolio-repo", required=True)
    dec.add_argument("--sources", required=True)
    dec.add_argument("--manifest", required=True)
    dec.add_argument("--new-state", required=True)
    dec.add_argument("--summary", default="")
    dec.set_defaults(func=decide)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
