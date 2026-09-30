# Demo questions: rehearsal, 2026-09-27

Opus 5.5, headless (`deploy/analysis-demo/ask*.sh`). "Clones" = Claude Code with Bash over
the 25 clones; "MCP" = only the four tools of https://cyphy.kz/kazakhstan-law/mcp.

## Analysis (clones)

| Question | Time | Result | Checked |
|---|---|---|---|
| Какой закон за последние 5 лет изменил больше всего других актов? Топ-5. | 54 s | № 223-VII of 19.04.2023, 156 acts; then 256-VIII (124), 71-VIII (127→110) | Same top 3 as an independent `git log` trailer count (165/140/127 by `Acts-Changed` sum; the model deduplicated per act and said so) |
| Какие министерства чаще всего меняли свои приказы в 2025 году? Топ-10. | 33 s | Minfin 190 amending acts, Health 164, Industry 112 … | Counted by commit author (the amending agency) and named the trap itself: after reorganisations most changed orders sit in a predecessor's directory |
| Какие статьи КоАП менялись чаще всего с 2020 года? Топ-10. | 73 s | Art. 804 (37), 684 (24), 729 (15), 62 (13) … procedural articles lead | Not independently recounted |
| С какого года работодатель обязан был заключать трудовой договор в письменной форме? (dogovor24.kz, 16.05.2021) | 86 s | Since 01.01.2000: Law № 493 of 10.12.1999, art. 12 — a repealed act, read from history | Link opens art. 12 at the 1999 commit |

## Everyday questions from forums (MCP)

| Question (verbatim) | Source | Time | Result |
|---|---|---|---|
| С какого года в Республике Казахстан работодатель обязан был заключать трудовой договор с работником в письменной форме? | [dogovor24 q/16624](https://dogovor24.kz/questions/s-kakogo-goda-v-respublike-kazahstan-rabotodatel-obyazan-byl-zaklyuchat-trudovoi-dogovor-s-rabotnikom-v-pismennoi-forme-16624.html) | 17 s | Only "since 2015 in the current Code": repealed acts are outside search. The contrast with the clones run is the demo point |
| …сдаешь форму 240… доход не превышает 500 000 в год, то можно применить стандартный вычет 14 МРП… (still so?) | [forum.zakon.kz 322725](https://forum.zakon.kz/topic/322725/) | 51 s | No: the 2026 Tax Code has a 30 МРП/month base deduction; 14 МРП remains for labour immigrants |
| Учитывается ли скидка 50%, если штраф за нарушение ПДД платится сразу в тот же день? | [dogovor24 q/14926](https://dogovor24.kz/questions/uchityvaetsya-li-skidka-50-esli-shtraf-za-narushenie-pdd-platitsya-srazu-v-tot-zhe-den-14926.html) | 18 s | Yes, within 7 days; КоАП art. 811 |
| Если водитель на машине ТОО нарушил ПДД, на кого оформляется штраф? | [dogovor24 q/22829](https://dogovor24.kz/questions/esli-voditel-na-mashine-too-narushil-pdd-na-kogo-oformlyaetsya-shtraf-kak-dannyi-vopros-reguliruetsya-v-kompanii-22829.html) | 31 s | Inspector → driver; camera → owner (the ТОО), who can name the driver; КоАП art. 31 |

More candidates (not yet run): forum.zakon.kz 113425 (since when the ТОО form exists),
326640 (transport tax arrears), 333438 (foreign property), 189054 (dog-walking signs,
a local decision).

# Rehearsal 2026-09-30: both paths, same 13 questions

Opus 5.5, headless, on air. MCP now has all five tools (`changes` added to `ask-mcp.sh` and the
bot). Clones = the server's corpus (HEADs equal), `~/demo/kazakhstan-law`. Streams in
`~/demo/runs/{git,mcp}-<id>.jsonl`.

| id | Question | Clones | MCP |
|---|---|---|---|
| a1 | Top-5 amending laws, 5 years | 56 s, 5 calls: 223-VII 156, 256-VIII 124, 71-VIII 110, 129-VII 73, 306-VIII 69 (unique acts) | 149 s, 27 calls: same top 3 as ranges (100–165, 120–130, 115–120); `changes` shows only 100 acts; #5 differs (141-VII ≈58) |
| a2 | Ministries that changed orders most, 2025 | 43 s: Minfin 259 orders, Health 242, Transport 148 … (distinct orders, not amending acts as on 27.09) | 22 s: declined, no corpus-wide counting |
| a3 | КоАП articles changed most since 2020 | 98 s: 804 (37), 684 (24), 729 (15), 62 (13) — matches 27.09 | 83 s: partial, 9 versions of 2026 only; `history` stops at 50 entries, 331-VIII too big for `changes` |
| a4 | Written labour contract since when | 42 s: 01.01.2000, Law № 493, art. 12 (repealed, from history) | 32 s: "since 2007" — the 1999 law is invisible |
| e1 | 14 МРП deduction still? | 90 s: no for 2026 (30 МРП), yes for 2025 | 71 s: same |
| e2 | 50% fine discount same day | 46 s: yes, art. 811 | 32 s: same |
| e3 | ТОО car, whose fine | 49 s: art. 31 | 48 s: same |
| c1 | Since when ТОО form exists | 60 s: ГК 27.12.1994 + Указ № 2255 of 02.05.1995 (found via `git log -S`) | 36 s: ГК 1994 + Law 220-I 1998; misses the 1995 Указ |
| c2 | Transport tax arrears notice | 87 s | 59 s: same substance |
| c3 | Property tax on foreign real estate | 46 s: no, art. 599 | 45 s: same |
| c4 | Dog-walking ban signs | 95 s: + 20 maslikhat rules in local-* repos | 36 s: law + ministerial rules, no local decisions |
| n1 | What the last КоАП version changed | 54 s | 39 s, 3 calls: same, with before/after links |
| n2 | What 223-VII changed in КоАП | 150 s: 156 acts, not КоАП | 71 s: not КоАП (it changed АППК); list cut at ~100 |

Everyday questions: parity, MCP a bit faster. `changes` moved a1 and n1–n2 into MCP's reach.
Still clones-only: corpus-wide counts (a2, a3), repealed acts (a4), local decisions without
naming the region (c4). Gaps filed as backlog mcp-1…mcp-5.
