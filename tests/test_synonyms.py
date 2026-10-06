def test_relaxed_stems():
    from kzlaw_mcp.synonyms import any_order, relaxed

    assert relaxed("налоговые вычеты по индивидуальному подоходному налогу") == [
        ["индиви", "подохо", "нало", "выче"],
        ["индиви", "подохо", "нало"],
    ]
    assert relaxed("стандартн.{0,20}вычет") == [["станда", "выче"]]
    assert relaxed("^#### Статья \\d+\\. Пен") == [] and relaxed("курение") == []
    assert any_order(["абвг", "деёж"]) == "абвг.*деёж|деёж.*абвг"


def test_relaxed_keeps_numbers_and_abbreviations():
    import re

    from kzlaw_mcp.synonyms import any_order, relaxed

    # Each was relaxed to "проце став" before, the same retry for two different rates.
    assert relaxed("ставка\\w* 3 процент") == [["3", "проце", "став"], ["3", "проце"]]
    assert relaxed("ставка\\w* 3 процент") != relaxed("ставка\\w* 4 процент")
    assert relaxed("декларац 910") == [["910", "деклар"]]
    assert relaxed("ИПН вычеты") == [["ипн", "выче"]]
    # Regex syntax is not the query's numbers; a short lowercase word is not an abbreviation.
    assert relaxed("стандартн.{0,20}вычет[0-9]") == [["станда", "выче"]]
    assert relaxed("вид на жительство") == []
    # Alternatives are not all required: prod "(3 063|3 180) тенге" found nothing that way.
    assert relaxed("месячный расчетный показатель (3 063|3 180) тенге")[0] == [
        "показа",
        "расчет",
        "месячн",
        "тенг",
    ]
    pattern = re.compile(any_order(["3", "ипн"]), re.IGNORECASE)
    assert pattern.search("ставка 3 процента по ИПН")
    assert not pattern.search("в 2023 году ИПН") and not pattern.search("3 года, ипнотека")
