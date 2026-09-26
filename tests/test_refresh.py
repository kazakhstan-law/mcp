import subprocess
from dataclasses import replace

from conftest import commit, init
from kzlaw_mcp.gitio import Git
from kzlaw_mcp.refresh import refresh_scope


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_clone_then_follow_a_force_push(tmp_path, settings):
    src = init(tmp_path / "src")
    commit(src, "2020-01-01", {"a/rus.md": "one\n"}, "first")
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    git("clone", "-q", "--bare", str(src), str(remotes / "codes.git"), cwd=tmp_path)
    s = replace(
        settings, corpus_root=tmp_path / "corpus", remote_template=f"file://{remotes}/{{scope}}.git"
    )
    (tmp_path / "corpus").mkdir()

    assert refresh_scope(s, "codes") == "cloned"
    assert refresh_scope(s, "codes") == "unchanged"

    # a rebuild rewrites history: amend (a new root commit) and force-push
    (src / "a/rus.md").write_text("one, rebuilt\n")
    git(
        "-c",
        "user.name=c",
        "-c",
        "user.email=c@example.invalid",
        "commit",
        "-qa",
        "--amend",
        "-m",
        "first",
        cwd=src,
    )
    git("push", "-q", "--force", str(remotes / "codes.git"), "main", cwd=src)
    assert refresh_scope(s, "codes") == "updated"
    clone = tmp_path / "corpus" / "codes"
    assert (clone / "a/rus.md").read_text() == "one, rebuilt\n"
    assert Git(clone, 5).head() == Git(src, 5).head()


def test_an_interrupted_clone_is_redone(tmp_path, settings):
    src = init(tmp_path / "src")
    commit(src, "2020-01-01", {"a/rus.md": "one\n"}, "first")
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    git("clone", "-q", "--bare", str(src), str(remotes / "codes.git"), cwd=tmp_path)
    s = replace(
        settings, corpus_root=tmp_path / "corpus", remote_template=f"file://{remotes}/{{scope}}.git"
    )
    leftover = tmp_path / "corpus" / "codes.tmp"
    leftover.mkdir(parents=True)
    (leftover / "junk").write_text("killed mid-clone")
    assert refresh_scope(s, "codes") == "cloned"
    assert not leftover.exists()
    assert (tmp_path / "corpus" / "codes" / "a/rus.md").read_text() == "one\n"
    # a directory left by the old in-place clone: .git exists, HEAD unborn
    git("clone", "-q", "--bare", str(src), str(remotes / "ministerial.git"), cwd=tmp_path)
    init(tmp_path / "corpus" / "ministerial")
    assert refresh_scope(s, "ministerial") == "cloned"
    assert (tmp_path / "corpus" / "ministerial" / "a/rus.md").exists()
