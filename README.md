# readme-autoupdate

A GitHub Actions workflow that runs once a week, goes over every repository you
own, has Claude compare each README with the code, and opens a pull request
wherever the README no longer describes the project.

## How it works

1. **Find repositories.** Lists the repositories your account owns, skipping
   forks, archived and empty repositories. On the weekly schedule only
   repositories pushed to in the last 8 days are checked, so unchanged projects
   cost nothing.
2. **Review each one.** For every repository (three at a time), Claude Code
   reads the code and edits the README only where it is wrong or incomplete. If
   there is no README, it writes one.
3. **Propose the change.** If the README changed, the workflow pushes a single
   commit to a `readme-autoupdate` branch in that repository and opens a pull
   request describing what changed and why. Nothing is merged for you.

A proposal is not repeated: while the `readme-autoupdate` branch is based on the
current default-branch commit (PR still open, or closed by you), the repository
is skipped. After the default branch moves, the next run replaces the branch
with a fresh proposal.

## Setup

1. **Create a personal access token** the workflow can use on your repositories
   and save it as the `REPOS_TOKEN` secret of this repository
   (Settings → Secrets and variables → Actions).
   - Fine-grained token: Repository access **All repositories**; permissions
     **Contents: Read and write**, **Pull requests: Read and write**
     (Metadata: Read is added automatically).
   - Or a classic token with the `repo` scope.
2. **Add Claude credentials** as one of these secrets:
   - `ANTHROPIC_API_KEY`: an API key from the [Claude Console](https://platform.claude.com), or
   - `CLAUDE_CODE_OAUTH_TOKEN`: a Claude subscription token created with
     `claude setup-token`.
3. **Make sure the workflow is on the default branch.** GitHub only runs
   scheduled workflows from the default branch.

Then run it once by hand to cover every repository, not just recently active
ones: Actions → **README auto-update** → Run workflow, with `lookback_days` set
to `0`. Tick `dry_run` first if you want to see the proposed diffs in the run
summary without anything being pushed.

## Options

Manual run inputs:

| Input | Default | Meaning |
| - | - | - |
| `repos` | empty | Only these repositories (comma-separated `owner/name` or `name`). |
| `lookback_days` | `8` | Only repositories pushed to in the last N days; `0` checks all of them. |
| `dry_run` | `false` | Show proposed diffs in the run summary; push nothing, open no PRs. |

Repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable | Default | Meaning |
| - | - | - |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model Claude Code uses. |
| `EXCLUDE_REPOS` | empty | Comma-separated repositories to never touch. |

To opt a single repository out, add the topic `no-readme-autoupdate` to it.

To change the schedule, edit the `cron` line in
[`.github/workflows/readme-autoupdate.yml`](.github/workflows/readme-autoupdate.yml)
(default: Mondays 05:17 UTC). To change what Claude is asked to do, edit
[`prompt.md`](prompt.md).

## Safety

- Claude runs with file reading and searching plus edits to the one README
  file, and nothing else: no shell, no network tools, no MCP servers, and the
  target repository's own Claude settings and hooks are ignored.
- The step that runs Claude only has the Claude credential. `REPOS_TOKEN` is
  used by the surrounding steps and is never written into the checkout.
- Only the README is ever committed, and changes always arrive as a pull
  request you review.

## Notes

- Only repositories owned by your user account are covered, not organization
  repositories you created.
- If this repository is public, GitHub pauses scheduled workflows after 60 days
  without repository activity; re-enable it from the Actions tab.
- Each repository checked is one Claude Code run, billed to your API key or
  counted against your subscription; the cost of each run is printed in its log.
