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
