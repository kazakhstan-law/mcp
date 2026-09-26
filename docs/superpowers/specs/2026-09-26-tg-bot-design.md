# tg-bot — design

Status: design agreed in chat 2026-09-26; this file is the agent-facing record.
Deadline: live demo at KazHackStan, **30 September 2026** (~2 minutes of the talk).

## 1. Purpose

A Telegram bot that answers everyday legal questions about Kazakhstan in plain
language, **with a citation behind every claim**, built **only on the public
corpus repositories** of the `kazakhstan-law` GitHub organisation. It exists to
show the talk's point: once the law is a git repository, anyone can build a
useful, verifiable tool on it — and history (git) is available when a question
needs it.

- Audience of the bot: ordinary people (not lawyers). Audience of the talk: a
  large general conference with an infosec interest.
- The bot is a demo, not the talk's subject: basic abuse limits yes, no
  "try to break it" segment, no hardening beyond §7.
- Repository: `kazakhstan-law/tg-bot`, **public**. Independent of `qaz-code`
  (private); it must not import or require it, the database, or embeddings.

## 2. Question modes

One agent handles all three; history is used only when the question needs it.

1. **Now** (main): "Может ли инспектор требовать открыть багажник?" — current law.
2. **On the date of an event**: "Оштрафовали в 2022 за …" — the redaction in
   force on that date, compared with today's.
3. **Since when**: "С каких пор нужно сдавать форму 270?" — when a rule or
   condition first appeared in the current act, with the amending act.
   Limitation (accepted): lineage across *different* acts (an order repealed
   and replaced by a new one) is not followed; the answer is scoped to the
   current act's history and says so.

## 3. Architecture

```
Telegram ──► aiogram bot ──► agent loop (Claude API, tool use)
                │                  │
     aiogram-blackbox JSONL        ├─ search      ┐
                                   ├─ read        │ over local clones of the
                                   ├─ history     │ 25 scope repositories
                                   └─ at_date     ┘ (git + ripgrep)
```

Runs on `latitude` (8 cores, 23 GB RAM, ~239 GB free, no GPU) via docker
compose, the same way `embedthat` runs there.

### 3.1 Data on the server

- Full clones (history required) of the 25 scope repositories
  (`codes`, `government`, `ministerial`, `local-*`). Packed ≈ 1.8 GB, working
  trees ≈ 6.1 GB (measured on the 2026-09-16 build: codes 477 MB, government
  975 MB, ministerial 1.9 GB, the 22 local repos the rest).
- Refresh hourly: `git fetch` + `git reset --hard origin/main` per scope. The
  corpus is force-pushed on every build, so `pull` is wrong.
- Citations link to a **commit sha**, not `main`. They stay valid after
  force-pushes because every build leaves an annotated `build/YYYY-MM-DD` tag
  that is never deleted, keeping the old commits reachable.

### 3.2 Corpus facts the tools depend on (measured 2026-09-26)

- Act directory: `<tier>/…/<YYYY>/<MMDD>-<slug>-<code>/` with `rus.md`,
  `kaz.md`, `meta.yaml` (title, requisite, act_code, caused_by, …).
- Large acts are **split**: `rus.md` becomes an index and the text lives in
  `rus/*.md` parts (КоАП: 37 parts). **Part names change over time** — КоАП had
  `rus/sec002-ch010.md` in 2022 and does not now. So an article is located by
  its anchor (`<a id="st592"></a>`), searched across `rus.md` and `rus/*.md`
  **at the revision in question**, never by a remembered part name.
- Article anchors: `st62`, `st62-1`, `an3_st1` (see qaz-code `anchors.py`
  grammar). Headings look like `### Статья 592. …`.
- Commits: date = the version's date; subject = amending act's number + title;
  trailers `Cause-Act-Code`, `Cause-Act-Requisite`, `Acts-Changed`.
- Search must be **case-insensitive** (headings are capitalised: a
  case-sensitive `превышение установленной скорости` misses КоАП art. 592).
- GitHub renders Markdown files up to roughly 390–430 KB; anchors only work in
  a rendered file. КоАП's part with art. 592 is 230 KB — fine. For a file over
  ~384 KiB the link falls back to the file without an anchor.

## 4. Tools (all read-only, all local)

| Tool | Input | Output |
|---|---|---|
| `search` | query (ripgrep regex, case-insensitive), language `rus`/`kaz`, optional scopes (default `codes,government,ministerial`; `local-*` only on request), limit | per hit: scope, act dir, act title (from `meta.yaml`), nearest article heading + anchor, matched line; capped (e.g. 20 hits, grouped by act) |
| `read` | act dir (or act code), optional article anchor, language | article text (or act head + table of contents when no anchor), act title, commit sha, GitHub URL with anchor |
| `history` | act dir, optional article anchor, optional phrase | commits touching the act: date, amending act (number, title, `Cause-Act-Code`); with a phrase, `git log -S` over the act's files to find when it appeared/disappeared |
| `at_date` | act dir, article anchor, date, language | the article's text at `git rev-list -1 --before=<date> main`, that sha, GitHub URL at that sha |

Measured search latency (warm cache, 8 cores): default three scopes 0.2–1.9 s;
all 25 scopes 0.9–3.2 s (cold). Hit counts are small for legal phrases
(`превышение установленной скорости`: 3 files) and moderate for everyday words
(`багажник`: 17 files in the default scopes).

Traffic rules (ПДД) are a ministerial order
(`ministerial/07-ministerial/103003000000-…/2023/0630-ob-utverzhdenii-pravil-dorozhnogo-dvizheniia-…-183572`),
which is why `ministerial` is in the default scope.

## 5. Agent

- Claude API with user-defined tools, SDK tool runner or a manual loop; at most
  **8 tool rounds** per question.
- Model: **decision pending** (see §9) — `claude-sonnet-5` ($2 / $10 per MTok)
  for latency, or `claude-opus-5` ($5 / $25). Prompt caching on the frozen
  system prompt + tool list.
- System prompt (English instructions, answer in the user's language):
  - Answer only from text returned by `read`/`at_date` in this conversation;
    no claim without a citation; if nothing relevant is found, say so and show
    what was searched.
  - Translate colloquial wording into legal terms before searching
    ("ГАИ" → "сотрудник полиции", "патрульная полиция", "остановка
    транспортного средства"); retry search with alternatives on no hits.
  - Off-topic requests are declined politely.
- Answer format (Telegram HTML, ≤ one phone screen, ≤ 3500 chars):
  1. 1–2 sentence answer.
  2. Steps / key points, each with a linked citation
     ("ст. 62 Закона о дорожном движении").
  3. When the cited article changed recently: "изменено DD.MM.YYYY законом №…".
  - **No disclaimer in answers.** The disclaimer lives in the bot description
    and the `/start` message.
- Progress: one status message edited as tools run ("ищу…", "открываю ст. 592
  КоАП…", "смотрю историю…"), replaced by the answer.
- Context: last 3 exchanges per chat kept in memory, so "а как было в 2020?"
  works as a follow-up. No database.
- Language: answer in the question's language; Kazakh questions search `kaz.md`.

### 5.1 Citation check (code, not prompt)

Before sending, every GitHub link in the answer is checked against the set of
(sha, path) pairs returned by `read`/`at_date` in this conversation. A link
outside that set is a fabricated citation: the answer is sent back to the model
once with the error; if it fails again the bot replies that it could not answer
reliably.

## 6. Bot

- aiogram 3; `aiogram-blackbox` records every inbound/outbound message to JSONL
  on a volume (review after the talk: what people asked, where it failed).
- Commands: `/start` (what the bot is, disclaimer, 2–3 example questions as
  buttons), `/help`.
- Secrets: `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY` from env / `.env`, never
  committed.

## 7. Limits

- Per user: 10 questions per hour (in memory).
- Global daily spend cap computed from `response.usage` and the model's price
  table; when reached, the bot replies that the daily limit is exhausted.
  Default cap $20/day, configurable. Rough per-question cost with caching:
  ~$0.1 (Sonnet 5) to ~$0.3 (Opus 5) — to be measured on the reference questions.
- One question in flight per user.

## 8. Testing

- **Unit tests** (hermetic): tools against a small fixture git repository built
  in the test (split act with parts renamed between two commits, anchors,
  trailers, `meta.yaml`); citation check; answer-length/format guard; limits.
- **Reference questions** (opt-in, real clones + real API, cost money). Assert
  on the tool trace and citations, not on wording:
  1. Traffic stop / trunk — cites at least one current act among the traffic
     rules order, the police law or КоАП; every link passes §5.1.
  2. **Revised** (the original "+20 km/h" is a flat demo: 10 МРП in 2022 and
     now): "В 2022 меня оштрафовали за превышение на 65 км/ч — какой был штраф
     и какой сейчас?" — must call `at_date` on КоАП art. 592 (`st592`); 2022:
     part 3 "от сорока и более" → 20 МРП; now: part 3-1 "от шестидесяти и более"
     → 40 МРП, added by the Law of 03.10.2024 № 131-VIII.
  3. "С каких пор надо сдавать форму 270?" — must reach act 158645
     (`ministerial/…/103002000000-minfin/2021/0913-…-158645`); history: initial
     2021-09-13, № 169 of 2024-03-29, suspension № 452 (2024-07-16 and
     2024-08-01), № 624 of 2025-10-24; `git log -S 'в собственности цифровые
     активы'` pinpoints the 2025-10-24 commit (№ 624, Cause-Act-Code 216103).
  The user may replace these questions; they stay as the regression set.

## 9. Open decisions

- Model: Sonnet 5 (faster, cheaper) vs Opus 5 (stronger). Recommendation:
  Sonnet 5, confirm latency and answer quality on the reference questions and
  switch if quality falls short.
- The final demo questions (the user will choose; §8 is the reference set).

## 10. Out of scope

A citation graph between acts (references exist only as prose; parsing them is
a post-talk idea), vector search, the qaz-code database, lineage across
replaced acts, hardening against a determined attacker, a web UI.
