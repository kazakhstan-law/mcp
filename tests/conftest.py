"""A tiny corpus with the shapes the tools depend on (spec §3.2)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kzlaw_mcp.config import Settings

KOAP = "02-codes/2014/0705-ob-administrativnykh-pravonarusheniiakh-81245"
KOAP_CODE = "81245"
PDD = "07-ministerial/103003000000-qriim/2023/0630-ob-utverzhdenii-pravil-dorozhnogo-dvizheniia-183572"
PDD_CODE = "183572"
CONST_CODE = "1005029"
OLD_WATER = "02-codes/2003/0709-vodnyi-kodeks-respubliki-kazakhstan-3880"
OLD_WATER_CODE = "3880"
WATER = "02-codes/2025/0409-vodnyi-kodeks-respubliki-kazakhstan-209026"
WATER_CODE = "209026"
PD = "03-laws/2013/0521-o-personalnykh-dannykh-i-ikh-zashchite-72730"
PD_CODE = "72730"
PD_AMENDER = "221115"
LABOUR = "03-laws/1999/1210-o-trude-v-respublike-kazakhstan-4875"
LABOUR_CODE = "4875"


def meta(code: str, title: str, requisite: str) -> str:
    return (
        f"act_code: '{code}'\n"
        f"requisite: {requisite}\n"
        f"title:\n  rus: {title}\n  kaz: {title} (kaz)\n"
    )


def commit(
    repo: Path,
    date: str,
    files: dict[str, str | None],
    subject: str,
    trailers: dict[str, str] | None = None,
) -> None:
    for rel, content in files.items():
        path = repo / rel
        if content is None:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    body = "\n".join(f"{k}: {v}" for k, v in (trailers or {}).items())
    message = f"{subject}\n\n{body}" if body else subject
    stamp = f"{date}T00:00:00Z"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "corpus",
        "GIT_AUTHOR_EMAIL": "corpus@example.invalid",
        "GIT_COMMITTER_NAME": "corpus",
        "GIT_COMMITTER_EMAIL": "corpus@example.invalid",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, env=env, check=True)


def init(repo: Path) -> Path:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return repo


ART_593 = '<a id="st593"></a>\n\n### Статья 593. Нарушение правил проезда\n\n1. Текст статьи 593.\n'


def koap_part(parts_3: str) -> str:
    return (
        "↑ [Вся редакция](../rus.md)\n\n"
        "## Глава 30. Административные правонарушения на транспорте\n\n"
        '<a id="st592"></a>\n\n'
        "### Статья 592. Превышение установленной скорости движения\n\n"
        "1. Превышение водителями установленной скорости движения на величину "
        "от десяти до двадцати километров в час -\n\nвлечет предупреждение.\n\n"
        f"{parts_3}\n" + ART_593
    )


KOAP_2022 = koap_part(
    "3. Те же действия, совершенные на величину от сорока и более километров в час, -\n\n"
    "влекут штраф в размере двадцати месячных расчетных показателей.\n"
)
KOAP_2024 = koap_part(
    "3. Те же действия, совершенные на величину от сорока до шестидесяти километров в час, -\n\n"
    "влекут штраф в размере двадцати месячных расчетных показателей.\n\n"
    "3-1. Те же действия, совершенные на величину от шестидесяти и более километров в час, -\n\n"
    "влекут штраф в размере сорока месячных расчетных показателей.\n\n"
    "> *Сноска. Статья 592 дополнена частью 3-1 Законом РК от 03.10.2024 № 131-VIII.*\n"
)


def pd_text(stage: int) -> str:
    """The personal data law: 0 as enacted, 1 with a deferred subpoint, 2 once it took effect."""
    sub3 = {
        0: "",
        1: "3) вводится в действие по истечении шести месяцев после дня его первого "
        "официального опубликования в соответствии с Законом РК от 09.01.2026 № 256-VIII.\n\n",
        2: "3) обработки данных для ведения реестра;\n\n",
    }[stage]
    note = (
        "\n> *Сноска. Статья 1 с изменением, внесенным Законом РК от 09.01.2026 № 256-VIII.*\n"
        if stage
        else ""
    )
    # Article 10-1 is announced as a bare heading over a placeholder footnote, as zan.gov.kz
    # publishes a deferred article, and gets its anchor and text when it takes effect.
    later = {
        0: "",
        1: "\n## Статья 10-1. Уведомление об обработке\n\n> *Сноска. Вводится в действие с "
        "12.07.2026 в соответствии с Законом РК от 09.01.2026 № 256-VIII.*\n",
        2: '\n<a id="st1-2"></a>\n\n### Статья 1-2. Вводится в действие с 01.01.2027 в '
        "соответствии с Законом РК от 30.12.2025 № 248-VIII.\n"
        '\n<a id="st10-1"></a>\n\n### Статья 10-1. Уведомление об обработке\n\n'
        "1. Оператор уведомляет уполномоченный орган.\n",
    }[stage]
    return (
        "# О персональных данных и их защите\n\n"
        "Настоящий Закон регулирует общественные отношения в сфере персональных данных.\n\n"
        "## Глава 1. ОБЩИЕ ПОЛОЖЕНИЯ\n\n"
        '<a id="st1"></a>\n\n### Статья 1. Основные понятия\n\n'
        "1) персональные данные – сведения о субъекте;\n" + note + later + "\n"
        '<a id="st9"></a>\n\n### Статья 9. Сбор без согласия\n\n'
        "1) осуществления деятельности правоохранительных органов;\n\n"
        "2) статистических целей;\n\n" + sub3 + "4) в иных случаях, установленных законами.\n"
    )


def pdd_text(with_scooters: bool) -> str:
    scooters = (
        "168-1. Водители электрических самокатов двигаются по велосипедной дорожке.\n\n"
        "Лицам, не достигшим восемнадцати лет, движение по проезжей части запрещается.\n\n"
        "> *Сноска. Глава дополнена пунктом 168-1 приказом от 31.08.2023 № 671.*\n\n"
        if with_scooters
        else ""
    )
    return (
        "# Об утверждении Правил дорожного движения\n\n"
        "## Глава 1. Общие положения\n\n"
        "1. Настоящие Правила устанавливают порядок дорожного движения.\n\n"
        "## Глава 24. Движение средств индивидуальной мобильности\n\n"
        "*167. Исключен приказом от 31.08.2023 № 671.*\n\n"
        + scooters
        + "169. Средства индивидуальной мобильности не перевозят пассажиров.\n\n"
        "## Разметка дорожная\n\n"
        "## Глава 1. Горизонтальная разметка\n\n"
        "1. Горизонтальная разметка наносится краской.\n"
    )


@pytest.fixture(scope="session")
def corpus_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("corpus")

    codes = init(root / "codes")
    commit(
        codes,
        "1995-08-30",
        {
            "00-constitution/rus.md": '# Конституция\n\n<a id="st1"></a>\n\n### Статья 1\n\n1. Республика.\n',
            "00-constitution/meta.yaml": meta(
                CONST_CODE, "Конституция Республики Казахстан", "Конституция"
            ),
        },
        "Конституция",
    )
    # Repealed in 2007 with no act in force naming it in `replaces:`.
    labour = (
        "# О труде в Республике Казахстан\n\n"
        '<a id="st12"></a>\n\n### Статья 12. Форма трудового договора\n\n'
        "1. Индивидуальный трудовой договор заключается в письменной форме.\n"
    )
    commit(
        codes,
        "1999-12-10",
        {
            f"{LABOUR}/meta.yaml": meta(
                LABOUR_CODE,
                "О труде в Республике Казахстан",
                "Закон РК от 10 декабря 1999 года N 493",
            ),
            f"{LABOUR}/rus.md": labour,
        },
        "О труде",
    )
    commit(
        codes,
        "2007-01-12",
        {f"{LABOUR}/rus.md": labour + "\n2. Экземпляр договора выдаётся работнику.\n"},
        "№224 О внесении изменений",
        {"Cause-Act-Code": "31399", "Acts-Changed": "1"},
    )
    commit(codes, "2007-05-15", {LABOUR: None}, "№252 О введении в действие Трудового кодекса")
    koap_meta = meta(
        KOAP_CODE,
        "Об административных правонарушениях",
        "Кодекс Республики Казахстан от 5 июля 2014 года № 235-V.",
    )
    commit(
        codes,
        "2022-01-10",
        {
            f"{KOAP}/meta.yaml": koap_meta,
            f"{KOAP}/rus.md": "# Об административных правонарушениях\n\n| [Глава 30](rus/sec002-ch010.md) |\n",
            f"{KOAP}/rus/sec002-ch010.md": KOAP_2022,
            f"{KOAP}/kaz.md": "# ӘКІМШІЛІК ҚҰҚЫҚБҰЗУШЫЛЫҚ ТУРАЛЫ\n\nЖылдамдықты асыру.\n",
        },
        "№100-VII О внесении изменений в Кодекс",
        {
            "Cause-Act-Code": "999100",
            "Cause-Act-Requisite": "Закон РК от 10 января 2022 года № 100-VII",
            "Acts-Changed": "1",
        },
    )
    commit(
        codes,
        "2024-10-03",
        {
            f"{KOAP}/rus/sec002-ch010.md": None,
            f"{KOAP}/rus/sec002-ch030.md": KOAP_2024,
            f"{KOAP}/rus.md": "# Об административных правонарушениях\n\n| [Глава 30](rus/sec002-ch030.md) |\n",
        },
        "№131-VIII О внесении изменений и дополнений в Кодекс",
        {
            "Cause-Act-Code": "999131",
            "Cause-Act-Requisite": "Закон РК от 3 октября 2024 года № 131-VIII",
            "Acts-Changed": "1",
        },
    )

    water_1 = '# Водный кодекс\n\n<a id="st1"></a>\n\n### 1-бап. Су қоры\n\n1. Водный фонд включает водные объекты.\n'
    water_2 = water_1 + "\n2. Реки и озёра охраняются государством.\n"
    old_meta = meta(
        OLD_WATER_CODE, "Водный кодекс Республики Казахстан", "Кодекс РК от 9 июля 2003 года № 481"
    )
    commit(
        codes,
        "2024-11-01",
        {f"{OLD_WATER}/meta.yaml": old_meta, f"{OLD_WATER}/rus.md": water_1},
        "Водный кодекс",
    )
    commit(
        codes,
        "2024-12-01",
        {f"{OLD_WATER}/rus.md": water_2},
        "№150-VIII О внесении изменений в Водный кодекс",
        {"Cause-Act-Code": "999150", "Acts-Changed": "1"},
    )
    new_meta = meta(
        WATER_CODE,
        "Водный кодекс Республики Казахстан",
        "Кодекс РК от 9 апреля 2025 года № 178-VIII",
    ) + (
        "replaces:\n"
        f"- code: '{OLD_WATER_CODE}'\n"
        "  requisite: Кодекс РК от 9 июля 2003 года № 481\n"
        "  title:\n    rus: Водный кодекс Республики Казахстан\n    kaz: Су кодексі\n"
        f"  link: https://zan.gov.kz/client/#!/doc/{OLD_WATER_CODE}/rus\n"
        f"  path: {OLD_WATER}\n"
    )
    commit(
        codes,
        "2025-04-09",
        {OLD_WATER: None, f"{WATER}/meta.yaml": new_meta, f"{WATER}/rus.md": water_2},
        "№178-VIII Водный кодекс Республики Казахстан",
        {"Cause-Act-Code": WATER_CODE, "Acts-Changed": "2"},
    )

    pd_meta = meta(
        PD_CODE, "О персональных данных и их защите", "Закон РК от 21 мая 2013 года № 94-V"
    )
    commit(codes, "2025-05-01", {f"{PD}/meta.yaml": pd_meta, f"{PD}/rus.md": pd_text(0)}, "№94-V")
    pd_cause = {
        "Cause-Act-Code": PD_AMENDER,
        "Cause-Act-Requisite": "Закон Республики Казахстан от 9 января 2026 года № 256-VIII ЗРК",
        "Cause-Act-Title": "О внесении изменений и дополнений по вопросам цифровизации",
        "Cause-Act-Link": f"https://zan.gov.kz/client/#!/doc/{PD_AMENDER}/rus",
        "Acts-Changed": "1",
    }
    commit(codes, "2026-01-09", {f"{PD}/rus.md": pd_text(1)}, "№256-VIII О внесении", pd_cause)
    commit(codes, "2026-07-12", {f"{PD}/rus.md": pd_text(2)}, "№256-VIII О внесении", pd_cause)

    ministerial = init(root / "ministerial")
    pdd_meta = meta(
        PDD_CODE,
        "Об утверждении Правил дорожного движения",
        "Приказ Министра внутренних дел РК от 30 июня 2023 года № 534",
    )
    commit(
        ministerial,
        "2023-06-30",
        {
            f"{PDD}/meta.yaml": pdd_meta,
            f"{PDD}/rus.md": pdd_text(False),
        },
        "3 акта без указанного основания",
    )
    commit(
        ministerial,
        "2023-08-31",
        {f"{PDD}/rus.md": pdd_text(True)},
        "№671 О внесении изменений в приказ № 534",
        {
            "Cause-Act-Code": "999671",
            "Cause-Act-Requisite": "Приказ Министра внутренних дел РК от 31 августа 2023 года № 671",
            "Acts-Changed": "1",
        },
    )
    return root


@pytest.fixture
def settings(corpus_root, tmp_path) -> Settings:
    return Settings(corpus_root=corpus_root, log_path=tmp_path / "calls.jsonl", ip_salt="test")


@pytest.fixture
def anyio_backend():
    return "asyncio"
