import pytest

from conftest import CONST_CODE, KOAP_CODE, PDD_CODE, commit, init, meta
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


def test_hits_carry_a_ready_link(settings):
    c = Corpus(settings)
    [act] = search(c, "превышение установленной скорости")["acts"]
    hit = act["hits"][0]
    sha = c.head("codes")
    assert hit["url"] == (f"https://github.com/kazakhstan-law/codes/blob/{sha}/{hit['file']}#st592")
    [pdd] = search(c, "восемнадцати лет")["acts"]
    line = pdd["hits"][0]["line"]
    assert pdd["hits"][0]["url"].endswith(f"rus.md?plain=1#L{line}-L{line}")


def test_title_match_ranks_first(tmp_path, settings):
    from dataclasses import replace

    repo = init(tmp_path / "ministerial")
    rules = "07-ministerial/x/2023/0630-rules-111"
    citer = "07-ministerial/x/2024/0101-citer-222"
    mention = "согласно Правилам дорожного движения"
    commit(
        repo,
        "2024-01-01",
        {
            f"{rules}/meta.yaml": meta("111", "Об утверждении Правил дорожного движения", "Приказ"),
            f"{rules}/rus.md": "# Об утверждении Правил дорожного движения\n\n1. Текст.\n",
            f"{citer}/meta.yaml": meta("222", "О внесении изменений", "Приказ"),
            f"{citer}/rus.md": "\n\n".join(["# О внесении изменений"] + [mention] * 3) + "\n",
        },
        "init",
    )
    gov = init(tmp_path / "government")
    other = "06-government/x/2024/0101-other-333"
    commit(
        gov,
        "2024-01-01",
        {
            f"{other}/meta.yaml": meta("333", "О мерах", "Постановление"),
            f"{other}/rus.md": "\n\n".join(["# О мерах"] + [mention] * 3) + "\n",
        },
        "init",
    )
    c = Corpus(replace(settings, corpus_root=tmp_path))
    res = search(c, "правил\\w* дорожного движения", scopes=["ministerial"])
    assert [a["act_code"] for a in res["acts"]] == ["111", "222"]
    # a title match outranks the scope order too
    res = search(c, "правил\\w* дорожного движения", scopes=["government", "ministerial"])
    assert [a["act_code"] for a in res["acts"]] == ["111", "333", "222"]


def test_scopes_take_turns(settings):
    # codes has two matching acts, ministerial one: ministerial must not wait for all of codes
    res = search(Corpus(settings), "Статья|самокат")
    assert [a["act_code"] for a in res["acts"]] == [KOAP_CODE, PDD_CODE, CONST_CODE]
