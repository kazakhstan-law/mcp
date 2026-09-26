# kazakhstan-law MCP server — design

Status: design agreed in chat 2026-09-26; this file is the agent-facing record.
Supersedes the same-day `tg-bot` design (a custom aiogram bot with its own
agent loop), which was dropped in favour of this one — see §11.
Deadline: live demo at KazHackStan, **30 September 2026** (~2 minutes of the talk).

## 1. Purpose

A public **remote MCP server** that lets any MCP-capable chatbot answer
everyday legal questions about Kazakhstan in plain language, **with a citation
behind every claim**, built **only on the public corpus repositories** of the
`kazakhstan-law` GitHub organisation. It shows the talk's point: once the law
is a git repository, anyone can build a useful, verifiable tool on it — and the
history (git) is there when a question needs it.

Two consumers of the same server:

1. **The audience** — the URL (and a QR code) on a slide; people add it as a
   custom connector to their own Claude (any plan, including Free — one custom
   connector — added on claude.ai web, then usable in the mobile app) or ChatGPT
   (Developer Mode, Plus and up, web). The model runs on *their* side; we pay
   for no tokens.
2. **The on-stage demo** — a Telegram bot answering only the speaker's chat,
   built from Claude Code Channels (§7), which calls the server over the same
   public URL the audience uses. What is shown is exactly what they can
   connect.

- Audience of the answers: ordinary people. Audience of the talk: a large
  general conference with an infosec interest.
- The server is a demo, not the talk's subject: basic abuse limits (§6), no
  "try to break it" segment.
- Repository: `kazakhstan-law/mcp`, **public**. Independent of `qaz-code`
  (private); it must not import or require it, its database, or embeddings.

## 2. Question modes

The tools support all three; the calling model picks.

1. **Now** (main): "Какие новые правила для электросамокатов?" — current law.
2. **On the date of an event**: "Оштрафовали в 2022 за …" — the redaction in
   force on that date, compared with today's.
3. **Since when**: "С каких пор нужно сдавать форму 270?" — when a rule or
   condition first appeared in the current act, with the amending act.
   Limitation (accepted): lineage across *different* acts (an order repealed
   and replaced by a new one) is not followed; `history` says the answer is
   scoped to the current act's history.

## 3. Architecture

```
audience's Claude / ChatGPT ─┐
                             ├─► https://<public host>/mcp ─► hub (TLS, reverse proxy)
speaker's Telegram ─► Claude │                                    │ tailnet
   Code Channels session ────┘                                    ▼
   (on latitude)                                  latitude: MCP server (Streamable HTTP)
                                                    ├─ search   ┐
                                                    ├─ read     │ over local clones of the
                                                    ├─ history  │ 25 scope repositories
                                                    └─ at_date  ┘ (git + ripgrep)
```

- **Transport:** MCP Streamable HTTP, **no authentication** (connect in 30
  seconds; everything served is public anyway). Python, official `mcp` SDK.
- **Hosting:** the server runs on `latitude` (8 cores, 23 GB RAM, ~239 GB
  free) under docker compose, like `embedthat`. latitude is tailnet-only, and
  Claude connects to custom connectors from Anthropic's cloud, so the endpoint
  must be publicly reachable: `hub` (the public VPS) terminates TLS for a
  public hostname and proxies to latitude over the tailnet. The hostname and
  the proxy software on hub are settled in the plan.

### 3.1 Data on the server

- Full clones (history required) of the 25 scope repositories
  (`codes`, `government`, `ministerial`, `local-*`). Packed ≈ 1.8 GB, working
  trees ≈ 6.1 GB (2026-09-16 build: codes 477 MB, government 975 MB,
  ministerial 1.9 GB, the 22 local repos the rest).
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
- Article anchors: `st62`, `st62-1`, `an3_st1` (qaz-code `anchors.py`
  grammar). Headings look like `### Статья 592. …`.
- Commits: date = the version's date; subject = amending act's number + title;
  trailers `Cause-Act-Code`, `Cause-Act-Requisite`, `Acts-Changed`.
- Search must be **case-insensitive** (headings are capitalised: a
  case-sensitive `превышение установленной скорости` misses КоАП art. 592).
- GitHub renders Markdown files up to roughly 390–430 KB; anchors only work in
  a rendered file. For a file over ~384 KiB the link falls back to the file
  without an anchor.

## 4. Tools (all read-only, all local)

| Tool | Input | Output |
|---|---|---|
| `search` | query (ripgrep regex, case-insensitive), language `rus`/`kaz`, optional scopes (default `codes,government,ministerial`; `local-*` only on request), limit | per hit: scope, act code, act title (from `meta.yaml`), nearest article anchor and/or point label, heading, matched line; capped (20 hits, grouped by act) |
| `read` | act code, language, optional article anchor (`st592`) and/or point label (`168-1`) | the passage (or the act's outline when neither is given), act title, commit sha, **ready-made citation link** |
| `history` | act code, optional phrase | commits touching the act: date, amending act (number, title, `Cause-Act-Code`); with a phrase, `git log -S` over the act's files to find when it appeared/disappeared |
| `at_date` | act code, date, language, anchor and/or point | the passage at `git rev-list -1 --before=<date> HEAD`, that sha, citation link at that sha |

Two corpus facts shape these (measured 2026-09-26): many orders, the traffic rules among
them, carry **no article anchors** — their points are lines like `168-1. …`, and annexes
restart the numbering, so a label can repeat; and the traffic rules file is 400 KB, past
what GitHub renders. So a passage is located by anchor or point label at the revision in
question, and a citation uses `#<anchor>` only when the file is under 384 KiB, otherwise
the plain view with line numbers (`?plain=1#L1167-L1177`), which works at any size.
Acts are addressed by their numeric code (unique, the directory's suffix), which also
means no tool input is ever a path.

Measured search latency (warm cache, 8 cores): default three scopes 0.2–1.9 s;
all 25 scopes 0.9–3.2 s (cold). Hit counts are small for legal phrases and
moderate for everyday words (`багажник`: 17 files in the default scopes).

Traffic rules (ПДД) are a ministerial order
(`ministerial/07-ministerial/103003000000-qriim/2023/0630-ob-utverzhdenii-pravil-dorozhnogo-dvizheniia-osnovnykh-polozheni-183572`),
which is why `ministerial` is in the default scope.

### 4.1 Input safety

Every input comes from a stranger's model, so:
- an act dir must resolve (after normalisation) to a directory **inside** one
  clone — no `..`, no absolute paths, no symlinks out;
- anchors match the anchor grammar, dates are `YYYY-MM-DD`, languages are
  `rus`/`kaz`, scopes come from the fixed list;
- `rg` and `git` are called with argument arrays (never a shell), with `--`
  before user text, so a query cannot become an option;
- query length is capped; every subprocess has a timeout; output is truncated
  to a fixed size per tool call.

## 5. Answer quality without owning the model

The model that writes the answer is the user's, so the old bot's code-level
citation check cannot exist. The server steers instead:

- **Server instructions** (MCP `instructions`, English, answer in the user's
  language): answer only from text returned by `read`/`at_date`; every claim
  carries the citation URL the tool returned, never a constructed one; if
  nothing relevant is found, say so and show what was searched; translate
  colloquial wording into legal terms before searching ("ГАИ" → "сотрудник
  полиции", "самокат" → "средство индивидуальной мобильности"), retry with
  alternatives on no hits; plain language, short answer first, then the key
  points with citations, then "изменено DD.MM.YYYY законом №…" when the cited
  article changed recently. **No disclaimer in answers.**
- **Tool descriptions** repeat the one rule that matters most: cite the
  returned URL.
- Tool results carry the citation as a ready-to-paste Markdown link, which
  makes the correct behaviour also the easiest one.

The disclaimer (unofficial copy; the official source is ЕСПИ at `law.gov.kz`;
not legal advice) lives in the README, the connect page and the server's
description.

## 6. Limits and logging

- Per client IP: rate limit on tool calls (e.g. 60 per 10 minutes), plus a
  global concurrency cap on subprocesses so one heavy user cannot starve the
  rest. Behind the proxy the client IP comes from the proxy header, trusted
  only from hub.
- JSONL log of every tool call: time, tool, arguments, result size, latency,
  a salted hash of the client IP (not the IP). Reviewed after the talk: what
  people asked and where it failed.

## 7. On-stage demo bot — Claude Code Channels

No bot code. Claude Code's Telegram channel plugin
(`telegram@claude-plugins-official`, research preview since v2.1.80) runs a
Claude Code session on latitude that the speaker talks to from Telegram.

- Auth: the speaker's Claude subscription (Agent SDK / `claude -p` usage on a
  plan is permitted and draws from its limits — support article 15036540).
  Model: **Opus 5.5**.
- Access: sender allowlist with only the speaker's Telegram user id; everyone
  else is dropped by the plugin.
- MCP: the server is added with `claude mcp add --transport http` **using the
  public URL**, so the demo exercises the same path as the audience.
- Lockdown: the session runs in an empty working directory with project
  settings that **deny** Bash, file read/write/edit, web fetch/search and every
  other built-in tool, and allow only the `mcp__kazakhstan-law__*` tools — in
  case the allowlist ever fails. Its `CLAUDE.md` repeats the answer-format rules
  of §5, tuned for Telegram (short, one phone screen).
- Runs under a user systemd unit wrapping tmux, restarted on failure.
- To verify in a smoke test before the talk: the model can be set to Opus 5.5
  in a channel session; the deny rules hold; answer latency on the reference
  questions.
- Fallbacks, in order: `RichardAtCT/claude-code-telegram` (allowlist, MCP
  config, tool restriction, subscription auth); the speaker's own Claude mobile
  app with the connector added.

## 8. Connect instructions

A short README section (and the slide) for Claude (Settings → Connectors → Add
custom connector → URL; on Free this uses the single custom-connector slot;
must be added on claude.ai web, then works on mobile) and ChatGPT (Developer
Mode, Plus and up, web). Two or three example questions.

## 9. Testing

- **Unit tests** (hermetic): tools against a small fixture git repository built
  in the test (split act with parts renamed between two commits, anchors,
  trailers, `meta.yaml`); input safety (§4.1: traversal, option injection,
  bad anchors/dates); output truncation; rate limiter.
- **MCP smoke test**: the server over Streamable HTTP, driven by the official
  MCP client — list tools, call each.
- **Reference questions** (opt-in, real clones, run through `claude -p` with
  the server configured, cost subscription quota). Assert on the tool trace and
  cited URLs, not on wording:
  1. **E-scooters, recent changes** — must cite at least two of: ПДД act 183572
     (chapter 24; point 168-1 and the under-18 carriageway rule added by
     № 671 of 2023-08-31; scooter signs by № 330 of 2024-04-17; the large
     change № 859 of 2025-11-10), the Закон о дорожном движении
     (`codes/03-laws/2014/0417-o-dorozhnom-dvizhenii-78910`, № 246-VIII of
     2026-07-02: rental operators must check a driver's licence, limit speed by
     zone, register scooters, not leave them obstructing), КоАП art. 619-2
     (№ 331-VIII of 2026-07-01: fine on a rental operator letting an
     unlicensed rider onto the carriageway; in force 6 months after Law
     30.12.2025 № 247-VIII).
  2. "В 2022 меня оштрафовали за превышение на 65 км/ч — какой был штраф и
     какой сейчас?" — must call `at_date` on КоАП art. 592 (`st592`); 2022:
     part 3 "от сорока и более" → 20 МРП; now: part 3-1 "от шестидесяти и
     более" → 40 МРП, added by the Law of 03.10.2024 № 131-VIII.
  3. "С каких пор надо сдавать форму 270?" — must reach act 158645
     (`ministerial/…/103002000000-minfin/2021/0913-…-158645`); history:
     initial 2021-09-13, № 169 of 2024-03-29, suspension № 452 (2024-07-16 and
     2024-08-01), № 624 of 2025-10-24; `git log -S 'в собственности цифровые
     активы'` pinpoints the 2025-10-24 commit (Cause-Act-Code 216103).
  The speaker may replace these; they stay as the regression set.

## 10. Open decisions

- Public hostname and the reverse proxy on hub (plan).
- The final demo questions (the speaker chooses; §9 is the reference set).

## 11. Out of scope, and what was dropped

- **Dropped:** the custom aiogram bot with its own Claude API agent loop,
  spend cap and code-level citation check — replaced by the public MCP server
  plus Claude Code Channels. The cost is that citation discipline is steered
  (§5), not enforced.
- **Out of scope:** OAuth on the server, a citation graph between acts
  (references exist only as prose), vector search, the qaz-code database,
  lineage across replaced acts, hardening against a determined attacker, a web
  UI.
