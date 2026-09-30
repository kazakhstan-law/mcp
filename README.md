# kazakhstan-law MCP

A public [MCP](https://modelcontextprotocol.io) server over the
[kazakhstan-law](https://github.com/kazakhstan-law) corpus: the acts of Kazakhstan as git
repositories, one commit per version. Your chatbot can search the law, read an article,
see the text in force on a past date, find when a rule appeared, and see what an amendment changed. Every answer links to
the exact version it quotes.

**Endpoint:** `https://cyphy.kz/kazakhstan-law/mcp` (Streamable HTTP, no authentication).

## Подключить

**Claude** (любой тариф, включая бесплатный): claude.ai → Настройки → Коннекторы →
Добавить свой коннектор → `https://cyphy.kz/kazakhstan-law/mcp`. Добавлять нужно на сайте; потом
коннектор работает и в приложении на телефоне. На бесплатном тарифе можно подключить один
свой коннектор.

**ChatGPT** (Plus и выше): Настройки → Приложения → Режим разработчика → Создать → тот же
адрес.

Спросите, например: «Какие новые правила для электросамокатов?», «В 2022 меня оштрафовали за
превышение на 65 км/ч — какой был штраф и какой сейчас?», «С каких пор надо сдавать форму 270?»

> Неофициальная копия. Официальный источник — ЕСПИ, [law.gov.kz](https://law.gov.kz).
> Это не юридическая консультация.

## Tools

| Tool | What it does |
|---|---|
| `search` | Case-insensitive regex search over acts in force, or inside one act (`act_code`, a repealed one too); hits carry article anchors / point labels; `include_repealed` adds repealed acts by title; `headings_only`; a query that finds nothing is retried in the law's wording for everyday words ("курение") |
| `read` | Current text of an article (`st592`), a point (`168-1`) or a part of an article; without either, the outline and the provisions not in force yet |
| `at_date` | The same text as in force on a past date |
| `history` | The act's versions and amending acts, paged (`offset`, `since`); with a phrase, when that wording appeared; with an anchor, the versions that changed that article |
| `changes` | What one version changed, article by article, with diffs, paged by `offset`; or a period (`since`, `until`): one item per article with the versions that touched it; narrowed by `chapter` or `anchors` (`st570..st621`), `summary` without diffs; for an amending act, the acts it changed |

## Run it yourself

```bash
uv sync
KZLAW_CORPUS_ROOT=./data/corpus uv run kzlaw-refresh --scopes codes   # clones from GitHub
KZLAW_CORPUS_ROOT=./data/corpus uv run kzlaw-mcp                      # http://127.0.0.1:8000/mcp
uv run pytest
```

Or `docker compose up -d` (see `compose.yml`).

**Deploy** (the server checkout): `scripts/deploy.sh` runs the tests in the image's test
stage, rebuilds, restarts and checks health, rolling back to the previous image on failure;
it does nothing when the image already runs HEAD. With `git config core.hooksPath
deploy/hooks` it runs by itself after every pull; logs: `journalctl --user -u 'kzlaw-deploy-*'`. Full clones of all 25 scopes take ≈ 1.8 GB packed
and ≈ 6 GB of working trees.

**Usage report**: with `KZLAW_LOG_PATH` set, each call is a line of JSON (the IP salted and
hashed; for search, how much it found and whether the dictionary rewrote it).
`docker compose exec server kzlaw-report --days 7` prints calls per day, tools, clients, the
searches that found nothing, the dictionary's rewrites, reformulations (a miss, then a hit in
the same conversation), errors and slow calls. It prints users' queries: keep it private.

## License

The texts are official documents and not subject to copyright. The code here is released
into the public domain under the [Unlicense](https://unlicense.org).
