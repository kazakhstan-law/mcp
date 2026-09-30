import pytest

from conftest import KOAP_CODE, OLD_WATER_CODE, PD_AMENDER, PD_CODE, PDD_CODE, WATER_CODE
from kzlaw_mcp.changes import changes, segments
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.history import history, requisite_date
from kzlaw_mcp.passages import read


def by_label(res: dict) -> dict:
    return {i["label"]: i for i in res["items"]}


def test_latest_version_by_article(settings):
    res = changes(Corpus(settings), PD_CODE)
    assert res["version"]["date"] == "2026-07-12"
    assert res["previous"]["date"] == "2026-01-09"
    items = by_label(res)
    assert items["ст. 10-1"]["status"] == "added"
    assert "Оператор уведомляет" in items["ст. 10-1"]["text"]
    assert items["ст. 9"]["status"] == "modified"
    assert items["ст. 9"]["stage"] == "took_effect"
    assert "+3) обработки данных для ведения реестра;" in items["ст. 9"]["diff"]
    assert "@@" not in items["ст. 9"]["diff"]
    assert f"/blob/{res['version']['sha']}/" in items["ст. 9"]["citation"]
    assert f"/blob/{res['previous']['sha']}/" in items["ст. 9"]["before_citation"]
    assert "ст. 1" not in items  # its footnote did not change in this version


def test_version_that_only_announces(settings):
    corpus = Corpus(settings)
    sha = next(c["sha"] for c in history(corpus, PD_CODE)["commits"] if c["date"] == "2026-01-09")
    res = changes(corpus, PD_CODE, sha=sha[:10])
    assert by_label(res)["ст. 9"]["stage"] == "announced"
    # a footnote alone does not make an article modified
    assert res["footnote_only"] == ["ст. 1"]


def test_by_date_and_anchor(settings):
    res = changes(Corpus(settings), PD_CODE, date="2026-03-01", anchor="st9")
    assert res["version"]["date"] == "2026-01-09"
    assert [i["label"] for i in res["items"]] == ["ст. 9"]


def test_split_code_renamed_part_is_not_delete_plus_add(settings):
    res = changes(Corpus(settings), KOAP_CODE)
    assert [(i["label"], i["status"]) for i in res["items"]] == [("ст. 592", "modified")]
    assert "+3-1. Те же действия" in res["items"][0]["diff"]


def test_order_without_anchors_compares_points(settings):
    res = changes(Corpus(settings), PDD_CODE)
    assert [(i["label"], i["status"]) for i in res["items"]] == [("п. 168-1", "added")]


def test_first_version(settings):
    corpus = Corpus(settings)
    first = history(corpus, PD_CODE)["first_version"]["sha"]
    res = changes(corpus, PD_CODE, sha=first)
    assert res["previous"] is None and res["items"] == []


def test_amending_act_lists_the_acts_it_changed(settings):
    res = changes(Corpus(settings), PD_AMENDER)
    assert "256-VIII" in res["amending_act"]["requisite"]
    assert [(a["act_code"], a["date"]) for a in res["acts_changed"]] == [
        (PD_CODE, "2026-01-09"),
        (PD_CODE, "2026-07-12"),
    ]
    assert res["acts_changed"][0]["title"] == "О персональных данных и их защите"


def test_unknown_act_points_to_changes(settings):
    with pytest.raises(InputError, match="changes"):
        read(Corpus(settings), PD_AMENDER)
    with pytest.raises(InputError, match="not in the corpus"):
        changes(Corpus(settings), "424242")


@pytest.mark.parametrize(
    "kwargs", [{"sha": "zzz"}, {"sha": "deadbeef"}, {"date": "2026-1-1"}, {"anchor": "../x"}]
)
def test_bad_input(settings, kwargs):
    with pytest.raises(InputError):
        changes(Corpus(settings), PD_CODE, **kwargs)


def test_sha_of_another_act(settings):
    corpus = Corpus(settings)
    koap = history(corpus, KOAP_CODE)["commits"][0]["sha"]
    with pytest.raises(InputError, match="did not change"):
        changes(corpus, PD_CODE, sha=koap)


def test_read_outline_lists_pending_provisions(settings):
    res = read(Corpus(settings), PD_CODE)
    [p] = res["pending"]
    assert p["label"] == "ст. 1-2" and p["effective"] == "2027-01-01"
    assert p["announced_in"]["date"] == "2026-07-12"
    assert p["announced_in"]["cause_act_code"] == PD_AMENDER
    # the overview stops before the first article instead of mid-sentence
    assert res["overview"].endswith("## Глава 1. ОБЩИЕ ПОЛОЖЕНИЯ")


def test_history_carries_the_adoption_date(settings):
    top = history(Corpus(settings), PD_CODE)["commits"][0]
    assert (top["date"], top["cause_act_date"]) == ("2026-07-12", "2026-01-09")


@pytest.mark.parametrize(
    ("requisite", "date"),
    [
        ("Закон Республики Казахстан от 24 июня 2026 года № 326-VIII ЗРК", "2026-06-24"),
        ("Приказ Министра от 31 августа 2023 года № 671", "2023-08-31"),
        ("Кодекс", None),
    ],
)
def test_requisite_date(requisite, date):
    assert requisite_date(requisite) == date


def test_segments_keep_nested_anchors_in_their_article():
    text = '<a id="st5"></a>\n\n### Статья 5\n\n<a id="st5_p1"></a>\n\n1. Текст.\n\n<a id="st6"></a>\n\n### Статья 6\n'
    assert [s.key for s in segments("f.md", text)] == ["st5", "st6"]


def test_repealed_act(settings):
    corpus = Corpus(settings)
    # its last version is the one before the repeal, not the repeal commit
    res = changes(corpus, OLD_WATER_CODE)
    assert res["version"]["date"] == "2024-12-01"
    assert "+2. Реки и озёра охраняются государством." in res["items"][0]["diff"]
    repeal = history(corpus, OLD_WATER_CODE)["commits"][0]["sha"]
    res = changes(corpus, OLD_WATER_CODE, sha=repeal)
    assert res["repealed"] is True and res["replaced_by"] == WATER_CODE


def test_impossible_date(settings):
    with pytest.raises(InputError):
        changes(Corpus(settings), PD_CODE, date="2026-13-45")
