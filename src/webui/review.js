/* Local skill workbench. Raw feedback and review results stay outside the ZIP. */
window.Review = (() => {
  let selected = '';
  let epoch = 0;
  let packageData = null;
  let cache = {};
  let evaluating = false;
  const sections = ['scenarios', 'evaluation', 'feedback', 'versions', 'privacy', 'memory'];
  const statusLabels = {fact: '事实', plan: '计划', promise: '承诺', mentioned: '提及', joke: '玩笑', uncertain: '不确定'};
  const date = value => value ? new Date(value).toLocaleString('zh-CN') : '时间未知';
  const badge = (text, bad = false) => `<span class="review-badge${bad ? ' review-badge--warn' : ''}">${esc(text)}</span>`;
  const empty = text => `<p class="empty">${esc(text)}</p>`;
  const endpoint = (section, name = selected) => `/api/workbench/${encodeURIComponent(name)}/${section}`;
  const post = (section, data, name = selected) => api(endpoint(section, name), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  });
  const active = () => document.querySelector('.tab.is-active')?.dataset.view;

  async function refreshList() {
    const {skills = []} = await api('/api/skills');
    const picker = $('review-skill');
    picker.replaceChildren(new Option(skills.length ? '选择一份技能' : '还没有技能', ''));
    skills.forEach(s => picker.add(new Option(s.title === s.name ? s.name : `${s.title}（${s.name}）`, s.name)));
    picker.value = selected;
    return skills;
  }

  async function select(name) {
    if (!name) return;
    selected = name;
    const turn = ++epoch;
    cache = {};
    packageData = null;
    $('review-status').textContent = `正在加载 ${name}…`;
    sections.forEach(s => { $('view-' + s).innerHTML = empty('正在加载…'); });
    $('view-skill').innerHTML = empty('正在加载…');
    try {
      const [data] = await Promise.all([api(endpoint('package', name)), refreshList()]);
      if (turn !== epoch) return;
      packageData = data;
      $('f-name').value = name;
      $('review-status').textContent = `当前技能：${name}`;
      ['skill', 'memory'].forEach(s => { document.querySelector(`.tab[data-view="${s}"]`).disabled = false; });
      $('view-skill').innerHTML = renderMarkdown(data.skill);
      $('view-memory').innerHTML = renderMarkdown(data.memory);
      $('artifact').hidden = !data.has_zip;
      $('download').href = endpoint('download');
      $('download').download = data.zip_name;
      $('download').textContent = `下载技能包 · ${data.zip_name}`;
      $('play').href = `/play?skill=${encodeURIComponent(name)}`;
      playUrl = `/play?skill=${encodeURIComponent(name)}&embed=1`;
      playLoaded = '';
      if (active() === 'play') openPlayFrame(playUrl);
      await open(active());
    } catch (err) {
      if (turn === epoch) {
        $('review-status').textContent = err.message;
        sections.forEach(s => { $('view-' + s).innerHTML = empty(err.message); });
      }
    }
  }

  async function open(section) {
    if (!sections.includes(section)) return;
    const pane = $('view-' + section);
    if (!selected) { pane.innerHTML = empty('先生成技能，或在左侧选择已有技能。'); return; }
    if (!packageData) return;
    if (cache[section]) { render(section, cache[section]); return; }
    const turn = epoch;
    pane.innerHTML = empty('正在读取…');
    try {
      const data = await api(endpoint(section));
      if (turn !== epoch) return;
      cache[section] = data;
      render(section, data);
    } catch (err) {
      if (turn === epoch) pane.innerHTML = empty(err.message);
    }
  }

  function render(section, data) {
    const pane = $('view-' + section);
    if (section === 'scenarios') {
      pane.innerHTML = '<h2>情境路由</h2><p>按相邻的真实接话归纳。先判断眼前的语境；单次观察只用于相似情境。</p>' +
        (data.scenarios.map(s => `<section class="review-card"><h3>${esc(s.label)}</h3>` +
          badge(s.sessions > 1 ? `${s.sessions} 段会话重复` : '单次观察') +
          `<p>触发信号：${esc(s.signals.join('、'))}</p><p><b>接法：</b>${esc(s.response_move)}</p>` +
          s.examples.map(e => `<blockquote>对方：${esc(e.incoming.join(' / '))}<br>本人：${esc(e.reply.join(' / '))}</blockquote>`).join('') +
          `<p class="review-muted">${esc(s.avoid.join('；'))}</p></section>`).join('') || empty('这份技能没有足够的场景证据；旧技能可重新生成以补齐。'));
    } else if (section === 'memory') {
      const ledger = (data.memories || []).map(m => `<details class="review-card"><summary>${badge(statusLabels[m.status] || '不确定', ['plan', 'promise', 'uncertain'].includes(m.status))} ${esc(m.text)}</summary>` +
        `<p>聊天提及日期：${esc(m.time_start || '未知')} ～ ${esc(m.time_end || '未知')}</p>` +
        `<p>${m.validity === 'needs_confirmation' ? '当前是否仍有效，需要重新确认。' : '历史观察，不代表当前状况。'}</p>` +
        m.evidence.map(e => `<blockquote>${esc(e.quote)}<br><small>${esc(e.time || '时间未知')}</small></blockquote>`).join('') + '</details>').join('');
      pane.innerHTML = '<h2>记忆状态与日期</h2><p>日期是聊天里的观察范围。计划、旧承诺和玩笑不能自动变成已发生的事实。</p>' +
        (ledger || empty('旧技能未附记忆状态，可重新生成补齐。')) + '<hr>' + renderMarkdown(packageData.memory);
    } else if (section === 'evaluation') {
      renderEvaluation(data);
    } else if (section === 'feedback') {
      pane.innerHTML = '<h2>试聊反馈</h2><p>在试聊每条回复下标注。差评会加入回归用例，修正要求用于后续试聊和同名技能生成；备注不当作新事实。</p>' +
        `<p>最近记录 ${data.total} 条 ${Object.entries(data.labels).map(([label, n]) => badge(`${label} ${n}`)).join(' ')}</p>` +
        (data.recent.slice().reverse().map(f => `<section class="review-card">${badge(f.label, f.label !== '像本人')} <small>${esc(date(f.time))}</small>` +
          `<p>你：${esc(f.user)}</p><p>回复：${esc(f.reply)}</p>` + (f.note ? `<p><b>备注：</b>${esc(f.note)}</p>` : '') + '</section>').join('') || empty('还没有反馈，先去试聊几句。'));
    } else if (section === 'versions') {
      pane.innerHTML = '<h2>版本与回滚</h2><p>每次生成自动保存一份快照。回滚会先保存当前内容，并重建技能包；本地反馈继续保留。</p>' +
        (data.modified ? '<p>' + badge('当前文件有未保存的修改', true) + '</p><button class="review-button" id="version-save">保存修改并重新打包</button>' : '') +
        (data.versions.map(v => `<section class="review-card"><h3>${esc(date(v.created_at))}</h3>` +
          (v.version === data.version && !data.modified ? badge('当前版本') : '') +
          `<p>${esc(v.reason || '生成')} · ${Object.keys(v.files).length} 个文件 · ${esc(v.metadata?.audience || '')}</p>` +
          `<button class="review-button" data-diff="${esc(v.version)}">和当前比较</button> ` +
          `<button class="review-button" data-rollback="${esc(v.version)}">选择回滚</button></section>`).join('') || empty('这份旧技能尚无快照，下次生成会自动开始保存。')) +
        '<div id="version-detail" aria-live="polite"></div>';
    } else if (section === 'privacy') {
      const risk = {high: '高', medium: '中', low: '低'}[data.risk];
      pane.innerHTML = '<h2>发布前隐私检查</h2><p>扫描技能包内的文本、原记录和附录。确认表示你已检查并决定保留该内容，不会自动替换或删除它。</p>' +
        `<p>${badge(`风险：${risk}`, data.risk !== 'low')} ${data.unconfirmed} 条待确认 / ${data.items.length} 条发现</p>` +
        '<button class="review-button" data-refresh="privacy">重新扫描</button>' +
        (data.items.map(i => `<section class="review-card">${badge(i.severity === 'high' ? '高风险' : '需检查', !i.confirmed)} ` +
          `<small>${esc(i.file)}${i.line ? ` · 第 ${i.line} 行` : ''}</small><p>${esc(i.suggestion)}</p><blockquote>${esc(i.text)}</blockquote>` +
          (i.redacted && i.redacted !== i.text ? `<p>脱敏参考：${esc(i.redacted)}</p>` : '') +
          `<button class="review-button" data-privacy="${esc(i.id)}" data-confirmed="${i.confirmed}">${i.confirmed ? '已确认 · 撤销' : '已检查，确认保留'}</button></section>`).join('') ||
          empty('未命中自动检查规则；私密指代与上下文仍需你阅读判断。'));
    }
  }

  function renderEvaluation(data) {
    $('view-evaluation').innerHTML = '<h2>情境回归测评</h2><p>用真实输入检查新的回复；原聊天答案只作参考。静态检查会找空回复、客服话术和路由冲突，是否像本人需要你对照判断。</p>' +
      (data.stale ? '<p>' + badge('内容已变化，旧报告失效', true) + '</p>' : '') +
      `<p id="eval-progress" role="status">${data.total} 个用例 · 已检查 ${data.checked} 个 · 未命中问题 ${data.passed} 个</p>` +
      '<div class="review-actions"><button class="review-button" id="eval-static">检查填写的回复</button>' +
      '<button class="review-button" id="eval-model">调用模型运行全部用例</button></div>' +
      '<details class="review-card"><summary>模型测评接口（会发送用例和人设到所填接口）</summary><div class="review-config">' +
      `<label>接口地址<input id="eval-base" type="text" value="${esc($('f-baseurl').value)}"></label>` +
      `<label>模型<input id="eval-model-name" type="text" value="${esc($('f-model').value)}"></label>` +
      '<label>API Key<input id="eval-key" type="password" autocomplete="off" placeholder="仅用于本次请求；有本轮生成配置时可留空"></label></div></details>' +
      (data.results.map(c => `<section class="review-card eval-case" data-case="${esc(c.id)}"><h3>${esc(c.scenario)}</h3>` +
        (c.origin === 'feedback' ? badge('来自试聊差评', true) : '') +
        `<blockquote>输入：${esc(c.prompt)}</blockquote><p>期望接法：${esc(c.expected_move)}</p>` +
        (c.allowed_quotes?.length ? `<p class="review-muted">原聊天回复：${esc(c.allowed_quotes.join(' / '))}</p>` : '') +
        (c.note ? `<p>反馈备注：${esc(c.note)}</p>` : '') +
        `<label>待检查回复<textarea rows="3" data-reply="${esc(c.id)}" data-checked="${Boolean(c.checked)}" placeholder="填你试聊得到的回复">${esc(c.reply || '')}</textarea></label>` +
        `<p class="eval-result">${c.checked ? (c.passed ? '未命中静态问题，继续人工看语感' : esc(c.reasons.join('；'))) : '尚未运行'}</p></section>`).join('') || empty('这份技能未提供回归用例；重新生成，或在试聊中标注差评即可建立用例。'));
    $('eval-static').disabled = $('eval-model').disabled = evaluating || !data.total;
  }

  async function evaluate(live) {
    if (evaluating) return;
    const name = selected, turn = epoch, data = cache.evaluation;
    evaluating = true;
    $('eval-static').disabled = $('eval-model').disabled = true;
    const config = {base_url: $('eval-base').value.trim(), model: $('eval-model-name').value.trim(), api_key: $('eval-key').value.trim()};
    let failure = '';
    try {
      let report;
      if (!live) {
        const replies = {};
        document.querySelectorAll('[data-reply]').forEach(el => {
          if (el.value.trim() || el.dataset.checked === 'true') replies[el.dataset.reply] = el.value;
        });
        report = await post('evaluation', {replies, fingerprint: data.fingerprint}, name);
      } else {
        for (let i = 0; i < data.results.length; i++) {
          if (epoch !== turn) break;
          $('eval-progress').textContent = `模型测评：${i + 1} / ${data.total}，等待回复…`;
          const result = await post('evaluate-model', {case: data.results[i].id, fingerprint: data.fingerprint, ...config}, name);
          report = result.report;
          if (epoch !== turn) break;
          cache.evaluation = report;
          const textarea = Array.from(document.querySelectorAll('[data-reply]')).find(el => el.dataset.reply === result.case);
          if (textarea) textarea.value = result.reply;
        }
      }
      if (turn === epoch && report) cache.evaluation = report;
    } catch (err) {
      if (turn === epoch) {
        failure = err.message + '；已完成的用例已保存在本地。';
      }
    } finally {
      evaluating = false;
      if (turn === epoch) $('eval-static').disabled = $('eval-model').disabled = false;
    }
    if (turn === epoch) {
      if (!failure || cache.evaluation !== data) renderEvaluation(cache.evaluation);
      if (failure) $('eval-progress').textContent = failure;
    }
  }

  $('review-skill').addEventListener('change', () => select($('review-skill').value));
  $('review-refresh').addEventListener('click', async () => {
    try {
      const skills = await refreshList();
      if (selected) await select(selected);
      else if (skills.length) await select(skills[0].name);
    } catch (err) { $('review-status').textContent = err.message; }
  });
  document.querySelector('.views').addEventListener('click', async ev => {
    const button = ev.target.closest('button');
    if (!button) return;
    const turn = epoch;
    try {
      if (button.id === 'eval-static' || button.id === 'eval-model') return evaluate(button.id === 'eval-model');
      if (button.dataset.refresh) { delete cache[button.dataset.refresh]; return open(button.dataset.refresh); }
      if (button.dataset.privacy) {
        button.disabled = true;
        const report = await post('privacy', {item: button.dataset.privacy, confirmed: button.dataset.confirmed !== 'true', fingerprint: cache.privacy.fingerprint});
        if (turn === epoch) { cache.privacy = report; render('privacy', report); }
      }
      if (button.dataset.diff) {
        const report = await api(endpoint('diff') + '?version=' + encodeURIComponent(button.dataset.diff));
        if (turn !== epoch) return;
        $('version-detail').innerHTML = '<h3>历史版本 → 当前内容</h3>' +
          `<p>新增 ${report.added.length} 个 · 移除 ${report.removed.length} 个 · 修改 ${report.changed.length} 个</p>` +
          (report.added.length ? `<p>新增：${esc(report.added.join('、'))}</p>` : '') +
          (report.removed.length ? `<p>移除：${esc(report.removed.join('、'))}</p>` : '') +
          report.details.map(d => `<details class="review-card" open><summary>${esc(d.file)}</summary><pre class="review-diff">${esc(d.diff)}</pre>${d.truncated ? '<p>差异过长，已截取前 600 行。</p>' : ''}</details>`).join('');
      }
      if (button.dataset.rollback) {
        $('version-detail').innerHTML = '<div class="review-card"><p>将恢复这份历史版本，并保存当前内容。测评报告和隐私确认需要重新检查。</p>' +
          `<button class="review-button" data-restore="${esc(button.dataset.rollback)}">确认回滚</button></div>`;
      }
      if (button.dataset.restore || button.id === 'version-save') {
        button.disabled = true;
        await post(button.dataset.restore ? 'rollback' : 'snapshot', {version: button.dataset.restore});
        if (turn === epoch) await select(selected);
      }
    } catch (err) {
      if (turn === epoch) {
        $('review-status').textContent = err.message;
        const message = document.createElement('p');
        message.className = 'log-bad'; message.textContent = err.message;
        button.parentElement.appendChild(message);
        button.disabled = false;
      }
    }
  });
  window.addEventListener('message', ev => {
    if (ev.origin !== location.origin || ev.source !== $('playframe').contentWindow || ev.data?.type !== 'kith-feedback' || ev.data.skill !== selected) return;
    delete cache.feedback; delete cache.evaluation;
    if (['feedback', 'evaluation'].includes(active())) open(active());
  });
  sections.forEach(s => { $('view-' + s).innerHTML = empty('先生成技能，或在左侧选择已有技能。'); });
  refreshList().then(skills => { if (skills.length) select(skills[0].name); }).catch(err => { $('review-status').textContent = err.message; });
  return {select, open};
})();
