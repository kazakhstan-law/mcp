import pytest

from conftest import KOAP
from kzlaw_mcp.gitio import CommandError, Git, run


def test_run_rejects_unexpected_exit(tmp_path):
    with pytest.raises(CommandError):
        run(["git", "rev-parse", "HEAD"], tmp_path, timeout=5)


def test_run_truncates(tmp_path):
    out = run(["python3", "-c", "print('x' * 1000)"], tmp_path, timeout=5, max_bytes=10)
    assert out.truncated and out.text == "x" * 10


def test_git_reads_objects_at_a_revision(corpus_root):
    g = Git(corpus_root / "codes", timeout=10)
    head = g.head()
    old = g.rev_before("2023-01-01")
    assert old and old != head
    assert g.rev_before("1990-01-01") is None
    assert g.commit_date(old) == "2022-01-10"
    assert f"{KOAP}/rus/sec002-ch010.md" in g.ls_tree(old, f"{KOAP}/rus")
    assert f"{KOAP}/rus/sec002-ch010.md" not in g.ls_tree(head, f"{KOAP}/rus")
    assert "от сорока и более" in g.blob(old, f"{KOAP}/rus/sec002-ch010.md")
    assert g.blob_size(head, f"{KOAP}/rus.md") > 0


def test_git_grep_returns_paths_and_lines(corpus_root):
    g = Git(corpus_root / "codes", timeout=10)
    hits = g.grep(g.head(), '<a id="st592"></a>', [f"{KOAP}/rus.md", f"{KOAP}/rus"], fixed=True)
    assert hits == [(f"{KOAP}/rus/sec002-ch030.md", 5)]
    assert g.grep(g.head(), "no such text", [f"{KOAP}/rus"], fixed=True) == []
