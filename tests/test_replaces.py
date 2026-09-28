"""A code that replaced a repealed code: history and at_date continue into the old one."""

import pytest

from conftest import OLD_WATER, OLD_WATER_CODE, WATER_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.history import history
from kzlaw_mcp.passages import at_date, read


def test_history_lists_the_repealed_predecessor(settings):
    res = history(Corpus(settings), WATER_CODE)
    assert [c["date"] for c in res["commits"]] == ["2025-04-09"]
    [pred] = res["predecessors"]
    assert pred["act_code"] == OLD_WATER_CODE and pred["replaced_by"] == WATER_CODE
    # the repeal commit deletes the old files, so it is the old act's newest entry
    assert [c["date"] for c in pred["commits"]] == ["2025-04-09", "2024-12-01", "2024-11-01"]
    assert pred["first_version"]["date"] == "2024-11-01"


def test_phrase_is_introduced_in_the_predecessor(settings):
    res = history(Corpus(settings), WATER_CODE, phrase="Реки и озёра")
    assert res["introduced"]["date"] == "2024-12-01"
    assert res["introduced"]["cause_act_code"] == "999150"


def test_at_date_before_the_new_code_reads_the_old_one(settings):
    res = at_date(Corpus(settings), WATER_CODE, "2024-11-15", anchor="st1")
    [p] = res["passages"]
    assert res["act_code"] == OLD_WATER_CODE and res["replaced_by"] == WATER_CODE
    assert p["file"] == f"{OLD_WATER}/rus.md" and "Реки" not in p["text"]
    assert res["sha"] in p["url"]


def test_at_date_on_the_old_code_itself(settings):
    res = at_date(Corpus(settings), OLD_WATER_CODE, "2025-01-01", anchor="st1")
    assert "Реки и озёра" in res["passages"][0]["text"]


def test_old_code_after_its_repeal(settings):
    with pytest.raises(InputError, match=f"replaced by act {WATER_CODE}"):
        at_date(Corpus(settings), OLD_WATER_CODE, "2025-06-01", anchor="st1")


def test_read_on_the_old_code_points_at_the_new(settings):
    with pytest.raises(InputError, match=f"replaced by act {WATER_CODE}"):
        read(Corpus(settings), OLD_WATER_CODE)


def test_history_on_the_old_code(settings):
    res = history(Corpus(settings), OLD_WATER_CODE)
    assert res["repealed_and_replaced_by"] == WATER_CODE
    assert res["title"] == "Водный кодекс Республики Казахстан"
    assert res["commits"][-1]["date"] == "2024-11-01" and res["predecessors"] == []
