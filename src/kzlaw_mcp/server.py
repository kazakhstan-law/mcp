"""FastMCP over Streamable HTTP: four read-only tools, a landing page and a health check."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from kzlaw_mcp.config import Settings
from kzlaw_mcp.corpus import Corpus
from kzlaw_mcp.gate import Gate
from kzlaw_mcp.history import history as history_tool
from kzlaw_mcp.passages import at_date as at_date_tool
from kzlaw_mcp.passages import read as read_tool
from kzlaw_mcp.search import search as search_tool

Lang = Literal["rus", "kaz"]

INSTRUCTIONS = """\
You answer questions about the law of the Republic of Kazakhstan for ordinary people, using \
only texts these tools return. The corpus is an unofficial copy of ЕСПИ (law.gov.kz) kept in \
git, with every act's full history.

1. Every claim about the law carries its citation: paste the `citation` link that read or \
at_date returned, as is. Never build or edit a link yourself. No citation, no claim. \
Each passage has its own link: never reuse one article's link for another. To merely \
name an act you did not open, use a search hit's `url`, verbatim.
2. Quote only passages you opened with read or at_date; a search hit alone is not enough.
3. Search with legal wording: "ГАИ" -> "полиция", "органы внутренних дел"; "самокат" -> \
"электрическ самокат", "средств индивидуальной мобильности". Use stems and alternation \
("самокат|мобильност"). Retry other wording before concluding; if nothing is found, say so \
and name what you searched. Keep the default scopes: do not narrow search to codes. \
Forms, rules and procedures are ministerial orders; a form number such as 270 is \
searched as "форм[аеуы] 270". A question about a form is answered from the order that \
approves it ("Об утверждении формы …"): read that order and run history on it.
4. Pick the mode: the law now -> read; the law on a past date ("оштрафовали в 2022") -> \
at_date on that date, compared with read; "since when" -> history with a short exact phrase \
from the current text (case-sensitive); the oldest commit is when it appeared.
5. Answer in the user's language, in plain words: one or two sentences first, then the key \
points each with its citation, then, if the cited text changed recently, "изменено \
DD.MM.YYYY <amending act>" from history.
6. Questions in Kazakh: search and read with lang="kaz".
7. Do not add legal disclaimers to answers.
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
    "Full-text search (regex, case-insensitive) over the acts of Kazakhstan in force. Returns "
    "acts with matching lines; each line carries the article anchor (e.g. st592) and/or point "
    "label (e.g. 168-1) to pass to read. Scopes: codes (constitution, codes, laws), government, "
    "ministerial by default (keep them: forms and rules are ministerial orders); "
    "local-<region> only for regional questions."
)
READ_DESC = (
    "Current text of an act: an article by anchor (st592), a point by label (168-1), or a part "
    "of an article (anchor + point). Without either, the act's outline. Each passage has a "
    "`citation` Markdown link pinned to a commit: paste it as is next to the claim."
)
AT_DATE_DESC = (
    "Like read, but the text in force on a past date (YYYY-MM-DD): for 'what was the rule when "
    "it happened'. The citation is pinned to that date's version."
)
HISTORY_DESC = (
    "The act's versions from git: date and amending act (number, title, code) of each. With "
    "phrase, only versions that added or removed that exact, case-sensitive text; the oldest is "
    "when it entered the act. Covers this act only."
)


def _request(ctx: Context):
    return getattr(ctx.request_context, "request", None)


def build_server(settings: Settings, corpus: Corpus | None = None) -> FastMCP:
    corpus = corpus or Corpus(settings)
    gate = Gate(settings)
    mcp = FastMCP(
        "kazakhstan-law",
        instructions=INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool(description=SEARCH_DESC)
    async def search(
        ctx: Context,
        query: str,
        lang: Lang = "rus",
        scopes: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        args = {"query": query, "lang": lang, "scopes": scopes, "limit": limit}
        return await gate.call(
            "search", args, _request(ctx), lambda: search_tool(corpus, query, lang, scopes, limit)
        )

    @mcp.tool(description=READ_DESC)
    async def read(
        ctx: Context,
        act_code: str,
        lang: Lang = "rus",
        anchor: str | None = None,
        point: str | None = None,
    ) -> dict[str, Any]:
        args = {"act_code": act_code, "lang": lang, "anchor": anchor, "point": point}
        return await gate.call(
            "read", args, _request(ctx), lambda: read_tool(corpus, act_code, lang, anchor, point)
        )

    @mcp.tool(description=AT_DATE_DESC)
    async def at_date(
        ctx: Context,
        act_code: str,
        date: str,
        lang: Lang = "rus",
        anchor: str | None = None,
        point: str | None = None,
    ) -> dict[str, Any]:
        args = {"act_code": act_code, "date": date, "lang": lang, "anchor": anchor, "point": point}
        return await gate.call(
            "at_date",
            args,
            _request(ctx),
            lambda: at_date_tool(corpus, act_code, date, lang, anchor, point),
        )

    @mcp.tool(description=HISTORY_DESC)
    async def history(
        ctx: Context, act_code: str, phrase: str | None = None, limit: int = 30
    ) -> dict[str, Any]:
        args = {"act_code": act_code, "phrase": phrase, "limit": limit}
        return await gate.call(
            "history", args, _request(ctx), lambda: history_tool(corpus, act_code, phrase, limit)
        )

    @mcp.custom_route("/", methods=["GET"])
    async def landing(request: Request) -> PlainTextResponse:
        return PlainTextResponse(LANDING.format(url=settings.public_url))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "scopes": len(corpus.scopes())})

    return mcp


def main() -> None:
    build_server(Settings.from_env()).run(transport="streamable-http")
