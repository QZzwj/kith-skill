import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

from . import (cite, corpus, offline, quality, relation, verify, scenarios,
               memory_ledger, evaluation, feedback, privacy_review, storage, versions)
from .analysis import analyse, sample_sessions
from .llm import consult_llm
from .package import upload_to_device, write_package
from .parsers import load_messages
from .privacy import flag_deixis, redact
from .models import Msg
from .render import (PROFILE_FILE, render_memory_md, render_observations_md,
                     render_profile_md, render_skill_md)


def build_args(argv=None):
    p = argparse.ArgumentParser(
        description="把聊天记录蒸馏成QZdesk可用的人设技能",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="输出：<out>/<name>/SKILL.md + references/memory.md（+ 参考资料层），"
               "以及 <out>/<name>.zip",
    )
    p.add_argument("--input", required=True,
                   help="聊天记录文件或目录（txt/csv/json/html/mht/mhtml/mbox/js/db）")
    p.add_argument("--name", required=True, help="技能目录名（字母数字下划线短横线点）")
    p.add_argument("--display", help="显示名（默认用实际蒸馏对象的名字）")
    p.add_argument("--me", default="我",
                   help="你自己在记录里的昵称（逗号分隔可多个，默认「我」）。"
                        "微信工具导出时本人一侧通常标成「我」，保持默认即可")
    p.add_argument("--target", help="要蒸馏的对象昵称（默认自动判断：除 --me 之外说话最多的人）")
    p.add_argument("--channel", help="微信 SQLite 数据库中的 StrTalker，会话对象（仅 --input 为 .db 时使用）")
    p.add_argument("--desc", default="", help="主观描述：性格/MBTI/星座/标签，例如『ENFP，双子座，话痨』")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "dist"),
                   help="输出目录（默认 <工具目录>/dist，建议显式指定；不要依赖系统盘根目录等绝对路径）")
    p.add_argument("--llm-chars", type=int, default=30000, help="每批送给 LLM 的语料字符预算（默认 30000）")
    p.add_argument("--corpus-mb", type=float, default=corpus.DEFAULT_BUDGET_MB,
                   help="原记录参考层的体积预算，单位 MB（默认 8，0 = 不附原记录；仍保留统计和原话出处）。带上它，"
                        "skill 里会多出逐月原记录 references/transcript/ 与结论依据 "
                        "references/evidence.md，设备侧才能检索到原话")
    p.add_argument("--no-source", action="store_true",
                   help="不把原始导出附进 references/source/。默认会附（脱敏开着时附的是"
                        "脱敏副本：字段全保留、敏感数字换标签），它是包体积的大头（约 1~2MB），"
                        "也是以后换口径重新蒸馏的依据；仅「本人」版生效")
    p.add_argument("--llm-batches", type=int, default=3, help="最多分几批分析（默认 3）")
    p.add_argument("--max-tokens", type=int, default=0,
                   help="单次 LLM 调用的输出上限（默认 0：不传，用服务端默认值）。"
                        "思考型模型（DeepSeek-V4 等）推理会占用预算，正文被截断时报 "
                        "finish_reason=length，把这里调大即可")
    p.add_argument("--timeout", type=int, default=int(os.environ.get("LLM_TIMEOUT", "600")),
                   help="单次 LLM 请求的等待上限，单位秒（默认 600，可用 LLM_TIMEOUT 覆盖）。"
                        "非流式请求要等模型把整段 JSON 写完才返回，思考型模型写关系记忆"
                        "常要几分钟；超时会报「等待 N 秒仍没等到响应」")
    p.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", "https://api-inference.modelscope.cn/v1"),
                   help="OpenAI 兼容接口地址")
    p.add_argument("--model", default=os.environ.get("LLM_MODEL", "Qwen/Qwen3-235B-A22B"), help="模型名")
    p.add_argument("--api-key", default=os.environ.get("LLM_API_KEY")
                   or os.environ.get("MODELSCOPE_API_KEY")
                   or os.environ.get("DASHSCOPE_API_KEY")
                   or os.environ.get("OPENAI_API_KEY", ""),
                   help="API Key（也可用环境变量 LLM_API_KEY / MODELSCOPE_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY）")
    p.add_argument("--no-llm", action="store_true",
                   help="不调用 LLM，改用本地抽取式蒸馏（文体计量 + 原话抽取，每条结论附统计依据）")
    p.add_argument("--relation", default="auto", choices=["auto", *relation.RELATIONS],
                   help="关系类型，决定章节标题与措辞（默认 auto：按称呼与话题自动判断）")
    p.add_argument("--both", action="store_true",
                   help="双向蒸馏：连同你自己也做一份画像，放进 references/self.md"
                        "（公开版放 references/other.md），主技能因此知道对面是什么人")
    p.add_argument("--audience", default="本人", choices=["本人", "公开"],
                   help="技能给谁用。本人：主技能扮演对方，你和 TA 聊；"
                        "公开：主技能扮演你自己，别人来跟你的分身聊，"
                        "并自动打开 --both、对产物脱敏、标注只有本人对得上的指代")
    p.add_argument("--no-verify", action="store_true",
                   help="跳过结论校验（默认会核验引用与日期是否真的来自聊天记录）")
    p.add_argument("--strict", action="store_true",
                   help="校验不通过的条目直接剔除，而不是打上标注保留")
    p.add_argument("--dry-run-llm", action="store_true", help="打印将要发送的请求，但不真正调用")
    p.add_argument("--no-redact", action="store_true",
                   help="不做脱敏。默认会对**整个包**脱敏（SKILL.md/memory.md 与 "
                        "references/ 下的聊天记录、主题档案、结论依据、参考文献表）："
                        "手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址 → [标签]")
    p.add_argument("--device", help="可选：生成后直接上传，例如 192.168.137.103:8080")
    return p.parse_args(argv)


def main(argv=None) -> int:
    # 控制台编码兜底：Windows 默认 GBK，遇到 ↔ / 🕶 这类字符会抛 UnicodeEncodeError
    # 把整次运行打断（打印是日志，不该有这种杀伤力）。退化成 "?" 即可。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_args(argv)
    if not re.fullmatch(r'[\w.\-]+', args.name) or args.name.lower() in ('.', '..', '.kith'):
        print('技能名只允许字母、数字、下划线、点和短横线', file=sys.stderr)
        return 2
    src = Path(args.input)
    if not src.exists():
        print(f"找不到输入：{src}", file=sys.stderr)
        return 2

    print(f"[1/6] 解析聊天记录：{src}")
    try:
        msgs = load_messages(src, channel=args.channel)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not msgs:
        print("没解析出任何消息。支持的格式：微信/QQ 导出的 txt、csv、json；"
              "纯文本请写成「昵称: 内容」每行一条。", file=sys.stderr)
        return 2

    me = {x.strip() for x in args.me.split(",") if x.strip()}
    speakers = Counter(m.speaker for m in msgs)
    target = args.target
    if not target:
        candidates = [(n, c) for n, c in speakers.most_common() if n not in me]
        if not candidates:
            print(f"无法判断要蒸馏谁。所有说话者：{list(speakers)}，请用 --target 指定。", file=sys.stderr)
            return 2
        target = candidates[0][0]
    if target not in speakers:
        print(f"--target {target} 不在记录里。说话者：{list(speakers)}", file=sys.stderr)
        return 2

    print(f"      共 {len(msgs)} 条消息；说话者 {dict(speakers.most_common())}")
    print(f"      蒸馏对象：{target}")

    # 双向蒸馏：把你自己也做成一份画像。你那份只做人设，关系记忆两边共用一份。
    audience = args.audience
    me_name = next((n for n, _ in speakers.most_common() if n in me), "")
    both = args.both or audience == "公开"
    if both and not me_name:
        print(f"      找不到你自己的发言（--me {args.me} 都不在记录里：{list(speakers)}），"
              "本次只蒸馏单方", file=sys.stderr)
        both = False
    if audience == "公开" and not both:
        # 公开版的前提就是"主技能扮演你"，没有你那份就只能退回本人使用的语义
        print("      公开版需要你自己的画像，但 --me 没对上任何说话者：退回本人使用的语义",
              file=sys.stderr)
        audience = "本人"
    # 主技能扮演谁：本人使用＝对方（你和 TA 聊）；公开使用＝你（别人跟你的分身聊）
    main_name = me_name if (both and audience == "公开") else target
    back_name = target if main_name == me_name else me_name
    skill_root = Path(args.out) / args.name
    previous = versions.current(skill_root).get('metadata', {})
    feedback_rows = feedback.read(skill_root) if previous.get('audience', audience) == audience else []
    args.feedback_context = feedback.context(feedback_rows)
    if feedback_rows:
        print(f'      已载入 {len(feedback_rows)} 条试聊反馈：用于修正接法和回归测评，不作为聊天事实')
    if both:
        print(f"      双向蒸馏：{target} ↔ {me_name}")
        print(f"      技能用途：{audience} —— 主技能扮演 {main_name}，"
              f"背景资料 {PROFILE_FILE[audience]} 放 {back_name} 的画像")

    relation_name = args.relation
    if relation_name == "auto":
        relation_name, why = relation.detect(msgs, target)
        print(f"      关系类型：{relation_name}（自动判断：{why}）")
    else:
        print(f"      关系类型：{relation_name}（--relation 指定）")

    print("[2/6] 统计画像")
    stats_target = analyse(msgs, target)
    print(f"      {target} 口头禅候选："
          f"{'、'.join(p for p, _ in stats_target.phrases.most_common(8)) or '（不足）'}")
    print(f"      深夜消息占比：{stats_target.late_night / max(1, stats_target.timed_total) * 100:.0f}%")
    stats_me = None
    if both:
        stats_me = analyse(msgs, me_name)
        print(f"      {me_name} 口头禅候选："
              f"{'、'.join(p for p, _ in stats_me.phrases.most_common(8)) or '（不足）'}")
    # 每份画像都要配自己的统计：拿对方的统计来写"高频口头禅"，等于张冠李戴
    stats_main = stats_me if (both and audience == "公开") else stats_target
    stats_back = stats_target if (both and audience == "公开") else stats_me

    persona: dict = {}
    memory: dict = {}
    back_persona: dict = {}
    fell_back = False
    use_llm = not args.no_llm
    if use_llm and not args.api_key and not args.dry_run_llm:
        print("      未配置 API Key（--api-key、MODELSCOPE_API_KEY 或其他支持的环境变量），"
              "改用本地抽取式蒸馏", file=sys.stderr)
        use_llm = False

    print("[3/6] 挑选代表片段")
    # 注意：别叫 corpus —— 那个名字是本模块要用的「参考资料层」（src/corpus.py）
    sample = ""
    if use_llm:
        sample, used = sample_sessions(msgs, main_name, args.llm_chars * max(1, args.llm_batches),
                                      window_chars=args.llm_chars)
        if not args.no_redact:
            sample = redact(sample)
        print(f"      选中 {used} 字符（覆盖不同月份、日常与摩擦，保留会话顺序）")
    else:
        print("      跳过：本地抽取模式直接读全部记录，不采样、不联网"
              "（脱敏照做，见第 6 步）")

    if use_llm:
        print(f"[4/6] LLM 蒸馏（{args.model} @ {args.base_url}）")
        try:
            persona, memory, back_persona = consult_llm(
                sample, main_name, args, stats_main, relation_name,
                also=(back_name if both else ""),
                also_stats=(stats_back if both else None),
                audience=audience)
        except Exception as e:
            # 整批都失败时不留空骨架：「没有 Key、限流、返回异常也能拿到完整人设」
            # 是这个工具的承诺；空骨架等于把整次运行作废——用户拿到的 SKILL.md
            # 全是「（暂缺：…）」，还得自己再用 --no-llm 跑一遍，而这一步不需要联网。
            print(f"      LLM 调用失败：{e}", file=sys.stderr)
            persona, memory, back_persona = {}, {}, {}

        # 只挂了一部分（比如人格分析跑成了、关系记忆挂了）时，别把成功的那半也丢掉：
        # 缺的那半用本地抽取式蒸馏补上。
        missing = [name for name, part in (("人设", persona), ("关系记忆", memory)) if not part]
        if both and not back_persona:
            missing.append(f"{back_name} 的画像")
        if missing:
            fell_back = True
            spare_persona, spare_memory = offline.distill(msgs, main_name, stats_main,
                                                          desc=args.desc,
                                                          relation=relation_name)
            persona = persona or spare_persona
            memory = memory or spare_memory
            if both and not back_persona:
                back_persona, _ = offline.distill(msgs, back_name, stats_back,
                                                  desc=args.desc, relation=relation_name)
            print(f"      {'、'.join(missing)}改用本地抽取式蒸馏（{offline.engine()} 分词）补齐："
                  "结论来自统计与原话，并附依据", file=sys.stderr)
    else:
        print(f"[4/6] 本地抽取式蒸馏（{offline.engine()} 分词，不调用 LLM）")
        persona, memory = offline.distill(msgs, main_name, stats_main, desc=args.desc,
                                          relation=relation_name)
        if both:
            # 只取人设：关系记忆两边共用一份，没必要算两遍
            back_persona, _ = offline.distill(msgs, back_name, stats_back,
                                              desc=args.desc, relation=relation_name)

    if fell_back or not use_llm:
        memory_count = sum(len(v) for v in memory.values())
        print(f"      {main_name}：说话风格 {len(persona.get('说话风格', []))} 条、"
              f"口头禅 {len(persona.get('口头禅', []))} 条、"
              f"接话方式 {len(persona.get('接话方式', []))} 条、"
              f"情感模式 {len(persona.get('情感模式', []))} 条、"
              f"温度与分寸 {len(persona.get('温度与分寸', []))} 条、"
              f"关系行为 {len(persona.get('关系行为', []))} 条、"
              f"典型例句 {len(persona.get('典型例句', []))} 条、关系记忆 {memory_count} 条")
        if both:
            print(f"      {back_name}：说话风格 {len(back_persona.get('说话风格', []))} 条、"
                  f"口头禅 {len(back_persona.get('口头禅', []))} 条、"
                  f"接话方式 {len(back_persona.get('接话方式', []))} 条、"
                  f"典型例句 {len(back_persona.get('典型例句', []))} 条")

    print("[5/6] 校验结论")
    # 模型看到的是脱敏片段；引用核验也使用相同文本，避免将标签误判为编造。
    evidence_msgs = ([Msg(m.ts, m.speaker, redact(m.text)) for m in msgs]
                     if not args.no_redact else msgs)
    if not args.no_redact:
        persona = {key: [redact(str(item)) for item in value] for key, value in persona.items()}
        memory = {key: [redact(str(item)) for item in value] for key, value in memory.items()}
        back_persona = {key: [redact(str(item)) for item in value] for key, value in back_persona.items()}
    persona, quality_notes = quality.prepare_persona(persona, evidence_msgs, main_name, stats_main,
                                                     redact(args.desc) if not args.no_redact else args.desc,
                                                     relation_name)
    if use_llm and any(note.startswith("从完整会话补入") for note in quality_notes):
        fell_back = True
    for note in quality_notes:
        print(f"      内容检查：{note}")
    if back_persona:
        back_persona, _ = quality.prepare_persona(back_persona, evidence_msgs, back_name, stats_back,
                                                  args.desc, relation_name)
    if args.no_verify:
        print("      跳过（--no-verify）")
    elif not persona and not memory:
        print("      跳过：没有产出可校验的内容")
    else:
        findings = verify.inspect(persona, memory, evidence_msgs)
        persona, memory = verify.apply(persona, memory, findings, strict=args.strict)
        print(verify.format_report(findings))
        if back_persona:
            # 背景资料也要过一遍：它同样是拿原话写的，编了照样要标出来
            back_findings = verify.inspect(back_persona, {}, evidence_msgs)
            back_persona, _ = verify.apply(back_persona, {}, back_findings,
                                           strict=args.strict)
            print(f"      {back_name} 的画像：")
            print(verify.format_report(back_findings))

    display = args.display or main_name
    desc = args.desc
    if not desc and (fell_back or not use_llm):
        # 如实交代这份人设是哪来的：LLM 版本和统计版本的腔调差得远，
        # 用户看到满屏统计口径时才知道不是模型跑歪了。
        desc = ("LLM 蒸馏 + 本地抽取式蒸馏补齐："
                "结论都来自聊天记录，并附依据" if use_llm else
                "本地抽取式蒸馏（未调用 LLM）：每条结论都来自统计或聊天原话，并附有依据")

    # 公开版额外做一件事：把只有本人对得上的指代标出来（不删不改，删错代价比标出来大）。
    # 脱敏则是**所有版本默认都做**（见下面 [6/6]，--no-redact 可关）——产物会被设备上的
    # 其他 agent 读到，references 下又整整齐齐放着聊天记录，不该默认带原始手机号和地址。
    public_marks = 0
    if audience == "公开":
        persona, n1 = flag_deixis(persona)
        memory, n2 = flag_deixis(memory)
        back_persona, n3 = flag_deixis(back_persona)
        public_marks = n1 + n2 + n3

    print("[6/6] 打包")
    # 脱敏（默认开，--no-redact 可关）：references 下放的是**聊天记录**，逐月记录、
    # 结论依据、主题档案、以及正文里的参考文献都是同一批原话，统一过一遍才叫脱敏。
    # 只有"公开版"的措辞层另有指代标注（见上）。
    scrub = redact if not args.no_redact else None
    # 引用体系：给每条结论配"时间 + 说话人 + 原话"的出处，文末汇总成参考文献表
    cites = cite.Citations(evidence_msgs, redact=scrub)
    routes = scenarios.build_scenarios(evidence_msgs, main_name, back_name)
    ledger = memory_ledger.build(memory, evidence_msgs, cites)
    cases = evaluation.build_cases(routes)
    correction_md = feedback.render_rules(feedback_rows, routes)
    # 参考资料层：人设文档是提炼过的结论，"记得住事"靠的是能检索到的原话
    refs = corpus.build(msgs, target=main_name, persona=persona, memory=memory,
                        budget_mb=args.corpus_mb, redact=scrub, source=src,
                        # 原始导出默认附（脱敏副本）——它是"以后能换口径重新蒸馏"的兜底，
                        # 也是包体积的大头；公开版不给：那份包是要给别人读的。
                        allow_source=(audience == "本人" and not args.no_source))
    if refs:
        months = len([rel for rel in refs if rel.startswith(corpus.TRANSCRIPT_DIR)])
        source_rel = next((rel for rel in refs if rel.startswith(corpus.SOURCE_DIR)), "")
        print(f"      参考资料：{months} 个月的原记录 + 主题档案 + 结论依据 + 带路文件"
              f"{' + 原始导出' if source_rel else ''}，"
              f"共 {corpus.total_bytes(refs) / 1024 / 1024:.1f} MB"
              f"（--corpus-mb {args.corpus_mb:g}，0 可关；"
              f"{'已脱敏' if scrub else '未脱敏（--no-redact）'}）")
        if source_rel and source_rel.endswith((".db", ".mbox", ".sqlite")):
            print("      ⚠ 原始导出是二进制，没法脱敏：这份包别外发")
    elif args.corpus_mb > 0:
        print("      参考资料：无（记录为空）")

    # SKILL.md 里点出这些文件，设备侧的模型才知道"有原始材料可查"
    refs_bullets: list[str] = []
    if refs:
        refs_bullets = [f"`{corpus.TRANSCRIPT_DIR}/`（逐月逐条原记录）",
                        f"`{corpus.TOPICS_FILE}`（按主题重组的原话档案）",
                        f"`{corpus.EVIDENCE_FILE}`（结论的原话依据）",
                        f"`{corpus.README_FILE}`（带路）"]
        if any(rel.startswith(corpus.SOURCE_DIR) for rel in refs):
            refs_bullets.insert(2, f"`{corpus.SOURCE_DIR}/`（原始导出文件原样附上）")

    skill_md = render_skill_md(display, args.name, desc, persona, stats_main, relation_name,
                               audience=audience,
                               counterpart=back_name if both else "",
                               counterpart_profile=back_persona if both else None,
                               extra_refs=refs_bullets, cites=cites,
                               scenarios_md=scenarios.render_markdown(routes) + '\n' + correction_md)
    memory_md = render_memory_md(display, memory, stats_main, main_name, relation_name,
                                 cites=cites, ledger=ledger)
    profile_md = ""
    if both:
        role_note = (f"这是你自己（{back_name}）的画像。主技能扮演的是 {display}，"
                     "开口前先按这里了解对面是什么人。"
                     if audience == "本人" else
                     f"这是 {back_name} 的画像。主技能是 {display} 的分身，"
                     f"别人提到 {back_name} 时按这里回答。")
        profile_md = render_profile_md(back_name, back_persona, stats_back, relation_name,
                                       role_note, cites=cites)

    # 参考文献表：三份文档各带一份完整的（设备侧是按文件读的，别的文件里的编号它找不到）
    reference_table = cites.table()
    if reference_table:
        memory_md += reference_table
        if profile_md:
            profile_md += reference_table
        print(f"      参考文献：{cites.count} 条原话（正文里的 [n] 都能在记录里搜到原句）")
    # 脱敏是对**整个包**做的，不只是 references：文档正文里也引了原话（典型例句、
    # 口头禅、参考文献表），只脱附录等于没脱。默认开，--no-redact 保留原始数字。
    if scrub:
        skill_md, memory_md = redact(skill_md), redact(memory_md)
        profile_md = redact(profile_md) if profile_md else profile_md
        print("      脱敏：手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址 已替换成 [标签]"
              "（想保留原样加 --no-redact）")
    else:
        print("      脱敏：未做（--no-redact），包里含原始手机号/地址等，别外发")
    if audience == "公开" and public_marks:
        print(f"      公开版：{public_marks} 条指代只有本人对得上，已在文中标注，请逐条确认")

    extra: dict[str, str] = dict(refs)
    observations = render_observations_md(display, persona, stats_main, main_name)
    extra['references/profile.md'] = scrub(observations) if scrub else observations
    extra['references/quotes.md'] = reference_table.lstrip() or '# 原话出处\n\n本次没有可编号的引用。\n'
    extra['references/scenarios.json'] = storage.dumps(scenarios.package_data(routes))
    extra['references/memory-ledger.json'] = storage.dumps(memory_ledger.package_data(ledger))
    extra['references/evaluation.json'] = storage.dumps({'schema_version': 1, 'cases': cases})
    if both:
        extra[PROFILE_FILE[audience]] = profile_md
    zip_path = write_package(Path(args.out), args.name, skill_md, memory_md,
                             extra=extra or None, metadata={'audience': audience,
                                 'engine': 'llm' if use_llm else 'offline',
                                 'relation': relation_name, 'redacted': bool(scrub)})
    privacy = privacy_review.review(skill_root)
    print(f'      情境路由 {len(routes)} 类 · 带状态记忆 {len(ledger)} 条 · 回归用例 {len(cases)} 条')
    print(f"      发布前隐私检查：{len(privacy['items'])} 条待确认；在 Web 工作台可逐条查看")
    packed = zip_path.stat().st_size
    print(f"      {zip_path}（{packed / 1024 / 1024:.1f} MB，压缩后）" if packed >= 1024 * 1024
          else f"      {zip_path}（{packed / 1024:.1f} KB）")

    if args.device:
        print(f"      上传到 {args.device} …")
        upload_to_device(args.device, args.name, zip_path)

    print()
    print("下一步：")
    print("  1) 打开设备控制台（板子 → 设置 → 助手 扫码，或直接访问 http://<设备IP>:8080）")
    print(f"  2) 上传 {zip_path.name}")
    print("  3) 在技能列表里把它设为「主技能」（人设类）——之后唤醒即生效")
    print("  4) 想改口味就编辑 SKILL.md / references/memory.md 再传一次，或直接说『ta不会这样说』后手改")
    return 0
