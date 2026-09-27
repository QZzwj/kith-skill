import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from . import offline, relation, verify
from .analysis import analyse, sample_sessions
from .llm import consult_llm
from .package import upload_to_device, write_package
from .parsers import load_messages
from .privacy import redact
from .render import render_memory_md, render_skill_md


def build_args(argv=None):
    p = argparse.ArgumentParser(
        description="把聊天记录蒸馏成xinpai-bot可用的人设技能",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="输出：<out>/<name>/SKILL.md + references/memory.md，以及 <out>/<name>.zip",
    )
    p.add_argument("--input", required=True,
                   help="聊天记录文件或目录（txt/csv/json/html/mht/mhtml/mbox/js/db）")
    p.add_argument("--name", required=True, help="技能目录名（字母数字下划线短横线点）")
    p.add_argument("--display", help="显示名（默认与 --name 相同）")
    p.add_argument("--me", default="我",
                   help="你自己在记录里的昵称（逗号分隔可多个，默认「我」）。"
                        "微信工具导出时本人一侧通常标成「我」，保持默认即可")
    p.add_argument("--target", help="要蒸馏的对象昵称（默认自动判断：除 --me 之外说话最多的人）")
    p.add_argument("--channel", help="微信 SQLite 数据库中的 StrTalker，会话对象（仅 --input 为 .db 时使用）")
    p.add_argument("--desc", default="", help="主观描述：性格/MBTI/星座/标签，例如『ENFP，双子座，话痨』")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "dist"),
                   help="输出目录（默认 <工具目录>/dist，建议显式指定；不要依赖系统盘根目录等绝对路径）")
    p.add_argument("--llm-chars", type=int, default=30000, help="送给 LLM 的语料字符预算（默认 30000）")
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
    p.add_argument("--no-verify", action="store_true",
                   help="跳过结论校验（默认会核验引用与日期是否真的来自聊天记录）")
    p.add_argument("--strict", action="store_true",
                   help="校验不通过的条目直接剔除，而不是打上标注保留")
    p.add_argument("--dry-run-llm", action="store_true", help="打印将要发送的请求，但不真正调用")
    p.add_argument("--no-redact", action="store_true", help="不做脱敏（默认会脱敏手机号/身份证/邮箱等）")
    p.add_argument("--device", help="可选：生成后直接上传，例如 192.168.137.103:8080")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = build_args(argv)
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

    relation_name = args.relation
    if relation_name == "auto":
        relation_name, why = relation.detect(msgs, target)
        print(f"      关系类型：{relation_name}（自动判断：{why}）")
    else:
        print(f"      关系类型：{relation_name}（--relation 指定）")

    print("[2/6] 统计画像")
    stats = analyse(msgs, target)
    print(f"      口头禅候选：{'、'.join(p for p, _ in stats.phrases.most_common(8)) or '（不足）'}")
    print(f"      深夜消息占比：{stats.late_night / max(1, stats.total) * 100:.0f}%")

    persona: dict = {}
    memory: dict = {}
    fell_back = False
    use_llm = not args.no_llm
    if use_llm and not args.api_key and not args.dry_run_llm:
        print("      未配置 API Key（--api-key、MODELSCOPE_API_KEY 或其他支持的环境变量），"
              "改用本地抽取式蒸馏", file=sys.stderr)
        use_llm = False

    print("[3/6] 挑选代表片段")
    corpus = ""
    if use_llm:
        corpus, used = sample_sessions(msgs, target, args.llm_chars)
        if not args.no_redact:
            corpus = redact(corpus)
        print(f"      选中 {used} 字符（深夜 / 争吵 / 长会话优先）")
    else:
        print("      跳过：本地抽取模式直接读全部记录，不采样、不脱敏、不联网")

    if use_llm:
        print(f"[4/6] LLM 蒸馏（{args.model} @ {args.base_url}）")
        try:
            persona, memory = consult_llm(corpus, target, args, stats, relation_name)
        except Exception as e:
            # 整批都失败时不留空骨架：「没有 Key、限流、返回异常也能拿到完整人设」
            # 是这个工具的承诺；空骨架等于把整次运行作废——用户拿到的 SKILL.md
            # 全是「（暂缺：…）」，还得自己再用 --no-llm 跑一遍，而这一步不需要联网。
            print(f"      LLM 调用失败：{e}", file=sys.stderr)
            persona, memory = {}, {}

        # 只挂了一部分（比如人格分析跑成了、关系记忆挂了）时，别把成功的那半也丢掉：
        # 缺的那半用本地抽取式蒸馏补上。
        missing = [name for name, part in (("人设", persona), ("关系记忆", memory)) if not part]
        if missing:
            fell_back = True
            spare_persona, spare_memory = offline.distill(msgs, target, stats,
                                                          desc=args.desc,
                                                          relation=relation_name)
            persona = persona or spare_persona
            memory = memory or spare_memory
            print(f"      {'、'.join(missing)}改用本地抽取式蒸馏（{offline.engine()} 分词）补齐："
                  "结论来自统计与原话，并附依据", file=sys.stderr)
    else:
        print(f"[4/6] 本地抽取式蒸馏（{offline.engine()} 分词，不调用 LLM）")
        persona, memory = offline.distill(msgs, target, stats, desc=args.desc,
                                          relation=relation_name)

    if fell_back or not use_llm:
        memory_count = sum(len(v) for v in memory.values())
        print(f"      说话风格 {len(persona.get('说话风格', []))} 条、口头禅 {len(persona.get('口头禅', []))} 条、"
              f"情感模式 {len(persona.get('情感模式', []))} 条、关系行为 {len(persona.get('关系行为', []))} 条、"
              f"典型例句 {len(persona.get('典型例句', []))} 条、关系记忆 {memory_count} 条")

    print("[5/6] 校验结论")
    if args.no_verify:
        print("      跳过（--no-verify）")
    elif not persona and not memory:
        print("      跳过：没有产出可校验的内容")
    else:
        findings = verify.inspect(persona, memory, msgs)
        persona, memory = verify.apply(persona, memory, findings, strict=args.strict)
        print(verify.format_report(findings))

    display = args.display or args.name
    desc = args.desc
    if not desc and (fell_back or not use_llm):
        # 如实交代这份人设是哪来的：LLM 版本和统计版本的腔调差得远，
        # 用户看到满屏统计口径时才知道不是模型跑歪了。
        desc = ("LLM 蒸馏 + 本地抽取式蒸馏补齐（部分环节失败）："
                "结论都来自聊天记录，并附依据" if use_llm else
                "本地抽取式蒸馏（未调用 LLM）：每条结论都来自统计或聊天原话，并附有依据")
    skill_md = render_skill_md(display, args.name, desc, persona, stats, relation_name)
    memory_md = render_memory_md(display, memory, stats, target, relation_name)

    print("[6/6] 打包")
    zip_path = write_package(Path(args.out), args.name, skill_md, memory_md)
    print(f"      {zip_path}（{zip_path.stat().st_size / 1024:.1f} KB）")

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
