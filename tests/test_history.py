import pytest

from conftest import KOAP_CODE, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.history import history


def test_history_lists_amending_acts(settings):
    res = history(Corpus(settings), KOAP_CODE)
    assert [c["date"] for c in res["commits"]] == ["2024-10-03", "2022-01-10"]
    top = res["commits"][0]
    assert top["cause_act_code"] == "999131" and "131-VIII" in top["cause_act_requisite"]
    assert top["url"] == f"https://github.com/kazakhstan-law/codes/commit/{top['sha']}"
    assert res["first_version"]["date"] == "2022-01-10"


def test_history_pages_and_since(settings):
    corpus = Corpus(settings)
    first = history(corpus, KOAP_CODE, limit=1)
    assert (first["total"], first["limited"], first["next_offset"]) == (2, True, 1)
    second = history(corpus, KOAP_CODE, limit=1, offset=1)
    assert [c["date"] for c in second["commits"]] == ["2022-01-10"]
    assert (second["limited"], second["next_offset"]) == (False, None)
    recent = history(corpus, KOAP_CODE, since="2024-10-03")  # the day itself counts
    assert [c["date"] for c in recent["commits"]] == ["2024-10-03"] and recent["total"] == 1


def test_since_leaves_introduced_unknown(settings):
    res = history(Corpus(settings), PDD_CODE, phrase="электрических самокатов", since="2023-01-01")
    assert res["commits"] and res["introduced"] is None


def test_bad_since(settings):
    with pytest.raises(InputError):
        history(Corpus(settings), KOAP_CODE, since="2024")


def test_phrase_pinpoints_when_it_appeared(settings):
    res = history(Corpus(settings), PDD_CODE, phrase="электрических самокатов")
    assert [c["date"] for c in res["commits"]] == ["2023-08-31"]
    assert res["introduced"]["cause_act_code"] == "999671"


def test_commit_without_cause(settings):
    res = history(Corpus(settings), PDD_CODE)
    assert res["commits"][-1]["cause_act_code"] == ""


def test_option_like_phrase_is_text(settings):
    assert history(Corpus(settings), PDD_CODE, phrase="--all")["commits"] == []


@pytest.mark.parametrize("phrase", ["ab", "x" * 201])
def test_bad_phrase(settings, phrase):
    with pytest.raises(InputError):
        history(Corpus(settings), PDD_CODE, phrase=phrase)
