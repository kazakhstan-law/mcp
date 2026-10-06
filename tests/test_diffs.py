from kzlaw_mcp.diffs import moves, renumbered, word_diffs

SIGNS = ["## Дорожные знаки", "Правила применения знаков.", "1.1 «Переезд».", "1.2 «Тоннель»."]


def item(label: str, status: str) -> dict:
    return {"label": label, "heading": None, "status": status}


def test_a_section_that_follows_new_points_is_a_move_not_a_loss_and_a_gain():
    # ПДД 183572, 2025-11-10: points 181-192 inserted after п.180; the road-signs section
    # that followed п.180 now follows п.192. Compared by anchor it read as two changes.
    entries = [
        ("p180", item("п. 180", "modified"), [" 180. Текст.", *(f"-{ln}" for ln in SIGNS)], "diff"),
        ("p181", item("п. 181", "added"), ["181. Колонна."], "text"),
        ("p192", item("п. 192", "added"), ["192. Участники колонны.", *SIGNS], "text"),
    ]
    out, moved = moves(entries)
    assert moved == [{"from": "п. 180", "to": "п. 192", "lines": 4, "starts": "## Дорожные знаки"}]
    assert [e[1]["label"] for e in out] == ["п. 181", "п. 192"]  # п.180 only lost the section
    assert out[1][2] == ["192. Участники колонны."] and out[1][1]["moved_in"] == moved


def test_a_short_repeated_line_is_not_a_move():
    entries = [
        ("p1", item("п. 1", "modified"), ["-1) иные случаи."], "diff"),
        ("p2", item("п. 2", "added"), ["2. Текст.", "1) иные случаи."], "text"),
    ]
    assert moves(entries) == (entries, [])


def test_the_same_text_under_a_new_number_is_renumbered():
    entries = [
        ("p5", item("п. 5", "removed"), ["5. Водитель уступает дорогу."], "text"),
        ("p6", item("п. 6", "added"), ["6. Водитель уступает дорогу."], "text"),
        ("p7", item("п. 7", "added"), ["7. Новое правило."], "text"),
    ]
    out = renumbered(entries)
    assert [(e[1]["label"], e[1]["status"], e[1].get("from")) for e in out] == [
        ("п. 6", "renumbered", "п. 5"),
        ("п. 7", "added", None),
    ]


def test_a_long_paragraph_is_diffed_by_words():
    words = " ".join(f"слово{n}" for n in range(80))
    old, new = f"{words} штраф десять МРП {words}", f"{words} штраф двадцать МРП {words}"
    (line,) = word_diffs([f"-{old}", f"+{new}"])
    assert line.startswith("~") and "[-десять-] {+двадцать+}" in line
    assert len(line) < 300  # unchanged words beyond the context are elided
    assert word_diffs(["-коротко", "+иначе"]) == ["-коротко", "+иначе"]


def test_a_section_edited_as_it_moved_shows_only_its_edits():
    signs = [f"{n}.1 «Знак {n}»." for n in range(10)]
    edited = [*signs[:4], "4.1 «Знак четыре».", *signs[5:]]
    entries = [
        ("p180", item("п. 180", "modified"), [" 180. Текст.", *(f"-{ln}" for ln in signs)], "diff"),
        ("p192", item("п. 192", "added"), ["192. Участники колонны.", *edited], "text"),
    ]
    out, moved = moves(entries)
    assert moved[0] | {"starts": ""} == {
        "from": "п. 180",
        "to": "п. 192",
        "lines": 10,
        "edited": True,
        "starts": "",
    }
    assert [(e[1]["label"], e[1]["status"]) for e in out] == [
        ("п. 192", "added"),
        ("п. 180 → п. 192", "moved"),
    ]
    assert out[0][2] == ["192. Участники колонны."]
    assert [ln for ln in out[1][2] if ln[:1] in "+-"] == ["-4.1 «Знак 4».", "+4.1 «Знак четыре»."]


def test_a_renumbered_point_of_several_lines_is_not_a_move():
    from kzlaw_mcp.changes import _readable

    rest = ["1) пешеходам;", "2) велосипедистам;", "3) иным лицам."]
    old, new = ["5. Водитель уступает дорогу:", *rest], ["6. Водитель уступает дорогу:", *rest]
    entries = [
        ("p5", item("п. 5", "removed"), old, "text"),
        ("p6", item("п. 6", "added") | {"citation": "[п. 6](new)"}, new, "text"),
    ]
    out, moved = _readable(entries)
    assert moved == [] and [(e[1]["label"], e[1]["status"]) for e in out] == [
        ("п. 6", "renumbered")
    ]


def test_a_moved_item_is_cited_on_both_sides():
    signs = [f"{n}.1 «Знак {n}»." for n in range(10)]
    edited = [*signs[:4], "4.1 «Знак четыре».", *signs[5:]]
    src = item("п. 180", "modified") | {"before_citation": "[п. 180, ред. до](old)"}
    dst = item("п. 192", "added") | {"citation": "[п. 192](new)"}
    entries = [
        ("p180", src, [" 180. Текст.", *(f"-{ln}" for ln in signs)], "diff"),
        ("p192", dst, ["192. Участники.", *edited], "text"),
    ]
    out, _ = moves(entries)
    (moved,) = [e[1] for e in out if e[1]["status"] == "moved"]
    assert (moved["citation"], moved["before_citation"]) == (
        "[п. 192](new)",
        "[п. 180, ред. до](old)",
    )


def test_three_lines_scattered_over_a_long_article_are_not_its_source():
    common = ["1) пешеходам;", "2) велосипедистам;", "3) иным лицам."]
    spread = [common[0], *(f"текст {n}" for n in range(10)), common[1], "ещё", common[2]]
    entries = [
        ("p1", item("п. 1", "modified"), [" 1. Текст.", *(f"-{ln}" for ln in common)], "diff"),
        ("p9", item("п. 9", "added"), ["9. Новое.", *spread], "text"),
    ]
    assert moves(entries)[1] == []
