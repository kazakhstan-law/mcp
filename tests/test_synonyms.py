def test_relaxed_stems():
    from kzlaw_mcp.synonyms import any_order, relaxed

    assert relaxed("налоговые вычеты по индивидуальному подоходному налогу") == [
        ["индиви", "подохо", "нало", "выче"],
        ["индиви", "подохо", "нало"],
    ]
    assert relaxed("стандартн.{0,20}вычет") == [["станда", "выче"]]
    assert relaxed("^#### Статья \\d+\\. Пен") == [] and relaxed("курение") == []
    assert any_order(["аб", "вг"]) == "аб.*вг|вг.*аб"
