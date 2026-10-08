"""Questions for evidence that should be confirmed by a person."""
from __future__ import annotations

from . import storage, versions
from .privacy import redact


def build(specificity: dict, coverage: dict, ledger: list[dict]) -> dict:
    questions = []
    for item in specificity.get("traits", []):
        if item.get("generalization_risk") in ("high", "medium"):
            questions.append({
                "id": "specificity-" + item["id"],
                "type": "trait",
                "priority": "high" if item.get("generalization_risk") == "high" else "medium",
                "source_id": item["id"],
                "question": f"“{item['text']}”是否确实适用于多个场景？请补充或确认原话。",
                "status": "pending",
            })
    for row in coverage.get("matrix", []):
        if row["status"] != "covered":
            questions.append({
                "id": "coverage-" + str(row["id"]),
                "type": "scenario",
                "priority": "medium",
                "source_id": row["id"],
                "question": f"“{row['label']}”是否有你希望保留的接法？目前只有 {row['sessions']} 段证据。",
                "status": "pending",
            })
    for item in ledger:
        if item.get("validity") == "needs_confirmation" or item.get("confidence") == "uncertain":
            questions.append({
                "id": "memory-" + str(item.get("id", len(questions))),
                "type": "memory",
                "priority": "high" if item.get("status") in ("promise", "fact") else "medium",
                "source_id": item.get("id", ""),
                "question": f"记忆“{item.get('text', '')}”现在仍然有效吗？",
                "status": "pending",
            })
    return {"schema_version": 1, "questions": questions, "pending": len(questions)}


def view(root):
    data = storage.load(root / 'references/questions.json', {'questions': []})
    saved = storage.load(storage.local_dir(root) / 'answers.json', {})
    fingerprint = versions.fingerprint(root)
    answers = saved.get('answers', {}) if saved.get('fingerprint') == fingerprint else {}
    entries = [{**q, **answers.get(q['id'], {})} for q in data.get('questions', [])]
    return {**versions.state(root), 'questions': entries,
            'pending': sum(q['status'] == 'pending' for q in entries),
            'stale': bool(saved) and saved.get('fingerprint') != fingerprint}


def answer(root, payload):
    with storage.lock(root):
        data = view(root)
        if payload.get('fingerprint') != data['fingerprint']:
            raise ValueError('内容已变化，请刷新补标问题')
        identity = str(payload.get('question') or '')
        if not any(q['id'] == identity for q in data['questions']):
            raise ValueError('补标问题不存在')
        status = payload.get('status')
        if status not in ('confirmed', 'rejected', 'pending'):
            raise ValueError('请选择确认、否定或待确认')
        note = redact(str(payload.get('answer') or '').strip())[:2000]
        if status == 'confirmed' and not note:
            raise ValueError('确认时请填写适用范围或当前情况')
        saved = storage.load(storage.local_dir(root) / 'answers.json', {})
        answers = saved.get('answers', {}) if saved.get('fingerprint') == data['fingerprint'] else {}
        answers[identity] = {'status': status, 'answer': note, 'answered_at': storage.now()}
        storage.write(storage.local_dir(root) / 'answers.json', {'fingerprint': data['fingerprint'], 'answers': answers})
        return view(root)


def prompt(root):
    entries = view(root)['questions']
    confirmed = [q for q in entries if q['status'] == 'confirmed']
    rejected = [q for q in entries if q['status'] == 'rejected']
    if not confirmed and not rejected:
        return ''
    lines = ['【用户补标：当前使用范围，不能当作原聊天证据】']
    lines.extend(q['question'] + ' 用户确认：' + q['answer'] for q in confirmed)
    lines.extend(q['question'] + ' 用户否定；不要采用该观察。' for q in rejected)
    return '\n'.join(lines)
