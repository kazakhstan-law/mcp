import pytest

from conftest import KOAP, KOAP_CODE, PDD, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.passages import at_date, read


def test_read_current_article(settings):
    res = read(Corpus(settings), KOAP_CODE, anchor="st592")
    [p] = res["passages"]
    assert "от шестидесяти и более" in p["text"] and p["file"] == f"{KOAP}/rus/sec002-ch030.md"
    assert p["url"] == (
        f"https://github.com/kazakhstan-law/codes/blob/{res['sha']}/{KOAP}/rus/sec002-ch030.md#st592"
    )
    assert p["citation"] == f"[ст. 592]({p['url']})"
    assert res["as_of"] == "current"


def test_at_date_follows_the_renamed_part(settings):
    res = at_date(Corpus(settings), KOAP_CODE, "2022-06-01", anchor="st592")
    [p] = res["passages"]
    assert p["file"].endswith("rus/sec002-ch010.md")
    assert "от сорока и более" in p["text"] and "шестидесяти" not in p["text"]
    assert res["commit_date"] == "2022-01-10" and res["sha"] in p["url"]


def test_part_of_an_article(settings):
    [p] = read(Corpus(settings), KOAP_CODE, anchor="st592", point="3-1")["passages"]
    assert p["text"].startswith("3-1.") and "?plain=1#L" in p["url"]
    assert p["citation"].startswith("[ст. 592, ч. 3-1]")


def test_point_without_anchor(settings):
    res = read(Corpus(settings), PDD_CODE, point="168-1")
    [p] = res["passages"]
    assert "восемнадцати" in p["text"] and p["heading"].startswith("Глава 24")
    assert p["url"].endswith(f"{PDD}/rus.md?plain=1#L{p['lines'][0]}-L{p['lines'][1]}")


def test_repeated_point_label_returns_all(settings):
    res = read(Corpus(settings), PDD_CODE, point="1")
    assert [p["heading"] for p in res["passages"]] == [
        "Глава 1. Общие положения",
        "Глава 1. Горизонтальная разметка",
    ]


def test_point_absent_on_an_earlier_date(settings):
    with pytest.raises(InputError, match="point 168-1 not found"):
        at_date(Corpus(settings), PDD_CODE, "2023-07-15", point="168-1")


def test_unknown_anchor(settings):
    with pytest.raises(InputError, match="anchor st9999 not found in act 81245"):
        read(Corpus(settings), KOAP_CODE, anchor="st9999")


def test_act_not_yet_in_force(settings):
    with pytest.raises(InputError, match="not in force on 2021-01-01"):
        at_date(Corpus(settings), KOAP_CODE, "2021-01-01", anchor="st592")


def test_before_the_corpus_starts(settings):
    with pytest.raises(InputError, match="no history before 1990-01-01"):
        at_date(Corpus(settings), KOAP_CODE, "1990-01-01")


@pytest.mark.parametrize("date", ["2022-13-01", "01.06.2022", "2022-06-01; ls"])
def test_bad_dates(settings, date):
    with pytest.raises(InputError, match="YYYY-MM-DD"):
        at_date(Corpus(settings), KOAP_CODE, date)


@pytest.mark.parametrize("kw", [{"anchor": "../../x"}, {"anchor": "st1 st2"}, {"point": "1; rm"}])
def test_bad_locators(settings, kw):
    with pytest.raises(InputError):
        read(Corpus(settings), KOAP_CODE, **kw)


def test_overview_without_locator(settings):
    res = read(Corpus(settings), KOAP_CODE)
    assert res["overview"].startswith("# Об административных") and res["parts"]
    assert "passages" not in res
