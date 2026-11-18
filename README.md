# readme-autoupdate

A GitHub Actions workflow that runs once a week, goes over every repository you
own, has Claude compare each README with the code, and opens a pull request
wherever the README no longer describes the project.

## How it works

1. **Find repositories.** Lists the repositories your account owns, skipping
   forks, archived and empty repositories. On the weekly schedule only
   repositories pushed to in the last 8 days are considered, and of those every
   repository whose default branch is still at the commit reviewed last time is
   dropped, so unchanged projects cost nothing.
2. **Review each one.** For every remaining repository (three at a time),
   Claude Code edits the README only where it is wrong or incomplete. If there
   is no README, it writes one. How much Claude reads depends on what happened
   since the last review (see below).
3. **Propose the change.** If the README changed, the workflow pushes a single
   commit to a `readme-autoupdate` branch in that repository and opens a pull
   request describing what changed and why. Nothing is merged for you.
4. **Remember the commit.** The reviewed commit is recorded in the repository
   as the hidden ref `refs/readme-autoupdate/reviewed`. It is not a branch or a
   tag and does not show up on GitHub.

A proposal is not repeated: while the `readme-autoupdate` branch is based on the
current default-branch commit (PR still open, or closed by you), the repository
is skipped. After the default branch moves, the next run replaces the branch
with a fresh proposal.

### Keeping token use low

Almost all of the cost of a review is the files Claude reads, so the workflow
gives it as little to read as it can:

| Since the last review | What runs | What Claude reads |
| - | - | - |
| Nothing changed | No job, Claude is not started | Nothing |
| Only the README or dependency lock files changed (for example, you merged the proposal) | Claude is not started | Nothing |
| Code changed | Incremental review | The diff since the reviewed commit and the README; other files only if the diff is not enough. A diff over 60,000 characters is replaced by the list of changed files. |
| Never reviewed, an earlier proposal is still open, or `force` is set | Full review | The README and the code it depends on |

Each review prints its token count and cost in the job log and in the run
summary.

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
| `dry_run` | `false` | Show proposed diffs in the run summary; push nothing, open no PRs, and do not record the commit as reviewed. |
| `force` | `false` | Review the whole repository again even if nothing changed since the last review, for example after editing the prompts. |

Repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable | Default | Meaning |
| - | - | - |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model Claude Code uses. A smaller model is the biggest single cost lever: the same tokens cost about half on `claude-sonnet-5-5` and far less on `claude-haiku-5-5`, at some loss of care. |
| `CLAUDE_EFFORT` | `low` | How hard the model works (`low`, `medium`, `high`). Higher levels read and think more and cost more. |
| `EXCLUDE_REPOS` | empty | Comma-separated repositories to never touch. |

To opt a single repository out, add the topic `no-readme-autoupdate` to it.

To change the schedule, edit the `cron` line in
[`.github/workflows/readme-autoupdate.yml`](.github/workflows/readme-autoupdate.yml)
(default: Mondays 05:17 UTC). To change what Claude is asked to do, edit
[`prompt.md`](prompt.md) (the rules), [`prompt-full.md`](prompt-full.md) (what
to read in a full review) or [`prompt-incremental.md`](prompt-incremental.md)
(what to do with a diff).

## Safety

- Claude runs with file reading and searching plus edits to the one README
  file, and nothing else: no shell, no network tools, no MCP servers, and the
  target repository's own Claude settings and hooks are ignored.
- The step that runs Claude only has the Claude credential. `REPOS_TOKEN` is
  used by the surrounding steps and is never written into the checkout.
- Only the README is ever committed, and changes always arrive as a pull
  request you review.

## Portfolio auto-update

A second workflow,
[`portfolio-autoupdate.yml`](.github/workflows/portfolio-autoupdate.yml), keeps
a public portfolio page in step with the same repositories. It runs on Mondays
at 06:47 UTC, after the README check, and uses the same secrets.

1. **Find what changed.** Lists the repositories that may appear on the page
   and compares the current version of each README with the version the page
   was last checked against. If nothing changed, the run ends here: Claude is
   not started and nothing is spent.
2. **Let Claude update the page.** Claude Code gets a copy of each repository
   whose README changed, or that is new, and edits the one page: it corrects
   existing entries, adds an entry for a new project that is worth showing, and
   removes the entry of a repository that is gone. Entries of unchanged
   repositories are left alone.
3. **Check the edit.** [`portfolio/check.py`](portfolio/check.py) rejects the
   edit if it touches the design, adds scripts, images or links to other
   sites, drops a project, changes an entry whose README did not change, or
   links to a private repository.
4. **Propose the change.** The page is pushed to a `portfolio-autoupdate`
   branch in the portfolio repository and a pull request is opened. The page
   goes live only when you merge it.

The record of which README versions the page was checked against is the file
`.portfolio-sources.json` in the portfolio repository. It travels with the
proposal, so a proposal is not repeated: while the `portfolio-autoupdate`
branch holds the record for the current READMEs (pull request open, or closed
by you with the branch kept), the next runs do nothing. When Claude finds that
changed READMEs need no change on the page, only the record is pushed to that
branch and no pull request is opened.

Which repositories may appear: the ones you own that are not forks, archived
or empty, and that have a README. The page is public, so a private repository
is only described when you name it in `PORTFOLIO_PRIVATE_REPOS`, and it is
never linked. To keep a single repository off the page, add the topic
`no-portfolio` to it.

Manual run inputs:

| Input | Default | Meaning |
| - | - | - |
| `plan_only` | `false` | Only list what would be checked. Claude is not run. |
| `dry_run` | `false` | Show the proposed diff in the run summary; push nothing, open no PR. |
| `force` | `false` | Recheck every project, even if no README changed. |

Repository variables:

| Variable | Default | Meaning |
| - | - | - |
| `PORTFOLIO_REPO` | `<you>/portfolio-html` | Repository that holds the page. |
| `PORTFOLIO_PAGE` | `docs/index.html` | Path of the page in it. |
| `PORTFOLIO_PRIVATE_REPOS` | `readme-autoupdate` | Private repositories that may be described; `none` for none. |
| `PORTFOLIO_EXCLUDE_REPOS` | `test` | Repositories that never appear. |
| `PORTFOLIO_MAX_BUDGET_USD` | `3` | The most one run may spend on Claude. |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Shared with the README workflow. |

`REPOS_TOKEN` must be able to read your repositories and to push a branch and
open a pull request in the portfolio repository. Claude runs under the same
limits as in the README workflow: it can read and search files and edit the
one page, and the step that runs it only has the Claude credential. To change
what Claude is asked to do, edit [`portfolio/prompt.md`](portfolio/prompt.md).

## Notes

- Only repositories owned by your user account are covered, not organization
  repositories you created.
- If this repository is public, GitHub pauses scheduled workflows after 60 days
  without repository activity; re-enable it from the Actions tab.
- Each repository reviewed is one Claude Code run, billed to your API key or
  counted against your subscription; skipped repositories use no tokens.
- To make a repository start over with a full review, run the workflow by hand
  for it with `force` ticked.
