#!/usr/bin/env python3
import argparse
import configparser
import dataclasses
import datetime as dt
import difflib
import hashlib
import os
import shutil
import sys
import time
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class MiniGitError(Exception):
    pass


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def repo_find(start: Optional[Path] = None) -> Path:
    path = (start or Path.cwd()).resolve()
    while True:
        if (path / ".git").is_dir():
            return path
        if path.parent == path:
            raise MiniGitError("not a mini-git repository (or any of the parent directories): .git")
        path = path.parent


def repo_git_dir(repo: Path) -> Path:
    return repo / ".git"


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def read_text(path: Path, default: Optional[str] = None) -> str:
    if not path.exists():
        if default is not None:
            return default
        raise MiniGitError(f"missing file: {path}")
    return path.read_text(encoding="utf-8")


def write_text(path: Path, data: str):
    ensure_parent(path)
    path.write_text(data, encoding="utf-8")


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def write_bytes(path: Path, data: bytes):
    ensure_parent(path)
    path.write_bytes(data)


def format_git_time(ts: Optional[int] = None) -> str:
    if ts is None:
        ts = int(time.time())
    local = dt.datetime.fromtimestamp(ts).astimezone()
    offset = local.strftime("%z")
    return f"{ts} {offset}"


def parse_author_env() -> str:
    name = os.environ.get("GIT_AUTHOR_NAME") or os.environ.get("MGIT_AUTHOR_NAME") or "Mini Git"
    email = os.environ.get("GIT_AUTHOR_EMAIL") or os.environ.get("MGIT_AUTHOR_EMAIL") or "mini-git@example.com"
    return f"{name} <{email}>"


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


@dataclasses.dataclass
class GitObject:
    type: str
    data: bytes


class ObjectStore:
    def __init__(self, repo: Path):
        self.repo = repo
        self.objects = repo_git_dir(repo) / "objects"

    def object_path(self, oid: str) -> Path:
        return self.objects / oid[:2] / oid[2:]

    def hash_object(self, obj_type: str, data: bytes, write: bool = True) -> str:
        raw = f"{obj_type} {len(data)}".encode() + b"\x00" + data
        oid = sha1_hex(raw)
        if write:
            path = self.object_path(oid)
            if not path.exists():
                ensure_parent(path)
                path.write_bytes(zlib.compress(raw))
        return oid

    def read_object(self, oid: str) -> GitObject:
        path = self.object_path(oid)
        if not path.exists():
            raise MiniGitError(f"object not found: {oid}")
        raw = zlib.decompress(path.read_bytes())
        actual = sha1_hex(raw)
        if actual != oid:
            raise MiniGitError(f"object corruption detected for {oid}: content hash mismatch")
        nul = raw.index(b"\x00")
        header = raw[:nul].decode()
        obj_type, size_s = header.split(" ", 1)
        data = raw[nul + 1 :]
        if len(data) != int(size_s):
            raise MiniGitError(f"object corruption detected for {oid}: size mismatch")
        return GitObject(obj_type, data)

    def resolve_prefix(self, prefix: str) -> str:
        if len(prefix) == 40:
            return prefix
        if len(prefix) < 2:
            raise MiniGitError("short SHA1 prefix must be at least 2 characters")
        dirp = self.objects / prefix[:2]
        if not dirp.exists():
            raise MiniGitError(f"unknown revision: {prefix}")
        matches = [prefix[:2] + p.name for p in dirp.iterdir() if p.name.startswith(prefix[2:])]
        if not matches:
            raise MiniGitError(f"unknown revision: {prefix}")
        if len(matches) > 1:
            raise MiniGitError(f"ambiguous revision: {prefix}")
        return matches[0]


def tree_entry(mode: str, name: str, oid: str) -> bytes:
    return mode.encode() + b" " + name.encode() + b"\x00" + bytes.fromhex(oid)


def parse_tree(data: bytes) -> List[Tuple[str, str, str]]:
    out = []
    i = 0
    while i < len(data):
        j = data.index(b" ", i)
        mode = data[i:j].decode()
        k = data.index(b"\x00", j)
        name = data[j + 1 : k].decode()
        oid = data[k + 1 : k + 21].hex()
        out.append((mode, name, oid))
        i = k + 21
    return out


def parse_commit(data: bytes) -> Dict[str, object]:
    text = data.decode()
    headers, _, message = text.partition("\n\n")
    result: Dict[str, object] = {"message": message}
    parents: List[str] = []
    for line in headers.splitlines():
        key, value = line.split(" ", 1)
        if key == "parent":
            parents.append(value)
        elif key == "tree":
            result["tree"] = value
        elif key == "author":
            result["author"] = value
        elif key == "committer":
            result["committer"] = value
    result["parents"] = parents
    return result


class Index:
    def __init__(self, repo: Path):
        self.path = repo_git_dir(repo) / "index"

    def load(self) -> Dict[str, str]:
        if not self.path.exists():
            return {}
        out = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            oid, path = line.split(" ", 1)
            out[path] = oid
        return out

    def save(self, entries: Dict[str, str]):
        lines = [f"{oid} {path}" for path, oid in sorted(entries.items())]
        write_text(self.path, "\n".join(lines) + ("\n" if lines else ""))


class Repo:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.git = repo_git_dir(self.root)
        self.store = ObjectStore(self.root)
        self.index = Index(self.root)

    @staticmethod
    def init(directory: Path) -> "Repo":
        root = directory.resolve()
        git = root / ".git"
        (git / "objects").mkdir(parents=True, exist_ok=True)
        (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        (git / "refs" / "stash").mkdir(parents=True, exist_ok=True)
        (git / "refs" / "remotes").mkdir(parents=True, exist_ok=True)
        if not (git / "HEAD").exists():
            write_text(git / "HEAD", "ref: refs/heads/main\n")
        if not (git / "config").exists():
            write_text(git / "config", "[core]\n\trepositoryformatversion = 0\n")
        if not (git / "refs" / "heads" / "main").exists():
            write_text(git / "refs" / "heads" / "main", "")
        return Repo(root)

    @staticmethod
    def discover() -> "Repo":
        return Repo(repo_find())

    def relpath(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def head_ref(self) -> Optional[str]:
        head = read_text(self.git / "HEAD").strip()
        if head.startswith("ref: "):
            return head[5:]
        return None

    def head_oid(self) -> Optional[str]:
        head = read_text(self.git / "HEAD").strip()
        if head.startswith("ref: "):
            ref = self.git / head[5:]
            if not ref.exists():
                return None
            value = ref.read_text(encoding="utf-8").strip()
            return value or None
        return head or None

    def update_head(self, oid: str):
        ref = self.head_ref()
        if ref:
            write_text(self.git / ref, oid + "\n")
        else:
            write_text(self.git / "HEAD", oid + "\n")

    def set_head_ref(self, ref: str):
        write_text(self.git / "HEAD", f"ref: {ref}\n")

    def read_ref(self, ref: str) -> Optional[str]:
        p = self.git / ref
        if not p.exists():
            return None
        value = p.read_text(encoding="utf-8").strip()
        return value or None

    def write_ref(self, ref: str, oid: str):
        write_text(self.git / ref, oid + "\n")

    def current_branch(self) -> Optional[str]:
        ref = self.head_ref()
        if ref and ref.startswith("refs/heads/"):
            return ref.split("/", 2)[2]
        return None

    def resolve_rev(self, name: Optional[str]) -> Optional[str]:
        if name is None:
            return self.head_oid()
        if name == "HEAD":
            return self.head_oid()
        if (self.git / "refs" / "heads" / name).exists():
            return self.read_ref(f"refs/heads/{name}")
        if (self.git / "refs" / "remotes" / name).exists():
            return self.read_ref(f"refs/remotes/{name}")
        try:
            return self.store.resolve_prefix(name)
        except MiniGitError:
            pass
        raise MiniGitError(f"unknown revision or branch: {name}")

    def get_commit(self, oid: str) -> Dict[str, object]:
        obj = self.store.read_object(oid)
        if obj.type != "commit":
            raise MiniGitError(f"{oid} is not a commit")
        c = parse_commit(obj.data)
        c["oid"] = oid
        return c

    def commit_tree_oid(self, oid: Optional[str]) -> Optional[str]:
        if not oid:
            return None
        return self.get_commit(oid)["tree"]  # type: ignore[index]

    def read_tree_recursive(self, tree_oid: str, prefix: str = "") -> Dict[str, str]:
        obj = self.store.read_object(tree_oid)
        if obj.type != "tree":
            raise MiniGitError("expected tree object")
        out: Dict[str, str] = {}
        for mode, name, oid in parse_tree(obj.data):
            path = f"{prefix}{name}"
            if mode == "40000":
                out.update(self.read_tree_recursive(oid, path + "/"))
            else:
                out[path] = oid
        return out

    def snapshot_from_commit(self, commit_oid: Optional[str]) -> Dict[str, str]:
        tree_oid = self.commit_tree_oid(commit_oid)
        if not tree_oid:
            return {}
        return self.read_tree_recursive(tree_oid)

    def build_tree_from_index(self, entries: Dict[str, str]) -> str:
        nested: Dict[str, object] = {}
        for path, oid in entries.items():
            parts = path.split("/")
            d = nested
            for p in parts[:-1]:
                d = d.setdefault(p, {})  # type: ignore[assignment]
            d[parts[-1]] = oid

        def write_dir(d: Dict[str, object]) -> str:
            items = []
            for name in sorted(d):
                value = d[name]
                if isinstance(value, dict):
                    child_oid = write_dir(value)
                    items.append(("40000", name, child_oid))
                else:
                    items.append(("100644", name, value))
            raw = b"".join(tree_entry(mode, name, oid) for mode, name, oid in items)
            return self.store.hash_object("tree", raw, write=True)

        return write_dir(nested)

    def scan_working_files(self) -> Dict[str, Path]:
        out = {}
        for p in self.root.rglob("*"):
            if p.is_dir():
                if p.name == ".git":
                    dirs = []
                    continue
                continue
            try:
                rel = p.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if rel.startswith(".git/") or rel == ".git":
                continue
            out[rel] = p
        return out

    def write_working_tree(self, snapshot: Dict[str, str]):
        existing = self.scan_working_files()
        for rel in list(existing):
            if rel not in snapshot:
                (self.root / rel).unlink()
        dirs = sorted(
            [p for p in self.root.rglob("*") if p.is_dir() and ".git" not in p.parts],
            key=lambda x: len(x.parts),
            reverse=True,
        )
        for d in dirs:
            try:
                next(d.iterdir())
            except StopIteration:
                d.rmdir()
            except Exception:
                pass
        for rel, oid in snapshot.items():
            obj = self.store.read_object(oid)
            if obj.type != "blob":
                raise MiniGitError("tree entry does not point to blob")
            target = self.root / rel
            ensure_parent(target)
            target.write_bytes(obj.data)

    def has_uncommitted_changes(self) -> bool:
        head = self.snapshot_from_commit(self.head_oid())
        idx = self.index.load()
        if idx != head:
            return True
        wt = self.working_snapshot_to_blobs(write=False)
        return wt != idx

    def working_snapshot_to_blobs(self, write: bool = False) -> Dict[str, str]:
        out = {}
        for rel, path in self.scan_working_files().items():
            data = path.read_bytes()
            oid = self.store.hash_object("blob", data, write=write)
            out[rel] = oid
        return out

    def ancestors(self, oid: Optional[str]) -> List[str]:
        out = []
        while oid:
            out.append(oid)
            commit = self.get_commit(oid)
            parents = commit["parents"]  # type: ignore[index]
            oid = parents[0] if parents else None
        return out

    def is_ancestor(self, anc: Optional[str], desc: Optional[str]) -> bool:
        if anc is None:
            return True
        while desc:
            if desc == anc:
                return True
            commit = self.get_commit(desc)
            parents = commit["parents"]  # type: ignore[index]
            desc = parents[0] if parents else None
        return False

    def merge_base(self, a: Optional[str], b: Optional[str]) -> Optional[str]:
        if a is None or b is None:
            return None
        ancestors_a = set(self.ancestors(a))
        cur = b
        while cur:
            if cur in ancestors_a:
                return cur
            commit = self.get_commit(cur)
            parents = commit["parents"]  # type: ignore[index]
            cur = parents[0] if parents else None
        return None

    def load_config(self) -> configparser.ConfigParser:
        cfg = configparser.ConfigParser()
        path = self.git / "config"
        if path.exists():
            cfg.read(path, encoding="utf-8")
        return cfg

    def save_config(self, cfg: configparser.ConfigParser):
        with (self.git / "config").open("w", encoding="utf-8") as f:
            cfg.write(f)

    def add_remote(self, name: str, url: str):
        cfg = self.load_config()
        section = f'remote "{name}"'
        if cfg.has_section(section):
            raise MiniGitError(f"remote '{name}' already exists")
        cfg.add_section(section)
        cfg.set(section, "url", url)
        self.save_config(cfg)

    def remove_remote(self, name: str):
        cfg = self.load_config()
        section = f'remote "{name}"'
        if not cfg.has_section(section):
            raise MiniGitError(f"remote '{name}' does not exist")
        cfg.remove_section(section)
        self.save_config(cfg)

    def list_remotes(self) -> List[Tuple[str, str]]:
        cfg = self.load_config()
        out = []
        for section in cfg.sections():
            if section.startswith('remote "') and section.endswith('"'):
                name = section[len('remote "') : -1]
                url = cfg.get(section, "url", fallback="")
                out.append((name, url))
        out.sort()
        return out

    def get_remote_url(self, name: str) -> str:
        cfg = self.load_config()
        section = f'remote "{name}"'
        if not cfg.has_section(section):
            raise MiniGitError(f"remote '{name}' does not exist")
        url = cfg.get(section, "url", fallback="").strip()
        if not url:
            raise MiniGitError(f"remote '{name}' has no url configured")
        return url


def resolve_remote_git_dir(url: str) -> Path:
    p = Path(url).expanduser()
    if p.name == ".git" and p.is_dir():
        return p.resolve()
    git = p / ".git"
    if git.is_dir():
        return git.resolve()
    raise MiniGitError(f"unsupported remote or invalid local path: {url}")


def copy_object_if_missing(src_objects: Path, dst_objects: Path, oid: str):
    src = src_objects / oid[:2] / oid[2:]
    dst = dst_objects / oid[:2] / oid[2:]
    if not src.exists():
        raise MiniGitError(f"remote object not found: {oid}")
    if dst.exists():
        return
    ensure_parent(dst)
    shutil.copy2(src, dst)


def collect_reachable_objects_from_commit(git_dir: Path, oid: Optional[str], seen: Optional[set] = None) -> set:
    if seen is None:
        seen = set()
    if not oid or oid in seen:
        return seen
    seen.add(oid)
    obj_path = git_dir / "objects" / oid[:2] / oid[2:]
    if not obj_path.exists():
        raise MiniGitError(f"object not found in repository: {oid}")
    raw = zlib.decompress(obj_path.read_bytes())
    nul = raw.index(b"\x00")
    header = raw[:nul].decode()
    obj_type, _ = header.split(" ", 1)
    data = raw[nul + 1 :]
    if obj_type == "commit":
        commit = parse_commit(data)
        tree_oid = commit.get("tree")
        if tree_oid:
            collect_reachable_objects_from_commit_tree(git_dir, str(tree_oid), seen)
        for parent in commit.get("parents", []):  # type: ignore[union-attr]
            collect_reachable_objects_from_commit(git_dir, parent, seen)
    return seen


def collect_reachable_objects_from_commit_tree(git_dir: Path, tree_oid: str, seen: set):
    if tree_oid in seen:
        return
    seen.add(tree_oid)
    obj_path = git_dir / "objects" / tree_oid[:2] / tree_oid[2:]
    if not obj_path.exists():
        raise MiniGitError(f"object not found in repository: {tree_oid}")
    raw = zlib.decompress(obj_path.read_bytes())
    nul = raw.index(b"\x00")
    header = raw[:nul].decode()
    obj_type, _ = header.split(" ", 1)
    if obj_type != "tree":
        raise MiniGitError(f"expected tree object, got {obj_type}")
    data = raw[nul + 1 :]
    for mode, _name, oid in parse_tree(data):
        if oid in seen:
            continue
        if mode == "40000":
            collect_reachable_objects_from_commit_tree(git_dir, oid, seen)
        else:
            seen.add(oid)


def read_ref_file(git_dir: Path, ref: str) -> Optional[str]:
    p = git_dir / ref
    if not p.exists():
        return None
    value = p.read_text(encoding="utf-8").strip()
    return value or None


def iter_refs_under(git_dir: Path, base_ref: str) -> List[Tuple[str, str]]:
    base = git_dir / base_ref
    out: List[Tuple[str, str]] = []
    if not base.exists():
        return out
    for p in sorted(base.rglob("*")):
        if p.is_file():
            rel = p.relative_to(git_dir).as_posix()
            val = p.read_text(encoding="utf-8").strip()
            if val:
                out.append((rel, val))
    return out


def cmd_init(args):
    directory = Path(args.directory or ".")
    directory.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(directory)
    print(f"Initialized empty Git repository in {repo.git}")


def add_paths(repo: Repo, paths: List[str]):
    entries = repo.index.load()
    for p in paths:
        if p == ".":
            candidates = list(repo.scan_working_files().items())
        else:
            abs_p = (repo.root / p).resolve()
            if not abs_p.exists():
                if p in entries:
                    del entries[p]
                    continue
                raise MiniGitError(f"pathspec '{p}' did not match any files")
            if abs_p.is_dir():
                candidates = []
                for f in abs_p.rglob("*"):
                    if f.is_file() and ".git" not in f.parts:
                        rel = f.relative_to(repo.root).as_posix()
                        candidates.append((rel, f))
            else:
                candidates = [(abs_p.relative_to(repo.root).as_posix(), abs_p)]
        for rel, filep in candidates:
            data = filep.read_bytes()
            oid = repo.store.hash_object("blob", data, write=True)
            entries[rel] = oid
    repo.index.save(entries)


def cmd_add(args):
    repo = Repo.discover()
    add_paths(repo, args.paths)


def status_data(repo: Repo):
    head = repo.snapshot_from_commit(repo.head_oid())
    idx = repo.index.load()
    wt = repo.working_snapshot_to_blobs(write=False)

    staged = []
    for path in sorted(set(head) | set(idx)):
        h = head.get(path)
        i = idx.get(path)
        if h != i:
            if h is None and i is not None:
                staged.append(("new file", path))
            elif h is not None and i is None:
                staged.append(("deleted", path))
            else:
                staged.append(("modified", path))

    not_staged = []
    for path in sorted(set(idx) | set(wt)):
        i = idx.get(path)
        w = wt.get(path)
        if i != w:
            if i is not None and w is None:
                not_staged.append(("deleted", path))
            elif i is None and w is not None:
                continue
            else:
                not_staged.append(("modified", path))

    untracked = [p for p in sorted(wt) if p not in idx]
    return staged, not_staged, untracked


def cmd_status(args):
    repo = Repo.discover()
    branch = repo.current_branch() or "(detached HEAD)"
    print(f"On branch {branch}" if branch != "(detached HEAD)" else "HEAD detached")
    print()
    staged, not_staged, untracked = status_data(repo)
    if staged:
        print("Changes to be committed:")
        for kind, path in staged:
            print(f"\t{kind}:   {path}")
        print()
    if not_staged:
        print("Changes not staged for commit:")
        for kind, path in not_staged:
            print(f"\t{kind}:   {path}")
        print()
    if untracked:
        print("Untracked files:")
        for path in untracked:
            print(f"\t{path}")
        print()
    if not any([staged, not_staged, untracked]):
        print("nothing to commit, working tree clean")


def cmd_commit(args):
    repo = Repo.discover()
    idx = repo.index.load()
    head = repo.head_oid()
    head_snapshot = repo.snapshot_from_commit(head)
    if idx == head_snapshot:
        raise MiniGitError("nothing to commit")
    tree_oid = repo.build_tree_from_index(idx)
    author = parse_author_env()
    when = format_git_time()
    lines = [f"tree {tree_oid}"]
    if head:
        lines.append(f"parent {head}")
    lines.append(f"author {author} {when}")
    lines.append(f"committer {author} {when}")
    lines.append("")
    lines.append(args.message)
    data = "\n".join(lines).encode()
    oid = repo.store.hash_object("commit", data, write=True)
    repo.update_head(oid)
    branch = repo.current_branch() or "detached"
    short = oid[:7]
    changed = len(set(idx) | set(head_snapshot))
    print(f"[{branch} {short}] {args.message}")
    print(f" {changed} file changed")


def cmd_log(args):
    repo = Repo.discover()
    oid = repo.head_oid()
    while oid:
        commit = repo.get_commit(oid)
        message = str(commit["message"]).rstrip("\n")
        if args.oneline:
            first = message.splitlines()[0] if message else ""
            print(f"{oid[:7]} {first}")
        else:
            print(f"commit {oid}")
            print(f"Author: {commit.get('author','')}")
            print(f"Date:   {commit.get('committer','')}")
            print()
            for line in message.splitlines() or [""]:
                print(f"    {line}")
            print()
        parents = commit["parents"]  # type: ignore[index]
        oid = parents[0] if parents else None


def cmd_branch(args):
    repo = Repo.discover()
    heads = repo.git / "refs" / "heads"
    current = repo.current_branch()
    if args.delete:
        name = args.delete
        if name == current:
            raise MiniGitError("cannot delete the branch you are currently on")
        ref = heads / name
        if not ref.exists():
            raise MiniGitError(f"branch '{name}' not found")
        ref.unlink()
        print(f"Deleted branch {name}")
        return
    if args.name:
        target = repo.head_oid()
        if target is None:
            raise MiniGitError("cannot create branch without any commits")
        ref = heads / args.name
        if ref.exists():
            raise MiniGitError(f"branch '{args.name}' already exists")
        write_text(ref, target + "\n")
        return
    for ref in sorted(heads.iterdir()):
        mark = "*" if ref.name == current else " "
        print(f"{mark} {ref.name}")


def checkout_target(repo: Repo, target: str):
    branch_ref = repo.git / "refs" / "heads" / target
    oid = None
    refname = None
    if branch_ref.exists():
        refname = f"refs/heads/{target}"
        oid = repo.read_ref(refname)
    else:
        oid = repo.resolve_rev(target)
    if repo.has_uncommitted_changes():
        raise MiniGitError("your local changes would be overwritten by checkout")
    snapshot = repo.snapshot_from_commit(oid)
    repo.write_working_tree(snapshot)
    repo.index.save(snapshot)
    if refname:
        repo.set_head_ref(refname)
        print(f"Switched to branch '{target}'")
    else:
        write_text(repo.git / "HEAD", oid + "\n")
        print(f"Note: switching to '{target}'.")
    return oid


def cmd_checkout(args):
    repo = Repo.discover()
    if args.create:
        if repo.has_uncommitted_changes():
            raise MiniGitError("your local changes would be overwritten by checkout")
        if (repo.git / "refs" / "heads" / args.create).exists():
            raise MiniGitError(f"branch '{args.create}' already exists")
        base = repo.head_oid()
        if base is None:
            raise MiniGitError("cannot create branch without any commits")
        repo.write_ref(f"refs/heads/{args.create}", base)
        repo.set_head_ref(f"refs/heads/{args.create}")
        print(f"Switched to a new branch '{args.create}'")
        return
    checkout_target(repo, args.target)


def merge_blobs(base: Optional[bytes], ours: Optional[bytes], theirs: Optional[bytes], branch: str) -> Tuple[bytes, bool]:
    if ours == theirs:
        return ours or b"", False
    if base == ours:
        return theirs or b"", False
    if base == theirs:
        return ours or b"", False
    try:
        ours_s = (ours or b"").decode()
        theirs_s = (theirs or b"").decode()
    except UnicodeDecodeError:
        marker = b"<<<<<<< HEAD\n" + (ours or b"") + b"\n=======\n" + (theirs or b"") + b"\n>>>>>>> " + branch.encode() + b"\n"
        return marker, True
    merged = f"<<<<<<< HEAD\n{ours_s}=======\n{theirs_s}>>>>>>> {branch}\n".encode()
    return merged, True


def cmd_merge(args):
    repo = Repo.discover()
    if repo.has_uncommitted_changes():
        raise MiniGitError("commit or stash your changes before merging")
    current = repo.head_oid()
    other = repo.resolve_rev(args.branch)
    if other is None:
        raise MiniGitError("nothing to merge")
    if current is None:
        checkout_target(repo, args.branch)
        return
    if repo.is_ancestor(current, other):
        snapshot = repo.snapshot_from_commit(other)
        repo.write_working_tree(snapshot)
        repo.index.save(snapshot)
        repo.update_head(other)
        print("Fast-forward")
        return
    if repo.is_ancestor(other, current):
        print("Already up to date.")
        return
    base = repo.merge_base(current, other)
    base_snap = repo.snapshot_from_commit(base)
    our_snap = repo.snapshot_from_commit(current)
    their_snap = repo.snapshot_from_commit(other)
    paths = sorted(set(base_snap) | set(our_snap) | set(their_snap))
    merged: Dict[str, str] = {}
    conflicts = []
    for path in paths:
        b = base_snap.get(path)
        o = our_snap.get(path)
        t = their_snap.get(path)
        if o == t:
            if o is not None:
                merged[path] = o
            continue
        if b == o:
            if t is not None:
                merged[path] = t
            continue
        if b == t:
            if o is not None:
                merged[path] = o
            continue
        base_data = repo.store.read_object(b).data if b else None
        our_data = repo.store.read_object(o).data if o else None
        their_data = repo.store.read_object(t).data if t else None
        merged_data, conflicted = merge_blobs(base_data, our_data, their_data, args.branch)
        oid = repo.store.hash_object("blob", merged_data, write=True)
        merged[path] = oid
        if conflicted:
            conflicts.append(path)
    repo.index.save(merged)
    repo.write_working_tree(merged)
    if conflicts:
        print("Automatic merge failed; fix conflicts and commit the result.")
        for p in conflicts:
            print(f"CONFLICT: {p}")
        return
    tree_oid = repo.build_tree_from_index(merged)
    author = parse_author_env()
    when = format_git_time()
    msg = f"Merge branch '{args.branch}'"
    lines = [
        f"tree {tree_oid}",
        f"parent {current}",
        f"parent {other}",
        f"author {author} {when}",
        f"committer {author} {when}",
        "",
        msg,
    ]
    oid = repo.store.hash_object("commit", "\n".join(lines).encode(), write=True)
    repo.update_head(oid)
    print(f"Merge made commit {oid[:7]}")


def blob_map_from_commit(repo: Repo, oid: Optional[str]) -> Dict[str, bytes]:
    snap = repo.snapshot_from_commit(oid)
    out = {}
    for path, boid in snap.items():
        out[path] = repo.store.read_object(boid).data
    return out


def blob_map_from_index(repo: Repo) -> Dict[str, bytes]:
    idx = repo.index.load()
    out = {}
    for path, boid in idx.items():
        out[path] = repo.store.read_object(boid).data
    return out


def blob_map_from_worktree(repo: Repo) -> Dict[str, bytes]:
    out = {}
    for rel, p in repo.scan_working_files().items():
        out[rel] = p.read_bytes()
    return out


def unified_diff_maps(a: Dict[str, bytes], b: Dict[str, bytes], from_label: str, to_label: str) -> str:
    lines = []
    for path in sorted(set(a) | set(b)):
        ad = a.get(path)
        bd = b.get(path)
        if ad == bd:
            continue
        atext = (ad or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        btext = (bd or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        diff = difflib.unified_diff(atext, btext, fromfile=f"{from_label}/{path}", tofile=f"{to_label}/{path}")
        lines.extend(diff)
    return "".join(lines)


def cmd_diff(args):
    repo = Repo.discover()
    if args.commit1 and args.commit2:
        a = blob_map_from_commit(repo, repo.resolve_rev(args.commit1))
        b = blob_map_from_commit(repo, repo.resolve_rev(args.commit2))
        print(unified_diff_maps(a, b, args.commit1, args.commit2), end="")
        return
    if args.staged:
        a = blob_map_from_commit(repo, repo.head_oid())
        b = blob_map_from_index(repo)
        print(unified_diff_maps(a, b, "HEAD", "index"), end="")
        return
    a = blob_map_from_index(repo)
    b = blob_map_from_worktree(repo)
    print(unified_diff_maps(a, b, "index", "working"), end="")


def cmd_reset(args):
    repo = Repo.discover()
    mode = "mixed"
    if args.soft:
        mode = "soft"
    elif args.hard:
        mode = "hard"
    target = repo.resolve_rev(args.commit) if args.commit else repo.head_oid()
    if target is None:
        raise MiniGitError("no commit specified and HEAD is unborn")
    repo.update_head(target)
    snapshot = repo.snapshot_from_commit(target)
    if mode in ("mixed", "hard"):
        repo.index.save(snapshot)
    if mode == "hard":
        repo.write_working_tree(snapshot)


def stash_ref_path(repo: Repo) -> Path:
    return repo.git / "refs" / "stash" / "stack"


def load_stash(repo: Repo) -> List[str]:
    p = stash_ref_path(repo)
    if not p.exists():
        return []
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_stash(repo: Repo, stack: List[str]):
    write_text(stash_ref_path(repo), "\n".join(stack) + ("\n" if stack else ""))


def make_commit(repo: Repo, snapshot: Dict[str, str], message: str, parent: Optional[str]) -> str:
    tree_oid = repo.build_tree_from_index(snapshot)
    author = parse_author_env()
    when = format_git_time()
    lines = [f"tree {tree_oid}"]
    if parent:
        lines.append(f"parent {parent}")
    lines.append(f"author {author} {when}")
    lines.append(f"committer {author} {when}")
    lines.append("")
    lines.append(message)
    return repo.store.hash_object("commit", "\n".join(lines).encode(), write=True)


def cmd_stash(args):
    repo = Repo.discover()
    sub = args.stash_cmd
    if sub in (None, "save"):
        wt = repo.working_snapshot_to_blobs(write=True)
        idx = repo.index.load()
        head = repo.head_oid()
        if wt == idx == repo.snapshot_from_commit(head):
            print("No local changes to save")
            return
        oid = make_commit(repo, wt, "WIP on stash", head)
        stack = load_stash(repo)
        stack.insert(0, oid)
        save_stash(repo, stack)
        head_snap = repo.snapshot_from_commit(head)
        repo.index.save(head_snap)
        repo.write_working_tree(head_snap)
        print(f"Saved working directory and index state {oid[:7]}")
        return
    if sub == "list":
        stack = load_stash(repo)
        for i, oid in enumerate(stack):
            print(f"stash@{{{i}}}: {oid}")
        return
    if sub == "pop":
        stack = load_stash(repo)
        if not stack:
            raise MiniGitError("No stash entries found.")
        oid = stack.pop(0)
        save_stash(repo, stack)
        snap = repo.snapshot_from_commit(oid)
        repo.index.save(snap)
        repo.write_working_tree(snap)
        print(f"Dropped refs/stash@{{0}} ({oid})")
        return
    if sub == "drop":
        stack = load_stash(repo)
        if not stack:
            raise MiniGitError("No stash entries found.")
        oid = stack.pop(0)
        save_stash(repo, stack)
        print(f"Dropped stash@{{0}} ({oid})")
        return
    raise MiniGitError(f"unknown stash subcommand: {sub}")


def cmd_remote(args):
    repo = Repo.discover()
    if args.remote_cmd == "add":
        repo.add_remote(args.name, args.url)
        return
    if args.remote_cmd == "remove":
        repo.remove_remote(args.name)
        rem_dir = repo.git / "refs" / "remotes" / args.name
        if rem_dir.exists():
            shutil.rmtree(rem_dir)
        return
    if args.remote_cmd in ("list", "verbose"):
        for name, url in repo.list_remotes():
            print(f"{name}\t{url}")
        return
    raise MiniGitError("unknown remote subcommand")


def cmd_fetch(args):
    repo = Repo.discover()
    remote_name = args.remote
    remote_url = repo.get_remote_url(remote_name)
    remote_git = resolve_remote_git_dir(remote_url)

    for _ref, oid in iter_refs_under(remote_git, "refs/heads"):
        reachable = collect_reachable_objects_from_commit(remote_git, oid)
        for obj_oid in reachable:
            copy_object_if_missing(remote_git / "objects", repo.git / "objects", obj_oid)

    for ref, oid in iter_refs_under(remote_git, "refs/heads"):
        branch = ref[len("refs/heads/") :]
        repo.write_ref(f"refs/remotes/{remote_name}/{branch}", oid)


def cmd_pull(args):
    repo = Repo.discover()
    fetch_args = argparse.Namespace(remote=args.remote)
    cmd_fetch(fetch_args)
    remote_ref = f"{args.remote}/{args.branch}"
    merge_args = argparse.Namespace(branch=remote_ref)
    cmd_merge(merge_args)


def cmd_push(args):
    repo = Repo.discover()
    remote_name = args.remote
    branch = args.branch
    remote_url = repo.get_remote_url(remote_name)
    remote_git = resolve_remote_git_dir(remote_url)

    local_oid = repo.read_ref(f"refs/heads/{branch}")
    if not local_oid:
        raise MiniGitError(f"branch '{branch}' not found")

    reachable = collect_reachable_objects_from_commit(repo.git, local_oid)
    for obj_oid in reachable:
        copy_object_if_missing(repo.git / "objects", remote_git / "objects", obj_oid)

    write_text(remote_git / "refs" / "heads" / branch, local_oid + "\n")


def build_parser():
    parser = argparse.ArgumentParser(prog="mini-git")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init")
    p.add_argument("directory", nargs="?")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("commit")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("log")
    p.add_argument("--oneline", action="store_true")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("branch")
    p.add_argument("name", nargs="?")
    p.add_argument("-d", dest="delete")
    p.set_defaults(func=cmd_branch)

    p = sub.add_parser("checkout")
    p.add_argument("-b", dest="create")
    p.add_argument("target", nargs="?")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("merge")
    p.add_argument("branch")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("diff")
    p.add_argument("--staged", action="store_true")
    p.add_argument("commit1", nargs="?")
    p.add_argument("commit2", nargs="?")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("reset")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--soft", action="store_true")
    grp.add_argument("--mixed", action="store_true")
    grp.add_argument("--hard", action="store_true")
    p.add_argument("commit", nargs="?")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("stash")
    p.add_argument("stash_cmd", nargs="?")
    p.set_defaults(func=cmd_stash)

    p = sub.add_parser("remote")
    remote_sub = p.add_subparsers(dest="remote_cmd")
    p_add = remote_sub.add_parser("add")
    p_add.add_argument("name")
    p_add.add_argument("url")
    p_add.set_defaults(func=cmd_remote)

    p_remove = remote_sub.add_parser("remove")
    p_remove.add_argument("name")
    p_remove.set_defaults(func=cmd_remote)

    p_list = remote_sub.add_parser("list")
    p_list.set_defaults(func=cmd_remote)

    p_verbose = remote_sub.add_parser("-v")
    p_verbose.set_defaults(remote_cmd="verbose", func=cmd_remote)

    p.set_defaults(func=cmd_remote, remote_cmd="list")

    p = sub.add_parser("fetch")
    p.add_argument("remote")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("pull")
    p.add_argument("remote")
    p.add_argument("branch")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("push")
    p.add_argument("remote")
    p.add_argument("branch")
    p.set_defaults(func=cmd_push)

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) == 2 and argv[0] == "remote" and argv[1] == "-v":
        argv = ["remote", "list"]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        args.func(args)
        return 0
    except MiniGitError as e:
        eprint(f"error: {e}")
        return 1
    except Exception as e:
        eprint(f"fatal: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

