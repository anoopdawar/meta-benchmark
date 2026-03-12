#!/usr/bin/env python3
"""
mini-git — a minimal but real implementation of git from scratch.

Architecture:
  ObjectStore   — content-addressable blob/tree/commit storage (.git/objects/)
  Index         — staging area (.git/index.json)
  Refs          — branch and HEAD management (.git/refs/, .git/HEAD)
  Repository    — ties everything together
  cmd_*         — porcelain commands (CLI entry points)
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import stat
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Object Store (plumbing)
# ---------------------------------------------------------------------------

def _sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _object_path(git_dir: Path, sha: str) -> Path:
    return git_dir / "objects" / sha[:2] / sha[2:]


def write_object(git_dir: Path, obj_type: str, content: bytes) -> str:
    """Serialize, compress, and store a git object. Returns its SHA1."""
    header = f"{obj_type} {len(content)}\x00".encode()
    store_data = header + content
    sha = _sha1_hex(store_data)
    path = _object_path(git_dir, sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(zlib.compress(store_data))
    return sha


def read_object(git_dir: Path, sha: str) -> tuple[str, bytes]:
    """Read and decompress a git object. Returns (type, content). Verifies SHA."""
    path = _object_path(git_dir, sha)
    if not path.exists():
        die(f"fatal: object {sha} not found")
    raw = zlib.decompress(path.read_bytes())
    actual_sha = _sha1_hex(raw)
    if actual_sha != sha:
        die(f"fatal: object {sha} is corrupt (actual SHA1: {actual_sha})")
    null = raw.index(b"\x00")
    header = raw[:null].decode()
    obj_type, _ = header.split(" ", 1)
    return obj_type, raw[null + 1:]


# ---------------------------------------------------------------------------
# Tree objects
# ---------------------------------------------------------------------------

@dataclass
class TreeEntry:
    mode: str   # e.g. "100644", "100755", "040000"
    name: str
    sha: str    # hex SHA1


def make_tree(git_dir: Path, entries: list[TreeEntry]) -> str:
    """Write a tree object and return its SHA1."""
    # Sort entries by name (git spec)
    sorted_entries = sorted(entries, key=lambda e: e.name + ("/" if e.mode == "040000" else ""))
    data = b""
    for e in sorted_entries:
        data += f"{e.mode} {e.name}\x00".encode()
        data += bytes.fromhex(e.sha)
    return write_object(git_dir, "tree", data)


def read_tree(git_dir: Path, sha: str) -> list[TreeEntry]:
    """Parse a tree object into a list of TreeEntry."""
    _, data = read_object(git_dir, sha)
    entries = []
    i = 0
    while i < len(data):
        null = data.index(b"\x00", i)
        header = data[i:null].decode()
        mode, name = header.split(" ", 1)
        sha_bytes = data[null + 1: null + 21]
        entries.append(TreeEntry(mode=mode, name=name, sha=sha_bytes.hex()))
        i = null + 21
    return entries


# ---------------------------------------------------------------------------
# Commit objects
# ---------------------------------------------------------------------------

@dataclass
class Commit:
    tree: str
    parent: Optional[str]
    author: str
    committer: str
    message: str
    timestamp: int = field(default_factory=lambda: int(time.time()))


def make_commit(git_dir: Path, commit: Commit) -> str:
    """Write a commit object and return its SHA1."""
    tz = "+0000"
    ts = commit.timestamp
    lines = [f"tree {commit.tree}"]
    if commit.parent:
        lines.append(f"parent {commit.parent}")
    lines.append(f"author {commit.author} {ts} {tz}")
    lines.append(f"committer {commit.committer} {ts} {tz}")
    lines.append("")
    lines.append(commit.message)
    data = "\n".join(lines).encode()
    return write_object(git_dir, "commit", data)


def read_commit(git_dir: Path, sha: str) -> Commit:
    """Parse a commit object."""
    _, data = read_object(git_dir, sha)
    text = data.decode(errors="replace")
    # Split header from message
    header_part, _, message = text.partition("\n\n")
    fields: dict[str, str] = {}
    parent = None
    for line in header_part.splitlines():
        if line.startswith("tree "):
            fields["tree"] = line[5:]
        elif line.startswith("parent "):
            parent = line[7:]
        elif line.startswith("author "):
            fields["author"] = line[7:]
        elif line.startswith("committer "):
            fields["committer"] = line[10:]
    return Commit(
        tree=fields.get("tree", ""),
        parent=parent,
        author=fields.get("author", ""),
        committer=fields.get("committer", ""),
        message=message.rstrip("\n"),
    )


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------

def _git_dir(repo_root: Path) -> Path:
    return repo_root / ".git"


def _head_path(git_dir: Path) -> Path:
    return git_dir / "HEAD"


def read_head(git_dir: Path) -> tuple[str, Optional[str]]:
    """Return (ref_or_sha, symbolic_ref). symbolic_ref is None for detached HEAD."""
    head = _head_path(git_dir).read_text().strip()
    if head.startswith("ref: "):
        ref = head[5:]
        ref_path = git_dir / ref
        sha = ref_path.read_text().strip() if ref_path.exists() else None
        return sha, ref
    return head, None  # detached HEAD


def current_branch(git_dir: Path) -> Optional[str]:
    """Return the current branch name, or None if detached HEAD."""
    head = _head_path(git_dir).read_text().strip()
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return None


def resolve_ref(git_dir: Path, name: str) -> Optional[str]:
    """Resolve a branch name or SHA to a full SHA1. Returns None if not found."""
    # Direct SHA (40 hex chars or abbreviated)
    if len(name) == 40 and all(c in "0123456789abcdef" for c in name):
        return name
    # Branch ref
    for ref_path in [
        git_dir / "refs" / "heads" / name,
        git_dir / "refs" / "remotes" / name,
    ]:
        if ref_path.exists():
            return ref_path.read_text().strip()
    # HEAD
    if name == "HEAD":
        sha, _ = read_head(git_dir)
        return sha
    # Abbreviated SHA — search objects
    if len(name) >= 4:
        objects_dir = git_dir / "objects"
        prefix = name[:2]
        rest = name[2:]
        obj_dir = objects_dir / prefix
        if obj_dir.exists():
            matches = [f.name for f in obj_dir.iterdir() if f.name.startswith(rest)]
            if len(matches) == 1:
                return prefix + matches[0]
    return None


def update_ref(git_dir: Path, ref: str, sha: str) -> None:
    """Write a ref file (e.g. refs/heads/main)."""
    ref_path = git_dir / ref
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(sha + "\n")


def advance_head(git_dir: Path, sha: str) -> None:
    """Advance HEAD (or the branch it points to) to sha."""
    head = _head_path(git_dir).read_text().strip()
    if head.startswith("ref: "):
        update_ref(git_dir, head[5:], sha)
    else:
        _head_path(git_dir).write_text(sha + "\n")


def list_branches(git_dir: Path) -> list[str]:
    heads_dir = git_dir / "refs" / "heads"
    if not heads_dir.exists():
        return []
    return sorted(p.name for p in heads_dir.iterdir() if p.is_file())


# ---------------------------------------------------------------------------
# Index (staging area)
# ---------------------------------------------------------------------------

def _index_path(git_dir: Path) -> Path:
    return git_dir / "index.json"


def read_index(git_dir: Path) -> dict[str, str]:
    """Return {relative_path: sha1} for all staged files."""
    p = _index_path(git_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def write_index(git_dir: Path, index: dict[str, str]) -> None:
    _index_path(git_dir).write_text(json.dumps(index, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Working tree utilities
# ---------------------------------------------------------------------------

def find_repo_root(start: Path) -> Optional[Path]:
    """Walk up from start looking for a .git directory."""
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _is_ignored(repo_root: Path, rel_path: str) -> bool:
    """Very basic .gitignore support."""
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return False
    patterns = gitignore.read_text().splitlines()
    name = Path(rel_path).name
    parts = rel_path.split("/")
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern == name or pattern == rel_path:
            return True
        if pattern.endswith("/") and (pattern.rstrip("/") in parts[:-1]):
            return True
        # Simple glob: *.ext
        if pattern.startswith("*.") and name.endswith(pattern[1:]):
            return True
    return False


def _collect_files(repo_root: Path, path: Path) -> list[str]:
    """Collect all files under path relative to repo_root, respecting .gitignore."""
    files = []
    if path.is_file():
        rel = path.relative_to(repo_root).as_posix()
        if not rel.startswith(".git"):
            files.append(rel)
    elif path.is_dir():
        for entry in sorted(path.rglob("*")):
            if entry.is_file():
                rel = entry.relative_to(repo_root).as_posix()
                if rel.startswith(".git/") or rel == ".git":
                    continue
                if not _is_ignored(repo_root, rel):
                    files.append(rel)
    return files


def _file_mode(path: Path) -> str:
    """Return git file mode string."""
    if path.is_symlink():
        return "120000"
    s = path.stat()
    if s.st_mode & stat.S_IXUSR:
        return "100755"
    return "100644"


# ---------------------------------------------------------------------------
# Tree ↔ working tree
# ---------------------------------------------------------------------------

def build_tree_from_index(git_dir: Path, repo_root: Path, index: dict[str, str]) -> str:
    """Build a nested tree structure from the flat index and write objects."""
    # Group by top-level directory
    return _build_tree_recursive(git_dir, repo_root, index, "")


def _build_tree_recursive(git_dir: Path, repo_root: Path, index: dict[str, str], prefix: str) -> str:
    """Recursively build tree objects."""
    entries: list[TreeEntry] = []
    # Collect direct children and subdirs
    direct_files: dict[str, str] = {}  # name -> sha
    subdirs: dict[str, dict[str, str]] = {}  # dirname -> {rel_name: sha}

    for rel_path, sha in index.items():
        if prefix:
            if not rel_path.startswith(prefix + "/"):
                continue
            rest = rel_path[len(prefix) + 1:]
        else:
            rest = rel_path

        if "/" in rest:
            top = rest.split("/", 1)[0]
            if top not in subdirs:
                subdirs[top] = {}
            # full path for recursion
            full_prefix = (prefix + "/" + top) if prefix else top
            subdirs[top][rel_path] = sha
        else:
            direct_files[rest] = sha

    # Add file entries
    for name, sha in direct_files.items():
        full_path = repo_root / ((prefix + "/" + name) if prefix else name)
        mode = _file_mode(full_path) if full_path.exists() else "100644"
        entries.append(TreeEntry(mode=mode, name=name, sha=sha))

    # Recurse into subdirs
    for dirname, _ in subdirs.items():
        sub_prefix = (prefix + "/" + dirname) if prefix else dirname
        sub_index = {k: v for k, v in index.items() if k.startswith(sub_prefix + "/")}
        sub_sha = _build_tree_recursive(git_dir, repo_root, sub_index, sub_prefix)
        entries.append(TreeEntry(mode="040000", name=dirname, sha=sub_sha))

    return make_tree(git_dir, entries)


def restore_tree(git_dir: Path, repo_root: Path, tree_sha: str, prefix: str = "") -> None:
    """Write a tree's contents to the working tree."""
    entries = read_tree(git_dir, tree_sha)
    for e in entries:
        rel_path = (prefix + "/" + e.name) if prefix else e.name
        target = repo_root / rel_path
        if e.mode == "040000":
            target.mkdir(parents=True, exist_ok=True)
            restore_tree(git_dir, repo_root, e.sha, rel_path)
        else:
            _, content = read_object(git_dir, e.sha)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if e.mode == "100755":
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


def tree_to_flat_index(git_dir: Path, tree_sha: str, prefix: str = "") -> dict[str, str]:
    """Flatten a tree into {rel_path: sha} dict."""
    result = {}
    entries = read_tree(git_dir, tree_sha)
    for e in entries:
        rel = (prefix + "/" + e.name) if prefix else e.name
        if e.mode == "040000":
            result.update(tree_to_flat_index(git_dir, e.sha, rel))
        else:
            result[rel] = e.sha
    return result


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_config(git_dir: Path) -> dict:
    config_path = git_dir / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {"user": {"name": os.environ.get("GIT_AUTHOR_NAME", "Author"),
                     "email": os.environ.get("GIT_AUTHOR_EMAIL", "author@example.com")}}


def author_string(git_dir: Path) -> str:
    cfg = get_config(git_dir)
    name = cfg.get("user", {}).get("name", "Author")
    email = cfg.get("user", {}).get("email", "author@example.com")
    return f"{name} <{email}>"


# ---------------------------------------------------------------------------
# Diff utilities
# ---------------------------------------------------------------------------

def _blob_lines(git_dir: Path, sha: Optional[str]) -> list[str]:
    if sha is None:
        return []
    _, content = read_object(git_dir, sha)
    try:
        return content.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        return ["<binary>\n"]


def unified_diff(git_dir: Path, path: str, old_sha: Optional[str], new_sha: Optional[str],
                 old_label: str = None, new_label: str = None) -> str:
    old_lines = _blob_lines(git_dir, old_sha)
    new_lines = _blob_lines(git_dir, new_sha)
    old_label = old_label or (f"a/{path}" if old_sha else "/dev/null")
    new_label = new_label or (f"b/{path}" if new_sha else "/dev/null")
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=old_label, tofile=new_label))
    return "".join(diff)


# ---------------------------------------------------------------------------
# Merge utilities
# ---------------------------------------------------------------------------

def find_common_ancestor(git_dir: Path, sha_a: str, sha_b: str) -> Optional[str]:
    """Simple linear ancestor search (not the full LCA algorithm)."""
    def ancestors(sha: str) -> list[str]:
        result = []
        current = sha
        seen = set()
        while current and current not in seen:
            seen.add(current)
            result.append(current)
            c = read_commit(git_dir, current)
            current = c.parent
        return result

    a_ancestors = ancestors(sha_a)
    b_set = set(ancestors(sha_b))
    for sha in a_ancestors:
        if sha in b_set:
            return sha
    return None


def is_ancestor(git_dir: Path, maybe_ancestor: str, descendant: str) -> bool:
    current = descendant
    seen = set()
    while current and current not in seen:
        seen.add(current)
        if current == maybe_ancestor:
            return True
        c = read_commit(git_dir, current)
        current = c.parent
    return False


def three_way_merge_text(base: list[str], ours: list[str], theirs: list[str],
                          our_label: str = "HEAD", their_label: str = "theirs") -> tuple[list[str], bool]:
    """Three-way merge. Returns (merged_lines, had_conflicts)."""
    # Use difflib SequenceMatcher for a simple 3-way merge
    result = []
    had_conflicts = False

    # Find changes from base to ours and base to theirs
    matcher_ours = difflib.SequenceMatcher(None, base, ours)
    matcher_theirs = difflib.SequenceMatcher(None, base, theirs)

    opcodes_ours = matcher_ours.get_opcodes()
    opcodes_theirs = matcher_theirs.get_opcodes()

    # Simple chunk-by-chunk approach
    # Collect changed ranges
    def changed_ranges(opcodes, a_len):
        ranges = []
        for tag, i1, i2, j1, j2 in opcodes:
            if tag != 'equal':
                ranges.append((i1, i2, j1, j2, tag))
        return ranges

    our_changes = {(i1, i2): (j1, j2) for _, i1, i2, j1, j2 in opcodes_ours if _ != 'equal'}
    their_changes = {(i1, i2): (j1, j2) for _, i1, i2, j1, j2 in opcodes_theirs if _ != 'equal'}

    # Build merged output line by line from base
    pos = 0
    all_change_starts = sorted(set(
        [i1 for i1, i2 in our_changes] + [i1 for i1, i2 in their_changes]
    ))

    i = 0
    while i < len(base):
        # Check if this position starts a change
        our_key = next(((i1, i2) for i1, i2 in our_changes if i1 == i), None)
        their_key = next(((i1, i2) for i1, i2 in their_changes if i1 == i), None)

        if our_key is None and their_key is None:
            result.append(base[i])
            i += 1
        elif our_key is not None and their_key is None:
            # Only ours changed
            j1, j2 = our_changes[our_key]
            result.extend(ours[j1:j2])
            i = our_key[1]
        elif our_key is None and their_key is not None:
            # Only theirs changed
            j1, j2 = their_changes[their_key]
            result.extend(theirs[j1:j2])
            i = their_key[1]
        else:
            # Both changed — check if they changed to the same thing
            our_j1, our_j2 = our_changes[our_key]
            their_j1, their_j2 = their_changes[their_key]
            our_new = ours[our_j1:our_j2]
            their_new = theirs[their_j1:their_j2]
            if our_new == their_new:
                result.extend(our_new)
            else:
                # Conflict
                had_conflicts = True
                result.append(f"<<<<<<< {our_label}\n")
                result.extend(our_new)
                result.append("=======\n")
                result.extend(their_new)
                result.append(f">>>>>>> {their_label}\n")
            i = max(our_key[1], their_key[1])

    # Append remaining base lines if any
    while i < len(base):
        result.append(base[i])
        i += 1

    # Handle additions past end of base
    if len(ours) > len(base) and not had_conflicts:
        result.extend(ours[len(base):])
    if len(theirs) > len(base) and not had_conflicts:
        result.extend(theirs[len(base):])

    return result, had_conflicts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def require_repo(start: Optional[Path] = None) -> tuple[Path, Path]:
    """Return (repo_root, git_dir) or die."""
    root = find_repo_root(start or Path.cwd())
    if root is None:
        die("fatal: not a git repository (or any of the parent directories): .git")
    return root, _git_dir(root)


def short_sha(sha: str) -> str:
    return sha[:7]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args) -> None:
    target = Path(args.directory) if args.directory else Path.cwd()
    target.mkdir(parents=True, exist_ok=True)
    git_dir = target / ".git"

    if git_dir.exists():
        print(f"Reinitialized existing Git repository in {git_dir.resolve()}/")
        return

    for d in ["objects", "refs/heads", "refs/tags"]:
        (git_dir / d).mkdir(parents=True)

    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "config.json").write_text(json.dumps({
        "user": {
            "name": os.environ.get("GIT_AUTHOR_NAME", "Author"),
            "email": os.environ.get("GIT_AUTHOR_EMAIL", "author@example.com"),
        }
    }, indent=2))

    print(f"Initialized empty Git repository in {git_dir.resolve()}/")


def cmd_add(args) -> None:
    repo_root, git_dir = require_repo()
    index = read_index(git_dir)

    for path_str in args.pathspec:
        target = (repo_root / path_str).resolve()
        if not target.exists():
            die(f"fatal: pathspec '{path_str}' did not match any files")

        for rel_path in _collect_files(repo_root, target):
            full_path = repo_root / rel_path
            content = full_path.read_bytes()
            sha = write_object(git_dir, "blob", content)
            index[rel_path] = sha

    write_index(git_dir, index)


def cmd_status(args) -> None:
    repo_root, git_dir = require_repo()
    index = read_index(git_dir)

    branch = current_branch(git_dir)
    head_sha, _ = read_head(git_dir)

    if branch:
        print(f"On branch {branch}")
    else:
        print(f"HEAD detached at {short_sha(head_sha or 'unknown')}")

    # Get committed state
    committed: dict[str, str] = {}
    if head_sha:
        c = read_commit(git_dir, head_sha)
        committed = tree_to_flat_index(git_dir, c.tree)

    # Changes to be committed (staged vs committed)
    staged_new = []
    staged_modified = []
    staged_deleted = []
    for path, sha in sorted(index.items()):
        if path not in committed:
            staged_new.append(path)
        elif committed[path] != sha:
            staged_modified.append(path)
    for path in committed:
        if path not in index:
            staged_deleted.append(path)

    # Changes not staged (working tree vs index)
    not_staged_modified = []
    not_staged_deleted = []
    for path, sha in sorted(index.items()):
        full_path = repo_root / path
        if not full_path.exists():
            not_staged_deleted.append(path)
        else:
            content = full_path.read_bytes()
            cur_sha = write_object(git_dir, "blob", content)
            if cur_sha != sha:
                not_staged_modified.append(path)

    # Untracked files
    all_files = _collect_files(repo_root, repo_root)
    untracked = [f for f in all_files if f not in index]

    if not (staged_new or staged_modified or staged_deleted or
            not_staged_modified or not_staged_deleted or untracked):
        if not head_sha:
            print("\nNo commits yet")
        print("\nnothing to commit, working tree clean")
        return

    if staged_new or staged_modified or staged_deleted:
        print("\nChanges to be committed:")
        for p in staged_new:
            print(f"\tnew file:   {p}")
        for p in staged_modified:
            print(f"\tmodified:   {p}")
        for p in staged_deleted:
            print(f"\tdeleted:    {p}")

    if not_staged_modified or not_staged_deleted:
        print("\nChanges not staged for commit:")
        for p in not_staged_modified:
            print(f"\tmodified:   {p}")
        for p in not_staged_deleted:
            print(f"\tdeleted:    {p}")

    if untracked:
        print("\nUntracked files:")
        for p in untracked:
            print(f"\t{p}")

    print()


def cmd_commit(args) -> None:
    repo_root, git_dir = require_repo()
    index = read_index(git_dir)

    if not index:
        die("On branch main\n\nnothing to commit, working tree clean")

    # Check if anything changed vs HEAD
    head_sha, _ = read_head(git_dir)
    if head_sha:
        c = read_commit(git_dir, head_sha)
        committed = tree_to_flat_index(git_dir, c.tree)
        if committed == index:
            die("nothing to commit, working tree clean")

    tree_sha = build_tree_from_index(git_dir, repo_root, index)
    author = author_string(git_dir)

    commit = Commit(
        tree=tree_sha,
        parent=head_sha,
        author=author,
        committer=author,
        message=args.message,
    )
    commit_sha = make_commit(git_dir, commit)
    advance_head(git_dir, commit_sha)

    branch = current_branch(git_dir)
    branch_display = branch or short_sha(commit_sha)
    print(f"[{branch_display} {short_sha(commit_sha)}] {args.message}")
    n_files = len(index)
    print(f" {n_files} file{'s' if n_files != 1 else ''} changed")


def cmd_log(args) -> None:
    repo_root, git_dir = require_repo()
    head_sha, _ = read_head(git_dir)

    if not head_sha:
        die("fatal: your current branch 'main' does not have any commits yet")

    sha = head_sha
    count = 0
    limit = args.n if args.n else None

    while sha:
        if limit is not None and count >= limit:
            break

        c = read_commit(git_dir, sha)

        if args.oneline:
            print(f"{short_sha(sha)} {c.message.splitlines()[0]}")
        else:
            print(f"commit {sha}")
            print(f"Author: {c.author}")
            # Parse timestamp from author string
            parts = c.author.rsplit(" ", 2)
            if len(parts) >= 2:
                try:
                    ts = int(parts[-2])
                    date_str = time.strftime("%a %b %d %H:%M:%S %Y +0000", time.gmtime(ts))
                    print(f"Date:   {date_str}")
                except (ValueError, IndexError):
                    pass
            print()
            for line in c.message.splitlines():
                print(f"    {line}")
            print()

        sha = c.parent
        count += 1


def cmd_branch(args) -> None:
    repo_root, git_dir = require_repo()

    if args.delete:
        # Delete a branch
        branch_name = args.name
        if branch_name == current_branch(git_dir):
            die(f"error: Cannot delete branch '{branch_name}' checked out at '{repo_root}'")
        ref_path = git_dir / "refs" / "heads" / branch_name
        if not ref_path.exists():
            die(f"error: branch '{branch_name}' not found")
        ref_path.unlink()
        sha, _ = read_head(git_dir)
        print(f"Deleted branch {branch_name} (was {short_sha(sha or '')}).")

    elif args.name:
        # Create a branch
        head_sha, _ = read_head(git_dir)
        if not head_sha:
            die("fatal: Not a valid object name 'HEAD'")
        ref_path = git_dir / "refs" / "heads" / args.name
        if ref_path.exists():
            die(f"fatal: A branch named '{args.name}' already exists")
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text(head_sha + "\n")

    else:
        # List branches
        branches = list_branches(git_dir)
        cur = current_branch(git_dir)
        for b in branches:
            prefix = "* " if b == cur else "  "
            print(f"{prefix}{b}")


def cmd_checkout(args) -> None:
    repo_root, git_dir = require_repo()

    if args.b:
        # Create and switch
        head_sha, _ = read_head(git_dir)
        if not head_sha:
            die("fatal: Not a valid object name 'HEAD'")
        new_ref = git_dir / "refs" / "heads" / args.target
        if new_ref.exists():
            die(f"fatal: A branch named '{args.target}' already exists")
        new_ref.parent.mkdir(parents=True, exist_ok=True)
        new_ref.write_text(head_sha + "\n")
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{args.target}\n")
        print(f"Switched to a new branch '{args.target}'")
        return

    # Check for uncommitted changes
    index = read_index(git_dir)
    head_sha, _ = read_head(git_dir)
    if head_sha:
        committed = tree_to_flat_index(git_dir, read_commit(git_dir, head_sha).tree)
        for path, sha in index.items():
            wt_path = repo_root / path
            if wt_path.exists():
                content = wt_path.read_bytes()
                wt_sha = write_object(git_dir, "blob", content)
                if wt_sha != sha:
                    die(f"error: Your local changes to '{path}' would be overwritten by checkout.\n"
                        f"Please commit your changes before you switch branches.")

    target = args.target

    # Try as branch
    branch_ref = git_dir / "refs" / "heads" / target
    if branch_ref.exists():
        target_sha = branch_ref.read_text().strip()
        _switch_to_commit(git_dir, repo_root, target_sha, index)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{target}\n")
        print(f"Switched to branch '{target}'")
        return

    # Try as SHA
    resolved = resolve_ref(git_dir, target)
    if resolved:
        _switch_to_commit(git_dir, repo_root, resolved, index)
        (git_dir / "HEAD").write_text(resolved + "\n")
        print(f"HEAD is now at {short_sha(resolved)}")
        return

    die(f"error: pathspec '{target}' did not match any file(s) known to git")


def _switch_to_commit(git_dir: Path, repo_root: Path, target_sha: str, current_index: dict) -> None:
    """Update working tree and index to match a commit."""
    target_commit = read_commit(git_dir, target_sha)
    new_files = tree_to_flat_index(git_dir, target_commit.tree)

    # Remove files that don't exist in target
    for path in current_index:
        if path not in new_files:
            (repo_root / path).unlink(missing_ok=True)

    # Write new files
    restore_tree(git_dir, repo_root, target_commit.tree)
    write_index(git_dir, new_files)


def cmd_merge(args) -> None:
    repo_root, git_dir = require_repo()

    head_sha, _ = read_head(git_dir)
    if not head_sha:
        die("fatal: Not a valid object name 'HEAD'")

    branch_name = args.branch
    their_sha = resolve_ref(git_dir, branch_name)
    if not their_sha:
        die(f"fatal: '{branch_name}' does not point to a commit")

    if head_sha == their_sha or is_ancestor(git_dir, their_sha, head_sha):
        print("Already up to date.")
        return

    # Fast-forward?
    if is_ancestor(git_dir, head_sha, their_sha):
        # head is ancestor of theirs — fast forward
        their_commit = read_commit(git_dir, their_sha)
        restore_tree(git_dir, repo_root, their_commit.tree)
        advance_head(git_dir, their_sha)
        write_index(git_dir, tree_to_flat_index(git_dir, their_commit.tree))
        print(f"Fast-forward")
        print(f" 1 file changed")
        return

    # Three-way merge
    base_sha = find_common_ancestor(git_dir, head_sha, their_sha)
    if base_sha is None:
        die("fatal: refusing to merge unrelated histories")

    head_commit = read_commit(git_dir, head_sha)
    their_commit = read_commit(git_dir, their_sha)

    base_files = tree_to_flat_index(git_dir, read_commit(git_dir, base_sha).tree)
    head_files = tree_to_flat_index(git_dir, head_commit.tree)
    their_files = tree_to_flat_index(git_dir, their_commit.tree)

    all_paths = set(base_files) | set(head_files) | set(their_files)
    new_index = {}
    had_conflicts = False

    for path in sorted(all_paths):
        base_sha_f = base_files.get(path)
        head_sha_f = head_files.get(path)
        their_sha_f = their_files.get(path)

        if head_sha_f == their_sha_f:
            if head_sha_f:
                new_index[path] = head_sha_f
            continue

        if head_sha_f == base_sha_f:
            # Only theirs changed
            if their_sha_f:
                new_index[path] = their_sha_f
                _, content = read_object(git_dir, their_sha_f)
                target = repo_root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            else:
                (repo_root / path).unlink(missing_ok=True)
            continue

        if their_sha_f == base_sha_f:
            # Only ours changed
            if head_sha_f:
                new_index[path] = head_sha_f
            else:
                (repo_root / path).unlink(missing_ok=True)
            continue

        # Both changed — three-way text merge
        base_lines = _blob_lines(git_dir, base_sha_f)
        head_lines = _blob_lines(git_dir, head_sha_f)
        their_lines = _blob_lines(git_dir, their_sha_f)

        merged, conflicts = three_way_merge_text(
            base_lines, head_lines, their_lines,
            our_label=f"HEAD", their_label=branch_name
        )

        merged_content = "".join(merged).encode()
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(merged_content)

        if conflicts:
            had_conflicts = True
            print(f"CONFLICT (content): Merge conflict in {path}")
        else:
            sha = write_object(git_dir, "blob", merged_content)
            new_index[path] = sha

    write_index(git_dir, new_index)

    if had_conflicts:
        print("Automatic merge failed; fix conflicts and then commit the result.")
        sys.exit(1)

    # Create merge commit
    author = author_string(git_dir)
    tree_sha = build_tree_from_index(git_dir, repo_root, new_index)
    merge_commit = Commit(
        tree=tree_sha,
        parent=head_sha,
        author=author,
        committer=author,
        message=f"Merge branch '{branch_name}'",
    )
    # Add second parent
    commit_data = make_commit.__wrapped__ if hasattr(make_commit, '__wrapped__') else None

    # Write merge commit manually to include both parents
    tz = "+0000"
    ts = int(time.time())
    lines = [
        f"tree {tree_sha}",
        f"parent {head_sha}",
        f"parent {their_sha}",
        f"author {author} {ts} {tz}",
        f"committer {author} {ts} {tz}",
        "",
        f"Merge branch '{branch_name}'",
    ]
    data = "\n".join(lines).encode()
    merge_sha = write_object(git_dir, "commit", data)
    advance_head(git_dir, merge_sha)
    print(f"Merge made by 'ort' strategy.")


def cmd_diff(args) -> None:
    repo_root, git_dir = require_repo()

    if args.commit1 and args.commit2:
        sha1 = resolve_ref(git_dir, args.commit1)
        sha2 = resolve_ref(git_dir, args.commit2)
        if not sha1: die(f"fatal: ambiguous argument '{args.commit1}'")
        if not sha2: die(f"fatal: ambiguous argument '{args.commit2}'")
        files1 = tree_to_flat_index(git_dir, read_commit(git_dir, sha1).tree)
        files2 = tree_to_flat_index(git_dir, read_commit(git_dir, sha2).tree)
        all_paths = sorted(set(files1) | set(files2))
        for path in all_paths:
            d = unified_diff(git_dir, path, files1.get(path), files2.get(path))
            if d:
                print(d, end="")
        return

    index = read_index(git_dir)
    head_sha, _ = read_head(git_dir)

    if args.staged:
        # Staged vs HEAD
        committed = {}
        if head_sha:
            committed = tree_to_flat_index(git_dir, read_commit(git_dir, head_sha).tree)
        all_paths = sorted(set(index) | set(committed))
        for path in all_paths:
            d = unified_diff(git_dir, path, committed.get(path), index.get(path))
            if d:
                print(d, end="")
    else:
        # Working tree vs index
        for path in sorted(index.keys()):
            full_path = repo_root / path
            if not full_path.exists():
                d = unified_diff(git_dir, path, index[path], None)
            else:
                content = full_path.read_bytes()
                wt_sha = write_object(git_dir, "blob", content)
                d = unified_diff(git_dir, path, index[path], wt_sha)
            if d:
                print(d, end="")


def cmd_reset(args) -> None:
    repo_root, git_dir = require_repo()
    head_sha, _ = read_head(git_dir)

    target_ref = args.commit or "HEAD"
    if target_ref == "HEAD~1" and head_sha:
        c = read_commit(git_dir, head_sha)
        target_sha = c.parent
        if not target_sha:
            die("fatal: ambiguous argument 'HEAD~1': unknown revision")
    elif target_ref.startswith("HEAD~"):
        n = int(target_ref[5:])
        current = head_sha
        for _ in range(n):
            if not current:
                die("fatal: not enough commits")
            c = read_commit(git_dir, current)
            current = c.parent
        target_sha = current
    else:
        target_sha = resolve_ref(git_dir, target_ref)

    if not target_sha:
        die(f"fatal: ambiguous argument '{target_ref}'")

    mode = args.mode or "mixed"
    target_commit = read_commit(git_dir, target_sha)

    # Always move HEAD/branch pointer
    advance_head(git_dir, target_sha)

    if mode == "soft":
        pass  # Index and working tree unchanged

    elif mode in ("mixed", None):
        # Reset index to target
        write_index(git_dir, tree_to_flat_index(git_dir, target_commit.tree))

    elif mode == "hard":
        # Reset index and working tree
        new_files = tree_to_flat_index(git_dir, target_commit.tree)
        # Remove files not in target
        index = read_index(git_dir)
        for path in index:
            if path not in new_files:
                (repo_root / path).unlink(missing_ok=True)
        restore_tree(git_dir, repo_root, target_commit.tree)
        write_index(git_dir, new_files)

    print(f"HEAD is now at {short_sha(target_sha)} {target_commit.message.splitlines()[0]}")


def cmd_stash(args) -> None:
    repo_root, git_dir = require_repo()
    stash_file = git_dir / "stash.json"
    stash_list: list[dict] = []
    if stash_file.exists():
        stash_list = json.loads(stash_file.read_text())

    subcmd = args.subcommand or "push"

    if subcmd == "push" or subcmd is None:
        index = read_index(git_dir)
        head_sha, _ = read_head(git_dir)
        if not head_sha:
            die("fatal: You do not have the initial commit yet")

        # Collect working tree changes
        wt_changes: dict[str, str] = {}
        for path, staged_sha in index.items():
            full_path = repo_root / path
            if full_path.exists():
                content = full_path.read_bytes()
                wt_sha = write_object(git_dir, "blob", content)
                if wt_sha != staged_sha:
                    wt_changes[path] = wt_sha

        if not wt_changes and index == tree_to_flat_index(git_dir, read_commit(git_dir, head_sha).tree):
            print("No local changes to save")
            return

        # Save stash entry
        committed = tree_to_flat_index(git_dir, read_commit(git_dir, head_sha).tree)
        stash_entry = {
            "index": index,
            "wt_changes": wt_changes,
            "head": head_sha,
            "message": f"WIP on {current_branch(git_dir) or 'HEAD'}: {short_sha(head_sha)}",
        }
        stash_list.insert(0, stash_entry)
        stash_file.write_text(json.dumps(stash_list, indent=2))

        # Revert to HEAD
        restore_tree(git_dir, repo_root, read_commit(git_dir, head_sha).tree)
        write_index(git_dir, committed)
        print(f"Saved working directory and index state {stash_entry['message']}")

    elif subcmd == "pop":
        if not stash_list:
            die("error: No stash entries found.")
        entry = stash_list.pop(0)
        stash_file.write_text(json.dumps(stash_list, indent=2))
        # Restore index
        write_index(git_dir, entry["index"])
        # Restore working tree changes
        for path, sha in entry.get("wt_changes", {}).items():
            _, content = read_object(git_dir, sha)
            full_path = repo_root / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)
        print(f"Restored {entry['message']}")

    elif subcmd == "list":
        if not stash_list:
            return
        for i, entry in enumerate(stash_list):
            print(f"stash@{{{i}}}: {entry['message']}")

    elif subcmd == "drop":
        idx = args.stash_index if hasattr(args, 'stash_index') and args.stash_index is not None else 0
        if idx >= len(stash_list):
            die(f"error: {args.stash_index} is not a valid reference")
        dropped = stash_list.pop(idx)
        stash_file.write_text(json.dumps(stash_list, indent=2))
        print(f"Dropped stash@{{{idx}}} ({dropped['message']})")

    else:
        die(f"error: unknown stash subcommand: {subcmd}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mini-git",
        description="A minimal but real implementation of git.",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p = sub.add_parser("init")
    p.add_argument("directory", nargs="?", default=None)

    # add
    p = sub.add_parser("add")
    p.add_argument("pathspec", nargs="+")

    # status
    sub.add_parser("status")

    # commit
    p = sub.add_parser("commit")
    p.add_argument("-m", "--message", required=True)

    # log
    p = sub.add_parser("log")
    p.add_argument("--oneline", action="store_true")
    p.add_argument("-n", type=int, default=None)

    # branch
    p = sub.add_parser("branch")
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("-d", "--delete", action="store_true")

    # checkout
    p = sub.add_parser("checkout")
    p.add_argument("-b", action="store_true")
    p.add_argument("target")

    # merge
    p = sub.add_parser("merge")
    p.add_argument("branch")

    # diff
    p = sub.add_parser("diff")
    p.add_argument("--staged", action="store_true")
    p.add_argument("commit1", nargs="?", default=None)
    p.add_argument("commit2", nargs="?", default=None)

    # reset
    p = sub.add_parser("reset")
    p.add_argument("--soft", dest="mode", action="store_const", const="soft")
    p.add_argument("--mixed", dest="mode", action="store_const", const="mixed")
    p.add_argument("--hard", dest="mode", action="store_const", const="hard")
    p.add_argument("commit", nargs="?", default=None)

    # stash
    p = sub.add_parser("stash")
    p.add_argument("subcommand", nargs="?", choices=["push", "pop", "list", "drop"], default=None)
    p.add_argument("stash_index", nargs="?", type=int, default=None)

    return parser


def main():
    parser = build_parser()
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "add": cmd_add,
        "status": cmd_status,
        "commit": cmd_commit,
        "log": cmd_log,
        "branch": cmd_branch,
        "checkout": cmd_checkout,
        "merge": cmd_merge,
        "diff": cmd_diff,
        "reset": cmd_reset,
        "stash": cmd_stash,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
