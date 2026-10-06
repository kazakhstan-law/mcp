import pytest

from conftest import KOAP_CODE, PD_CODE, PDD_CODE
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


def test_introduced_skips_a_placeholder_heading(settings):
    res = history(Corpus(settings), PD_CODE, phrase="Статья 10-1. Уведомление")
    assert [c["date"] for c in res["commits"]] == ["2026-01-09"]  # the heading came first
    assert res["introduced"]["date"] == "2026-07-12"  # the text came then
    assert res["introduced"]["placeholder"] is False
    assert res["introduced"]["announced"]["date"] == "2026-01-09"


def test_introduced_marks_a_provision_not_in_force(settings):
    res = history(Corpus(settings), PD_CODE, phrase="Статья 1-2.")
    assert res["introduced"]["date"] == "2026-07-12"
    assert res["introduced"]["placeholder"] is True


def test_introduced_of_real_text_has_no_placeholder(settings):
    res = history(Corpus(settings), PD_CODE, phrase="Оператор уведомляет")
    assert res["introduced"]["date"] == "2026-07-12" and "placeholder" not in res["introduced"]


def test_commit_without_cause(settings):
    res = history(Corpus(settings), PDD_CODE)
    assert res["commits"][-1]["cause_act_code"] == ""


def test_option_like_phrase_is_text(settings):
    assert history(Corpus(settings), PDD_CODE, phrase="--all")["commits"] == []


@pytest.mark.parametrize("phrase", ["ab", "x" * 201])
def test_bad_phrase(settings, phrase):
    with pytest.raises(InputError):
        history(Corpus(settings), PDD_CODE, phrase=phrase)


def test_history_since_lists_the_articles_each_version_touched(settings):
    commits = history(Corpus(settings), PD_CODE, since="2025-01-01")["commits"]
    by_date = {c["date"]: c for c in commits}
    # 2026-01-09 only announced: a placeholder subpoint in ст.9 and a bare heading ст.10-1.
    assert by_date["2026-01-09"]["touched_anchors"] == ["st9"]
    assert by_date["2026-01-09"]["placeholders_only"] is True
    assert by_date["2026-07-12"]["placeholders_only"] is False
    assert "st10-1" in by_date["2026-07-12"]["touched_anchors"]
    assert "touched_anchors" not in by_date["2025-05-01"]  # the first version: nothing before


def test_article_history_names_the_act_its_footnote_gained(settings):
    commits = history(Corpus(settings), KOAP_CODE, anchor="st592")["commits"]
    (v2024,) = [c for c in commits if c["date"] == "2024-10-03"]
    assert v2024["cause_acts"] == [{"date": "2024-10-03", "number": "131-VIII"}]
    assert "attribution_ambiguous" not in v2024  # the footnote agrees with the version's act


def test_a_footnote_naming_another_act_than_the_version_is_ambiguous():
    from kzlaw_mcp.history import _cause

    # Prod, ст.619-2 КоАП: version 2026-07-01 recorded under 331-VIII, footnote says 247-VIII.
    commit = {"cause_act_requisite": "Закон РК от 1 июля 2026 года № 331-VIII ЗРК"}
    res = _cause(commit, {("2025-12-30", "247-VIII")})
    assert res == {
        "cause_acts": [{"date": "2025-12-30", "number": "247-VIII"}],
        "attribution_ambiguous": True,
    }


def test_a_cyrillic_numeral_is_the_same_act():
    from kzlaw_mcp.history import _cause

    # Requisites type the convocation as "300-VІ" with a Cyrillic І; footnotes often in Latin.
    commit = {"cause_act_requisite": "Закон РК от 26 декабря 2019 года № 300-VІ ЗРК"}
    assert "attribution_ambiguous" not in _cause(commit, {("2019-12-26", "300-VI")})
