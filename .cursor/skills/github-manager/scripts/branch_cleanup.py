#!/usr/bin/env python3
"""Clean merged local branches and report PR/remote/local-only status."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class Branch:
    name: str
    upstream: str


@dataclass
class Row:
    branch: str
    status: str
    pr: str = ""
    remote: str = ""
    notes: str = ""


def run(cmd: list[str], cwd: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"{cmd[0]} failed"
        raise RuntimeError(message)
    return proc


def git(cwd: str, args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd, check=check)


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def repo_root() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("not inside a Git repository")
    return proc.stdout.strip()


def ref_exists(cwd: str, ref: str) -> bool:
    return git(cwd, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).returncode == 0


def remote_exists(cwd: str, remote: str) -> bool:
    proc = git(cwd, ["remote"])
    return remote in {line.strip() for line in proc.stdout.splitlines()}


def commit_oid(cwd: str, ref: str) -> str:
    proc = git(cwd, ["rev-parse", "--verify", f"{ref}^{{commit}}"], check=True)
    return proc.stdout.strip()


def resolve_base(
    cwd: str,
    remote: str,
    explicit_base: str | None,
    *,
    allow_local_fallback: bool = True,
) -> tuple[str, str]:
    """Resolve the base once and return its immutable commit OID plus label."""
    if explicit_base:
        if not ref_exists(cwd, explicit_base):
            raise RuntimeError(f"base ref does not exist: {explicit_base}")
        return commit_oid(cwd, explicit_base), explicit_base

    remote_head = git(cwd, ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"])
    if remote_head.returncode == 0 and remote_head.stdout.strip():
        base = remote_head.stdout.strip()
        if ref_exists(cwd, base):
            return commit_oid(cwd, base), base

    candidates = [f"{remote}/main", f"{remote}/master"]
    if allow_local_fallback:
        candidates.extend(["main", "master"])
    for candidate in candidates:
        if ref_exists(cwd, candidate):
            return commit_oid(cwd, candidate), candidate

    raise RuntimeError(f"could not resolve a base branch from {remote}/HEAD, main, or master")


def refresh_default_base(cwd: str, remote: str, explicit_base: str | None, notes: list[str]) -> bool:
    """Refresh remote-tracking refs without moving any local branch.

    Local refs are shared by every linked worktree. Moving ``refs/heads/main``
    from a different worktree can leave the worktree that has ``main`` checked
    out with an index and files from the old commit. The cleanup helper therefore
    treats ``origin/main`` (or the remote's equivalent HEAD) as its comparison
    base and never pulls or writes a local branch ref.
    """
    if explicit_base:
        return True
    if not remote_exists(cwd, remote):
        notes.append(f"remote not found, skipped fetch: {remote}")
        return False

    remote_refspec = f"+refs/heads/*:refs/remotes/{remote}/*"
    fetch_proc = git(cwd, ["fetch", "--prune", "--no-tags", remote, remote_refspec])
    if fetch_proc.returncode != 0:
        notes.append(f"fetch failed: {first_line(fetch_proc.stderr) or first_line(fetch_proc.stdout)}")
        return False
    return True


def local_base_names(base_label: str, remote: str) -> set[str]:
    names = {"main", "master"}
    if base_label.startswith("refs/heads/"):
        names.add(base_label[len("refs/heads/"):])
    elif base_label.startswith(f"refs/remotes/{remote}/"):
        prefix = f"refs/remotes/{remote}/"
        names.add(base_label[len(prefix):])
    elif base_label.startswith(f"{remote}/"):
        prefix = f"{remote}/"
        names.add(base_label[len(prefix):])
    else:
        names.add(base_label)
    return names


def list_local_branches(cwd: str) -> list[Branch]:
    proc = git(
        cwd,
        ["for-each-ref", "--format=%(refname:short)%00%(upstream:short)", "refs/heads"],
        check=True,
    )
    branches: list[Branch] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\0")
        branches.append(Branch(name=parts[0], upstream=parts[1] if len(parts) > 1 else ""))
    return branches


def current_branch(cwd: str) -> str:
    proc = git(cwd, ["branch", "--show-current"])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def checked_out_branches(cwd: str) -> dict[str, str]:
    """Return every local branch checked out in this repository's worktrees."""
    proc = git(cwd, ["worktree", "list", "--porcelain"], check=True)
    locations: dict[str, str] = {}
    records = [record for record in proc.stdout.split("\n\n") if record.strip()]
    if not records:
        raise RuntimeError("git worktree inventory was empty or malformed")
    for record in records:
        fields = record.splitlines()
        for line in fields:
            if not (
                line.startswith("worktree ")
                or line.startswith("HEAD ")
                or line.startswith("branch refs/heads/")
                or line == "detached"
                or line == "bare"
                or line == "locked"
                or line.startswith("locked ")
                or line == "prunable"
                or line.startswith("prunable ")
            ):
                raise RuntimeError(
                    f"git worktree inventory contained an unknown field: {line}"
                )
        path_fields = [line[len("worktree "):] for line in fields if line.startswith("worktree ")]
        head_fields = [line[len("HEAD "):] for line in fields if line.startswith("HEAD ")]
        branch_fields = [
            line[len("branch refs/heads/"):]
            for line in fields
            if line.startswith("branch refs/heads/")
        ]
        detached = "detached" in fields
        bare = "bare" in fields
        if len(path_fields) != 1 or not path_fields[0]:
            raise RuntimeError("git worktree inventory contained an invalid path record")
        if not bare and (len(head_fields) != 1 or not head_fields[0]):
            raise RuntimeError("git worktree inventory contained a record without HEAD")
        if len(branch_fields) > 1 or (branch_fields and not branch_fields[0]):
            raise RuntimeError("git worktree inventory contained an invalid branch record")
        if not bare and bool(branch_fields) == detached:
            raise RuntimeError("git worktree inventory contained an ambiguous checkout state")
        if branch_fields:
            locations[branch_fields[0]] = path_fields[0]
    return locations


def is_ancestor(cwd: str, branch: str, base_ref: str) -> bool:
    branch_ref = f"refs/heads/{branch}"
    return git(cwd, ["merge-base", "--is-ancestor", branch_ref, base_ref]).returncode == 0


def matching_remote(cwd: str, remote: str, branch: str, upstream: str) -> str:
    if upstream:
        return upstream
    remote_ref = f"refs/remotes/{remote}/{branch}"
    if git(cwd, ["show-ref", "--verify", "--quiet", remote_ref]).returncode == 0:
        return f"{remote}/{branch}"
    return ""


class PrLookup:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.disabled_reason = ""
        self.cache: dict[str, tuple[dict[str, Any] | None, str]] = {}
        if shutil.which("gh") is None:
            self.disabled_reason = "gh is not installed"

    def lookup(self, branch: str) -> tuple[dict[str, Any] | None, str]:
        if self.disabled_reason:
            return None, self.disabled_reason
        if branch in self.cache:
            return self.cache[branch]

        proc = run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--limit",
                "10",
                "--json",
                "number,title,state,url,isDraft,updatedAt",
            ],
            cwd=self.cwd,
        )
        if proc.returncode != 0:
            reason = first_line(proc.stderr) or first_line(proc.stdout) or "gh pr list failed"
            self.disabled_reason = f"PR lookup unavailable: {reason}"
            result = (None, self.disabled_reason)
            self.cache[branch] = result
            return result

        try:
            prs = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            result = (None, "PR lookup unavailable: gh returned invalid JSON")
            self.cache[branch] = result
            return result

        if not prs:
            result = (None, "")
            self.cache[branch] = result
            return result

        def sort_key(pr: dict[str, Any]) -> tuple[int, str]:
            state_rank = {"OPEN": 0, "MERGED": 1, "CLOSED": 2}.get(str(pr.get("state", "")), 9)
            return state_rank, str(pr.get("updatedAt", ""))

        selected = sorted(prs, key=sort_key)[0]
        result = (selected, "")
        self.cache[branch] = result
        return result


def pr_cells(pr: dict[str, Any]) -> tuple[str, str, str]:
    state = str(pr.get("state", "unknown")).lower()
    if pr.get("isDraft") and state == "open":
        state = "draft open"
    number = pr.get("number")
    url = str(pr.get("url", ""))
    title = str(pr.get("title", ""))
    link = f"[#{number} {state}]({url})" if number and url else state
    return f"PR created ({state})", link, title


def clean_branch(cwd: str, branch: str) -> tuple[bool, str]:
    proc = git(cwd, ["branch", "-d", "--", branch])
    if proc.returncode == 0:
        return True, first_line(proc.stdout)
    return False, first_line(proc.stderr) or first_line(proc.stdout) or "git branch -d failed"


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def code_cell(value: str) -> str:
    escaped = value.replace("`", "\\`")
    return f"`{escaped}`"


def print_table(rows: list[Row]) -> None:
    print("| Branch | Status | PR | Remote | Notes |")
    print("|--------|--------|----|--------|-------|")
    for row in rows:
        print(
            "| "
            + " | ".join(
                [
                    code_cell(row.branch),
                    markdown_cell(row.status),
                    markdown_cell(row.pr),
                    markdown_cell(row.remote),
                    markdown_cell(row.notes),
                ]
            )
            + " |"
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean local branches merged into main/master and print a branch status table."
    )
    parser.add_argument("--base", help="Base ref to check for merged branches. Defaults to origin/HEAD, main, or master.")
    parser.add_argument("--remote", default="origin", help="Remote name used for fetch and remote-branch detection.")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--clean", action="store_true", help="Delete safely merged local branches with git branch -d.")
    mode.add_argument("--dry-run", action="store_true", help="Preview cleanup without deleting branches.")

    fetch = parser.add_mutually_exclusive_group()
    fetch.add_argument(
        "--fetch",
        dest="fetch",
        action="store_true",
        help="Refresh the default base before inspecting branches. This is the default.",
    )
    fetch.add_argument("--no-fetch", dest="fetch", action="store_false", help="Skip refreshing the default base.")
    parser.set_defaults(fetch=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    notes: list[str] = []

    try:
        cwd = repo_root()
        if args.fetch:
            refreshed = refresh_default_base(cwd, args.remote, args.base, notes)
            if args.clean and not refreshed:
                detail = notes[-1] if notes else "remote refresh failed"
                raise RuntimeError(
                    "refusing cleanup because the requested remote refresh failed; "
                    f"retry the fetch or explicitly use --no-fetch ({detail})"
                )

        base_commit, base_label = resolve_base(
            cwd,
            args.remote,
            args.base,
            allow_local_fallback=not args.fetch,
        )
        branches = list_local_branches(cwd)
        current = current_branch(cwd)
        checkout_locations = checked_out_branches(cwd)
        protected = local_base_names(base_label, args.remote)
        protected.update(checkout_locations)

        pr_lookup = PrLookup(cwd)
        clean = bool(args.clean)
        rows: list[Row] = []

        for branch in branches:
            branch_notes: list[str] = []
            checkout_path = checkout_locations.get(branch.name, "")
            if branch.name == current:
                branch_notes.append("current branch")
            elif checkout_path:
                branch_notes.append(f"checked out at {checkout_path}")

            branch_is_base = branch.name in local_base_names(base_label, args.remote)
            merged = is_ancestor(cwd, branch.name, base_commit)
            remote_ref = matching_remote(cwd, args.remote, branch.name, branch.upstream)

            if branch_is_base:
                rows.append(Row(branch.name, "base branch", remote=remote_ref, notes=", ".join(branch_notes)))
                continue

            if merged and checkout_path:
                rows.append(
                    Row(
                        branch.name,
                        "merged; kept (checked out in worktree)",
                        remote=remote_ref,
                        notes=", ".join(branch_notes),
                    )
                )
                continue

            if merged and branch.name not in protected:
                if clean:
                    latest_checkouts = checked_out_branches(cwd)
                    if branch.name in latest_checkouts:
                        rows.append(
                            Row(
                                branch.name,
                                "merged; kept (checked out in worktree)",
                                remote=remote_ref,
                                notes=f"checked out at {latest_checkouts[branch.name]}",
                            )
                        )
                        continue
                    deleted, message = clean_branch(cwd, branch.name)
                    if deleted:
                        rows.append(Row(branch.name, "merged and cleaned locally", remote=remote_ref, notes=message))
                    else:
                        rows.append(Row(branch.name, "merged; cleanup failed", remote=remote_ref, notes=message))
                else:
                    rows.append(Row(branch.name, "merged; would clean locally", remote=remote_ref, notes=", ".join(branch_notes)))
                continue

            pr, pr_error = pr_lookup.lookup(branch.name)
            if pr:
                status, link, title = pr_cells(pr)
                rows.append(Row(branch.name, status, pr=link, remote=remote_ref, notes=title))
            elif remote_ref:
                if pr_error:
                    branch_notes.append(pr_error)
                rows.append(Row(branch.name, "pushed to remote", remote=remote_ref, notes=", ".join(branch_notes)))
            else:
                if pr_error:
                    branch_notes.append(pr_error)
                rows.append(Row(branch.name, "local only", notes=", ".join(branch_notes)))

        print(f"Base: `{base_label}`")
        print(f"Mode: `{'clean' if clean else 'dry-run'}`")
        print()
        print_table(rows)

        if notes:
            print()
            print("Notes:")
            for note in notes:
                print(f"- {note}")
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
