from conftest import KOAP_2024, pdd_text
from kzlaw_mcp.locate import (
    ANCHOR_ID,
    POINT_LABEL,
    article_span,
    line_context,
    point_spans,
    stage_between,
)


def test_article_span_runs_to_the_next_article():
    span = article_span(KOAP_2024, "st592")
    assert span.heading == "Статья 592. Превышение установленной скорости движения"
    assert "3-1. Те же действия" in span.text and "Сноска" in span.text
    assert "Статья 593" not in span.text
    assert span.text.splitlines()[0] == '<a id="st592"></a>'


def test_article_span_missing_anchor():
    assert article_span(KOAP_2024, "st9999") is None


def test_point_inside_an_article():
    art = article_span(KOAP_2024, "st592")
    [part] = point_spans(KOAP_2024, "3-1", within=art)
    assert part.text.startswith("3-1. Те же действия")
    assert "сорока месячных" in part.text
    assert "Статья 593" not in part.text


def test_point_label_repeats_across_annexes():
    spans = point_spans(pdd_text(True), "1")
    assert [s.heading for s in spans] == [
        "Глава 1. Общие положения",
        "Глава 1. Горизонтальная разметка",
    ]


def test_point_span_keeps_continuation_and_footnote():
    [span] = point_spans(pdd_text(True), "168-1")
    assert "восемнадцати лет" in span.text and "№ 671" in span.text
    assert "169." not in span.text


def test_line_context_inside_article_part():
    lines = KOAP_2024.split("\n")
    lineno = next(i for i, l in enumerate(lines, 1) if l.startswith("3-1."))
    ctx = line_context(lines, lineno + 2)  # the "влекут штраф" continuation line
    assert (ctx.anchor, ctx.point) == ("st592", "3-1")
    assert ctx.heading.startswith("Статья 592")


def test_line_context_without_anchors():
    lines = pdd_text(True).split("\n")
    lineno = next(i for i, l in enumerate(lines, 1) if "восемнадцати" in l)
    ctx = line_context(lines, lineno)
    assert (ctx.anchor, ctx.point, ctx.heading) == (
        None,
        "168-1",
        "Глава 24. Движение средств индивидуальной мобильности",
    )


def test_chapter_heading_resets_the_anchor():
    text = '<a id="st1"></a>\n\n### Статья 1\n\nтекст\n\n## Глава 2\n\nвводный абзац\n'
    lines = text.split("\n")
    assert line_context(lines, len(lines) - 1).anchor is None


def test_grammar():
    for ok in ("st592", "st62-1", "an3_st1", "st62_p2", "st62_p2_sp3", "p168-1", "an0_p168-1"):
        assert ANCHOR_ID.match(ok)
    for bad in ("592", "st", "../st1", "st1;rm", "ST592", "p", "an0_", "p1_st2"):
        assert not ANCHOR_ID.match(bad)
    assert POINT_LABEL.match("168-1") and not POINT_LABEL.match("1.2; x")


POINT_ANCHORED = (
    "## Глава 24. Движение средств индивидуальной мобильности\n\n"
    '<a id="an0_p168"></a>\n\n168. Первый пункт.\n\nпродолжение\n\n'
    '<a id="an0_p168-1"></a>\n\n168-1. Лицам до восемнадцати лет.\n\n'
    '<a id="an0_p169"></a>\n\n169. Следующий пункт.\n'
)


def test_a_point_anchor_spans_its_point_alone():
    # Corpus builds from 2026-09-27 anchor the points of an order that has no articles.
    span = article_span(POINT_ANCHORED, "an0_p168-1")
    assert span.text.splitlines()[0] == '<a id="an0_p168-1"></a>'
    assert "восемнадцати" in span.text and "169." not in span.text
    [part] = point_spans(POINT_ANCHORED, "168-1", within=span)
    assert part.text == "168-1. Лицам до восемнадцати лет."


def test_line_context_reports_the_point_anchor():
    lines = POINT_ANCHORED.split("\n")
    lineno = next(i for i, l in enumerate(lines, 1) if l == "продолжение")
    ctx = line_context(lines, lineno)
    assert (ctx.anchor, ctx.point) == ("an0_p168", "168")


def test_stage_comes_from_the_lines_that_changed():
    placeholder = "3) вводится в действие с 01.01.2027 в соответствии с Законом РК № 1-VIII."
    old = ["1) первое;", placeholder]
    # an edit elsewhere in an article that keeps its placeholder announces nothing
    assert stage_between(old, ["1) первое изменено;", placeholder]) is None
    assert stage_between(["1) первое;"], old) == "announced"
    assert stage_between(old, ["1) первое;", "3) текст."]) == "took_effect"
