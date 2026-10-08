"""Resolve explicit reply targets and persist manual links across regeneration."""
from collections import Counter
from dataclasses import replace
import re
import uuid

from . import storage, versions, message_index
from .privacy import redact


def apply(root, msgs, redacted=True, links=None):
    links = links if links is not None else storage.load(storage.local_dir(root) / 'reply-links.json', {}) or {}
    keys = [message_index.content_key(replace(m, text=redact(m.text)) if redacted else m) for m in msgs]
    counts = Counter(keys)
    positions = {key: index for index, key in enumerate(keys) if counts[key] == 1}
    source_ids = Counter(m.source_id for m in msgs if m.source_id)
    result = list(msgs)
    for index, key in enumerate(keys):
        source = links.get(key)
        if not source or counts[key] != 1 or counts[source] != 1:
            continue
        source_index = positions[source]
        if source_index >= index or msgs[source_index].speaker == msgs[index].speaker:
            continue
        # Synthetic IDs make the association independent of ordinal changes.
        identity = result[source_index].source_id
        if not identity or source_ids[identity] > 1:
            identity = 'manual-' + source
        result[source_index] = replace(result[source_index], source_id=identity)
        result[index] = replace(result[index], reply_to=identity)
    return result


def save(root, payload):
    from . import incremental, scenarios, coverage, evaluation
    from .package import write_package
    with storage.lock(root):
        if payload.get('fingerprint') != versions.fingerprint(root):
            raise ValueError('内容已变化，请刷新原话后关联')
        info, indexed = incremental.baseline(root)
        msgs = incremental.to_messages(indexed['messages'])
        reply_index, source_index = int(payload.get('reply', 0)), int(payload.get('source', 0))
        if not 1 <= source_index < reply_index <= len(msgs):
            raise ValueError('引用对象必须是回复之前存在的消息')
        reply, source = msgs[reply_index - 1], msgs[source_index - 1]
        if reply.speaker != info['target'] or source.speaker != info['counterpart']:
            raise ValueError('请把目标人物的回复关联到对话方的输入')
        from .conversations import has_unresolved_reply
        if source.reply_to or has_unresolved_reply(source.text):
            raise ValueError('引用对象本身仍带引用，请选择原始输入消息')
        counts = Counter(message_index.content_key(m) for m in msgs)
        reply_key, source_key = message_index.content_key(reply), message_index.content_key(source)
        if counts[reply_key] != 1 or counts[source_key] != 1:
            raise ValueError('消息内容重复且无法唯一定位，请保留完整时间戳后重新导入')
        links = storage.load(storage.local_dir(root) / 'reply-links.json', {}) or {}
        links[reply_key] = source_key
        full = apply(root, msgs, redacted=False, links=links)
        routes = scenarios.build_scenarios(full, info['target'], info['counterpart'])
        matrix = coverage.build(routes, full, info['target'], info['counterpart'])
        new_id = uuid.uuid4().hex
        files = versions.current_files(root)
        skill = files.pop('SKILL.md').decode('utf-8')
        memory = files.pop('references/memory.md')
        scenario_md = scenarios.render_markdown(routes)
        if '## 情境路由表' in skill:
            skill = re.sub(r'^## 情境路由表\n.*?(?=^## |\Z)', scenario_md + '\n', skill,
                           count=1, flags=re.MULTILINE | re.DOTALL)
        else:
            skill += '\n\n' + scenario_md
        replacements = {'observations': {**info, 'baseline_id': new_id},
                        'message-index': message_index.build(full), 'coverage': matrix,
                        'scenarios': scenarios.package_data(routes),
                        'evaluation': {'schema_version': 1, 'cases': evaluation.build_cases(routes)}}
        replacements['message-index']['citations'] = indexed.get('citations', {})
        if not info.get('corpus_enabled'):
            included = {row['index'] for row in storage.load(root / 'references/message-index.json', {}).get('messages', [])}
            included.update((source_index, reply_index))
            replacements['message-index'].update(complete=False,
                messages=[row for row in replacements['message-index']['messages'] if row['index'] in included])
        files.update({'references/' + key + '.json': storage.dumps(value) for key, value in replacements.items()})
        storage.write(storage.local_dir(root) / 'baselines' / (new_id + '.json'), message_index.build(full))
        write_package(root.parent, root.name, skill, memory, extra=files, reason='人工关联引用消息')
        storage.write(storage.local_dir(root) / 'reply-links.json', links)
        return {**versions.state(root), 'reply': reply_index, 'source': source_index}
