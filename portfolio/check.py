#!/usr/bin/env python3
"""Check the portfolio page after Claude edited it, before it is proposed.

The page is public and goes live when the pull request is merged, so an edit
is only proposed when it stays inside these limits:

  - the design is untouched (everything above the content, and no new class
    names, inline styles, scripts, images or forms);
  - the HTML is still well formed and every project has its link in the index;
  - no existing project disappeared unless its repository did;
  - projects whose README did not change are byte for byte the same;
  - links only go to the owner's public repositories listed for this run.

Exit code 0 when the page passes, 1 with one line per problem when it does not.
"""

import argparse
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}
# Elements the page has no use for. None may be added.
UNWANTED = {
    "script", "iframe", "object", "embed", "form", "img", "video", "audio",
    "base", "svg", "canvas", "input", "button", "textarea", "select", "link",
    "meta", "style",
}
CONTENT_MARKER = '<div class="wrap">'
MAX_BYTES = 300_000

ARTICLE = re.compile(r"<article\b([^>]*)>(.*?)</article>", re.S)
NAV = re.compile(r'<nav\b[^>]*\bclass="[^"]*\bindex\b[^"]*"[^>]*>(.*?)</nav>', re.S)
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def attr(text, name):
    match = re.search(r'(?<![\w-])' + re.escape(name) + r'="([^"]*)"', text)
    return match.group(1) if match else None


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.tags = Counter()
        self.classes = set()
        self.links = []
        self.inline_styles = 0
        self.handlers = 0

    def _open(self, tag, attrs):
        self.tags[tag] += 1
        for name, value in attrs:
            if name == "class":
                self.classes.update((value or "").split())
            elif name == "style":
                self.inline_styles += 1
            elif name.startswith("on"):
                self.handlers += 1
            elif name == "href" and tag == "a":
                self.links.append(value or "")

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif len(self.errors) < 5:
            line = self.getpos()[0]
            inside = self.stack[-1] if self.stack else "nothing"
            self.errors.append(f"line {line}: </{tag}> closes while <{inside}> is open")

    def finish(self):
        self.close()
        if self.stack and len(self.errors) < 5:
            self.errors.append("never closed: " + ", ".join(f"<{t}>" for t in self.stack[-5:]))
        return self


def articles(text):
    """Project entries in page order: (id, repo, whole source of the entry)."""
    found = []
    for match in ARTICLE.finditer(text):
        head = match.group(1)
        if "project" not in (attr(head, "class") or "").split():
            continue
        found.append((attr(head, "id"), attr(head, "data-repo"), match.group(0)))
    return found


def index_targets(text):
    nav = NAV.search(text)
    if not nav:
        return None
    return [href[1:] for href in re.findall(r'href="([^"]*)"', nav.group(1)) if href.startswith("#")]


def check(before, after, manifest):
    problems = []
    owner = manifest["owner"]
    projects = manifest["projects"]
    by_repo = {p["repo"].lower(): p for p in projects}
    removed = {r.lower() for r in manifest.get("removed", [])}

    if len(after.encode("utf-8")) > MAX_BYTES:
        problems.append(f"the page grew past {MAX_BYTES} bytes")

    # Design: everything above the content is unchanged.
    if CONTENT_MARKER in before:
        if CONTENT_MARKER not in after:
            problems.append(f"the content wrapper {CONTENT_MARKER} is gone")
        elif before.split(CONTENT_MARKER, 1)[0] != after.split(CONTENT_MARKER, 1)[0]:
            problems.append("the part above the content (head, title, styles) was changed")

    was = Scan()
    was.feed(before)
    was.finish()
    now = Scan()
    now.feed(after)
    now.finish()

    if now.errors and not was.errors:
        problems.extend("HTML is not well formed, " + e for e in now.errors)
    for tag in sorted(UNWANTED):
        if now.tags[tag] > was.tags[tag]:
            problems.append(f"a <{tag}> element was added")
    if now.inline_styles > was.inline_styles:
        problems.append("an inline style attribute was added")
    if now.handlers > was.handlers:
        problems.append("an event handler attribute was added")
    new_classes = sorted(now.classes - was.classes)
    if new_classes:
        problems.append("class names the stylesheet does not have: " + ", ".join(new_classes))

    # Links: nothing new except the owner's public repositories of this run.
    public = {r for r, p in by_repo.items() if not p["private"]}
    homepages = {p["homepage"] for p in projects if p["homepage"] and not p["private"]}
    known = set(was.links)
    profile = f"https://github.com/{owner}".lower()
    for href in now.links:
        if href in known or href in homepages:
            continue
        if href.startswith("#") and SLUG.match(href[1:]):
            continue
        low = href.lower().rstrip("/")
        if low == profile:
            continue
        match = re.match(r"^https://github\.com/([^/?#]+/[^/?#]+)(?:/[^?#]*)?$", low)
        if match and match.group(1) in public:
            continue
        problems.append(f"link not allowed: {href}")

    old = articles(before)
    new = articles(after)

    ids = [a[0] for a in new]
    for ident, repo, _ in new:
        if not ident or not SLUG.match(ident):
            problems.append(f"a project entry has a missing or malformed id: {ident!r}")
        if not repo:
            problems.append(f"project entry #{ident} has no data-repo attribute")
        elif repo.lower() not in by_repo:
            problems.append(f"project entry #{ident} is for {repo}, which is not listed for this run")
    for ident, count in Counter(ids).items():
        if count > 1:
            problems.append(f"id {ident!r} is used by {count} project entries")
    repos_now = [a[1].lower() for a in new if a[1]]
    for repo, count in Counter(repos_now).items():
        if count > 1:
            problems.append(f"{repo} has {count} entries")

    targets = index_targets(after)
    if targets is None:
        if index_targets(before) is not None:
            problems.append("the project index (nav) is gone")
    elif targets != ids:
        problems.append(
            "the index and the project entries differ: index "
            + ", ".join(targets) + " / entries " + ", ".join(str(i) for i in ids)
        )

    # Nothing that was there may vanish, unless its repository did.
    new_by_id = {a[0]: a for a in new}
    new_by_repo = {a[1].lower(): a for a in new if a[1]}
    for ident, repo, source in old:
        key = repo.lower() if repo else None
        kept = new_by_repo.get(key) if key else new_by_id.get(ident)
        if key in removed:
            if kept:
                problems.append(f"{repo} is no longer listed but its entry is still on the page")
            continue
        if not kept:
            problems.append(f"the entry {repo or '#' + str(ident)} was removed")
            continue
        if key and by_repo.get(key, {}).get("status") == "unchanged" and kept[2] != source:
            problems.append(f"{repo} did not change, but its entry was edited")

    # A private repository is described, never linked.
    for ident, repo, source in new:
        project = by_repo.get((repo or "").lower())
        if project and project["private"] and re.search(r'href="https?://', source):
            problems.append(f"the entry for the private repository {repo} contains a link")

    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    with open(args.before, encoding="utf-8") as handle:
        before = handle.read()
    with open(args.after, encoding="utf-8") as handle:
        after = handle.read()
    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)

    if before == after:
        # Nothing to vet, except that an entry which had to go is still there.
        removed = {r.lower() for r in manifest.get("removed", [])}
        problems = [
            f"{repo} is no longer listed but its entry is still on the page"
            for _, repo, _ in articles(after)
            if repo and repo.lower() in removed
        ]
        if not problems:
            print("The page was not changed.")
    else:
        problems = check(before, after, manifest)
        if not problems:
            print("The edited page passed every check.")
    for problem in problems:
        print(f"::error::Portfolio check: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
