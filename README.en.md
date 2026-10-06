# kith-skill

<div align="center"><img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg"><img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg"></div>

<p align="center">🇺🇸 <a href="./README.en.md">English</a> | 🇨🇳 <a href="./README.md">简体中文</a></p>

<p align="center">
<img src="assets/readme/hero.svg" width="100%" alt="kith-skill: turn a chat log into a persona skill pack you can drop onto a device; the outputs are SKILL.md, references/memory.md and name.zip, followed by the six-step pipeline parse → profile → sample → distil → verify → package">
</p>

**Turn a chat log into a persona skill pack you can drop onto a device**: `SKILL.md` + `references/memory.md` + `<name>.zip`.

Python 3.10+ standard library only: no `pip install`, no model downloads, and no network unless you explicitly turn on LLM distillation. The result loads into tools that support the Skill format or a similar packaging mechanism; it currently targets QZdesk (open-sourcing in progress).

> Every nickname, skill name, path and API key in this document is a placeholder. Replace them with your own values, and check the generated files for personal information before uploading.

How to read: [What you get](#what-you-get) · [Six-step pipeline](#the-six-step-pipeline-checkable-at-every-step) · [Illustrated tutorial](#illustrated-tutorial) · [Common options](#common-options) · [Troubleshooting](#troubleshooting) · [Privacy](#privacy-and-security)

## First look

<p align="center">
<img src="docs/images/tutorial-a4-log.png" width="100%" alt="First look: the run log of an offline pass — six pipeline steps, verification counts and pack size in one column">
</p>

One web workbench, two commands, two routes. The left column builds the pack and the right column accepts it: as soon as a run finishes you can say a couple of things to them under "try-chat", and if it does not feel right, edit the artifact by hand or change the recipe and re-run.

## What you get

| Artifact | What it is |
| --- | --- |
| `SKILL.md` | The persona: identity, **traits grounded in quotes**, **situations and reply strategies**, speaking style, verbal habits, real exchanges, warmth and restraint, example lines |
| `references/memory.md` | Relationship memory: timeline, shared places, inside jokes, conflict patterns, forms of address |
| `references/scenarios.json` | Situations, trigger signals, response moves, real adjacent exchanges and evidence strength |
| `references/memory-ledger.json` | Memory dates, evidence and status: fact / plan / promise / mentioned / joke / uncertain |
| `references/evaluation.json` | Regression cases derived from real situations, with original replies as references |
| `references/` | Always includes observations and statistics (`profile.md`) and quote sources (`quotes.md`); the size budget controls monthly transcripts (`transcript/`), topic files (`topics.md`), claim evidence (`evidence.md`) and the redacted raw export (`source/`) |
| `<name>.zip` | All of the above, packed. Upload it in the device console, set it as the main skill, and it takes effect on the next wake-up |

<p align="center">
<img src="assets/readme/pack-anatomy.svg" width="100%" alt="Anatomy of the pack: the role-play layer SKILL.md, the retrieval layer references/ (memory.md, transcript/, topics.md, evidence.md) and the packed name.zip; the whole pack is redacted by default">
</p>

The directory looks like this, and every layer has its own job:

```text
<out>/<name>/SKILL.md                          persona (role-play instructions)
<out>/<name>/references/memory.md              relationship memory
<out>/<name>/references/profile.md             statistics and observation scope, not chat instructions
<out>/<name>/references/quotes.md              time, speaker and original text for each [n]
<out>/<name>/references/scenarios.json         situation routing and real exchanges
<out>/<name>/references/memory-ledger.json     memory dates, status, evidence and confidence
<out>/<name>/references/evaluation.json        situation regression cases
<out>/<name>/references/transcript/YYYY-MM.md  every message, by month (redacted by default)
<out>/<name>/references/topics.md              quotes regrouped by topic
<out>/<name>/references/evidence.md            claim ← original line, for every claim
<out>/<name>/references/source/                redacted copy of the raw export (--no-source to skip)
<out>/<name>.zip                               all of the above; usually 1–3 MB
<out>/.kith/<name>/                            local feedback, snapshots and review reports; excluded from ZIP
```

The persona documents are only a dozen KB — those are distilled conclusions; "on which day, and what exactly was said" comes from searching `references/`. Entries that fail verification carry `（未在记录中找到依据）`; parts that came from a fallback or a fill-in are stated at the top of `SKILL.md` (for example "LLM 蒸馏 + 本地抽取式蒸馏补齐").

The main instructions describe the situation, the response and the wording, with original exchanges as evidence. In the sample, a thank-you gets “请我喝水” (buy me water), and “烧烤那次” (that barbecue time) gets “……那叫改期” (that was rescheduling). These examples guide the next reply more clearly than “humorous”. A single observation applies only to similar situations; it does not establish a permanent trait or make an old promise current.

Generation filters generic labels, topic words presented as verbal habits, exchanges paired across sessions or with the wrong speaker, and rules such as “never uses emoji” or “wait several minutes before replying”. Consecutive messages keep their individual boundaries. When all messages have timestamps, verbal habits must repeat across sessions. **Quote verification checks sources; it cannot prove the interpretation is sound or that try-chat sounds like the person.** Review the original context and try the persona yourself.

## Six improvements

| Capability | How to use it |
| --- | --- |
| Situation routing | Inspect signals, real exchanges and evidence strength in “情境路由”. Try-chat injects a situation matched to the current input and avoids mechanically applying playful replies to serious distress. |
| Situation regression | Enter replies in “回归测评” for offline checks, or configure an endpoint to run all cases with a model. Inspect empty replies, generic service language and routing conflicts alongside the original exchanges. |
| Try-chat feedback | Label each reply: sounds like them / too polite / off topic / wrong situation / factual error / other. Add how they would reply. Corrections guide later chat and regeneration; the four negative categories become regression cases. |
| Dated memory with status | Inspect chat observation dates, quotes and status in “关系记忆”. Plans, promises and jokes do not automatically become current facts; fulfillment needs confirmation. |
| Version comparison and rollback | Each generation saves a snapshot. Use “版本” to compare changes, save manual edits and rebuild the ZIP, or roll back. Rollback first saves current content and preserves custom files and local feedback. |
| Privacy review before sharing | “隐私检查” scans identifiers, email, locations, private references and binary files requiring manual inspection. Confirm items individually; confirmations expire when the content changes. |

Regression reports also follow the skill content: a manual edit or rollback to different content invalidates the old report. **Passing static checks means only that these rules found no issue; it does not prove likeness.** Model regression sends the persona and cases to your configured endpoint; static checks stay offline.

Feedback, generated evaluation replies, privacy confirmations and version snapshots live in `<out>/.kith/<name>/` and survive server restarts. Raw feedback and review reports stay out of the ZIP. Generation adds applicable feedback as response corrections to `SKILL.md`; notes are preferences, never new chat facts or original evidence. Version management covers files owned by the generator, preserving custom files in the directory.

## The six-step pipeline, checkable at every step

<p align="center">
<img src="assets/readme/workflow.svg" width="100%" alt="The six pipeline steps — parse, profile, sample, distil, verify, package — with what each one produces and what you can check on it; the footer explains the fallback to offline extraction when the LLM fails">
</p>

In between sits a six-step pipeline, and those are the six headings you see in the log:
`[1/6]` parse → `[2/6]` profile → `[3/6]` sample → `[4/6]` distil → `[5/6]` verify → `[6/6]` package.

Below is an example of the offline log structure for the bundled synthetic `samples/demo-chat.json`; actual counts and package size depend on the current run:

```text
[1/6] 解析聊天记录：demo-chat.json
      共 123 条消息；说话者 {'潘小雨': 66, '小蒯': 57}
      蒸馏对象：潘小雨
      关系类型：朋友（自动判断：没有明显的关系信号（每千字命中：恋人 0.0, 家人 0.0, 同事 0.0），按默认的「朋友」处理）
[2/6] 统计画像
      潘小雨 口头禅候选：下次一定、牛嘿、我擦、食堂二楼、行吧、在干嘛、出来吃烧烤不、我这都烤上了
      深夜消息占比：33%
[3/6] 挑选代表片段
      跳过：本地抽取模式直接读全部记录，不采样、不联网（脱敏照做，见第 6 步）
[4/6] 本地抽取式蒸馏（内置短句抽取 分词，不调用 LLM）
      潘小雨：说话风格 2 条、口头禅 2 条、接话方式 8 条、情感模式 0 条、温度与分寸 3 条、关系行为 0 条、典型例句 8 条、关系记忆 18 条
[5/6] 校验结论
      内容检查：保留 2 条有原话的人物特点、6 条情境接法、8 段接话示范；引用核验不能判断语义是否成立或是否像本人
      84 条可核验结论：原文命中 84、改写命中 0、未找到依据 0、时间不符 0
[6/6] 打包
      参考资料：2 个月的原记录 + 主题档案 + 结论依据 + 带路文件 + 原始导出，共 0.0 MB（--corpus-mb 8，0 可关；已脱敏）
      参考文献：25 条原话（正文里的 [n] 都能在记录里搜到原句）
      脱敏：手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址 已替换成 [标签]（想保留原样加 --no-redact）
      <out>/demo-persona.zip（16.5 KB）
```

Distillation has two engines with an identical field structure, switchable at any time:

| | `--no-llm` (offline, run this first) | LLM (default) |
| --- | --- | --- |
| Speed / dependencies | Seconds; no network, no key | Minutes; needs a network |
| Where claims come from | Full-log statistics, adjacent exchanges within a session and a limited set of situations | Complete session windows → situations and responses → consolidation across batches, followed by quote and exchange checks |
| Good for | Confirming parsing and speakers, reviewing real examples | Interpreting more complex situations and traits, with human review |

## Illustrated tutorial

Both routes produce exactly the same thing, so **pick one and stay on it**: route A if you would rather not touch a terminal, route B if you want to script it.

<p align="center">
<img src="assets/readme/routes.svg" width="100%" alt="Route comparison: route A opens the web workbench with python -m src.web, route B scripts python3 ex_distill.py; both emit the same SKILL.md, references/ and name.zip">
</p>

### Route A: the web workbench

```bash
python -m src.web            # defaults to http://127.0.0.1:8765/ and opens a browser
python -m src.web --port 9000 --no-open
```

The left column contains input, settings, run and an existing-skill picker. The right column has **ten tabs**: log / verification / SKILL.md / memory / try-chat / situation routing / regression / feedback / versions / privacy. The map below shows the basic generation flow; the new tabs are described under “Six improvements”.

<p align="center">
<img src="assets/readme/workbench-map.svg" width="100%" alt="Map of the workbench: the left column has the input, settings and run cards; the right column has the log, verification, SKILL.md, memory and try-chat tabs with what to look at in each">
</p>

> [!IMPORTANT]
> The workbench is a long-lived process: after editing code under `src/`, stop the old process and run `python -m src.web` again. Refreshing the browser does not load new code. An occupied port prevents startup. Editing generated Markdown only requires refreshing try-chat.

**A1 · Drop in the log and read the diagnosis first.** Once parsing succeeds: the header shows the file name and message count, the diagnosis expands below the drop zone, and only then does "Start distillation" stop being greyed out (it stays disabled while nothing has been parsed).

> The screenshot below is the synthetic sample that ships with this repository, `samples/demo-chat.json` (123 messages, 潘小雨 / 小蒯), dropped straight in.

<p align="center">
<img src="docs/images/tutorial-a2-diagnose.png" width="880" alt="Parsing diagnosis: parser, message count, time span and candidate list">
</p>

Build a habit around two numbers: **how many messages carry a timestamp** (the generic parser can produce a thousand messages with not a single timestamp, and every time-based statistic downstream is then void) and **the speaker count**. If the counts look wrong, switch files first, or re-save as UTF-8 and drop it again.

**A2 · Fill in the settings.** Skill name (ASCII; it determines the directory and zip name), who am I, who to distil — all pickable from candidates or typed in; the distillation mode is either `本地抽取` (offline) or `LLM 蒸馏` (the latter reveals endpoint, model and API key). Optional: extra description, relationship type, strict mode, distil both sides, public use.

<p align="center">
<img src="docs/images/tutorial-a3-config.png" width="880" alt="Settings card: skill name, who am I, who to distil, relationship type, distillation mode">
</p>

**A3 · Click "Start distillation" and read the log.** The right column streams those `[N/6]` steps live — the same six headings shown above — and the offline pass finishes in seconds.

<p align="center">
<img src="docs/images/tutorial-a4-log.png" width="880" alt="Run log: the six-step pipeline streams live, with pack size and next steps at the end">
</p>

With LLM distillation step 4 gets slow, but it reports three things: how many batches and calls in total, which one is running now, and how long each call actually took. Seeing `改用本地抽取式蒸馏` means that LLM stage failed and offline extraction already filled in — **the pack is still complete**, and you can re-run once the endpoint recovers.

**A4 · Review, download and upload.** Review situations, regression cases and privacy in the new tabs. After manual edits, use “保存修改并重新打包” under versions to rebuild the archive. Download `<skill-name>.zip` from the "run" card → upload it in the device console (board → Settings → Assistant, scan the QR code, or open `http://<DEVICE_IP>:8080`) → set it as the main skill in the skill list.

### Route B: the command line

The two commands in the quick start are the main path; here is what you can stack on top:

```bash
python3 ex_distill.py ... --device '<DEVICE_IP>:8080'   # upload straight to the device
python3 ex_distill.py ... --both                        # also distil you → references/self.md
python3 ex_distill.py ... --audience 公开                # the main skill becomes you, plus redaction
python3 ex_distill.py ... --dry-run-llm                 # print the request that would be sent, send nothing
python3 ex_distill.py ... --llm-chars 12000 --llm-batches 1   # smaller requests, less waiting
```

To use CLI output in the complete workbench, generate with `--out ./out`, then run `python -m src.web` and choose it in the existing-skill picker. For try-chat alone, open `/play?skill=<skill-name>` or use its header dropdown.

### Acceptance: three places to look

| Where | What you should see |
| --- | --- |
| "verification" tab | The number on the stamp is how many entries need a human decision (**0 is best**). On an LLM run a few "no evidence found" entries are normal — **what matters is the "closest original line" it prints next to each one** |
| "SKILL.md" / "memory" tabs | Check whether traits and reply strategies capture distinctive responses, verify both speakers and message boundaries, then review verbal habits, timeline and names (suspicious entries are marked in vermilion) |
| "try-chat" tab | Say a couple of things to them. This takes the least time and surfaces the most problems |

Try-chat reads the **artifacts on disk**: edit `out/<name>/SKILL.md` or `references/memory.md` by hand and refresh the page — no re-distillation needed. It never modifies the artifacts either.

<p align="center">
<img src="docs/images/tutorial-a5-play.png" width="880" alt="Try-chat tab: talking to the persona built from the artifacts just generated; the header shows how many files and sample exchanges are in play">
</p>

### Does not sound like them: three fixes

1. **Edit the artifacts by hand** (fastest): delete the line it keeps repeating, add a tic, replace an example line that does not sound like them → refresh the try-chat page. A few rounds of this usually beats re-distilling.
2. **Change the recipe and re-run**: `--desc 'quiet, likes to bicker'`, `--relation 同事`, `--both` — all of them change what the model sees.
3. **Drop entries with no evidence**: if you are sure a line was invented, re-run with `--strict` so it is deleted rather than annotated.

You can also save feedback under a reply and check similar inputs in regression. Regenerating the same skill reads previous feedback; generation does not carry feedback across a change from personal to public use.

> [!TIP]
> If try-chat sounds bookish, over-explaining or too polite, check the situation strategies and real exchanges for distinctive examples, then review speaking style and example lines. If those examples are sufficient but the model ignores them, try another model.

## Common options

| Option | Default | Description |
| --- | --- | --- |
| `--input` | required | Chat log file or directory (a directory is read recursively). |
| `--name` | required | Skill directory and zip name. |
| `--me` | `我` | Your nickname(s) in the log; comma-separated for several. |
| `--target` | automatic | Who to distil: the most talkative person other than you. |
| `--out` | `<tool dir>/dist` | Output directory; passing it explicitly is recommended. |
| `--no-llm` | off | Offline extraction: no network, no key. |
| `--desc` | empty | Extra relationship, personality or background description, e.g. `college classmates, often discuss reports and weekend plans`; treated as user input, not chat evidence. |
| `--relation` | `auto` | `auto` / `恋人` / `朋友` / `同事` / `家人`; changes headings and wording only. |
| `--both` | off | Two-way distillation: also writes your profile to `references/self.md`. |
| `--audience` | `本人` | `公开`: the main skill plays you, redacts the pack, and flags references only the original counterpart can resolve. |
| `--corpus-mb` | `8` | Size budget in MB for raw-log references. `0` disables `transcript/`, `topics.md`, `evidence.md`, `source/` and their guide; memory, statistics, quotes, situations, the memory ledger and regression cases are still generated. |
| `--strict` | off | Drop failing entries instead of annotating them. |
| `--no-redact` | off | Turn redaction off (on by default for the whole pack: phone numbers, ID numbers, card numbers, e-mail addresses, detailed addresses). |
| `--device` | none | Upload to `<DEVICE_IP>:8080` after generating. |
| `--timeout` / `--max-tokens` | `600` / `0` | Per-request read ceiling (seconds) / output ceiling. |

Full list: `python3 ex_distill.py --help`.

## Troubleshooting

| Symptom | Most likely cause | What to do |
| --- | --- | --- |
| Nothing / very few messages parsed | Format or encoding mismatch; another parser took the file | Read the parsing diagnosis in the workbench (how many messages each candidate got); for text files, re-save as UTF-8 |
| `LLM 返回的不是 JSON` | The model did not answer in JSON | Try a non-reasoning model |
| `等待 N 秒仍没等到响应` | Read timeout | `--timeout 1200`; if it always sticks around 200 seconds, that ceiling is on the gateway side — change models |
| `输出被截断（finish_reason=length）` | A reasoning model spent the budget on thinking | `--max-tokens 8192` or more |
| The workbench behaves like the old code / `端口 … 已有一个服务在运行` | The long-running process holds the old modules / the previous one is still up | Restart it; or use `--port 9000` |
| An entry carries `（未在记录中找到依据）` | The model may have invented a quote | Read the "closest original line" and search the source file for it; if it is not there, `--strict` |
| Try-chat says it cannot find the run / there is no API key | The job id only lives in the process / an offline pack carries no key | Pick an artifact from the header dropdown; enter a key under "Endpoint" |
| In try-chat it answers like a support agent | Concrete reply strategies are missing, or the model ignores the examples | Review strategies, real exchanges and example lines; edit and refresh, then try another model if needed |
| The words are right but it does not feel like them | Traits are too generic, or examples lost their context | Check the trigger, response and consecutive messages; after changing generator code, restart the workbench and distil again |

## Privacy and security

> [!WARNING]
> Chat logs can contain highly sensitive personal information. Before uploading them anywhere or calling an external LLM, confirm that you have the right to use the data and check the provider's policy.

- With `--no-llm`, chat content is processed on your machine only; in LLM mode samples are redacted before they leave.
- **The whole pack is redacted by default**: phone numbers, ID numbers, card numbers, e-mail addresses and detailed addresses become `[标签]`, across `SKILL.md`, `memory.md` and `references/`. `--no-redact` keeps the originals — **do not send that pack anywhere**.
- A `--audience 公开` pack will be read by other people: the tool **flags** references only the original counterpart can resolve and deliberately **does not rewrite them** — confirm every one before publishing.
- The try-chat API key is never written to disk or to the log; never put a key in the README, in source code or in a commit.
- The workbench listens on `127.0.0.1` only; the front end is plain static files with no CDN assets, so it works offline.

> [!CAUTION]
> The screenshots in this document use the synthetic sample that ships with this repository, `samples/demo-chat.json` (nicknames 潘小雨 / 小蒯). A real run contains real nicknames and conversations, so review any output before publishing it.

## Advanced

<details>
<summary><b>Supported input formats</b></summary>

#### Supported input

| Type | Example | Parsing behaviour |
| --- | --- | --- |
| JSON | `chat.json` | Looks for a message array under `messages`, `list`, `items`, `data` and friends; bodies use `text`/`content`/`message`/`body`, senders use `name`/`remark`/`nickname`. |
| CSV | `chat.csv` | Detects common column names for time, sender, body and `IsSender`. |
| TXT | `chat.txt` | `nickname: text`, timestamped message lines, QQ text exports, WhatsApp exports. |
| HTML / MHT / MHTML | `chat.html` | Strips the MIME envelope, undoes quoted-printable, then takes the plain text (QQ message-manager exports go this way). |
| WeChat SQLite | `EnMicroMsg.db` | Reads the `MSG` table of a decrypted database; `--channel` filters by `StrTalker`. |
| Twitter / X | `tweets.js` | `tweets.js` and `direct-messages.js` from an archive. |
| mbox | `archive.mbox` | Mail archive: body text, sender, date. |
| Directory | `exports/` | Recurses into `.txt` `.csv` `.json` `.js` `.mbox` `.html` `.htm` `.mht` `.mhtml`. |

Encodings are tried in order `utf-8-sig → utf-8 → gb18030 → utf-16`; formats are recognised by **extension plus content sniffing**, and **a mismatch degrades silently** — which is why the step-1 diagnosis matters.

A WeChat PC 4.x `chat.json` from wx-cli / WeChatExporter goes through the JSON path, but "who is who" needs untangling: **the other side's messages have an empty `sender`** (only your own messages carry a nickname) — in a private chat the empty string becomes the conversation name and the other side is normalised to "我".

</details>

<details>
<summary><b>LLM configuration and failure fallback</b></summary>

#### LLM configuration

| Setting | Resolution order |
| --- | --- |
| API key | `--api-key` → `LLM_API_KEY` → `MODELSCOPE_API_KEY` → `DASHSCOPE_API_KEY` → `OPENAI_API_KEY` |
| Endpoint | `--base-url` → `LLM_BASE_URL` → the ModelScope default |
| Model | `--model` → `LLM_MODEL` → `Qwen/Qwen3-235B-A22B` |

Requests are non-streaming: the call returns only once the model has written the whole JSON, so "slow" is normal — one or two minutes for the persona is routine, and the relationship memory has an even longer JSON to write.

A failure never leaves you empty-handed:

- **Whole-batch failure** (no key, unreachable, rate limiting, or a response that is not JSON) → falls back to offline extraction; the pack is still complete.
- **Half failure** (the persona came through, the memory timed out) → the successful half is kept, the missing half is filled in offline, with the provenance noted in the file.
- **Upstream flakiness** (an HTTP 200 shell, a read timeout) → backs off and retries, then splits that batch in half and re-runs each part; results are merged as usual.
- **One broken JSON blob does not take the whole run down** — only that batch is dropped.
- **A misbehaving gateway** (a BOM, an SSE-wrapped body, another JSON object glued to the end, or the bare completion text) → all four are salvaged.

</details>

<details>
<summary><b>Relationship types</b></summary>

#### Relationship types

`--relation` changes headings and wording only, **never facts**: `auto` / `恋人` / `朋友` / `同事` / `家人`. The default `auto` judges by the density of forms of address and topic words and prints its reasoning (for example "colleague signal densest (5.3 hits per 1,000 characters)"); `--relation` overrides it at any time.

| Internal field | 恋人 | 朋友 | 同事 | 家人 |
| --- | --- | --- | --- | --- |
| relationship timeline | 关系时间线 | 认识与相处时间线 | 共事时间线 | 关系时间线 |
| highlights | 甜蜜瞬间 | 相处高光 | 配合默契的瞬间 | 温暖瞬间 |
| conflicts | 争吵模式 | 闹别扭的时候 | 分歧与摩擦 | 争执模式 |
| inside_jokes | inside jokes | inside jokes | 你们之间的固定说法 | 家里的梗 |

</details>

<details>
<summary><b>How verification checks a claim</b></summary>

#### Verification

Every claim that says "this is a quote" or "this happened then" is checked against the original log (standard library only, no network): a quote check (verbatim hit / rewritten hit with coverage ≥ 0.75 / not found), a date check, and an evidence check. Because the prompt asks for provenance, quotes often carry a `time speaker:` prefix — verification strips that layer before comparing.

When checking by hand, read the **closest original line in the log** that the tool prints:

| What you see | What it means | What to do |
| --- | --- | --- |
| It is the same sentence as your quote | A hit; only a prefix or punctuation differs | Ignore it |
| The two texts differ | The model rewrote the meaning — this is what needs checking | Search the source file for that sentence; if it is not there, it was invented |
| It is an unrelated system line | There really is nothing close in the log | Suspect it |

Three ways to handle it: ignore it (the artifact already carries the annotation), edit the file, or re-run with `--strict` (which also drops false positives).

A deliberate boundary: **this checks whether a quotation is genuine, not whether a claim is semantically true.** Turning "I did not say that" into "I said that" is a reversal no string comparison can catch — that needs a semantic model of several hundred MB, which contradicts the zero-dependency goal. Luckily, wholesale invention is far more common than subtle inversion.

</details>

## Development and validation

```bash
python3 -m py_compile ex_distill.py
python3 ex_distill.py --help

python3 ex_distill.py --input /path/to/chat.json --me 'your nickname' \
  --name smoke-test --out ./dist-smoke --no-llm
unzip -l ./dist-smoke/smoke-test.zip

python3 -m src.web --no-open     # workbench self-check: http://127.0.0.1:8765/
```

Run `python -m compileall -q src tests` and `python -m unittest discover -s tests -v`. The suite covers conversation boundaries, grounded traits, routing, memory status, feedback, stale reports, privacy scanning, rollback, failed-write recovery and local HTTP endpoints. Model calls use local substitutes and need no real key. For browser validation, install Playwright and run `python tests/browser_workbench.py` (add `--browser-channel msedge` for installed Edge). It uses synthetic data, local model substitutes and temporary output.

### Workbench API

All routes start with `/api/workbench/<skill-name>/`. The skill must be under `out/` in the directory used to start the workbench.

| Route | Method | Purpose |
| --- | --- | --- |
| `package` / `download` | GET | Preview documents / download the current ZIP |
| `scenarios` / `memory` | GET | Situation routing / memory ledger |
| `evaluation` | GET / POST | Read report / submit `replies` (case ID → reply) and `fingerprint` for static checks |
| `evaluate-model` | POST | Submit one `case`, `fingerprint` and endpoint settings to run and save one model reply |
| `feedback` | GET / POST | Read summary / submit `user`, `reply`, `label` and optional `note` |
| `versions` / `diff?version=<version>` | GET | List snapshots / compare history with current files |
| `snapshot` / `rollback` | POST | Save edits and rebuild / submit `version` to restore |
| `privacy` | GET / POST | Scan / submit `item`, `confirmed` and `fingerprint` to record a decision |

Legacy skills without the new reference files show empty states and remain available for preview and try-chat. Regenerate to add routing, the memory ledger and regression cases. Local `.kith/` data may include original trial messages and historical personal information; it is excluded from the ZIP but should be reviewed when sharing an entire output directory. Privacy confirmation records a decision to keep an item; it does not redact or remove it.

## Contributing

Issues and pull requests are welcome. Before submitting:

- [ ] Run `python3 -m py_compile ex_distill.py`
- [ ] Validate parsing behaviour with redacted or synthetic chat data
- [ ] Do not commit chat logs, API keys or generated persona files
- [ ] Keep the related documentation in sync

## Acknowledgements

- [agenmod/immortal-skill](https://github.com/agenmod/immortal-skill): the ideas behind a digital double, per-dimension distillation and evidence awareness.
- [shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter): JSON export for QQ chat logs.
- [93857536-pixel/WeChatExporter](https://github.com/93857536-pixel/WeChatExporter): WeChat chat-log export.

## License

Released under the [MIT License](LICENSE).
