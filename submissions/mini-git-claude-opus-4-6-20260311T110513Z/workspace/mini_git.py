#!/usr/bin/env python3
"""A minimal Git implementation supporting basic and remote operations."""

import os
import sys
import hashlib
import zlib
import time
import configparser
import shutil
import stat


# ─── helpers ────────────────────────────────────────────────────────────────

def find_repo_root(start=None):
    """Walk up from `start` (default cwd) until we find a .git directory."""
    if start is None:
        start = os.getcwd()
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def repo_path(*parts, repo_root=None):
    if repo_root is None:
        repo_root = find_repo_root()
    if repo_root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)
    return os.path.join(repo_root, ".git", *parts)


def hash_object(data: bytes, obj_type: str = "blob", write: bool = True,
                repo_root=None) -> str:
    header = f"{obj_type} {len(data)}\0".encode()
    store = header + data
    sha = hashlib.sha1(store).hexdigest()
    if write:
        path = repo_path("objects", sha[:2], sha[2:], repo_root=repo_root)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(zlib.compress(store))
    return sha


def read_object(sha: str, repo_root=None):
    path = repo_path("objects", sha[:2], sha[2:], repo_root=repo_root)
    if not os.path.exists(path):
        return None, None
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())
    # header\0body
    nul = raw.index(b"\0")
    header = raw[:nul].decode()
    obj_type, size_str = header.split(" ", 1)
    body = raw[nul + 1:]
    return obj_type, body


def get_head_ref(repo_root=None):
    """Return (is_detached, value).  value is either a sha or a ref path."""
    head_file = repo_path("HEAD", repo_root=repo_root)
    if not os.path.exists(head_file):
        return False, "refs/heads/master"
    content = open(head_file).read().strip()
    if content.startswith("ref: "):
        return False, content[5:]
    return True, content


def resolve_ref(ref, repo_root=None):
    """Resolve a symbolic ref (or bare sha) to a commit sha (or None)."""
    # If it looks like a full sha already
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref):
        return ref
    path = repo_path(ref, repo_root=repo_root)
    if os.path.exists(path):
        content = open(path).read().strip()
        if content.startswith("ref: "):
            return resolve_ref(content[5:], repo_root=repo_root)
        return content if content else None
    return None


def get_current_branch(repo_root=None):
    detached, val = get_head_ref(repo_root=repo_root)
    if detached:
        return None
    if val.startswith("refs/heads/"):
        return val[len("refs/heads/"):]
    return val


def set_ref(ref, sha, repo_root=None):
    path = repo_path(ref, repo_root=repo_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(sha + "\n")


def get_head_commit(repo_root=None):
    detached, val = get_head_ref(repo_root=repo_root)
    if detached:
        return val if val else None
    return resolve_ref(val, repo_root=repo_root)


# ─── tree / commit helpers ──────────────────────────────────────────────────

def write_tree(directory=None, repo_root=None):
    """Recursively write tree objects for directory, return sha."""
    if directory is None:
        directory = repo_root or find_repo_root() or os.getcwd()
    if repo_root is None:
        repo_root = find_repo_root(directory)
    entries = []
    git_dir = os.path.join(repo_root, ".git")
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if os.path.abspath(full).startswith(os.path.abspath(git_dir)):
            continue
        if name == ".git":
            continue
        if os.path.isfile(full):
            with open(full, "rb") as f:
                data = f.read()
            blob_sha = hash_object(data, "blob", True, repo_root=repo_root)
            entries.append((b"100644", name.encode(), bytes.fromhex(blob_sha)))
        elif os.path.isdir(full):
            tree_sha = write_tree(full, repo_root=repo_root)
            entries.append((b"40000", name.encode(), bytes.fromhex(tree_sha)))
    # build tree object body
    body = b""
    for mode, nameb, sha_bytes in entries:
        body += mode + b" " + nameb + b"\0" + sha_bytes
    return hash_object(body, "tree", True, repo_root=repo_root)


def read_tree_entries(sha, repo_root=None):
    """Return list of (mode_str, name, entry_sha_hex) from a tree object."""
    obj_type, data = read_object(sha, repo_root=repo_root)
    if obj_type != "tree":
        return []
    entries = []
    i = 0
    while i < len(data):
        space = data.index(b" ", i)
        mode = data[i:space].decode()
        nul = data.index(b"\0", space)
        name = data[space + 1:nul].decode()
        sha_bytes = data[nul + 1:nul + 21]
        entry_sha = sha_bytes.hex()
        entries.append((mode, name, entry_sha))
        i = nul + 21
    return entries


def parse_commit(sha, repo_root=None):
    """Return dict with tree, parents (list), author, committer, message."""
    obj_type, data = read_object(sha, repo_root=repo_root)
    if obj_type != "commit":
        return None
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    result = {"parents": [], "tree": None, "author": "", "committer": "", "message": ""}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "":
            result["message"] = "\n".join(lines[i + 1:])
            break
        if line.startswith("tree "):
            result["tree"] = line[5:]
        elif line.startswith("parent "):
            result["parents"].append(line[7:])
        elif line.startswith("author "):
            result["author"] = line[7:]
        elif line.startswith("committer "):
            result["committer"] = line[10:]
        i += 1
    return result


def flatten_tree(tree_sha, prefix="", repo_root=None):
    """Yield (path, blob_sha) for every blob in tree recursively."""
    for mode, name, entry_sha in read_tree_entries(tree_sha, repo_root=repo_root):
        path = os.path.join(prefix, name) if prefix else name
        if mode == "40000":
            yield from flatten_tree(entry_sha, path, repo_root=repo_root)
        else:
            yield (path, entry_sha)


# ─── index helpers ──────────────────────────────────────────────────────────

def read_index(repo_root=None):
    """Return dict mapping path -> sha from a simple text index."""
    idx_path = repo_path("index", repo_root=repo_root)
    index = {}
    if os.path.exists(idx_path):
        for line in open(idx_path).read().strip().split("\n"):
            if not line.strip():
                continue
            sha, path = line.split(" ", 1)
            index[path] = sha
    return index


def write_index(index, repo_root=None):
    idx_path = repo_path("index", repo_root=repo_root)
    with open(idx_path, "w") as f:
        for path in sorted(index):
            f.write(f"{index[path]} {path}\n")


def build_tree_from_index(index, repo_root=None):
    """Build tree objects from a flat index dict, return root tree sha."""
    # Build a nested dict structure
    root = {}
    for path, sha in index.items():
        parts = path.replace("\\", "/").split("/")
        node = root
        for part in parts[:-1]:
            if part not in node:
                node[part] = {}
            node = node[part]
        node[parts[-1]] = sha

    def _build(node):
        entries = []
        for name in sorted(node):
            val = node[name]
            if isinstance(val, dict):
                tree_sha = _build(val)
                entries.append((b"40000", name.encode(), bytes.fromhex(tree_sha)))
            else:
                entries.append((b"100644", name.encode(), bytes.fromhex(val)))
        body = b""
        for mode, nameb, sha_bytes in entries:
            body += mode + b" " + nameb + b"\0" + sha_bytes
        return hash_object(body, "tree", True, repo_root=repo_root)

    return _build(root)


# ─── config helpers ─────────────────────────────────────────────────────────

def read_config(repo_root=None):
    cfg = configparser.ConfigParser()
    cfg_path = repo_path("config", repo_root=repo_root)
    if os.path.exists(cfg_path):
        cfg.read(cfg_path)
    return cfg


def write_config(cfg, repo_root=None):
    cfg_path = repo_path("config", repo_root=repo_root)
    with open(cfg_path, "w") as f:
        cfg.write(f)


# ─── commands ───────────────────────────────────────────────────────────────

def cmd_init(args):
    path = args[0] if args else "."
    git_dir = os.path.join(path, ".git")
    os.makedirs(git_dir, exist_ok=True)
    for d in ["objects", "refs/heads", "refs/tags", "refs/remotes"]:
        os.makedirs(os.path.join(git_dir, d), exist_ok=True)
    head = os.path.join(git_dir, "HEAD")
    if not os.path.exists(head):
        with open(head, "w") as f:
            f.write("ref: refs/heads/master\n")
    # Create empty config
    cfg_path = os.path.join(git_dir, "config")
    if not os.path.exists(cfg_path):
        with open(cfg_path, "w") as f:
            f.write("")
    abs_path = os.path.abspath(git_dir)
    print(f"Initialized empty mini-git repository in {abs_path}")


def cmd_hash_object(args):
    write = True
    fname = None
    i = 0
    while i < len(args):
        if args[i] == "-w":
            write = True
            i += 1
        else:
            fname = args[i]
            i += 1
    if fname is None:
        print("usage: mini-git hash-object [-w] <file>", file=sys.stderr)
        sys.exit(1)
    with open(fname, "rb") as f:
        data = f.read()
    sha = hash_object(data, "blob", write)
    print(sha)


def cmd_cat_file(args):
    if len(args) < 2:
        print("usage: mini-git cat-file <type> <sha>", file=sys.stderr)
        sys.exit(1)
    # Support -p flag
    if args[0] == "-p":
        sha = args[1]
        obj_type, data = read_object(sha)
        if data is None:
            print(f"fatal: Not a valid object name {sha}", file=sys.stderr)
            sys.exit(1)
        if obj_type == "tree":
            for mode, name, entry_sha in read_tree_entries(sha):
                etype = "tree" if mode == "40000" else "blob"
                print(f"{mode.zfill(6)} {etype} {entry_sha}\t{name}")
        else:
            sys.stdout.buffer.write(data)
    elif args[0] == "-t":
        sha = args[1]
        obj_type, data = read_object(sha)
        if data is None:
            print(f"fatal: Not a valid object name {sha}", file=sys.stderr)
            sys.exit(1)
        print(obj_type)
    else:
        expected_type = args[0]
        sha = args[1]
        obj_type, data = read_object(sha)
        if data is None:
            print(f"fatal: Not a valid object name {sha}", file=sys.stderr)
            sys.exit(1)
        sys.stdout.buffer.write(data)


def cmd_add(args):
    if not args:
        print("Nothing specified, nothing added.", file=sys.stderr)
        return
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)
    index = read_index(repo_root=root)
    for pattern in args:
        # Handle "." to add everything
        if pattern == ".":
            for dirpath, dirnames, filenames in os.walk(root):
                # Skip .git
                dirnames[:] = [d for d in dirnames if d != ".git"]
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, root)
                    rel = rel.replace("\\", "/")
                    with open(full, "rb") as f:
                        data = f.read()
                    sha = hash_object(data, "blob", True, repo_root=root)
                    index[rel] = sha
        else:
            full = os.path.abspath(pattern)
            if os.path.isfile(full):
                rel = os.path.relpath(full, root).replace("\\", "/")
                with open(full, "rb") as f:
                    data = f.read()
                sha = hash_object(data, "blob", True, repo_root=root)
                index[rel] = sha
            elif os.path.isdir(full):
                for dirpath, dirnames, filenames in os.walk(full):
                    dirnames[:] = [d for d in dirnames if d != ".git"]
                    for fname in filenames:
                        fp = os.path.join(dirpath, fname)
                        rel = os.path.relpath(fp, root).replace("\\", "/")
                        with open(fp, "rb") as f:
                            data = f.read()
                        sha = hash_object(data, "blob", True, repo_root=root)
                        index[rel] = sha
            else:
                # Check if file was removed - remove from index
                rel = os.path.relpath(full, root).replace("\\", "/")
                if rel in index:
                    del index[rel]
                else:
                    print(f"fatal: pathspec '{pattern}' did not match any files",
                          file=sys.stderr)
                    sys.exit(1)
    write_index(index, repo_root=root)


def cmd_commit(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)
    # parse -m
    message = ""
    i = 0
    while i < len(args):
        if args[i] == "-m" and i + 1 < len(args):
            message = args[i + 1]
            i += 2
        else:
            i += 1
    if not message:
        print("error: must supply a commit message with -m", file=sys.stderr)
        sys.exit(1)

    index = read_index(repo_root=root)
    if not index:
        print("nothing to commit", file=sys.stderr)
        sys.exit(1)

    tree_sha = build_tree_from_index(index, repo_root=root)
    parent = get_head_commit(repo_root=root)

    author_name = os.environ.get("GIT_AUTHOR_NAME", "Mini Git User")
    author_email = os.environ.get("GIT_AUTHOR_EMAIL", "user@example.com")
    ts = int(time.time())
    tz = "+0000"
    author_line = f"{author_name} <{author_email}> {ts} {tz}"
    committer_line = author_line

    lines = [f"tree {tree_sha}"]
    if parent:
        lines.append(f"parent {parent}")
    lines.append(f"author {author_line}")
    lines.append(f"committer {committer_line}")
    lines.append("")
    lines.append(message)

    commit_data = "\n".join(lines).encode()
    commit_sha = hash_object(commit_data, "commit", True, repo_root=root)

    # update HEAD
    detached, ref = get_head_ref(repo_root=root)
    if detached:
        head_file = repo_path("HEAD", repo_root=root)
        with open(head_file, "w") as f:
            f.write(commit_sha + "\n")
    else:
        set_ref(ref, commit_sha, repo_root=root)

    short = commit_sha[:7]
    branch = get_current_branch(repo_root=root) or "detached"
    is_root = " (root-commit)" if not parent else ""
    print(f"[{branch}{is_root} {short}] {message}")
    return commit_sha


def cmd_log(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    sha = get_head_commit(repo_root=root)
    if not sha:
        print("fatal: your current branch does not have any commits yet",
              file=sys.stderr)
        sys.exit(1)

    # Simple linear log: follow first parent
    while sha:
        info = parse_commit(sha, repo_root=root)
        if info is None:
            break
        print(f"commit {sha}")
        print(f"Author: {info['author']}")
        print()
        for line in info["message"].split("\n"):
            print(f"    {line}")
        print()
        sha = info["parents"][0] if info["parents"] else None


def cmd_status(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    branch = get_current_branch(repo_root=root)
    if branch:
        print(f"On branch {branch}")
    else:
        print("HEAD detached")

    index = read_index(repo_root=root)

    # Compare index to HEAD tree
    head_sha = get_head_commit(repo_root=root)
    head_files = {}
    if head_sha:
        info = parse_commit(head_sha, repo_root=root)
        if info and info["tree"]:
            for path, blob_sha in flatten_tree(info["tree"], repo_root=root):
                head_files[path] = blob_sha

    staged_new = []
    staged_modified = []
    staged_deleted = []

    for path in sorted(set(list(index.keys()) + list(head_files.keys()))):
        in_index = path in index
        in_head = path in head_files
        if in_index and not in_head:
            staged_new.append(path)
        elif in_index and in_head and index[path] != head_files[path]:
            staged_modified.append(path)
        elif not in_index and in_head:
            staged_deleted.append(path)

    if staged_new or staged_modified or staged_deleted:
        print("\nChanges to be committed:")
        for f in staged_new:
            print(f"  new file:   {f}")
        for f in staged_modified:
            print(f"  modified:   {f}")
        for f in staged_deleted:
            print(f"  deleted:    {f}")

    # Compare working tree to index
    wt_modified = []
    wt_deleted = []
    untracked = []

    tracked = set(index.keys())
    work_files = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root).replace("\\", "/")
            work_files.add(rel)

    for f in sorted(tracked):
        full = os.path.join(root, f)
        if not os.path.exists(full):
            wt_deleted.append(f)
        else:
            with open(full, "rb") as fh:
                data = fh.read()
            current_sha = hash_object(data, "blob", False, repo_root=root)
            if current_sha != index[f]:
                wt_modified.append(f)

    for f in sorted(work_files - tracked):
        untracked.append(f)

    if wt_modified or wt_deleted:
        print("\nChanges not staged for commit:")
        for f in wt_modified:
            print(f"  modified:   {f}")
        for f in wt_deleted:
            print(f"  deleted:    {f}")

    if untracked:
        print("\nUntracked files:")
        for f in untracked:
            print(f"  {f}")


def cmd_diff(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    staged = "--staged" in args or "--cached" in args

    index = read_index(repo_root=root)

    if staged:
        head_sha = get_head_commit(repo_root=root)
        head_files = {}
        if head_sha:
            info = parse_commit(head_sha, repo_root=root)
            if info and info["tree"]:
                for path, blob_sha in flatten_tree(info["tree"], repo_root=root):
                    head_files[path] = blob_sha
        all_paths = sorted(set(list(index.keys()) + list(head_files.keys())))
        for path in all_paths:
            old_sha = head_files.get(path)
            new_sha = index.get(path)
            if old_sha == new_sha:
                continue
            old_content = ""
            new_content = ""
            if old_sha:
                _, data = read_object(old_sha, repo_root=root)
                if data:
                    old_content = data.decode("utf-8", errors="replace")
            if new_sha:
                _, data = read_object(new_sha, repo_root=root)
                if data:
                    new_content = data.decode("utf-8", errors="replace")
            _print_diff(path, old_content, new_content)
    else:
        for path in sorted(index):
            full = os.path.join(root, path)
            if not os.path.exists(full):
                _, data = read_object(index[path], repo_root=root)
                old_content = data.decode("utf-8", errors="replace") if data else ""
                _print_diff(path, old_content, "")
                continue
            with open(full, "rb") as f:
                working_data = f.read()
            working_sha = hash_object(working_data, "blob", False, repo_root=root)
            if working_sha != index[path]:
                _, data = read_object(index[path], repo_root=root)
                old_content = data.decode("utf-8", errors="replace") if data else ""
                new_content = working_data.decode("utf-8", errors="replace")
                _print_diff(path, old_content, new_content)


def _print_diff(path, old_content, new_content):
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    print(f"diff --git a/{path} b/{path}")
    print(f"--- a/{path}")
    print(f"+++ b/{path}")

    # Simple diff: show removed/added lines
    import difflib
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
    # Skip the first two lines (--- and +++) since we already printed them
    lines = list(diff)
    for line in lines[2:]:
        # Remove trailing newline for clean output
        print(line.rstrip("\n"))


def cmd_branch(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if not args:
        # List branches
        refs_dir = repo_path("refs", "heads", repo_root=root)
        branches = []
        if os.path.isdir(refs_dir):
            for name in sorted(os.listdir(refs_dir)):
                full = os.path.join(refs_dir, name)
                if os.path.isfile(full):
                    branches.append(name)
        current = get_current_branch(repo_root=root)
        for b in branches:
            if b == current:
                print(f"* {b}")
            else:
                print(f"  {b}")
        return

    # Check for -d flag
    if args[0] == "-d" or args[0] == "-D":
        if len(args) < 2:
            print("fatal: branch name required", file=sys.stderr)
            sys.exit(1)
        branch_name = args[1]
        current = get_current_branch(repo_root=root)
        if branch_name == current:
            print(f"error: Cannot delete branch '{branch_name}' checked out",
                  file=sys.stderr)
            sys.exit(1)
        ref_file = repo_path("refs", "heads", branch_name, repo_root=root)
        if not os.path.exists(ref_file):
            print(f"error: branch '{branch_name}' not found.", file=sys.stderr)
            sys.exit(1)
        os.remove(ref_file)
        print(f"Deleted branch {branch_name}")
        return

    # Create branch
    branch_name = args[0]
    head_commit = get_head_commit(repo_root=root)
    if not head_commit:
        print("fatal: not a valid object name: 'HEAD'", file=sys.stderr)
        sys.exit(1)
    ref_file = repo_path("refs", "heads", branch_name, repo_root=root)
    if os.path.exists(ref_file):
        print(f"fatal: a branch named '{branch_name}' already exists",
              file=sys.stderr)
        sys.exit(1)
    set_ref(f"refs/heads/{branch_name}", head_commit, repo_root=root)
    print(f"Created branch {branch_name}")


def cmd_checkout(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if not args:
        print("usage: mini-git checkout <branch>", file=sys.stderr)
        sys.exit(1)

    # Check for -b flag
    create_new = False
    if args[0] == "-b":
        create_new = True
        if len(args) < 2:
            print("usage: mini-git checkout -b <new-branch>", file=sys.stderr)
            sys.exit(1)
        target = args[1]
    else:
        target = args[0]

    if create_new:
        # Create and switch
        head_commit = get_head_commit(repo_root=root)
        if not head_commit:
            print("fatal: not a valid object name: 'HEAD'", file=sys.stderr)
            sys.exit(1)
        ref_file = repo_path("refs", "heads", target, repo_root=root)
        if os.path.exists(ref_file):
            print(f"fatal: a branch named '{target}' already exists",
                  file=sys.stderr)
            sys.exit(1)
        set_ref(f"refs/heads/{target}", head_commit, repo_root=root)
        head_file = repo_path("HEAD", repo_root=root)
        with open(head_file, "w") as f:
            f.write(f"ref: refs/heads/{target}\n")
        print(f"Switched to a new branch '{target}'")
        return

    # Try as branch name
    ref_file = repo_path("refs", "heads", target, repo_root=root)
    if os.path.exists(ref_file):
        commit_sha = open(ref_file).read().strip()
        # Update working tree
        _checkout_tree(commit_sha, root)
        head_file = repo_path("HEAD", repo_root=root)
        with open(head_file, "w") as f:
            f.write(f"ref: refs/heads/{target}\n")
        print(f"Switched to branch '{target}'")
        return

    # Try as a commit sha
    if len(target) >= 4:
        obj_type, _ = read_object(target, repo_root=root) if len(target) == 40 else (None, None)
        if obj_type == "commit":
            _checkout_tree(target, root)
            head_file = repo_path("HEAD", repo_root=root)
            with open(head_file, "w") as f:
                f.write(target + "\n")
            print(f"HEAD is now at {target[:7]}")
            return

    print(f"error: pathspec '{target}' did not match any branch or commit",
          file=sys.stderr)
    sys.exit(1)


def _checkout_tree(commit_sha, root):
    """Update working directory and index to match commit."""
    info = parse_commit(commit_sha, repo_root=root)
    if info is None or info["tree"] is None:
        return

    # Get current index files to know what to remove
    old_index = read_index(repo_root=root)

    # Get new tree files
    new_files = dict(flatten_tree(info["tree"], repo_root=root))

    # Remove files that are in old index but not in new tree
    for path in old_index:
        if path not in new_files:
            full = os.path.join(root, path)
            if os.path.exists(full):
                os.remove(full)
                # Remove empty parent dirs
                parent = os.path.dirname(full)
                while parent != root:
                    try:
                        os.rmdir(parent)
                    except OSError:
                        break
                    parent = os.path.dirname(parent)

    # Write new files
    for path, blob_sha in new_files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        _, data = read_object(blob_sha, repo_root=root)
        with open(full, "wb") as f:
            f.write(data)

    # Update index
    write_index(new_files, repo_root=root)


def cmd_merge(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if not args:
        print("usage: mini-git merge <branch>", file=sys.stderr)
        sys.exit(1)

    target = args[0]

    # Resolve target
    target_sha = resolve_ref(f"refs/heads/{target}", repo_root=root)
    if not target_sha:
        # Try as remote tracking ref
        target_sha = resolve_ref(f"refs/remotes/{target}", repo_root=root)
    if not target_sha:
        # Try to split as remote/branch
        parts = target.split("/", 1)
        if len(parts) == 2:
            target_sha = resolve_ref(f"refs/remotes/{parts[0]}/{parts[1]}", repo_root=root)
    if not target_sha:
        target_sha = resolve_ref(target, repo_root=root)
    if not target_sha:
        print(f"error: branch '{target}' not found.", file=sys.stderr)
        sys.exit(1)

    head_sha = get_head_commit(repo_root=root)
    if not head_sha:
        # No commits on current branch - just fast-forward
        detached, ref = get_head_ref(repo_root=root)
        if not detached:
            set_ref(ref, target_sha, repo_root=root)
        _checkout_tree(target_sha, root)
        print(f"Fast-forward to {target_sha[:7]}")
        return

    if head_sha == target_sha:
        print("Already up to date.")
        return

    # Check if target is ancestor of HEAD (already merged)
    if _is_ancestor(target_sha, head_sha, root):
        print("Already up to date.")
        return

    # Check for fast-forward: if HEAD is ancestor of target
    if _is_ancestor(head_sha, target_sha, root):
        detached, ref = get_head_ref(repo_root=root)
        if not detached:
            set_ref(ref, target_sha, repo_root=root)
        else:
            head_file = repo_path("HEAD", repo_root=root)
            with open(head_file, "w") as f:
                f.write(target_sha + "\n")
        _checkout_tree(target_sha, root)
        print(f"Fast-forward")
        return

    # Non-fast-forward merge: create merge commit
    # Find merge base
    base_sha = _find_merge_base(head_sha, target_sha, root)

    # Get trees
    head_info = parse_commit(head_sha, repo_root=root)
    target_info = parse_commit(target_sha, repo_root=root)

    head_files = dict(flatten_tree(head_info["tree"], repo_root=root))
    target_files = dict(flatten_tree(target_info["tree"], repo_root=root))
    base_files = {}
    if base_sha:
        base_info = parse_commit(base_sha, repo_root=root)
        if base_info and base_info["tree"]:
            base_files = dict(flatten_tree(base_info["tree"], repo_root=root))

    # Three-way merge
    merged = {}
    conflict = False
    all_paths = sorted(set(list(head_files.keys()) + list(target_files.keys()) +
                           list(base_files.keys())))
    for path in all_paths:
        in_base = path in base_files
        in_head = path in head_files
        in_target = path in target_files

        base_blob = base_files.get(path)
        head_blob = head_files.get(path)
        target_blob = target_files.get(path)

        if head_blob == target_blob:
            if head_blob:
                merged[path] = head_blob
            continue

        if in_base:
            if head_blob == base_blob:
                # Only target changed
                if target_blob:
                    merged[path] = target_blob
                # else: target deleted
                continue
            if target_blob == base_blob:
                # Only head changed
                if head_blob:
                    merged[path] = head_blob
                # else: head deleted
                continue
            # Both changed differently - conflict
            conflict = True
            merged_content = _merge_conflict_content(
                path, base_blob, head_blob, target_blob, root)
            merged[path] = hash_object(merged_content, "blob", True, repo_root=root)
        else:
            # File added in one or both
            if in_head and not in_target:
                merged[path] = head_blob
            elif in_target and not in_head:
                merged[path] = target_blob
            else:
                # Both added differently
                conflict = True
                merged_content = _merge_conflict_content(
                    path, None, head_blob, target_blob, root)
                merged[path] = hash_object(merged_content, "blob", True, repo_root=root)

    # Write merged files to working tree and index
    for path, blob_sha in merged.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        _, data = read_object(blob_sha, repo_root=root)
        with open(full, "wb") as f:
            f.write(data)
    write_index(merged, repo_root=root)

    if conflict:
        print("Merge conflict detected. Resolve conflicts and commit.")
        return

    # Create merge commit
    tree_sha = build_tree_from_index(merged, repo_root=root)
    author_name = os.environ.get("GIT_AUTHOR_NAME", "Mini Git User")
    author_email = os.environ.get("GIT_AUTHOR_EMAIL", "user@example.com")
    ts = int(time.time())
    tz = "+0000"
    author_line = f"{author_name} <{author_email}> {ts} {tz}"
    message = f"Merge {target} into {get_current_branch(repo_root=root) or 'HEAD'}"
    lines = [f"tree {tree_sha}", f"parent {head_sha}", f"parent {target_sha}",
             f"author {author_line}", f"committer {author_line}", "", message]
    commit_data = "\n".join(lines).encode()
    commit_sha = hash_object(commit_data, "commit", True, repo_root=root)
    detached, ref = get_head_ref(repo_root=root)
    if not detached:
        set_ref(ref, commit_sha, repo_root=root)
    else:
        head_file = repo_path("HEAD", repo_root=root)
        with open(head_file, "w") as f:
            f.write(commit_sha + "\n")
    print(f"Merge made by the 'recursive' strategy.")


def _merge_conflict_content(path, base_blob, head_blob, target_blob, root):
    head_content = b""
    target_content = b""
    if head_blob:
        _, data = read_object(head_blob, repo_root=root)
        head_content = data or b""
    if target_blob:
        _, data = read_object(target_blob, repo_root=root)
        target_content = data or b""
    result = b"<<<<<<< HEAD\n"
    result += head_content
    if not head_content.endswith(b"\n"):
        result += b"\n"
    result += b"=======\n"
    result += target_content
    if not target_content.endswith(b"\n"):
        result += b"\n"
    result += b">>>>>>> merge\n"
    return result


def _is_ancestor(maybe_ancestor, descendant, root):
    """Check if maybe_ancestor is an ancestor of descendant."""
    visited = set()
    stack = [descendant]
    while stack:
        sha = stack.pop()
        if sha == maybe_ancestor:
            return True
        if sha in visited:
            continue
        visited.add(sha)
        info = parse_commit(sha, repo_root=root)
        if info:
            stack.extend(info["parents"])
    return False


def _find_merge_base(sha1, sha2, root):
    """Find a common ancestor (simple BFS approach)."""
    ancestors1 = set()
    stack = [sha1]
    while stack:
        sha = stack.pop()
        if sha in ancestors1:
            continue
        ancestors1.add(sha)
        info = parse_commit(sha, repo_root=root)
        if info:
            stack.extend(info["parents"])

    stack = [sha2]
    visited = set()
    while stack:
        sha = stack.pop(0)
        if sha in visited:
            continue
        visited.add(sha)
        if sha in ancestors1:
            return sha
        info = parse_commit(sha, repo_root=root)
        if info:
            stack.extend(info["parents"])
    return None


def cmd_tag(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if not args:
        # List tags
        tags_dir = repo_path("refs", "tags", repo_root=root)
        if os.path.isdir(tags_dir):
            for name in sorted(os.listdir(tags_dir)):
                print(name)
        return

    tag_name = args[0]
    target = args[1] if len(args) > 1 else None

    if target:
        sha = resolve_ref(f"refs/heads/{target}", repo_root=root) or target
    else:
        sha = get_head_commit(repo_root=root)

    if not sha:
        print("fatal: cannot create tag without a commit", file=sys.stderr)
        sys.exit(1)

    tag_file = repo_path("refs", "tags", tag_name, repo_root=root)
    if os.path.exists(tag_file):
        print(f"fatal: tag '{tag_name}' already exists", file=sys.stderr)
        sys.exit(1)

    set_ref(f"refs/tags/{tag_name}", sha, repo_root=root)
    print(f"Tagged {sha[:7]} as {tag_name}")


# ─── remote commands ────────────────────────────────────────────────────────

def cmd_remote(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if not args or args[0] in ("-v", "list"):
        # List remotes
        cfg = read_config(repo_root=root)
        found = False
        for section in sorted(cfg.sections()):
            if section.startswith('remote "') and section.endswith('"'):
                name = section[8:-1]
                url = cfg.get(section, "url", fallback="")
                print(f"{name}\t{url}")
                found = True
        return

    subcmd = args[0]

    if subcmd == "add":
        if len(args) < 3:
            print("usage: mini-git remote add <name> <url>", file=sys.stderr)
            sys.exit(1)
        name = args[1]
        url = args[2]
        cfg = read_config(repo_root=root)
        section = f'remote "{name}"'
        if cfg.has_section(section):
            print(f"fatal: remote {name} already exists.", file=sys.stderr)
            sys.exit(1)
        cfg.add_section(section)
        cfg.set(section, "url", url)
        write_config(cfg, repo_root=root)
        return

    if subcmd == "remove" or subcmd == "rm":
        if len(args) < 2:
            print("usage: mini-git remote remove <name>", file=sys.stderr)
            sys.exit(1)
        name = args[1]
        cfg = read_config(repo_root=root)
        section = f'remote "{name}"'
        if not cfg.has_section(section):
            print(f"fatal: No such remote: '{name}'", file=sys.stderr)
            sys.exit(1)
        cfg.remove_section(section)
        write_config(cfg, repo_root=root)
        # Also remove remote tracking refs
        remote_refs_dir = repo_path("refs", "remotes", name, repo_root=root)
        if os.path.isdir(remote_refs_dir):
            shutil.rmtree(remote_refs_dir)
        return

    print(f"error: Unknown subcommand: {subcmd}", file=sys.stderr)
    sys.exit(1)


def _get_remote_url(remote_name, repo_root=None):
    """Get URL for a named remote. Returns the URL string or exits on error."""
    cfg = read_config(repo_root=repo_root)
    section = f'remote "{remote_name}"'
    if not cfg.has_section(section):
        print(f"fatal: '{remote_name}' does not appear to be a git repository",
              file=sys.stderr)
        sys.exit(1)
    return cfg.get(section, "url", fallback="")


def _collect_all_objects(sha, repo_root, collected=None):
    """Recursively collect all object SHAs reachable from sha."""
    if collected is None:
        collected = set()
    if sha in collected:
        return collected
    obj_type, data = read_object(sha, repo_root=repo_root)
    if obj_type is None:
        return collected
    collected.add(sha)
    if obj_type == "commit":
        info = parse_commit(sha, repo_root=repo_root)
        if info:
            if info["tree"]:
                _collect_all_objects(info["tree"], repo_root, collected)
            for parent in info["parents"]:
                _collect_all_objects(parent, repo_root, collected)
    elif obj_type == "tree":
        for mode, name, entry_sha in read_tree_entries(sha, repo_root=repo_root):
            _collect_all_objects(entry_sha, repo_root, collected)
    return collected


def _copy_objects(from_root, to_root, shas):
    """Copy object files from one repo to another."""
    for sha in shas:
        src = repo_path("objects", sha[:2], sha[2:], repo_root=from_root)
        dst = repo_path("objects", sha[:2], sha[2:], repo_root=to_root)
        if os.path.exists(dst):
            continue
        if not os.path.exists(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def _get_remote_refs(remote_root):
    """Get all refs from a remote repo. Returns dict {ref_path: sha}."""
    refs = {}
    heads_dir = os.path.join(remote_root, ".git", "refs", "heads")
    if os.path.isdir(heads_dir):
        for name in os.listdir(heads_dir):
            ref_file = os.path.join(heads_dir, name)
            if os.path.isfile(ref_file):
                sha = open(ref_file).read().strip()
                refs[f"refs/heads/{name}"] = sha
    return refs


def cmd_fetch(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if not args:
        print("usage: mini-git fetch <remote>", file=sys.stderr)
        sys.exit(1)

    remote_name = args[0]
    remote_url = _get_remote_url(remote_name, repo_root=root)

    # For local paths, remote_url is a directory path
    remote_root = os.path.abspath(remote_url)
    if not os.path.isdir(os.path.join(remote_root, ".git")):
        print(f"fatal: '{remote_url}' does not appear to be a git repository",
              file=sys.stderr)
        sys.exit(1)

    # Read remote refs
    remote_refs = _get_remote_refs(remote_root)

    # For each remote ref, collect all objects and copy them
    for ref_path, sha in remote_refs.items():
        # Collect all objects reachable from this sha
        objects = _collect_all_objects(sha, remote_root)
        _copy_objects(remote_root, root, objects)

        # Update remote tracking ref
        # refs/heads/master -> refs/remotes/<remote>/master
        if ref_path.startswith("refs/heads/"):
            branch = ref_path[len("refs/heads/"):]
            tracking_ref = f"refs/remotes/{remote_name}/{branch}"
            set_ref(tracking_ref, sha, repo_root=root)

    print(f"From {remote_url}")
    for ref_path, sha in remote_refs.items():
        if ref_path.startswith("refs/heads/"):
            branch = ref_path[len("refs/heads/"):]
            print(f" * [{sha[:7]}] {remote_name}/{branch}")


def cmd_pull(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if len(args) < 2:
        print("usage: mini-git pull <remote> <branch>", file=sys.stderr)
        sys.exit(1)

    remote_name = args[0]
    branch = args[1]

    # Fetch first
    cmd_fetch([remote_name])

    # Then merge the remote tracking branch
    tracking_ref = f"refs/remotes/{remote_name}/{branch}"
    tracking_sha = resolve_ref(tracking_ref, repo_root=root)
    if not tracking_sha:
        print(f"fatal: no tracking ref for {remote_name}/{branch}", file=sys.stderr)
        sys.exit(1)

    # Merge
    head_sha = get_head_commit(repo_root=root)
    if not head_sha:
        # No commits - just set HEAD to tracking ref
        detached, ref = get_head_ref(repo_root=root)
        if not detached:
            set_ref(ref, tracking_sha, repo_root=root)
        _checkout_tree(tracking_sha, root)
        print(f"Fast-forward to {tracking_sha[:7]}")
        return

    # Use the merge machinery
    cmd_merge([f"{remote_name}/{branch}"])


def cmd_push(args):
    root = find_repo_root()
    if root is None:
        print("fatal: not a mini-git repository", file=sys.stderr)
        sys.exit(1)

    if len(args) < 2:
        print("usage: mini-git push <remote> <branch>", file=sys.stderr)
        sys.exit(1)

    remote_name = args[0]
    branch = args[1]
    remote_url = _get_remote_url(remote_name, repo_root=root)

    remote_root = os.path.abspath(remote_url)
    if not os.path.isdir(os.path.join(remote_root, ".git")):
        print(f"fatal: '{remote_url}' does not appear to be a git repository",
              file=sys.stderr)
        sys.exit(1)

    # Get the local branch sha
    local_sha = resolve_ref(f"refs/heads/{branch}", repo_root=root)
    if not local_sha:
        print(f"error: src refspec {branch} does not match any", file=sys.stderr)
        sys.exit(1)

    # Collect all objects reachable from local branch
    objects = _collect_all_objects(local_sha, root)

    # Copy to remote
    _copy_objects(root, remote_root, objects)

    # Update remote's ref
    set_ref(f"refs/heads/{branch}", local_sha, repo_root=remote_root)

    # Update our remote-tracking ref too
    set_ref(f"refs/remotes/{remote_name}/{branch}", local_sha, repo_root=root)

    print(f"To {remote_url}")
    print(f"   {local_sha[:7]}  {branch} -> {branch}")


# ─── main dispatch ──────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("usage: mini-git <command> [<args>]")
        print()
        print("Commands:")
        print("  init          Create an empty repository")
        print("  hash-object   Compute object hash and optionally store")
        print("  cat-file      Display object contents")
        print("  add           Add file contents to the index")
        print("  commit        Record changes to the repository")
        print("  log           Show commit logs")
        print("  status        Show the working tree status")
        print("  diff          Show changes")
        print("  branch        List, create, or delete branches")
        print("  checkout      Switch branches or restore files")
        print("  merge         Join two development histories")
        print("  tag           Create, list tags")
        print("  remote        Manage remotes")
        print("  fetch         Download objects and refs from remote")
        print("  pull          Fetch and merge from remote")
        print("  push          Send objects and refs to remote")
        sys.exit(1)

    cmd = sys.argv[1]
    cmd_args = sys.argv[2:]

    commands = {
        "init": cmd_init,
        "hash-object": cmd_hash_object,
        "cat-file": cmd_cat_file,
        "add": cmd_add,
        "commit": cmd_commit,
        "log": cmd_log,
        "status": cmd_status,
        "diff": cmd_diff,
        "branch": cmd_branch,
        "checkout": cmd_checkout,
        "merge": cmd_merge,
        "tag": cmd_tag,
        "remote": cmd_remote,
        "fetch": cmd_fetch,
        "pull": cmd_pull,
        "push": cmd_push,
    }

    if cmd not in commands:
        print(f"mini-git: '{cmd}' is not a command.", file=sys.stderr)
        sys.exit(1)

    commands[cmd](cmd_args)


if __name__ == "__main__":
    main()
