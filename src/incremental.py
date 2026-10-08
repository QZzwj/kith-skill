"""Deduplicate new messages and surface possible memory conflicts."""
from __future__ import annotations

from collections import Counter
import re
from datetime import datetime
from types import SimpleNamespace
import uuid

from .message_index import content_key, rows
from .models import Msg
from . import storage, versions, offline, quality, specificity, coverage, questions, scenarios, memory_ledger, evaluation, message_index
from .analysis import analyse, sample_sessions
from .privacy import redact


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def to_messages(values) -> list[Msg]:
    result = []
    if not isinstance(values, list):
        return result
    for row in values:
        if not isinstance(row, dict) or not str(row.get("speaker", "")).strip():
            continue
        result.append(Msg(_parse_time(row.get("time") or row.get("ts")),
                          str(row["speaker"]), str(row.get("text", ""))))
    return result


def key(msg: Msg) -> str:
    return content_key(msg)


def detect(existing: dict | None, incoming: list[Msg], ledger: list[dict] | None = None) -> dict:
    known = Counter(key(msg) for msg in to_messages(rows(existing)))
    added = []
    for msg in incoming:
        identity = key(msg)
        if known[identity]:
            known[identity] -= 1
        else:
            added.append(msg)
    old_facts = [item for item in (ledger or []) if item.get("status") in ("fact", "promise", "plan")]
    conflicts = []
    for item in old_facts:
        quoted = [row.get("quote", "") for row in item.get("evidence", [])] or [str(item.get("text", ""))]
        words = {text[i:i+2] for text in quoted for i in range(len(text)-1)
                 if re.fullmatch(r"[\u4e00-\u9fff]{2}", text[i:i+2]) and text[i:i+2] not in {"已经", "下次", "可能", "没有", "原话"}}
        for index, msg in enumerate(added, 1):
            if any(word in msg.text for word in words) and any(mark in msg.text for mark in ("不", "没", "未", "取消", "改了", "不再")):
                conflicts.append({"memory_id": item.get("id", ""), "memory": item.get("text", ""),
                                  "message": index, "quote": msg.text, "status": "needs_review"})
    return {
        "schema_version": 1,
        "added_count": len(added),
        "duplicate_count": len(incoming) - len(added),
        "messages": [{"time": msg.ts.isoformat() if msg.ts else None, "speaker": msg.speaker,
                      "text": msg.text, "id": key(msg)} for msg in added],
        "conflicts": conflicts,
        "requires_review": bool(conflicts),
    }


def baseline(root):
    info = storage.load(root / 'references/observations.json', {})
    identity = str(info.get('baseline_id', ''))
    if not re.fullmatch(r'[a-f0-9]{32}', identity):
        raise ValueError('旧技能没有增量基线，请先重新生成一次')
    indexed = storage.load(storage.local_dir(root) / 'baselines' / (identity + '.json'))
    if not indexed:
        indexed = storage.load(root / 'references/message-index.json', {})
        if not indexed.get('complete'):
            raise ValueError('本地增量基线缺失，请用完整原记录重新生成一次')
    return info, indexed


def preview(root, incoming, fingerprint):
    if fingerprint != versions.fingerprint(root):
        raise ValueError('技能内容已变化，请刷新后重新预览')
    info, indexed = baseline(root)
    if info.get('redacted', True):
        incoming = [Msg(m.ts, m.speaker, redact(m.text)) for m in incoming]
    ledger = storage.load(root / 'references/memory-ledger.json', {}).get('memories', [])
    return {**detect(indexed, incoming, ledger), 'fingerprint': fingerprint}


def _merge(left, right):
    merged = {key: list(value) for key, value in left.items() if isinstance(value, list)}
    for key, values in right.items():
        for value in values:
            if value not in merged.setdefault(key, []):
                merged[key].append(value)
    return merged


def apply(root, incoming, payload):
    fingerprint = str(payload.get('fingerprint') or '')
    with storage.lock(root):
        report = preview(root, incoming, fingerprint)
        info, old_index = baseline(root)
        old_ledger = storage.load(root / 'references/memory-ledger.json', {}).get('memories', [])
        if not report['added_count']:
            return {**report, 'applied': False, **versions.state(root)}
    added = to_messages(report['messages'])
    target, counterpart = info['target'], info['counterpart']
    if not any(m.speaker == target for m in added):
        raise ValueError('新增内容没有目标人物的发言，不能提炼人物特点')
    stats = analyse(added, target)
    engine = 'offline'
    if payload.get('use_llm'):
        from .llm import consult_llm
        if not str(payload.get('api_key') or '').strip():
            raise ValueError('增量模型分析需要填写 API Key')
        args = SimpleNamespace(llm_chars=30000, llm_batches=3, base_url=str(payload.get('base_url') or ''),
                               model=str(payload.get('model') or ''), api_key=str(payload['api_key']),
                               timeout=600, max_tokens=0, dry_run_llm=False, desc='', no_redact=True,
                               feedback_context='')
        sample, _ = sample_sessions(added, target, args.llm_chars * args.llm_batches, window_chars=args.llm_chars)
        if not sample:
            raise ValueError('新增内容无法形成模型分析窗口')
        persona, memory, _ = consult_llm(sample, target, args, stats, info['relation'])
        if not persona or not memory:
            raise ValueError('增量模型分析没有完整结果，原技能未修改')
        engine = 'llm'
    else:
        persona, memory = offline.distill(added, target, stats, relation=info['relation'])
    if info.get('redacted', True):
        persona = {key: [redact(str(v)) for v in values] for key, values in persona.items()}
        memory = {key: [redact(str(v)) for v in values] for key, values in memory.items()}
    persona, _ = quality.prepare_persona(persona, added, target, stats, relation=info['relation'])
    from . import verify
    persona, memory = verify.apply(persona, memory, verify.inspect(persona, memory, added), strict=True)
    merged_persona, merged_memory = _merge(info['persona'], persona), _merge(info['memory'], memory)
    # A high-risk claim is left in the review data rather than added as a
    # definitive instruction. New limited observations retain their wording.
    full = to_messages(old_index['messages']) + added
    scores = specificity.build(merged_persona, full, target)
    routes = scenarios.build_scenarios(full, target, counterpart)
    matrix = coverage.build(routes, full, target, counterpart)
    ledger = memory_ledger.build(merged_memory, full)
    outstanding = {entry['id']: list(entry.get('conflicts', [])) for entry in old_ledger}
    for conflict in report['conflicts']:
        saved = outstanding.setdefault(conflict['memory_id'], [])
        if conflict not in saved:
            saved.append(conflict)
    for entry in ledger:
        if outstanding.get(entry['id']):
            entry.update(status='uncertain', validity='needs_confirmation', confidence='uncertain',
                         conflicts=outstanding[entry['id']])
    indexed = message_index.build(full)
    indexed['citations'] = storage.load(root / 'references/message-index.json', {}).get('citations', {})
    if not info.get('corpus_enabled'):
        included = {row['index'] for row in storage.load(root / 'references/message-index.json', {}).get('messages', [])}
        included.update(e['message'] for item in scores['items'] for e in item['evidence'])
        included.update(e['message'] for item in ledger for e in item['evidence'])
        included.update(i for item in matrix['matrix'] for i in item['message_indices'])
        included.update(i for item in routes for e in item['examples'] for i in e['incoming_messages'] + e['reply_messages'])
        indexed.update(complete=False, messages=[row for row in indexed['messages'] if row['index'] in included])
    question_data = questions.build(scores, matrix, ledger)
    for entry in ledger:
        for index, conflict in enumerate(entry.get('conflicts', [])):
            question_data['questions'].append({'id': f'conflict-{entry["id"]}-{index}',
                                              'type': 'conflict', 'priority': 'high', 'status': 'pending',
                                              'source_id': entry['id'],
                                              'question': f'旧记忆“{conflict["memory"]}”与新原话“{conflict["quote"]}”是否冲突？请确认适用时间。'})
    question_data['pending'] = len(question_data['questions'])
    new_id = uuid.uuid4().hex
    new_info = {**info, 'persona': merged_persona, 'memory': merged_memory, 'baseline_id': new_id}
    with storage.lock(root):
        if fingerprint != versions.fingerprint(root):
            raise ValueError('分析期间技能内容已变化，未合并；请重新预览')
        files = versions.current_files(root)
        skill = files.pop('SKILL.md').decode('utf-8')
        memory_md = files.pop('references/memory.md').decode('utf-8')
        new_traits = [item for item in scores['items'] if item['section'] in ('人物特点', '情境策略', '接话方式', '口头禅')
                      and item['text'] not in info['persona'].get(item['section'], [])
                      and item['generalization_risk'] != 'high']
        if new_traits:
            skill += '\n\n## 新增聊天观察\n\n以下仅描述新增记录里的有限观察，跨情境使用前先确认。\n\n'
            skill += '\n'.join('- ' + item['text'] for item in new_traits) + '\n'
        old_routes = storage.load(root / 'references/scenarios.json', {}).get('scenarios', [])
        changed_routes = [route for route in routes if route not in old_routes]
        if changed_routes:
            skill += '\n\n## 增量情境参考\n\n' + scenarios.render_markdown(changed_routes)
        new_memories = [entry for entry in ledger if entry['text'] not in info['memory'].get(entry['section'], [])]
        if new_memories:
            memory_md += '\n\n## 新增记录中的记忆（观察状态）\n\n'
            memory_md += '\n'.join(f'- [{memory_ledger.status_label(e["status"])}] {e["text"]}；'
                                    f'观察于 {e["time_start"] or "时间未知"}；当前有效性待确认' for e in new_memories) + '\n'
        if report['conflicts']:
            warning = '\n\n## 增量更新的冲突记忆\n\n以下旧记忆存在潜在冲突，确认前不要作为当前事实：\n\n'
            warning += '\n'.join(f'- {c["memory"]}；新原话：{c["quote"]}' for c in report['conflicts']) + '\n'
            skill += warning
            memory_md += warning
        replacements = {
            'observations': new_info, 'specificity': scores, 'coverage': matrix, 'message-index': indexed,
            'scenarios': scenarios.package_data(routes), 'memory-ledger': memory_ledger.package_data(ledger),
            'evaluation': {'schema_version': 1, 'cases': evaluation.build_cases(routes)}, 'questions': question_data,
        }
        files.update({'references/' + name + '.json': storage.dumps(value) for name, value in replacements.items()})
        # Keep the transcript reference layer up to date without re-analyzing it.
        if info.get('corpus_enabled'):
            from . import corpus
            refs = corpus.build(full, target=target, persona=merged_persona, memory=merged_memory, budget_mb=8,
                                redact=redact if info.get('redacted') else None, allow_source=False)
            files.update(refs)
        storage.write(storage.local_dir(root) / 'baselines' / (new_id + '.json'), message_index.build(full))
        from .package import write_package
        write_package(root.parent, root.name, skill, memory_md, extra=files,
                      metadata=versions.current(root).get('metadata', {}), reason=f'增量合并 {len(added)} 条消息')
        report = {**report, 'applied': True, 'engine': engine, **versions.state(root)}
        storage.write(storage.local_dir(root) / 'incremental-report.json', report)
        return report
