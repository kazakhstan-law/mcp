"""Acts repealed with no act in force naming them: found by code and title, read by date."""

import pytest

from conftest import LABOUR_CODE, OLD_WATER_CODE, PD_AMENDER
from kzlaw_mcp.changes import changes
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.history import history
from kzlaw_mcp.passages import at_date, read
from kzlaw_mcp.search import search


def test_index_holds_only_acts_without_a_successor(settings):
    corpus = Corpus(settings)
    rep = corpus.repealed(LABOUR_CODE)
    assert rep is not None and rep.date == "2007-05-15"
    assert corpus.repealed(OLD_WATER_CODE) is None  # a successor names it: predecessors
    assert corpus.repealed(PD_AMENDER) is None


def test_read_points_to_the_history(settings):
    with pytest.raises(InputError, match="repealed on 2007-05-15.*at_date"):
        read(Corpus(settings), LABOUR_CODE)


def test_title_search_lists_repealed_acts(settings):
    corpus = Corpus(settings)
    assert "repealed" not in search(corpus, "О труде")
    res = search(corpus, "о труде", include_repealed=True)
    assert [(a["act_code"], a["repealed_on"]) for a in res["repealed"]] == [
        (LABOUR_CODE, "2007-05-15")
    ]


def test_search_inside_a_repealed_act_then_read_it(settings):
    corpus = Corpus(settings)
    res = search(corpus, r"письменн\w* форм", act_code=LABOUR_CODE)
    (act,) = res["acts"]
    assert (act["repealed_on"], act["as_of"]) == ("2007-05-15", "2007-01-12")
    (hit,) = act["hits"]
    assert hit["anchor"] == "st12" and f"/blob/{res['sha']['codes']}/" in hit["url"]
    passage = at_date(corpus, LABOUR_CODE, act["as_of"], anchor=hit["anchor"])["passages"][0]
    assert "письменной форме" in passage["text"]


def test_at_date_after_the_repeal(settings):
    with pytest.raises(InputError, match="repealed on 2007-05-15"):
        at_date(Corpus(settings), LABOUR_CODE, "2010-01-01")


def test_history_and_changes_of_a_repealed_act(settings):
    corpus = Corpus(settings)
    res = history(corpus, LABOUR_CODE)
    assert res["title"] == "О труде в Республике Казахстан"
    assert res["repealed_on"] == "2007-05-15"
    assert [c["date"] for c in res["commits"]] == ["2007-05-15", "2007-01-12", "1999-12-10"]
    assert changes(corpus, LABOUR_CODE)["version"]["date"] == "2007-01-12"


def test_amending_act_code_still_lists_what_it_changed(settings):
    assert changes(Corpus(settings), PD_AMENDER)["acts_total"] == 1
