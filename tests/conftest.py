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
