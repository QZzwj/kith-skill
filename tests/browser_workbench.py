"""Optional browser acceptance with synthetic data and local model substitutes.

python tests/browser_workbench.py --browser-channel msedge
Requires Playwright only for this development check, not for the application.
"""
import argparse
import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import feedback, storage, versions, web


def run(browser_channel=None, screenshots=None):
    from playwright.sync_api import expect, sync_playwright

    with tempfile.TemporaryDirectory(prefix='kith-browser-') as folder:
        out = Path(folder) / 'out'
        legacy = out / 'legacy'
        legacy.mkdir(parents=True)
        (legacy / 'SKILL.md').write_text('# 旧技能\n\n随口聊两句\n', encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), web._Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        errors = []
        console_errors = []
        expected_console_errors = []
        expected_model_failure = False
        requests_failed = []
        calls = []
        checked = []

        def model_reply(*args, **kwargs):
            calls.append(args)
            return '请我喝水'

        try:
            with patch.object(web, 'OUT_ROOT', out), patch('src.web.llm_chat', side_effect=model_reply), sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel=browser_channel)
                context = browser.new_context(viewport={'width': 1440, 'height': 900})
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                def record_console(message):
                    if message.type != 'error':
                        return
                    if (expected_model_failure and '502' in message.text and
                            message.location.get('url', '').endswith('/evaluate-model')):
                        expected_console_errors.append(message.text)
                    else:
                        console_errors.append(message.text)

                page.on('console', record_console)
                page.on('requestfailed', lambda request: requests_failed.append(request.url))
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base)
                page.wait_for_load_state('networkidle')
                # Inspect the rendered state before interactions.
                assert page.locator('#tabs .tab').count() == 10
                expect(page.locator('#review-skill')).to_have_value('legacy')

                def tab(name):
                    page.locator(f'.tab[data-view="{name}"]').click()
                    expect(page.locator('#view-' + name)).to_be_visible()

                for name in ['skill', 'memory', 'scenarios', 'evaluation', 'feedback', 'versions', 'privacy']:
                    tab(name)
                    expect(page.locator('#view-' + name)).not_to_contain_text('正在读取')
                checked.append('legacy compatibility')

                sample = Path(__file__).resolve().parents[1] / 'samples/demo-chat.json'
                page.locator('#file').set_input_files(str(sample))
                expect(page.locator('#run')).to_be_enabled()
                page.locator('#f-name').fill('browser-demo')
                page.locator('#f-me').fill('小蒯')
                page.locator('#f-target').fill('潘小雨')
                page.locator('input[name="mode"][value="offline"]').check()
                page.locator('#run').click()
                expect(page.locator('#state-text')).to_have_text('完成', timeout=30000)
                expect(page.locator('#review-skill')).to_have_value('browser-demo')
                expect(page.locator('#review-status')).to_have_text('当前技能：browser-demo')
                root = out / 'browser-demo'
                first = versions.current(root)['version']
                checked.append('upload, parse and offline generation')

                for name in ['log', 'verify', 'skill', 'memory', 'scenarios', 'evaluation', 'feedback', 'versions', 'privacy', 'play']:
                    tab(name)
                    if name != 'play':
                        expect(page.locator('#view-' + name)).not_to_contain_text('正在读取')
                checked.append('all ten tabs')

                frame = page.frame_locator('#playframe')
                expect(frame.locator('#say')).to_be_enabled()
                frame.locator('#f-apikey').fill('local-test-only-key')
                frame.locator('#f-baseurl').fill('http://local.invalid/v1')
                frame.locator('#f-model').fill('local-test')
                frame.locator('#say').fill('谢谢你提醒我')
                frame.locator('#send').click()
                expect(frame.locator('.bubble--ta')).to_contain_text('请我喝水')
                form = frame.locator('.chat-feedback').last
                form.get_by_label('反馈类型').select_option('太客气')
                form.get_by_label('反馈备注').fill('这次要更随口一些')
                form.get_by_role('button', name='保存反馈').click()
                expect(form.locator('[role="status"]')).to_contain_text('已保存')
                assert feedback.summary(root)['total'] == 1
                tab('feedback')
                expect(page.locator('#view-feedback')).to_contain_text('这次要更随口一些')
                checked.append('trial reply and saved feedback')

                tab('evaluation')
                expect(page.locator('#view-evaluation')).to_contain_text('来自试聊差评')
                page.locator('[data-reply]').first.fill('不客气，请问还有什么')
                page.locator('#eval-static').click()
                expect(page.locator('.eval-result').first).to_contain_text('泛化客服话术')
                page.get_by_text('模型测评接口（会发送用例和人设到所填接口）', exact=True).click()
                page.locator('#eval-key').fill('local-test-only-key')
                page.locator('#eval-base').fill('http://local.invalid/v1')
                page.locator('#eval-model-name').fill('local-test')
                total = page.locator('[data-reply]').count()
                # The first case reaches the real server; the second fails,
                # exercising partial-result display and cache across tab changes.
                request_count = 0

                def fail_second_request(route):
                    nonlocal request_count
                    request_count += 1
                    if request_count == 2:
                        route.fulfill(status=502, content_type='application/json',
                                      body=json.dumps({'error': '合成接口故障'}))
                    else:
                        route.continue_()

                evaluation_url = '**/api/workbench/browser-demo/evaluate-model'
                expected_model_failure = True
                page.route(evaluation_url, fail_second_request)
                page.locator('#eval-model').click()
                expect(page.locator('#eval-progress')).to_contain_text('合成接口故障')
                expect(page.locator('[data-reply]').first).to_have_value('请我喝水')
                expect(page.locator('[data-reply]').first).to_have_attribute('data-checked', 'true')
                expect(page.locator('.eval-result').first).not_to_contain_text('泛化客服话术')
                page.unroute(evaluation_url, fail_second_request)
                expected_model_failure = False
                assert request_count == 2
                assert len(expected_console_errors) == 1
                tab('feedback')
                tab('evaluation')
                expect(page.locator('#eval-progress')).to_contain_text('已检查 1 个')
                expect(page.locator('[data-reply]').first).to_have_value('请我喝水')
                checked.append('partial regression results retained after endpoint failure')

                page.get_by_text('模型测评接口（会发送用例和人设到所填接口）', exact=True).click()
                page.locator('#eval-key').fill('local-test-only-key')
                page.locator('#eval-base').fill('http://local.invalid/v1')
                page.locator('#eval-model-name').fill('local-test')
                page.locator('#eval-model').click()
                expect(page.locator('#eval-progress')).to_contain_text(f'已检查 {total} 个', timeout=30000)
                assert len(calls) >= total + 1
                checked.append('static and model regression through real HTTP')

                # Simulate manual edits, preserving a custom reference on rollback.
                custom = root / 'references/custom.md'
                custom.write_text('用户自己添加的参考', encoding='utf-8')
                skill = root / 'SKILL.md'
                skill.write_text(skill.read_text(encoding='utf-8') + '\n手改标记 13800138000\n', encoding='utf-8')
                page.locator('#review-refresh').click()
                expect(page.locator('#review-status')).to_have_text('当前技能：browser-demo')
                tab('evaluation')
                expect(page.locator('#view-evaluation')).to_contain_text('旧报告失效')
                tab('versions')
                expect(page.locator('#version-save')).to_be_visible()
                page.locator('#version-save').click()
                expect(page.locator('#view-versions')).not_to_contain_text('未保存的修改')
                page.locator(f'[data-diff="{first}"]').click()
                expect(page.locator('#version-detail')).to_contain_text('手改标记')
                checked.append('manual save, stale report and diff')

                tab('privacy')
                expect(page.locator('#view-privacy')).to_contain_text('手机号可能未脱敏')
                item = page.locator('[data-privacy][data-confirmed="false"]').first
                item_id = item.get_attribute('data-privacy')
                item.click()
                expect(page.locator(f'[data-privacy="{item_id}"]')).to_have_attribute('data-confirmed', 'true')
                memory = root / 'references/memory.md'
                memory.write_text(memory.read_text(encoding='utf-8') + '\n再次手改\n', encoding='utf-8')
                page.locator('[data-refresh="privacy"]').click()
                expect(page.locator(f'[data-privacy="{item_id}"]')).to_have_attribute('data-confirmed', 'false')
                checked.append('privacy scan, confirmation and invalidation')

                tab('versions')
                page.locator(f'[data-rollback="{first}"]').click()
                page.get_by_role('button', name='确认回滚', exact=True).click()
                tab('skill')
                expect(page.locator('#view-skill')).not_to_contain_text('手改标记')
                assert custom.read_text(encoding='utf-8') == '用户自己添加的参考'
                assert feedback.summary(root)['total'] == 1
                with page.expect_download() as downloading:
                    page.locator('#download').click()
                download = downloading.value
                with ZipFile(download.path()) as archive:
                    assert archive.read('SKILL.md') == skill.read_bytes()
                    assert not any('.kith' in name or 'feedback.jsonl' in name for name in archive.namelist())
                assert all(b'local-test-only-key' not in file.read_bytes()
                           for file in storage.local_dir(root).rglob('*') if file.is_file())
                checked.append('rollback, feedback retention and rebuilt ZIP download')

                if screenshots:
                    screenshots.mkdir(parents=True, exist_ok=True)
                    tab('scenarios')
                    expect(page.locator('#view-scenarios .review-card').first).to_be_visible()
                    page.screenshot(path=str(screenshots / 'desktop.png'), animations='disabled')

                for width in [390, 320]:
                    page.set_viewport_size({'width': width, 'height': 844})
                    for name in ['memory', 'scenarios', 'evaluation', 'feedback', 'versions', 'privacy', 'play']:
                        tab(name)
                        if name == 'play':
                            expect(frame.locator('#say')).to_be_enabled()
                        else:
                            expect(page.locator('#view-' + name)).not_to_contain_text('正在读取')
                        dimensions = page.evaluate('({width: innerWidth, scroll: document.documentElement.scrollWidth})')
                        if dimensions['scroll'] > dimensions['width']:
                            overflow = page.evaluate('''Array.from(document.querySelectorAll('body *')).filter(el => {
                                const rect = el.getBoundingClientRect();
                                return rect.width && (rect.right > innerWidth || rect.left < 0) &&
                                    !el.closest('.tabs');
                            }).map(el => ({tag: el.tagName, class: el.className, id: el.id,
                                right: el.getBoundingClientRect().right})).slice(0, 20)''')
                            raise AssertionError((width, name, dimensions, overflow))
                        if name == 'play':
                            dimensions = frame.locator('body').evaluate('(el) => ({width: innerWidth, scroll: document.documentElement.scrollWidth})')
                            assert dimensions['scroll'] <= dimensions['width'], ('iframe', width, dimensions)
                    if screenshots:
                        tab('privacy')
                        page.locator('#view-privacy').scroll_into_view_if_needed()
                        page.screenshot(path=str(screenshots / f'mobile-{width}.png'), animations='disabled')
                checked.append('mobile layout at 390 and 320 pixels')

                assert not errors, errors
                assert not console_errors, console_errors
                assert not requests_failed, requests_failed
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            # Uploaded synthetic input is normally cleaned by web.main().
            for token in list(web._UPLOADS):
                uploaded = web._UPLOADS.pop(token)
                uploaded.unlink(missing_ok=True)
                uploaded.parent.rmdir()
            web._JOBS.clear()
        print(json.dumps({'passed': checked, 'model': 'local substitute', 'browser_errors': errors,
                          'console_errors': console_errors, 'failed_requests': requests_failed}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-channel', help='e.g. msedge or chrome; default is Playwright Chromium')
    parser.add_argument('--screenshots', type=Path, help='optional directory for synthetic browser screenshots')
    args = parser.parse_args()
    run(args.browser_channel, args.screenshots)
