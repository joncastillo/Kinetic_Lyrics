"""Copy the commits another clone has made since it last matched this repository.

Run from the repository the commits should land in:

    python automation/copy_commits.py ../kinetic_lyrics_pub --dry-run
    python automation/copy_commits.py ../kinetic_lyrics_pub
    python automation/copy_commits.py ../kinetic_lyrics_pub --since SOURCE_COMMIT

The two repositories need not share history, so commits are compared by their
patches (`git patch-id`), not their hashes. A reverse-patch check also recognises
changes already present through a combined commit. The source is walked back from its tip
to the first commit this repository already has, and only the commits after that
one are copied: older commits can differ on purpose, and are left alone.
If later edits prevent either check from recognising an integrated change, use
--since with the last fully integrated SOURCE commit. Commits
after that point are checked individually rather than stopping at a patch match.
A manually resolved integration commit can record the same boundary with an
Integrated-source-commit: <full source hash> line in its message.

Before copying, the entire range is tried in a temporary clone. A conflict there
leaves this checkout untouched. --dry-run performs this check too. Real content
conflicts need a manual merge; this script never chooses one side automatically.

Each copy is authored by this repository's git identity, keeps its original date,
and loses any Co-Authored-By or "Generated with Claude" line. Nothing is pushed.
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CREDIT_LINE = re.compile(r"^\s*co-authored-by:|^\W*generated with\b.*\bclaude\b", re.IGNORECASE)


class Refused(Exception):
    """The copy can't safely go ahead; the message says why."""


def git(*args: str, cwd: Path | None = None, stdin: str | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True, encoding="utf-8", errors="replace")
    if done.returncode:
        raise Refused(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def succeeds(*args: str) -> bool:
    return subprocess.run(["git", *args], capture_output=True).returncode == 0


def patch_ids(*revisions: str) -> dict[str, str]:
    """Map each commit in the revisions to its patch id. Empty commits have none."""
    log = subprocess.Popen(
        ["git", "log", "-p", "--no-merges", "--no-color", "--no-ext-diff", "--no-decorate", *revisions],
        stdout=subprocess.PIPE,
    )
    ids = subprocess.run(["git", "patch-id", "--stable"], stdin=log.stdout, capture_output=True, encoding="utf-8")
    log.stdout.close()
    if log.wait() or ids.returncode:
        raise Refused(f"could not read patches: {ids.stderr.strip()}")
    return {commit: patch for patch, commit in (line.split() for line in ids.stdout.splitlines())}


def already_applied(commit: str) -> bool:
    """The whole patch can be removed from the index, without actually removing it."""
    patch = subprocess.run(
        ["git", "show", "--format=", "--binary", "--no-ext-diff", "--no-color", commit],
        capture_output=True,
    )
    if patch.returncode:
        raise Refused(f"could not read patch for {commit}: {patch.stderr.decode(errors='replace').strip()}")
    return (
        bool(patch.stdout.strip())
        and subprocess.run(
            ["git", "apply", "--reverse", "--check", "--cached"],
            input=patch.stdout,
            capture_output=True,
        ).returncode
        == 0
    )


def commits_to_copy(tip: str, since: str | None = None) -> list[str]:
    """The source's commits after the newest one already here, oldest first."""
    if since is None:
        messages = git('log', '--format=%B', 'HEAD', f'^{tip}')
        for boundary in re.findall(r'^Integrated-source-commit: ([0-9a-f]{40})$', messages, re.MULTILINE):
            if succeeds('merge-base', '--is-ancestor', boundary, tip):
                since = boundary
                break
    if since is not None:
        since = git("rev-parse", "--verify", f"{since}^{{commit}}")
        if not succeeds("merge-base", "--is-ancestor", since, tip):
            raise Refused("--since must name a commit in the source branch's history")
        here = set(patch_ids("HEAD", f"^{tip}").values())
        theirs = patch_ids(tip, f"^{since}", "^HEAD")
        return [
            commit
            for commit in git("rev-list", "--no-merges", "--topo-order", "--reverse", tip, f"^{since}", "^HEAD").split()
            if commit in theirs and theirs[commit] not in here
        ]

    here = set(patch_ids("HEAD", f"^{tip}").values())
    theirs = patch_ids(tip, "^HEAD")
    newest_first = git("rev-list", "--no-merges", "--topo-order", tip, "^HEAD").split()

    missing = []
    for commit in newest_first:
        if theirs.get(commit) in here or (commit in theirs and already_applied(commit)):
            break
        if commit in theirs:  # an empty commit has nothing to copy
            missing.append(commit)
    else:
        if missing and not succeeds("merge-base", "HEAD", tip):
            raise Refused("the source shares no commit with this repository, so nothing marks where to start")
    return missing[::-1]


def describe(commit: str) -> str:
    return git("log", "-1", "--format=%h %ad %s", "--date=short", commit)[:110]


def set_credits(identity: str) -> None:
    """Make HEAD authored by the identity alone, leaving its date as it is."""
    message = git("log", "-1", "--format=%B")
    kept = "\n".join(line for line in message.split("\n") if not CREDIT_LINE.search(line)).strip()
    if git("log", "-1", "--format=%an <%ae>") != identity or kept != message:
        git("commit", "--amend", "--allow-empty", f"--author={identity}", "-F", "-", stdin=kept + "\n")


def is_redundant_pick() -> bool:
    """Whether the cherry-pick in progress changed nothing, as opposed to conflicting."""
    in_progress = succeeds("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD")
    return in_progress and not git("status", "--porcelain", "--untracked-files=no")


def preflight(commits: list[str], name: str, email: str) -> None:
    """Try the complete sequence without changing this checkout or its index."""
    root = git("rev-parse", "--show-toplevel")
    head = git("rev-parse", "HEAD")
    untracked = set(git("ls-files", "--others", "--exclude-standard", "-z").split("\0")) - {""}
    for commit in commits:
        added = git(
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--no-renames",
            "-r",
            "--diff-filter=A",
            "--name-only",
            "-z",
            commit,
        ).split("\0")
        for path in filter(None, added):
            if any(
                path == local or path.startswith(local + "/") or local.startswith(path + "/") for local in untracked
            ):
                raise Refused(f"incoming path {path} overlaps an untracked file; move or commit that file first")
    print("Checking for conflicts in a temporary checkout...", flush=True)
    with tempfile.TemporaryDirectory(prefix="kinetic-copy-") as folder:
        trial = Path(folder) / "repo"
        git("clone", "--quiet", "--shared", "--no-checkout", "--", root, str(trial))
        git("checkout", "--quiet", "--detach", head, cwd=trial)
        for commit in commits:
            picked = subprocess.run(
                [
                    "git",
                    "-c",
                    f"user.name={name}",
                    "-c",
                    f"user.email={email}",
                    "-c",
                    f"core.hooksPath={Path(folder) / 'no-hooks'}",
                    "cherry-pick",
                    "--no-gpg-sign",
                    commit,
                ],
                cwd=trial,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            if not picked.returncode:
                continue
            if (
                not git("status", "--porcelain", "--untracked-files=no", cwd=trial)
                and subprocess.run(
                    ["git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"],
                    cwd=trial,
                    capture_output=True,
                ).returncode
                == 0
            ):
                git("cherry-pick", "--skip", cwd=trial)
                continue
            conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=trial)
            detail = f"Conflicting files:\n{conflicts}" if conflicts else picked.stdout + picked.stderr
            raise Refused(
                f"preflight stopped at {describe(commit)}.\n{detail}\n"
                "No commits or working files were changed in this checkout.\n"
                "If this change was already integrated in a larger commit, rerun with "
                "--since <last-fully-integrated-source-commit>. Otherwise merge the conflicting change manually."
            )
    if git("rev-parse", "HEAD") != head or git("status", "--porcelain", "--untracked-files=no"):
        raise Refused("this checkout changed during the conflict check; rerun after saving those changes")


def copy(commits: list[str], identity: str) -> int:
    copied = 0
    for position, commit in enumerate(commits):
        print(f"copying {describe(commit)}")
        picked = subprocess.run(["git", "cherry-pick", commit], capture_output=True, encoding="utf-8", errors="replace")
        if picked.returncode and is_redundant_pick():
            print("  its change is already here, so it was skipped")
            git("cherry-pick", "--skip")
            continue
        if picked.returncode:
            print(f"\nStopped at {commit[:7]}, which doesn't apply cleanly:\n{picked.stdout}{picked.stderr}")
            print("Resolve it and run `git cherry-pick --continue`, or undo it with `git cherry-pick --abort`.")
            rest = commits[position + 1 :]
            if rest:
                print(f"Then copy the rest with: git cherry-pick {' '.join(c[:10] for c in rest)}")
            return 1
        set_credits(identity)
        copied += 1
    print(f"Copied {copied} commit(s). Nothing was pushed.")
    return 0


def run(source: Path, branch: str, dry_run: bool, since: str | None = None) -> int:
    if not source.is_dir():
        raise Refused(f"{source} is not a git repository")
    git("-C", str(source), "rev-parse", "--git-dir")
    source_private = git("-C", str(source), "ls-tree", "--name-only", branch, "--", ".private-repository")
    target_private = git("ls-tree", "--name-only", "HEAD", "--", ".private-repository")
    if source_private and not target_private:
        raise Refused("private changes cannot be imported into a public checkout; nothing was fetched")
    name, email = (git("config", key) for key in ("user.name", "user.email"))
    for operation in ("CHERRY_PICK_HEAD", "MERGE_HEAD", "REVERT_HEAD"):
        if succeeds("rev-parse", "-q", "--verify", operation):
            raise Refused("a cherry-pick, merge or revert is already in progress; finish or abort it first")
    for operation in ("rebase-merge", "rebase-apply", "sequencer"):
        if Path(git("rev-parse", "--git-path", operation)).exists():
            raise Refused("a rebase or sequenced operation is already in progress; finish or abort it first")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise Refused("this repository has uncommitted changes; commit or stash them first")

    git("fetch", str(source), branch)
    tip = git("rev-parse", "FETCH_HEAD")
    commits = commits_to_copy(tip, since)
    if not commits:
        print(f"Nothing to copy in the selected range ending at {describe(tip)}")
        return 0

    merges = git("rev-list", "--merges", "--count", f"{commits[0]}..{tip}")
    if merges != "0":
        print(f"Warning: {merges} merge commit(s) in that range are skipped; their own changes aren't copied.")
    if dry_run:
        print(f"Would copy {len(commits)} commit(s) as {name} <{email}>:")
        for commit in commits:
            print(f"  {describe(commit)}")
    preflight(commits, name, email)
    if dry_run:
        print("Conflict check passed. No commits or working files were changed in this checkout.")
        return 0
    return copy(commits, f"{name} <{email}>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy another clone's recent commits into this repository.")
    parser.add_argument("source", type=Path, help="folder of the repository to copy from")
    parser.add_argument("--branch", default="HEAD", help="branch to copy from (default: the source's current one)")
    parser.add_argument("--dry-run", action="store_true", help="list commits and check conflicts without copying them")
    parser.add_argument("--since", help="last fully integrated source commit; copy only changes after it")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(args.source.resolve(), args.branch, args.dry_run, args.since)
    except Refused as reason:
        print(f"Error: {reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
