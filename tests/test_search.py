import pytest

from conftest import KOAP_CODE, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.search import search


def test_finds_an_article_case_insensitively(settings):
    res = search(Corpus(settings), "превышение установленной скорости")
    [act] = res["acts"]
    assert act["act_code"] == KOAP_CODE and act["title"] == "Об административных правонарушениях"
    hit = act["hits"][0]
    assert hit["anchor"] == "st592" and hit["heading"].startswith("Статья 592")
    assert hit["file"].endswith("rus/sec002-ch030.md")  # current revision only


def test_hits_without_anchors_carry_the_point(settings):
    res = search(Corpus(settings), "восемнадцати лет")
    [act] = res["acts"]
    assert act["act_code"] == PDD_CODE
    assert act["hits"][0]["point"] == "168-1" and act["hits"][0]["anchor"] is None


def test_kazakh_is_case_insensitive(settings):
    res = search(Corpus(settings), "әкімшілік", lang="kaz")
    assert [a["act_code"] for a in res["acts"]] == [KOAP_CODE]


def test_codes_rank_before_ministerial(settings):
    res = search(Corpus(settings), "километров|самокат")
    assert [a["scope"] for a in res["acts"]] == ["codes", "ministerial"]


def test_limit_truncates(settings):
    res = search(Corpus(settings), "километров|самокат", limit=1)
    assert len(res["acts"]) == 1 and res["truncated"] is True


def test_missing_scope_is_reported(settings):
    res = search(Corpus(settings), "самокат", scopes=["ministerial", "local-abai"])
    assert res["missing_scopes"] == ["local-abai"] and res["acts"]


def test_no_hits_gives_a_hint(settings):
    res = search(Corpus(settings), "гиппопотам")
    assert res["acts"] == [] and "wording" in res["hint"]


@pytest.mark.parametrize("query", ["--files", "-e x", "--pre=sh"])
def test_option_like_queries_are_patterns(settings, query):
    assert search(Corpus(settings), query)["acts"] == []  # searched as text, nothing matches


@pytest.mark.parametrize("query", ["(", "x", "a" * 201])
def test_bad_queries(settings, query):
    with pytest.raises(InputError):
        search(Corpus(settings), query)


def test_bad_scope(settings):
    with pytest.raises(InputError, match="unknown scope"):
        search(Corpus(settings), "самокат", scopes=["../etc"])


def test_one_act_cannot_take_every_hit(settings, monkeypatch):
    import kzlaw_mcp.search as mod

    monkeypatch.setattr(mod, "PER_ACT", 1)
    res = search(Corpus(settings), "километров|самокат")
    assert [len(a["hits"]) for a in res["acts"]] == [1, 1] and res["truncated"] is True
