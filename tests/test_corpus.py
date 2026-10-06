import pytest

from conftest import CONST_CODE, KOAP, KOAP_CODE, PDD_CODE, init
from kzlaw_mcp.corpus import Corpus, InputError, locator_label


def test_scopes_are_the_repos_on_disk(settings):
    assert Corpus(settings).scopes() == ["codes", "ministerial"]


def test_find_by_code(settings):
    c = Corpus(settings)
    assert c.find(KOAP_CODE).path == KOAP and c.find(KOAP_CODE).scope == "codes"
    assert c.find(PDD_CODE).scope == "ministerial"
    assert c.find(CONST_CODE).path == "00-constitution"


@pytest.mark.parametrize("bad", ["../etc", "81245/..", "", "1" * 13, "812 45"])
def test_find_rejects_non_codes(settings, bad):
    with pytest.raises(InputError):
        Corpus(settings).find(bad)


def test_find_names_an_adilet_id(settings):
    # Prod: history(act_code='K1400000235') twice, answered only "must be numeric".
    with pytest.raises(InputError, match="adilet.zan.kz document id.*search"):
        Corpus(settings).find("K1400000235")


def test_find_unknown_code(settings):
    with pytest.raises(InputError, match="not in the corpus"):
        Corpus(settings).find("424242")


def test_files_follow_the_revision(settings):
    c = Corpus(settings)
    ref = c.find(KOAP_CODE)
    g = c.git("codes")
    old = g.rev_before("2023-01-01")
    assert c.lang_files(ref, old, "rus") == [
        f"{KOAP}/rus.md",
        f"{KOAP}/rus/sec001.md",
        f"{KOAP}/rus/sec002-ch010.md",
        f"{KOAP}/rus/sec002-ch025.md",
    ]
    assert c.lang_files(ref, c.head("codes"), "rus")[-1].endswith("sec002-ch030.md")
    assert c.lang_files(ref, c.head("codes"), "kaz") == [f"{KOAP}/kaz.md"]
    assert c.meta(ref, old)["requisite"].startswith("Кодекс")


def test_citation_urls(settings):
    c = Corpus(settings)
    ref = c.find(KOAP_CODE)
    base = f"https://github.com/kazakhstan-law/codes/blob/abc/{KOAP}/rus/x.md"
    f = f"{KOAP}/rus/x.md"
    assert (
        c.citation_url(ref, "abc", f, anchor="st592", lines=(5, 20), size=1000) == base + "#st592"
    )
    # too large for GitHub to render: anchors do not exist, fall back to line numbers
    assert c.citation_url(ref, "abc", f, anchor="st592", lines=(5, 20), size=500_000) == (
        base + "?plain=1#L5-L20"
    )
    assert (
        c.citation_url(ref, "abc", f, anchor=None, lines=(7, 9), size=10) == base + "?plain=1#L7-L9"
    )


def test_labels():
    assert locator_label("st592", None) == "ст. 592"
    assert locator_label("st592", "3-1") == "ст. 592, ч. 3-1"
    assert locator_label(None, "168-1") == "п. 168-1"
    assert locator_label("an3_st1", None) == "прил. 3, ст. 1"


def test_a_half_cloned_scope_is_skipped(tmp_path, settings):
    from dataclasses import replace

    from kzlaw_mcp.passages import read

    for scope in ("codes", "ministerial"):
        (tmp_path / scope).symlink_to(settings.corpus_root / scope)
    init(tmp_path / "government")  # `git clone` in progress: .git exists, HEAD is unborn
    c = Corpus(replace(settings, corpus_root=tmp_path))
    assert c.scopes() == ["codes", "ministerial"]
    assert read(c, KOAP_CODE, anchor="st592")["passages"]
