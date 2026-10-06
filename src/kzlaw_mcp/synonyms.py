"""Everyday words the law does not use, and the legal wording to search for instead.

The law says "потребление табачных изделий", never "курение": a search in the words people
use finds nothing. search applies this only when a query found nothing, and says it did. Each
pattern is matched against the lowercased query as the model sent it, regex and all. The legal
wordings are tried in order, narrowest first: a broad one ("табачн\\w* издели") names every
article on tobacco before the one on smoking.
"""

from __future__ import annotations

import re
from itertools import permutations

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
    (r"самогон", [r"производств\w* .*алкогольн\w* продукци\w*", r"этилов\w* спирт\w*"]),
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


# Words in nearly every paragraph or heading: as a required stem they only slow the search.
_COMMON = (
    "стат",
    "пункт",
    "подпункт",
    "кодекс",
    "закон",
    "республик",
    "казахст",
    "либо",
    "также",
    "может",
    "быть",
    "если",
    "после",
    "более",
    "менее",
    "который",
    "которы",
    "этом",
    "того",
    "иной",
    "иных",
    "соответств",
    "настоящ",
    "бап",
    "заң",
    "республикас",
)
MAX_RELAXED = 4


# Regex syntax whose digits and letters are not the query's words: "{0,20}", "[0-9]", "\d".
_SYNTAX = re.compile(r"\{[^}]*\}|\[[^\]]*\]|\\.")
# Kept whole, not cut to a stem: a number ("ставка 3 процент" is not "ставка 4 процент") and
# an abbreviation too short to be a word ("ИПН", "НДС"). Matched as whole tokens.
_EXACT = re.compile(r"\b(?:\d+|[^\W\d_]{2,3})\b")
_EXACT_TOKEN = re.compile(r"^(?:\d+|[^\W\d_]{2,3})$")


def _exact(text: str) -> list[str]:
    found = (t for t in _EXACT.findall(text) if t.isdigit() or t.isupper())
    return list(dict.fromkeys(t.lower() for t in found))


def relaxed(query: str) -> list[list[str]]:
    """Stem sets to retry a phrase that found nothing with: its numbers and abbreviations,
    whole, and its longest words' stems, in any order, in one paragraph; then one stem fewer.
    Empty for a query of fewer than two such tokens."""
    text = _SYNTAX.sub(" ", query)
    # In "(3 063|3 180) тенге" the numbers are alternatives: requiring them all finds nothing.
    exact = [] if "|" in text else _exact(text)[:MAX_RELAXED]
    words = [w for w in _WORD.findall(text.lower()) if not w.startswith(_COMMON)]
    picked: list[str] = []
    for w in sorted(dict.fromkeys(words), key=len, reverse=True):
        stem = w[: min(6, max(4, len(w) - 2))]
        same = [i for i, p in enumerate(picked) if p.startswith(stem) or stem.startswith(p)]
        if same:  # "налоговые" and "налогу": one stem, the shorter, covers both
            picked[same[0]] = min(picked[same[0]], stem, key=len)
        elif len(exact) + len(picked) < MAX_RELAXED:
            picked.append(stem)
    if len(exact) + len(picked) < 2:
        return []
    # One stem fewer drops a word, never a number: without it the retry is another question.
    fewer = [exact + picked[:-1]] if len(picked) >= 2 and len(exact) + len(picked) >= 3 else []
    return [exact + picked] + fewer


def any_order(stems: list[str]) -> str:
    """A regex for all of `stems` in one line, in any order: ripgrep has no lookahead. A
    number or an abbreviation matches only as a whole token: "3" not inside "13" or "2023"."""
    parts = [rf"\b{s}\b" if _EXACT_TOKEN.match(s) else re.escape(s) for s in stems]
    return "|".join(".*".join(p) for p in permutations(parts))
