import os
from pathlib import Path

import pytest

import mini_git


def run_ok(cwd: Path, *argv):
    old = Path.cwd()
    os.chdir(cwd)
    try:
        rc = mini_git.main(list(argv))
        assert rc == 0
    finally:
        os.chdir(old)


def run_out(cwd: Path, *argv, capsys=None):
    old = Path.cwd()
    os.chdir(cwd)
    try:
        rc = mini_git.main(list(argv))
        out = ""
        err = ""
        if capsys:
            captured = capsys.readouterr()
            out, err = captured.out, captured.err
        return rc, out, err
    finally:
        os.chdir(old)


def test_blob_hash_and_read(tmp_path):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    repo = mini_git.Repo(repo_dir)
    data = b"hello world\n"
    oid = repo.store.hash_object("blob", data, write=True)
    obj = repo.store.read_object(oid)
    assert obj.type == "blob"
    assert obj.data == data


def test_init_existing_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    run_ok(tmp_path, "init", str(repo_dir))
    assert (repo_dir / ".git" / "HEAD").exists()


def test_add_commit_log_status(tmp_path, capsys):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "hello.txt").write_text("hello\n", encoding="utf-8")

    rc, out, _ = run_out(repo_dir, "status", capsys=capsys)
    assert rc == 0
    assert "Untracked files:" in out
    assert "hello.txt" in out

    run_ok(repo_dir, "add", "hello.txt")
    rc, out, _ = run_out(repo_dir, "status", capsys=capsys)
    assert "Changes to be committed:" in out
    assert "new file:   hello.txt" in out

    run_ok(repo_dir, "commit", "-m", "initial commit")
    rc, out, _ = run_out(repo_dir, "log", "--oneline", capsys=capsys)
    assert "initial commit" in out


def test_branch_and_checkout(tmp_path, capsys):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "a.txt").write_text("a\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "c1")
    run_ok(repo_dir, "branch", "feature")
    rc, out, _ = run_out(repo_dir, "branch", capsys=capsys)
    assert "* main" in out
    assert "  feature" in out

    rc, out, _ = run_out(repo_dir, "checkout", "feature", capsys=capsys)
    assert "Switched to branch 'feature'" in out


def test_fast_forward_merge(tmp_path, capsys):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "a.txt").write_text("a\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "base")
    run_ok(repo_dir, "branch", "feature")
    run_ok(repo_dir, "checkout", "feature")
    (repo_dir / "b.txt").write_text("b\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "feature")
    run_ok(repo_dir, "checkout", "main")
    rc, out, _ = run_out(repo_dir, "merge", "feature", capsys=capsys)
    assert "Fast-forward" in out
    assert (repo_dir / "b.txt").exists()


def test_merge_conflict(tmp_path, capsys):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "f.txt").write_text("base\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "base")
    run_ok(repo_dir, "branch", "feature")

    run_ok(repo_dir, "checkout", "feature")
    (repo_dir / "f.txt").write_text("feature\n", encoding="utf-8")
    run_ok(repo_dir, "add", "f.txt")
    run_ok(repo_dir, "commit", "-m", "feature change")

    run_ok(repo_dir, "checkout", "main")
    (repo_dir / "f.txt").write_text("main\n", encoding="utf-8")
    run_ok(repo_dir, "add", "f.txt")
    run_ok(repo_dir, "commit", "-m", "main change")

    rc, out, _ = run_out(repo_dir, "merge", "feature", capsys=capsys)
    assert "Automatic merge failed" in out
    text = (repo_dir / "f.txt").read_text(encoding="utf-8")
    assert "<<<<<<< HEAD" in text
    assert ">>>>>>> feature" in text


def test_diff_and_staged_diff(tmp_path, capsys):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "d.txt").write_text("one\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "c1")
    (repo_dir / "d.txt").write_text("two\n", encoding="utf-8")

    rc, out, _ = run_out(repo_dir, "diff", capsys=capsys)
    assert "--- index/d.txt" in out
    assert "+++ working/d.txt" in out

    run_ok(repo_dir, "add", "d.txt")
    rc, out, _ = run_out(repo_dir, "diff", "--staged", capsys=capsys)
    assert "--- HEAD/d.txt" in out
    assert "+++ index/d.txt" in out


def test_reset_hard(tmp_path):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "x.txt").write_text("1\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "c1")
    first = mini_git.Repo(repo_dir).head_oid()
    (repo_dir / "x.txt").write_text("2\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "c2")
    run_ok(repo_dir, "reset", "--hard", first)
    assert (repo_dir / "x.txt").read_text(encoding="utf-8") == "1\n"


def test_stash_save_list_pop(tmp_path, capsys):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "s.txt").write_text("1\n", encoding="utf-8")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "c1")
    (repo_dir / "s.txt").write_text("2\n", encoding="utf-8")

    rc, out, _ = run_out(repo_dir, "stash", capsys=capsys)
    assert "Saved working directory" in out
    assert (repo_dir / "s.txt").read_text(encoding="utf-8") == "1\n"

    rc, out, _ = run_out(repo_dir, "stash", "list", capsys=capsys)
    assert "stash@{0}" in out

    rc, out, _ = run_out(repo_dir, "stash", "pop", capsys=capsys)
    assert "Dropped" in out
    assert (repo_dir / "s.txt").read_text(encoding="utf-8") == "2\n"


def test_empty_file_binary_and_spaces(tmp_path):
    repo_dir = tmp_path / "repo"
    run_ok(tmp_path, "init", str(repo_dir))
    (repo_dir / "empty.txt").write_text("", encoding="utf-8")
    (repo_dir / "file with spaces.bin").write_bytes(b"\x00\x01\x02abc")
    run_ok(repo_dir, "add", ".")
    run_ok(repo_dir, "commit", "-m", "files")
    repo = mini_git.Repo(repo_dir)
    snap = repo.snapshot_from_commit(repo.head_oid())
    assert "empty.txt" in snap
    assert "file with spaces.bin" in snap
