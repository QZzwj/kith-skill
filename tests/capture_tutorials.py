"""Recapture bilingual tutorials with synthetic data and local model substitutes.

python tests/capture_tutorials.py --browser-channel msedge
Requires Playwright for development only. English labels are translated in the
browser during capture; the application and quoted chat evidence stay unchanged.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src import scenarios, storage, web
from tutorial_labels import LABELS, LOCALIZE, RESTORE

SIZES = {name: (1440, 960) for name in (
    'workbench', 'tutorial-a2-diagnose', 'tutorial-a3-config', 'tutorial-a4-log',
    'scenarios', 'evidence', 'coverage', 'messages', 'updates', 'incremental', 'ab',
)}
SIZES.update({'verify': (1440, 3000), 'skill-preview': (1440, 3000),
              'tutorial-a5-play': (2880, 2000)})
TEST_KEY = 'local-test-only-key'


def capture_set(context, base: str, temporary: Path, destination: Path, english=False):
    from playwright.sync_api import expect

    page = context.new_page()
    errors, failed_requests, unknown = [], [], set()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.on('requestfailed', lambda request: failed_requests.append(request.url))

    def tab(view):
        page.locator(f'.tab[data-view="{view}"]').click()
        pane = page.locator('#view-' + view)
        expect(pane).to_be_visible()
        expect(pane).not_to_contain_text('正在读取')
        return pane

    def scroll_to(selector, padding=90):
        page.locator(selector).evaluate('''(el, padding) => {
          const pane = el.closest('.view');
          pane.scrollTop += el.getBoundingClientRect().top - pane.getBoundingClientRect().top - padding;
        }''', padding)

    def photo(name):
        width, height = SIZES[name]
        density = 2 if name == 'tutorial-a5-play' else 1
        page.set_viewport_size({'width': width // density, 'height': height // density})
        page.evaluate('document.activeElement?.blur()')
        # Normalize temporary upload/output paths in the displayed run log.
        # Actual generated files, counts, source text and replies are preserved.
        changed = []
        try:
            for frame in page.frames:
                if not frame.url.startswith(base):
                    continue
                unknown.update(frame.evaluate(LOCALIZE, {
                    'labels': LABELS if english else {}, 'english': english,
                    'temporary': str(temporary),
                }))
                changed.append(frame)
                frame.evaluate('document.fonts.ready')
                # Finish finite UI animations before capture; repeated shots
                # must not restore a just-opened pane to a half-faded state.
                frame.evaluate('''() => Promise.all(document.getAnimations()
                  .filter(a => a.effect?.getComputedTiming().iterations !== Infinity)
                  .map(a => a.finished.catch(() => {})))''')
            page.evaluate('''() => {
              const tab = document.querySelector('.tab.is-active');
              const nav = document.querySelector('.tabs');
              if (tab.offsetLeft < nav.scrollLeft) nav.scrollLeft = tab.offsetLeft;
              if (tab.offsetLeft + tab.offsetWidth > nav.scrollLeft + nav.clientWidth)
                nav.scrollLeft = tab.offsetLeft + tab.offsetWidth - nav.clientWidth;
              window.scrollTo(0, 0);
            }''')
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            assert page.locator('.view.is-active').evaluate('(el) => getComputedStyle(el).opacity') == '1'
            destination.mkdir(parents=True, exist_ok=True)
            path = destination / (name + '.png')
            page.screenshot(path=str(path), animations='disabled', scale='device' if density == 2 else 'css')
            data = path.read_bytes()
            assert data[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', data[16:24]) == (width, height)
        finally:
            for frame in changed:
                frame.evaluate(RESTORE)
            page.set_viewport_size({'width': 1440, 'height': 960})

    page.goto(base)
    page.wait_for_load_state('networkidle')
    expect(page.locator('#review-skill')).to_have_value('')
    page.wait_for_function("document.querySelector('.brand__mark').naturalWidth === 1080")
    assert page.locator('#tabs .tab').count() == 14
    photo('workbench')

    page.locator('#file').set_input_files(str(REPO / 'samples/demo-chat.json'))
    expect(page.locator('#run')).to_be_enabled()
    expect(page.locator('#diag-total')).to_contain_text('123')
    photo('tutorial-a2-diagnose')

    page.locator('#f-name').fill('demo-persona')
    page.locator('#f-me').fill('小蒯')
    page.locator('#f-target').fill('潘小雨')
    page.locator('input[name="mode"][value="offline"]').check()
    page.locator('#f-name').evaluate('''el => {
      const rail = el.closest('.rail'), card = el.closest('.card');
      rail.scrollTop += card.getBoundingClientRect().top - rail.getBoundingClientRect().top;
    }''')
    photo('tutorial-a3-config')

    page.locator('#run').click()
    expect(page.locator('#state-text')).to_have_text('完成', timeout=30000)
    expect(page.locator('#review-status')).to_have_text('当前技能：demo-persona')
    expect(page.locator('#download')).to_be_visible()
    page.locator('#view-log').evaluate('(el) => el.scrollTop = 0')
    photo('tutorial-a4-log')

    tab('verify')
    expect(page.locator('#verify .stamp')).to_be_visible()
    photo('verify')
    tab('skill')
    expect(page.locator('#view-skill')).to_contain_text('人物特点')
    page.locator('#view-skill').evaluate('(el) => el.scrollTop = 0')
    photo('skill-preview')

    tab('play')
    frame = page.frame_locator('#playframe')
    expect(frame.locator('#say')).to_be_enabled()
    frame.locator('#f-apikey').fill(TEST_KEY)
    frame.locator('#f-baseurl').fill('http://local.invalid/v1')
    frame.locator('#f-model').fill('local-demo-a')
    frame.locator('#say').fill('谢谢你提醒我')
    frame.locator('#send').click()
    expect(frame.locator('.bubble--ta')).to_contain_text('请我喝水')
    expect(frame.locator('#send')).to_be_enabled()
    frame.locator('#f-apikey').fill('')
    frame.locator('#cfg').evaluate('(el) => el.open = false')
    photo('tutorial-a5-play')

    tab('scenarios')
    cards = page.locator('#view-scenarios .review-card')
    expect(cards.first).to_be_visible()
    photo('scenarios')
    thanks = cards.filter(has=page.locator('h3', has_text='对方表达感谢')).first
    thanks.locator('[data-source]').first.click()
    expect(page.locator('#view-messages')).to_be_visible()
    expect(page.locator('.message-row--selected').first).to_be_visible()
    scroll_to('#view-messages h2')
    photo('messages')

    tab('evidence')
    expect(page.locator('#view-evidence .review-card').first).to_be_visible()
    photo('evidence')
    scroll_to('#view-evidence h3:has-text("情境覆盖矩阵")')
    photo('coverage')

    tab('updates')
    question = page.locator('[data-question-card]').first
    expect(question).to_be_visible()
    question.locator('[data-answer]').fill(
        'Only for everyday reminders; confirm timing and requirements for important tasks.' if english
        else '仅限日常提醒；重要事项先确认时间和要求。')
    identity = question.get_attribute('data-question-card')
    question.locator('[data-answer-status="confirmed"]').click()
    expect(page.locator(f'[data-question-card="{identity}"] .review-badge').last).to_have_text('已确认')
    photo('updates')

    # One duplicate plus two illustrative new messages, including a change to
    # an old promise. They are previewed only, so no history is changed.
    root = web.OUT_ROOT / 'demo-persona'
    first = storage.load(root / 'references/message-index.json')['messages'][0]
    additions = [{'time': first['time'], 'sender': first['speaker'], 'text': first['text']},
                 {'time': '2026-10-08T12:00:00', 'sender': '小蒯', 'text': '周末还约烧烤吗'},
                 {'time': '2026-10-08T12:01:00', 'sender': '潘小雨', 'text': '下次叫你这事取消了，周末不约烧烤了'}]
    incoming = temporary / 'new-chat.json'
    incoming.write_text(json.dumps(additions, ensure_ascii=False), encoding='utf-8')
    page.locator('#incremental-file').set_input_files(str(incoming))
    expect(page.locator('#incremental-file-status')).to_contain_text('已读取 3 条')
    page.locator('#incremental-preview').click()
    expect(page.locator('#incremental-result')).to_contain_text('新增 2 条 · 重复 1 条')
    expect(page.locator('#incremental-result')).to_contain_text('发现潜在冲突')
    expect(page.locator('#incremental-apply')).to_be_enabled()
    scroll_to('#incremental-form', padding=115)
    photo('incremental')

    tab('ab')
    expect(page.locator('#ab-start')).to_be_visible()
    for side in ('a', 'b'):
        page.locator(f'#ab-base-{side}').fill('http://local.invalid/v1')
        page.locator(f'#ab-model-{side}').fill('local-demo-' + side)
        page.locator(f'#ab-recipe-{side}').fill(
            ('Keep the original casual wording.' if side == 'a' else 'Use a polite acknowledgement.') if english
            else ('保留原话的随口措辞。' if side == 'a' else '用礼貌的确认来回应。'))
    page.locator('#ab-start').click()
    expect(page.locator('#ab-run')).to_be_enabled()
    count = page.locator('.ab-case').count()
    for side in ('a', 'b'):
        page.locator(f'#ab-key-{side}').fill(TEST_KEY)
    page.locator('#ab-run').click()
    expect(page.locator('#ab-progress')).to_have_text(f'已完成 {count * 2} / {count * 2} 次回复', timeout=30000)
    expect(page.locator('#ab-key-a')).to_have_value('')
    expect(page.locator('#ab-key-b')).to_have_value('')
    page.locator('[data-ab-choice="a"]').first.click()
    expect(page.locator('[data-ab-choice="a"]').first).to_have_class('review-button is-chosen')
    scroll_to('#ab-results', padding=150)
    photo('ab')

    assert not errors, errors
    assert not failed_requests, failed_requests
    assert not unknown, 'Untranslated interface labels: ' + json.dumps(sorted(unknown), ensure_ascii=False)
    assert not any(TEST_KEY.encode() in p.read_bytes() for p in web.OUT_ROOT.rglob('*') if p.is_file())
    page.close()


def model_substitute(base_url, api_key, model, system, turns, **kwargs):
    if model == 'local-demo-b':
        return '好的，我明白了。请问还有什么需要帮助的吗？'
    root = web.OUT_ROOT / 'demo-persona'
    routes = storage.load(root / 'references/scenarios.json')['scenarios']
    text = turns[-1]['content']
    # Replay a known adjacent exchange for the same synthetic input.
    for route in routes:
        for example in route['examples']:
            if text == ' '.join(example['incoming']):
                return '\n'.join(example['reply'])
    matched = scenarios.route(text, routes)
    return '\n'.join(matched['examples'][0]['reply']) if matched else '请我喝水'


def run(browser_channel=None):
    from playwright.sync_api import sync_playwright

    original_session = web.SESSION_DIR
    with tempfile.TemporaryDirectory(prefix='kith-capture-') as folder:
        temporary = Path(folder)
        uploads = temporary / 'uploads'
        uploads.mkdir()
        server = ThreadingHTTPServer(('127.0.0.1', 0), web._Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        try:
            with patch.object(web, 'SESSION_DIR', uploads), patch('src.web.llm_chat', side_effect=model_substitute), sync_playwright() as playwright:
                for language in ('zh', 'en'):
                    locale = 'en-US' if language == 'en' else 'zh-CN'
                    browser = playwright.chromium.launch(headless=True, channel=browser_channel, args=['--lang=' + locale])
                    try:
                        with patch.object(web, 'OUT_ROOT', temporary / language / 'out'):
                            context = browser.new_context(viewport={'width': 1440, 'height': 960},
                                                          device_scale_factor=2, timezone_id='Asia/Shanghai',
                                                          locale=locale)
                            try:
                                capture_set(context, f'http://127.0.0.1:{server.server_port}', temporary,
                                            temporary / language / 'images', english=language == 'en')
                            finally:
                                context.close()
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            web._UPLOADS.clear()
            web._JOBS.clear()
            original_session.rmdir()  # Empty directory created when src.web was imported.
        # Publish only after both sets finish and their dimensions are checked.
        for language in ('zh', 'en'):
            output = REPO / 'docs/images' / ('en' if language == 'en' else '')
            output.mkdir(parents=True, exist_ok=True)
            for name in SIZES:
                shutil.copyfile(temporary / language / 'images' / (name + '.png'), output / (name + '.png'))
    print(json.dumps({'screenshots_per_language': len(SIZES), 'languages': ['zh', 'en'],
                      'browser_errors': [], 'failed_requests': [], 'model': 'local substitute',
                      'temporary_directory_removed': not temporary.exists()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-channel', help='e.g. msedge; default is Playwright Chromium')
    run(parser.parse_args().browser_channel)
