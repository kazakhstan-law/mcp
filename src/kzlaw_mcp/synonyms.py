"""Everyday words the law does not use, and the legal wording to search for instead.

The law says "потребление табачных изделий", never "курение": a search in the words people
use finds nothing. search applies this only when a query found nothing, and says it did. Each
pattern is matched against the lowercased query as the model sent it, regex and all. The legal
wordings are tried in order, narrowest first: a broad one ("табачн\\w* издели") names every
article on tobacco before the one on smoking.
"""

from __future__ import annotations

import re

EVERYDAY: list[tuple[str, list[str]]] = [
    (
        r"\bкур(?:ени|ит|ил|ящ|ят|ю\b|е\b|ен\b)|сигарет|вейп",
        [
            r"потреблени\w* табачн\w*",
            r"электронн\w* систем\w* потреблени\w*",
            r"табачн\w* издели\w*",
        ],
    ),
    (r"\bгаи\b|гибдд|\bдпс\b|гаишн|автоинспектор", [r"полици\w*", r"органы? внутренних дел"]),
    (
        r"без\s+прав\b|лишени\w*\s+прав\b|водительск\w*\s+прав|прав[аоу]?\s+(?:на\s+)?вождени",
        [r"права управления транспортн\w*", r"водительск\w* удостоверени\w*"],
    ),
    (
        r"штраф\w*\s*(?:стоянк|площадк)|эвакуатор",
        [r"специализированн\w* стоянк\w*", r"задержани\w* транспортн\w*"],
    ),
    (r"психуч|психдиспансер|психбольниц", [r"психиатрическ\w*", r"психическ\w* расстройств\w*"]),
    (r"пьян|нетрезв|\bбух(?:ой|ая|ие|ом|им)\b|подшоф", [r"состояни\w* опьянени\w*"]),
    (r"зарплат|\bзп\b", [r"заработн\w* плат\w*"]),
    (r"больничн", [r"временн\w* нетрудоспособност\w*"]),
    (r"декрет", [r"отпуск\w* по беременности", r"отпуск\w* по уходу за ребенком"]),
    (r"прописк|прописан", [r"регистраци\w* по месту жительства"]),
    (r"\bдтп\b|авари[яиюей]", [r"дорожно-транспортн\w* происшестви\w*"]),
    (r"техосмотр", [r"технически\w* осмотр\w*"]),
    (r"развод", [r"расторжени\w* брака"]),
    (r"парковк|припарков", [r"остановк\w* и стоянк\w*", r"стоянк\w* транспортн\w*"]),
    (r"самокат", [r"электрическ\w* самокат\w*", r"средств\w* индивидуальной мобильности"]),
    (r"коммуналк", [r"коммунальн\w* услуг\w*"]),
    (r"мусор", [r"отход\w*", r"санитарн\w* очистк\w*"]),
    (r"\bшум", [r"тишин\w*"]),
]
_COMPILED = [(re.compile(p), legal) for p, legal in EVERYDAY]
_ESCAPE = re.compile(r"\\.")
_WORD = re.compile(r"[^\W\d_]{4,}")


def legal_wordings(query: str) -> list[str]:
    """The legal wordings for the everyday words in `query`, narrowest first."""
    q = query.lower()
    found = [w for pattern, legal in _COMPILED if pattern.search(q) for w in legal]
    return list(dict.fromkeys(found))


def stems(query: str) -> list[str]:
    """Word stems of a query for a loose heading match: "запрет\\w* куре" -> ["запр", "куре"]."""
    words = _WORD.findall(_ESCAPE.sub(" ", query.lower()))
    return list(dict.fromkeys(w[: min(6, max(4, len(w) - 2))] for w in words))
