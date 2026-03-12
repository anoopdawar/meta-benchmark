#!/usr/bin/env python3
import argparse
import hashlib
import shutil
import sys
import zlib
from pathlib import Path
from typing import Dict, Optional, Tuple

GIT_DIRNAME = ".git"
HEAD_FILE = "HEAD"
OBJECTS_DIR = "objects"
REFS_HEADS_DIR = "refs/heads"
REFS_REMOTES_DIR = "refs/remotes"
CONFIG_FILE = "config"


class MiniGitError(Exception):
    pass


def eprint(msg: str):
    print(msg, file=sys.stderr)


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    p = (start or Path.cwd()).resolve()
    while True:
        if (p / GIT_DIRNAME).is_dir():
            return p
        if p.parent == p:
            return None
        p = p.parent


def ensure_repo() -> Path:
    root = find_repo_root()
    if not root:
        raise MiniGitError("fatal: not a mini-git repository (or any of the parent directories): .git")
    return root


def git_path(root: Path, *parts: str) -> Path:
    return root / GIT_DIRNAME / Path(*parts)


def read_file(path: Path, binary=False):
    if binary:
        return path.read_bytes()
    return path.read_text(encoding="utf-8")


def write_file(path: Path, data, binary=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def obj_path(root: Path, oid: str) -> Path:
    return git_path(root, OBJECTS_DIR, oid[:2], oid[2:])


def read_object(root: Path, oid: str) -> Tuple[str, bytes]:
    p = obj_path(root, oid)
    if not p.exists():
        raise MiniGitError(f"fatal: bad object {oid}")
    raw = zlib.decompress(read_file(p, binary=True))
    if sha1_hex(raw) != oid:
        raise MiniGitError(f"fatal: object corruption detected for {oid}")
    header, content = raw.split(b"\0", 1)
    t, _size = header.decode().split(" ", 1)
    return t, content


def parse_commit(content: bytes) -> Dict[str, str]:
    text = content.decode(errors="replace")
    headers, _, msg = text.partition("\n\n")
    d = {"message": msg}
    for line in headers.splitlines():
        if not line.strip():
            continue
        k, v = line.split(" ", 1)
        if k in d:
            d[k] += "\n" + v
        else:
            d[k] = v
    return d


def get_head_ref(root: Path) -> Tuple[bool, str]:
    h = read_file(git_path(root, HEAD_FILE)).strip()
    if h.startswith("ref: "):
        return True, h[5:]
    return False, h


def resolve_ref(root: Path, ref: str) -> Optional[str]:
    p = git_path(root, ref)
    if p.exists():
        v = read_file(p).strip()
        return v or None
    return None


def get_head_commit(root: Path) -> Optional[str]:
    is_ref, val = get_head_ref(root)
    if is_ref:
        return resolve_ref(root, val)
    return val if val else None


def update_head(root: Path, oid: str):
    is_ref, val = get_head_ref(root)
    if is_ref:
        write_file(git_path(root, val), oid + "\n")
    else:
        write_file(git_path(root, HEAD_FILE), oid + "\n")


def cmd_init(args):
    target = Path(args.directory or ".").resolve()
    git = target / GIT_DIRNAME
    git.mkdir(parents=True, exist_ok=True)
    (git / OBJECTS_DIR).mkdir(parents=True, exist_ok=True)
    (git / REFS_HEADS_DIR).mkdir(parents=True, exist_ok=True)
    (git / REFS_REMOTES_DIR).mkdir(parents=True, exist_ok=True)
    head = git / HEAD_FILE
    if not head.exists():
        write_file(head, "ref: refs/heads/main\n")
    main_ref = git / REFS_HEADS_DIR / "main"
    if not main_ref.exists():
        write_file(main_ref, "")
    cfg = git / CONFIG_FILE
    if not cfg.exists():
        write_file(cfg, "")
    print(f"Initialized empty Git repository in {git}")
    return 0


def parse_config(root: Path) -> Dict[str, str]:
    cfg = git_path(root, CONFIG_FILE)
    if not cfg.exists():
        return {}
    out = {}
    for line in read_file(cfg).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            name, url = line.split("\t", 1)
        else:
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue
            name, url = parts
        out[name.strip()] = url.strip()
    return out


def write_config(root: Path, remotes: Dict[str, str]):
    lines = [f"{name}\t{url}" for name, url in sorted(remotes.items())]
    write_file(git_path(root, CONFIG_FILE), ("\n".join(lines) + "\n") if lines else "")


def resolve_remote_url(root: Path, remote_name: str) -> Path:
    remotes = parse_config(root)
    if remote_name not in remotes:
        raise MiniGitError(f"fatal: remote '{remote_name}' does not exist")
    url = remotes[remote_name]
    p = Path(url).expanduser()
    if not p.is_absolute():
        p = (root / p).resolve()
    git_dir = p / ".git" if (p / ".git").is_dir() else p
    if not git_dir.is_dir():
        raise MiniGitError(f"fatal: remote path not found: {url}")
    if not (git_dir / OBJECTS_DIR).is_dir():
        raise MiniGitError(f"fatal: invalid remote repository: {url}")
    return git_dir


def iter_refs(git_dir: Path, prefix: str = "refs/heads") -> Dict[str, str]:
    base = git_dir / prefix
    out = {}
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_file():
            ref = p.relative_to(git_dir).as_posix()
            val = p.read_text(encoding="utf-8").strip()
            if val:
                out[ref] = val
    return out


def copy_missing_objects(src_git: Path, dst_git: Path):
    src_obj = src_git / OBJECTS_DIR
    dst_obj = dst_git / OBJECTS_DIR
    for p in src_obj.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src_obj)
        tgt = dst_obj / rel
        if not tgt.exists():
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, tgt)


def cmd_remote_add(args):
    root = ensure_repo()
    remotes = parse_config(root)
    if args.name in remotes:
        raise MiniGitError(f"fatal: remote '{args.name}' already exists")
    remotes[args.name] = args.url
    write_config(root, remotes)
    return 0


def cmd_remote_list(args):
    root = ensure_repo()
    remotes = parse_config(root)
    for name, url in sorted(remotes.items()):
        print(f"{name}\t{url}")
    return 0


def cmd_remote_remove(args):
    root = ensure_repo()
    remotes = parse_config(root)
    if args.name not in remotes:
        raise MiniGitError(f"fatal: remote '{args.name}' does not exist")
    del remotes[args.name]
    write_config(root, remotes)
    return 0


def cmd_fetch(args):
    root = ensure_repo()
    remote_git = resolve_remote_url(root, args.remote)
    local_git = root / GIT_DIRNAME

    copy_missing_objects(remote_git, local_git)
    remote_heads = iter_refs(remote_git, "refs/heads")
    for ref, oid in remote_heads.items():
        branch = ref[len("refs/heads/"):]
        local_remote_ref = git_path(root, REFS_REMOTES_DIR, args.remote, branch)
        write_file(local_remote_ref, oid + "\n")
    return 0


def cmd_pull(args):
    root = ensure_repo()
    fetch_args = argparse.Namespace(remote=args.remote)
    cmd_fetch(fetch_args)

    remote_ref = f"{REFS_REMOTES_DIR}/{args.remote}/{args.branch}"
    fetched_oid = resolve_ref(root, remote_ref)
    if not fetched_oid:
        raise MiniGitError(f"fatal: couldn't find remote branch {args.branch}")

    update_head(root, fetched_oid)
    print(f"Updated current branch to {fetched_oid}")
    return 0


def cmd_push(args):
    root = ensure_repo()
    remote_git = resolve_remote_url(root, args.remote)
    local_git = root / GIT_DIRNAME

    local_ref = f"{REFS_HEADS_DIR}/{args.branch}"
    local_oid = resolve_ref(root, local_ref)
    if not local_oid:
        raise MiniGitError(f"fatal: src refspec {args.branch} does not match any")

    copy_missing_objects(local_git, remote_git)
    remote_ref_path = remote_git / REFS_HEADS_DIR / args.branch
    remote_ref_path.parent.mkdir(parents=True, exist_ok=True)
    remote_ref_path.write_text(local_oid + "\n", encoding="utf-8")
    print(f"Pushed {args.branch} -> {args.remote}/{args.branch}")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="mini-git")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("init")
    p.add_argument("directory", nargs="?")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("remote")
    rsub = p.add_subparsers(dest="remote_cmd")

    p_add = rsub.add_parser("add")
    p_add.add_argument("name")
    p_add.add_argument("url")
    p_add.set_defaults(func=cmd_remote_add)

    p_list = rsub.add_parser("list")
    p_list.set_defaults(func=cmd_remote_list)

    p_v = rsub.add_parser("-v")
    p_v.set_defaults(func=cmd_remote_list)

    p_rm = rsub.add_parser("remove")
    p_rm.add_argument("name")
    p_rm.set_defaults(func=cmd_remote_remove)

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

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except MiniGitError as e:
        eprint(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())

