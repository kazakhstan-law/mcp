# kazakhstan-law MCP

A public [MCP](https://modelcontextprotocol.io) server over the
[kazakhstan-law](https://github.com/kazakhstan-law) corpus: the acts of Kazakhstan as git
repositories, one commit per version. Your chatbot can search the law, read an article,
see the text in force on a past date, and find when a rule appeared. Every answer links to
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
| `search` | Case-insensitive regex search over acts in force; hits carry article anchors / point labels |
| `read` | Current text of an article (`st592`), a point (`168-1`) or a part of an article |
| `at_date` | The same text as in force on a past date |
| `history` | The act's versions and amending acts; with a phrase, when that wording appeared |

## Run it yourself

```bash
uv sync
KZLAW_CORPUS_ROOT=./data/corpus uv run kzlaw-refresh --scopes codes   # clones from GitHub
KZLAW_CORPUS_ROOT=./data/corpus uv run kzlaw-mcp                      # http://127.0.0.1:8000/mcp
uv run pytest
```

Or `docker compose up -d` (see `compose.yml`). Full clones of all 25 scopes take ≈ 1.8 GB packed
and ≈ 6 GB of working trees.

## License

The texts are official documents and not subject to copyright. The code here is released
into the public domain under the [Unlicense](https://unlicense.org).
