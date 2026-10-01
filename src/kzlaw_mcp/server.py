"""FastMCP over Streamable HTTP: five read-only tools, a feedback tool, a landing page and a
health check."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from kzlaw_mcp.changes import changes as changes_tool
from kzlaw_mcp.config import Settings
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.gate import FEEDBACK_MAX, FeedbackKind, Gate
from kzlaw_mcp.history import history as history_tool
from kzlaw_mcp.passages import at_date as at_date_tool
from kzlaw_mcp.passages import read as read_tool
from kzlaw_mcp.search import search as search_tool

Lang = Literal["rus", "kaz"]

INSTRUCTIONS = """\
You answer questions about the law of the Republic of Kazakhstan for ordinary people, using \
only texts these tools return. The corpus is an unofficial copy of ЕСПИ (law.gov.kz) kept in \
git, with every act's full history.

1. Every claim about the law carries its citation: paste the `citation` link that read, \
at_date or changes returned (or changes' `before_citation` for the old text), as is. Never build or edit a link yourself. No citation, no claim. \
Each passage has its own link: never reuse one article's link for another. To merely \
name an act you did not open, use a search hit's `url`, verbatim.
2. Quote only passages you opened with read, at_date or changes; a search hit alone is not \
enough. A pending provision is cited by its `url`.
3. Search with legal wording: "ГАИ" -> "полиция", "органы внутренних дел"; "самокат" -> \
"электрическ\\w* самокат", "средств индивидуальной мобильности". Use stems and alternation \
("самокат|мобильност"). Each line is one paragraph: "A.*B" matches only inside one, so \
search separate concepts apart or with "|". Search one or two distinctive words, not a phrase \
recalled from memory: an older edition may word it differently. A stem inside a phrase needs \
"\\w*" after it ("банкротств\\w* граждан"). Retry other wording before concluding; if nothing \
is found, say so and name what you searched. When search answers with `rewritten`, the law \
uses other words than the user's: say which ("в законе это «потребление табачных изделий»"). \
When it answers with `relaxed`, your phrase was not the law's: check the hits say what you \
need before citing, and search stems next time. \
To find the article on a topic inside one act, search it with headings_only=true. Keep the default scopes: do not narrow search to codes. \
Forms, rules and procedures are ministerial orders; a form number such as 270 is \
searched as "форм[аеуы] 270". A question about a form is answered from the order that \
approves it ("Об утверждении формы …"): read that order and run history on it.
4. Pick the mode: the law now -> read; the law on a past date ("оштрафовали в 2022") -> \
at_date on that date, compared with read; "since when" -> history with a short exact phrase \
from the current text (case-sensitive); `introduced` is when it appeared. A new code that \
replaced a repealed one lists it in history's `predecessors`; at_date on the new code before \
it took effect returns the old code's text, so a past date never needs the old code's number. \
"What changed", "что нового в законе", "за год" -> changes(act_code, since=YYYY-MM-DD) in one \
call: each article added, removed or modified in the period, with the net diff and the \
versions that touched it. Narrow a code to the topic with chapter (a part from read's outline) \
or anchors (["st570..st621"]); summary=true first for a large act, then anchor=... for one \
article in full. "When did article X change" -> history(act_code, anchor="st613"). An \
amending act ("О внесении изменений…") has no text here: changes on its code lists the acts \
it changed. A rule older than the act now in force may come from a repealed act that no \
`predecessors` names: search with include_repealed=true lists repealed acts by title, then \
search(act_code) inside one and at_date before its repealed_on. "What will change" -> read without anchor: `pending` lists provisions enacted \
but not in force yet. To find something inside one act, pass act_code to search.
5. Answer in the user's language, in plain words: one or two sentences first, then the key \
points each with its citation, then, if the cited text changed recently, "изменено \
DD.MM.YYYY <amending act>" from history.
6. Questions in Kazakh: search and read with lang="kaz".
7. Do not add legal disclaimers to answers.
8. Call feedback when nothing was found after retrying other wording, when the user says an \
answer or a text is wrong or something is missing, or when asked to pass something on to the \
developers ("передай разработчикам"). Write what was asked, what you searched or read, and \
what was missing or wrong. No names, phone numbers, ИИН or other personal data: describe the \
situation, not the person.
"""

LANDING = """\
kazakhstan-law MCP — законы Казахстана с историей изменений, для вашего чат-бота.

Подключить к Claude (любой тариф, включая бесплатный):
  claude.ai -> Настройки -> Коннекторы -> Добавить свой коннектор -> адрес:
  {url}
  Добавлять нужно на сайте claude.ai; потом коннектор работает и в приложении на телефоне.

Подключить к ChatGPT (Plus и выше): Настройки -> Приложения -> Режим разработчика ->
  Создать -> тот же адрес.

Пример вопроса: «Какие новые правила для электросамокатов?»

Неофициальная копия. Официальный источник — ЕСПИ, law.gov.kz. Не юридическая консультация.
Исходный код: https://github.com/kazakhstan-law/mcp
"""

SEARCH_DESC = (
    "Full-text search (regex, case-insensitive) over the acts of Kazakhstan in force. Query: "
    "two or three word stems ('пен\\w* несвоевременн', 'вычет|подоходн'), not a sentence, "
    "not a phrase recalled from memory, no '.{0,80}' chains: the wording of the law is not "
    "yours. Returns "
    "acts with matching lines; each line carries the article anchor (e.g. st592) and/or point "
    "label (e.g. 168-1) to pass to read. Scopes: codes (constitution, codes, laws), government, "
    "ministerial by default (keep them: forms and rules are ministerial orders); "
    "local-<region> only for regional questions. With act_code, only inside that act, with "
    "every matching line; for a repealed act, in its last version. include_repealed: also "
    "the repealed acts whose title matches (for the law before the acts now in force). Each "
    "line is one paragraph, so 'A.*B' never spans two; a stem "
    "followed by more words needs '\\w*' ('банкротств\\w* граждан'). Inside one act, lines "
    "that are article headings come first; headings_only: match headings only, to find the "
    "article on a topic. A query that finds nothing is retried with the legal wording for "
    "everyday words ('курение' -> 'потреблени\\w* табачн\\w*'); rewritten says so. Then a "
    "phrase is retried as its words' stems, in any order, in one paragraph; relaxed says so. "
    "Inside one act, nothing found lists nearest_headings."
)
READ_DESC = (
    "Current text of an act: an article by anchor (st592), a point by label (168-1), or a part "
    "of an article (anchor + point). Without either, the act's outline. Each passage has a "
    "`citation` Markdown link pinned to a commit: paste it as is next to the claim. The outline "
    "also lists `pending`: provisions enacted but not in force yet, with the date they take effect."
)
AT_DATE_DESC = (
    "Like read, but the text in force on a past date (YYYY-MM-DD): for 'what was the rule when "
    "it happened'. The citation is pinned to that date's version. Before a code took effect it "
    "returns the text of the repealed code it replaced (replaced_by names the new one)."
)
HISTORY_DESC = (
    "The act's versions from git: the date each took effect and its amending act (number, title, "
    "code, adoption date); changes(act_code, sha) shows what a version changed. With "
    "phrase, only versions that added or removed that exact, case-sensitive text; the oldest is "
    "when it entered the law. predecessors: the repealed acts it replaced (an earlier code), "
    "with their versions. Newest first, up to limit (max 50); total counts them all. For more: "
    "offset=next_offset, or since=YYYY-MM-DD for the versions from a date. With anchor "
    "(st613): only the versions that changed that article's text."
)

CHANGES_DESC = (
    "What one version of an act changed, compared with the previous one: the articles (or "
    "points) added, removed and modified, each with a diff and citations to both sides. Pick the "
    "version by sha (from history) or by date (the version in force then); default: the latest. "
    "anchor narrows it to one article, in full. total and counts cover the whole version; a "
    "large one comes in pages: pass next_offset as offset for the next. For an amending act's "
    "code: the acts it changed (acts_total distinct acts), paged the same way; a repealed act "
    "that also amended others answers so too unless sha or date is given. A period: "
    "since=YYYY-MM-DD (until optional) compares the text the day before since with the end of "
    "the period, one item per article with the versions (touched_by) that changed it: 'what "
    "changed this year' in one call. Narrow any mode with chapter (a part file of a split "
    "code, e.g. sec002-ch030, from read's outline) or anchors (['st613', 'st570..st621']). "
    "summary=true: the list only, no text or diffs."
)

FEEDBACK_DESC = (
    "Tell the developers of this server what went wrong; it is read by people. kind: not_found "
    "(searched with several wordings, found nothing), wrong (the user says an answer or a text "
    "is wrong), missing (an act, edition or date is not in the corpus), other. message: what "
    "was asked, the queries and tools tried, what was missing or wrong; no personal data. "
    f"act_code: the act concerned, if any. Up to {FEEDBACK_MAX} characters. Changes no text."
)
# The corpus is a closed set of texts: nothing here reaches the outside world.
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}


def _request() -> Request | None:
    try:
        return get_http_request()
    except RuntimeError:  # called in-process, not over HTTP
        return None


def build_server(settings: Settings, corpus: Corpus | None = None) -> FastMCP:
    corpus = corpus or Corpus(settings)
    gate = Gate(settings)
    mcp = FastMCP("kazakhstan-law", instructions=INSTRUCTIONS)

    async def call(tool: str, args: dict, fn: Callable[[], dict]) -> dict:
        try:
            return await gate.call(tool, args, _request(), fn)
        except InputError as exc:  # the message is for the model: no "Error calling tool" prefix
            raise ToolError(str(exc)) from exc

    @mcp.tool(description=SEARCH_DESC, annotations=READ_ONLY)
    async def search(
        query: str,
        lang: Lang = "rus",
        scopes: list[str] | None = None,
        limit: int = 20,
        act_code: str | None = None,
        include_repealed: bool = False,
        headings_only: bool = False,
    ) -> dict[str, Any]:
        args = {
            "query": query,
            "lang": lang,
            "scopes": scopes,
            "limit": limit,
            "act_code": act_code,
            "include_repealed": include_repealed,
            "headings_only": headings_only,
        }
        return await call(
            "search",
            args,
            lambda: search_tool(
                corpus, query, lang, scopes, limit, act_code, include_repealed, headings_only
            ),
        )

    @mcp.tool(description=READ_DESC, annotations=READ_ONLY)
    async def read(
        act_code: str,
        lang: Lang = "rus",
        anchor: str | None = None,
        point: str | None = None,
    ) -> dict[str, Any]:
        args = {"act_code": act_code, "lang": lang, "anchor": anchor, "point": point}
        return await call("read", args, lambda: read_tool(corpus, act_code, lang, anchor, point))

    @mcp.tool(description=AT_DATE_DESC, annotations=READ_ONLY)
    async def at_date(
        act_code: str,
        date: str,
        lang: Lang = "rus",
        anchor: str | None = None,
        point: str | None = None,
    ) -> dict[str, Any]:
        args = {"act_code": act_code, "date": date, "lang": lang, "anchor": anchor, "point": point}
        return await call(
            "at_date",
            args,
            lambda: at_date_tool(corpus, act_code, date, lang, anchor, point),
        )

    @mcp.tool(description=HISTORY_DESC, annotations=READ_ONLY)
    async def history(
        act_code: str,
        phrase: str | None = None,
        limit: int = 30,
        offset: int = 0,
        since: str | None = None,
        anchor: str | None = None,
    ) -> dict[str, Any]:
        args = {
            "act_code": act_code,
            "phrase": phrase,
            "limit": limit,
            "offset": offset,
            "since": since,
            "anchor": anchor,
        }
        return await call(
            "history",
            args,
            lambda: history_tool(corpus, act_code, phrase, limit, offset, since, anchor),
        )

    @mcp.tool(description=CHANGES_DESC, annotations=READ_ONLY)
    async def changes(
        act_code: str,
        sha: str | None = None,
        date: str | None = None,
        lang: Lang = "rus",
        anchor: str | None = None,
        offset: int = 0,
        since: str | None = None,
        until: str | None = None,
        anchors: list[str] | None = None,
        chapter: str | None = None,
        summary: bool = False,
    ) -> dict[str, Any]:
        args = {
            "act_code": act_code,
            "sha": sha,
            "date": date,
            "lang": lang,
            "anchor": anchor,
            "offset": offset,
            "since": since,
            "until": until,
            "anchors": anchors,
            "chapter": chapter,
            "summary": summary,
        }
        return await call(
            "changes",
            args,
            lambda: changes_tool(
                corpus,
                act_code,
                sha,
                date,
                lang,
                anchor,
                offset,
                since,
                until,
                anchors,
                chapter,
                summary,
            ),
        )

    @mcp.tool(description=FEEDBACK_DESC, annotations=WRITES)
    async def feedback(
        kind: FeedbackKind, message: str, act_code: str | None = None
    ) -> dict[str, Any]:
        args = {"kind": kind, "act_code": act_code, "length": len(message)}
        request = _request()
        return await call("feedback", args, lambda: gate.feedback(request, kind, message, act_code))

    @mcp.custom_route("/", methods=["GET"])
    async def landing(request: Request) -> PlainTextResponse:
        return PlainTextResponse(LANDING.format(url=settings.public_url))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "scopes": len(corpus.scopes())})

    return mcp


def _warm(corpus: Corpus) -> None:
    """Build the repealed-act index before the first call needs it: seconds per scope."""
    for scope in corpus.scopes():
        # a cold index is only slower: the first call that needs it builds it
        with contextlib.suppress(Exception):
            corpus.repealed_titles(scope)


def main() -> None:
    settings = Settings.from_env()
    corpus = Corpus(settings)
    threading.Thread(target=_warm, args=(corpus,), daemon=True).start()
    build_server(settings, corpus).run(
        transport="http",
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        json_response=True,
        show_banner=False,
    )
