import pytest

from conftest import KOAP, KOAP_CODE, PD_CODE, PDD, PDD_CODE
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


def test_missing_language_is_not_called_not_in_force(settings):
    # the traffic rules have Russian text only; on 2023-07-15 the act was in force
    with pytest.raises(InputError, match="no 'kaz' text"):
        at_date(Corpus(settings), PDD_CODE, "2023-07-15", lang="kaz", point="1")


def test_at_date_before_the_corpus_has_the_act_says_no_data(settings):
    corpus = Corpus(settings)
    # Prod: at_date('81245', 'st613', '2016-09-15') answered "was not in force", which reads
    # as "the act did not exist"; the corpus simply starts later.
    with pytest.raises(InputError, match="no data before 2025-05-01.*adopted on 2013-05-21"):
        at_date(corpus, PD_CODE, "2020-01-01", anchor="st9")
    with pytest.raises(InputError, match="not adopted yet on 2010-01-01"):
        at_date(corpus, PD_CODE, "2010-01-01")
    res = at_date(corpus, PD_CODE, "2020-01-01", anchor="st9", earliest=True)
    assert (res["approximate"], res["as_of"], res["asked"]) == (True, "2025-05-01", "2020-01-01")
    assert "статистических целей" in res["passages"][0]["text"]


def test_amended_between_reads_footnotes():
    from kzlaw_mcp.passages import _amended_between

    text = (
        "1. Текст.\n"
        "> *Сноска. Статья 613 с изменениями, внесенными законами РК от 29.10.2015 № 376-V "
        "(вводится в действие с 01.01.2016); от 22.12.2016 № 28-VI; от 03.10.2024 № 131-VIII.*\n"
        "2. Штраф от 01.01.2016 № 5 в тексте статьи, не в сноске.\n"
    )
    assert _amended_between([text], "2016-09-15", "2017-07-11") == [
        {"date": "2016-12-22", "number": "28-VI"}
    ]
