/* Local skill workbench. Raw feedback and review results stay outside the ZIP. */
window.Review = (() => {
  let selected = '';
  let epoch = 0;
  let packageData = null;
  let cache = {};
  let evaluating = false;
  let comparing = false, stopComparison = false, abSelected = '';
  let messageQuery = '', messagePage = 0, highlighted = [];
  let updatePreview = null, updateToken = '';
  let evaluationPool = 'regression';
  let abDraft = null;
  const sections = ['scenarios', 'evidence', 'messages', 'updates', 'ab', 'evaluation', 'feedback', 'versions', 'privacy', 'memory'];
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
    messageQuery = ''; messagePage = 0; highlighted = [];
    updatePreview = null; updateToken = ''; abSelected = '';
    evaluationPool = 'regression';
    abDraft = null;
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
      let data;
      if (section === 'evidence') {
        const [specificity, coverage, claims] = await Promise.all([api(endpoint('specificity')), api(endpoint('coverage')), api(endpoint('claims'))]);
        data = {specificity, coverage, claims};
      } else if (section === 'evaluation') {
        const [evaluation, holdout] = await Promise.all([api(endpoint('evaluation')), api(endpoint('holdout'))]);
        data = evaluation;
        cache.holdout = holdout;
      } else if (section === 'updates') {
        const [questions, incremental] = await Promise.all([api(endpoint('questions')), api(endpoint('incremental'))]);
        data = {questions, incremental};
      } else {
        data = await api(endpoint(section));
      }
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
          s.examples.map(e => `<blockquote>对方：${esc(e.incoming.join(' / '))}<br>本人：${esc(e.reply.join(' / '))}</blockquote>` +
            sourceButton([...(e.incoming_messages || []), ...(e.reply_messages || [])])).join('') +
          `<p class="review-muted">${esc(s.avoid.join('；'))}</p></section>`).join('') || empty('这份技能没有足够的场景证据；旧技能可重新生成以补齐。'));
    } else if (section === 'evidence') {
      renderEvidence(data);
    } else if (section === 'messages') {
      renderMessages(data);
    } else if (section === 'updates') {
      renderUpdates(data);
    } else if (section === 'ab') {
      renderAb(data);
    } else if (section === 'memory') {
      const ledger = (data.memories || []).map(m => `<details class="review-card"><summary>${badge(statusLabels[m.status] || '不确定', ['plan', 'promise', 'uncertain'].includes(m.status))} ${esc(m.text)}</summary>` +
        `<p>聊天提及日期：${esc(m.time_start || '未知')} ～ ${esc(m.time_end || '未知')}</p>` +
        `<p>${m.validity === 'needs_confirmation' ? '当前是否仍有效，需要重新确认。' : '历史观察，不代表当前状况。'}</p>` +
        m.evidence.map(e => `<blockquote>${esc(e.quote)}<br><small>${esc(e.time || '时间未知')}</small></blockquote>` + sourceButton([e.message])).join('') + '</details>').join('');
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

  function sourceButton(indices) {
    const ids = [...new Set(indices.filter(Number.isInteger))];
    return ids.length ? `<button class="review-button source-link" data-source="${ids.join(',')}">查看原话 · ${ids.map(n => '#' + n).join('、')}</button>` : '';
  }

  function renderEvidence(data) {
    const labels = {low: '低', medium: '中', high: '高'};
    const states = {covered: '已覆盖', evidence_insufficient: '证据不足', missing_response: '缺失接法'};
    const traits = data.specificity.traits || [], matrix = data.coverage.matrix || [];
    $('view-evidence').innerHTML = '<h2>证据质量</h2><p>具体性分数衡量目标人物的原话数量、会话覆盖和独特措辞。它不是性格准确率，点击出处可核对判断。</p><h3>人物特点的具体性</h3>' +
      (traits.map(t => `<section class="review-card"><h3>${esc(t.text)}</h3>` + badge(`${t.score} / 100`) +
        badge(`泛化风险：${labels[t.generalization_risk] || '未知'}`, t.generalization_risk !== 'low') +
        `<p>原话 ${t.quote_count} 条 · 会话 ${t.session_count} 段</p><p>独特词：${esc(t.unique_words.join('、') || '无')}</p>` +
        sourceButton(t.evidence.map(e => e.message)) + '</section>').join('') || empty('还没有可评分的人物特点；旧技能请重新生成。')) +
      renderClaims(data.claims) +
      '<h3>情境覆盖矩阵</h3><p>至少两段会话有可用接法才算已覆盖。出现过输入但没有可用接法，会标为缺失接法；未观察到或仅一次观察，保留为证据不足。</p>' +
      `<div class="coverage-grid">${matrix.map(r => `<section class="review-card"><h3>${esc(r.label)}</h3>` +
        badge(states[r.status], r.status !== 'covered') + `<p>输入 ${r.observed_inputs} 条 · 会话 ${r.sessions} 段 · 示例 ${r.examples} 个</p>` +
        `<p>${esc(r.response_move || '待补充真实接法')}</p>` + sourceButton(r.message_indices) + '</section>').join('')}</div>` +
      (!matrix.length ? empty('旧技能未附覆盖矩阵，请重新生成。') : '');
  }

  function renderClaims(data) {
    const labels = {kept: '已保留', rewritten: '已改写', rejected: '已否定', pending: '待审阅'};
    return '<h3>人物结论审阅</h3><p>逐条核对支持原话与候选反例。决定立即约束本地试聊，重新生成时应用到人设；人工修订会明确标记来源。决定跨重生成保留。</p>' +
      (data?.cards || []).map(card => `<section class="review-card" data-claim-card="${esc(card.id)}"><h3>${esc(card.text)}</h3>` +
        badge(labels[card.decision.status] || '待审阅') +
        '<p>支持原话：</p>' + card.evidence.map(e => `<blockquote>${esc(e.quote)}</blockquote>`).join('') + sourceButton(card.evidence.map(e => e.message)) +
        '<p>候选反例（仅有共用词和否定信号，须人工核对）：</p>' +
        (card.counter_candidates.map(e => `<blockquote>${esc(e.quote)}</blockquote>`).join('') || '<p>未找到候选反例。</p>') + sourceButton(card.counter_candidates.map(e => e.message)) +
        `<label>适用范围<input data-claim-scope value="${esc(card.decision.scope || '')}" placeholder="例如：熟人之间的玩笑；认真难过时不用"></label>` +
        `<label>修订后的结论<textarea data-claim-replacement rows="2">${esc(card.decision.replacement || '')}</textarea></label>` +
        '<div class="review-actions">' + Object.entries({kept: '保留', rewritten: '改写', rejected: '否定', pending: '撤销决定'}).map(([status, label]) =>
          `<button class="review-button" data-claim="${esc(card.id)}" data-claim-status="${status}">${label}</button>`).join('') + '</div></section>').join('');
  }

  function renderMessages(data) {
    $('view-messages').innerHTML = '<h2>逐条原话索引</h2><p>消息保留时间、说话人、会话和稳定编号。当前技能的脱敏设置同样适用于这里。</p>' +
      (data.complete === false ? '<p>' + badge('包内只保留被引用的消息', true) + '</p>' : '') +
      '<label>搜索文字、日期、说话人或消息编号<input id="message-search" type="search" autocomplete="off"></label>' +
      '<div id="message-toolbar" class="review-actions"></div><div id="message-results"></div>';
    $('message-search').value = messageQuery;
    showMessages();
  }

  function showMessages() {
    const all = cache.messages?.messages || [], chosen = new Set(highlighted);
    const related = new Set(highlighted.flatMap(i => [i - 1, i, i + 1]));
    const query = messageQuery.trim().toLowerCase();
    const rows = all.filter(m => (!highlighted.length || related.has(m.index)) &&
      (!query || `${m.index} ${m.time || ''} ${m.speaker} ${m.text}`.toLowerCase().includes(query)));
    const pages = Math.max(1, Math.ceil(rows.length / 100));
    messagePage = Math.min(messagePage, pages - 1);
    $('message-toolbar').innerHTML = `<span>${rows.length} 条 · 第 ${messagePage + 1} / ${pages} 页</span>` +
      (highlighted.length ? '<button class="review-button" id="message-all">显示全部原话</button>' : '') +
      `<button class="review-button" data-message-page="-1" ${messagePage === 0 ? 'disabled' : ''}>上一页</button>` +
      `<button class="review-button" data-message-page="1" ${messagePage + 1 >= pages ? 'disabled' : ''}>下一页</button>`;
    $('message-results').innerHTML = rows.slice(messagePage * 100, (messagePage + 1) * 100).map(m =>
      `<section class="review-card message-row${chosen.has(m.index) ? ' message-row--selected' : ''}" id="message-${m.index}" tabindex="-1">` +
      `<h3>#${m.index} · ${esc(m.speaker)}</h3><small>${esc(m.time || '时间未知')} · 会话 ${m.session}</small><p>${esc(m.text)}</p>` +
      (m.reply_to ? '<p>引用对象：</p>' + sourceButton(all.filter(row => row.source_id === m.reply_to).map(row => row.index)) : '') +
      (m.speaker === cache.messages.target ? `<details><summary>关联或修正引用对象</summary><label>对话方原消息编号<input type="number" min="1" max="${m.index - 1}" data-quote-source="${m.index}"></label>` +
        `<button class="review-button" data-link-reply="${m.index}">保存关联并更新情境</button></details>` : '') + '</section>').join('') || empty('没有匹配的原话。');
  }

  async function jumpToMessages(value) {
    const turn = epoch;
    highlighted = value.split(',').map(Number).filter(Number.isInteger);
    messageQuery = ''; messagePage = 0;
    switchTab('messages');
    await open('messages');
    if (turn !== epoch) return;
    const row = $('message-' + highlighted[0]);
    row?.scrollIntoView({block: 'center'}); row?.focus({preventScroll: true});
  }

  function renderUpdates(data) {
    const types = {trait: '人物特点', scenario: '情境', memory: '记忆', conflict: '冲突记忆'};
    const statuses = {pending: '待确认', confirmed: '已确认', rejected: '已否定'};
    const q = data.questions, inc = data.incremental;
    $('view-updates').innerHTML = '<h2>主动补标与增量更新</h2><p>证据薄弱的观察先提问。你的补标会影响本地试聊，保持为人工标注；不会冒充聊天原话或进入 ZIP。内容变化后需要重新确认。</p>' +
      (q.stale ? '<p>' + badge('内容已变化，旧补标需要重新确认', true) + '</p>' : '') +
      `<h3>待补标 ${q.pending} 个</h3>` + (q.questions.map(item => `<section class="review-card question-card" data-question-card="${esc(item.id)}">` +
        badge(types[item.type] || item.type) + badge(statuses[item.status], item.status === 'pending') + `<p>${esc(item.question)}</p>` +
        `<label>适用范围或当前情况<textarea rows="2" data-answer="${esc(item.id)}" placeholder="确认时请填写范围或当前情况">${esc(item.answer || '')}</textarea></label>` +
        `<div class="review-actions">${['confirmed', 'rejected', 'pending'].map(status => `<button class="review-button" data-question="${esc(item.id)}" data-answer-status="${status}">${statuses[status]}</button>`).join('')}</div></section>`).join('') || empty('没有待补标问题；旧技能请重新生成以补齐。')) +
      '<h3>加入新聊天</h3><p>先预览去重结果和潜在冲突，再合并新增观察。合并前保留历史版本；冲突记忆保持待确认。</p>' +
      (!inc.available ? empty(inc.error || '旧技能需要重新生成增量基线。') :
        `<section class="review-card" id="incremental-form"><p>主人物：${esc(inc.target)} · 对话方：${esc(inc.counterpart)}</p>` +
        '<label>选择完整记录或新增记录<input type="file" id="incremental-file"></label><p id="incremental-file-status" role="status"></p>' +
        '<details><summary>也可填写消息数组</summary><label>JSON 消息数组<textarea id="incremental-json" rows="5" spellcheck="false" placeholder="[{&quot;time&quot;:&quot;2026-10-06T12:00:00&quot;,&quot;speaker&quot;:&quot;人物昵称&quot;,&quot;text&quot;:&quot;原话&quot;}]">[]</textarea></label></details>' +
        '<label class="check"><input type="checkbox" id="incremental-llm"><span>使用模型分析新增内容</span></label>' +
        '<details><summary>增量模型接口（勾选后会发送新增聊天）</summary><div class="review-config">' +
        `<label>接口地址<input id="incremental-base" value="${esc($('f-baseurl').value)}"></label>` +
        `<label>模型<input id="incremental-model" value="${esc($('f-model').value)}"></label>` +
        '<label>API Key<input type="password" id="incremental-key" autocomplete="off"></label></div></details>' +
        '<div class="review-actions"><button class="review-button" id="incremental-preview">预览新增与冲突</button><button class="review-button" id="incremental-apply" disabled>合并预览中的新增记录</button></div>' +
        '<div id="incremental-result" role="status"></div></section>') +
      (inc.last_report?.applied ? `<p>上次合并 ${inc.last_report.added_count} 条 · 跳过重复 ${inc.last_report.duplicate_count} 条 · 潜在冲突 ${inc.last_report.conflicts.length} 个</p>` : '');
    updatePreview = null; updateToken = '';
  }

  function renderAb(data) {
    const runs = data.runs || [];
    const run = runs.find(r => r.id === abSelected) || runs[0];
    if (run) abSelected = run.id;
    const configs = run?.blind && !run.revealed && abDraft ? abDraft : run?.configs;
    $('view-ab').innerHTML = '<h2>模型与配方 A/B 对比</h2><p>两侧使用同一份人设和同一组回归用例。比较静态问题、耗时和语感，最后逐条选你更认可的回复。配置与结果留在本地，Key 只用于当前请求。</p>' +
      '<div class="ab-grid">' + ['a', 'b'].map(side => `<section class="review-card"><h3>${side.toUpperCase()} 配置</h3>` +
        `<label>接口地址<input id="ab-base-${side}" value="${esc(configs?.[side].base_url || $('f-baseurl').value)}"></label>` +
        `<label>模型<input id="ab-model-${side}" value="${esc(configs?.[side].model || $('f-model').value)}"></label>` +
        `<label>温度<input id="ab-temperature-${side}" type="number" min="0" max="2" step="0.1" value="${configs?.[side].temperature ?? .7}"></label>` +
        `<label>配方（附加回复指令）<textarea id="ab-recipe-${side}" rows="3">${esc(configs?.[side].recipe || '')}</textarea></label>` +
        `<label>API Key<input id="ab-key-${side}" type="password" autocomplete="off"></label></section>`).join('') + '</div>' +
      '<label class="check"><input id="ab-blind" type="checkbox"' + (run?.blind ? ' checked' : '') + '>盲评：每个用例随机左右排序，选择后揭晓模型</label>' +
      '<label>用例来源<select id="ab-pool"><option value="regression">生成示范回归</option><option value="holdout">留出会话</option></select></label>' +
      `<label>固定追问（每行一条，最多五条；各侧使用自己的回复历史）<textarea id="ab-followups" rows="3">${esc((run?.followups || []).join('\n'))}</textarea></label>` +
      `<div class="review-actions"><button class="review-button" id="ab-start" ${comparing ? 'disabled' : ''}>保存配置并新建对比</button>` +
      `<button class="review-button" id="ab-run" ${comparing || !run || run.stale ? 'disabled' : ''}>运行未完成的用例</button>` +
      `<button class="review-button" id="ab-stop" ${!comparing ? 'disabled' : ''}>完成当前调用后停止</button></div>` +
      '<p>先保存两侧配置，再填写本次运行的 Key；运行使用已保存的配置。</p><p id="ab-progress" role="status"></p>' +
      `<label>历史对比<select id="ab-history" ${comparing ? 'disabled' : ''}><option value="">选择对比</option>` + runs.map(r => `<option value="${esc(r.id)}" ${run?.id === r.id ? 'selected' : ''}>${esc(date(r.created_at))} · ${esc(r.configs.a.model)} / ${esc(r.configs.b.model)}</option>`).join('') + '</select></label>' +
      '<div id="ab-results"></div>';
    if (run) renderAbResults(run);
    else $('ab-results').innerHTML = empty('尚无对比，请先保存两侧配置。');
  }

  function renderAbResults(run) {
    const labels = {a: run.blind ? '位置 A' : 'A', b: run.blind ? '位置 B' : 'B', tie: '相当', neither: '都不合适'};
    const tally = Object.fromEntries(Object.keys(labels).map(key => [key, Object.values(run.choices).filter(c => c === key).length]));
    const results = Object.values(run.results).flatMap(pair => Object.entries(pair).map(([side, result]) => ({side, ...result})));
    $('ab-progress').textContent = `已完成 ${run.completed} / ${run.total * 2} 次回复`;
    $('ab-results').innerHTML = (run.stale ? '<p>' + badge('人设已变化，此对比失效；请新建对比', true) + '</p>' : '') +
      `<p>${Object.entries(tally).map(([key, count]) => badge(`${labels[key]} ${count}`)).join(' ')}</p>` +
      (run.revealed ? '<p>揭晓后的模型统计：' + Object.values(run.summary || {}).map(s => `${esc(s.model)}：选择 ${s.wins} 次 · 未命中静态问题 ${s.passed} 次 · ${s.seconds} 秒`).join('；') + '</p>' : '') +
      '<p>' + ['a', 'b'].map(side => {
        const rows = results.filter(r => r.side === side);
        return `${run.blind ? '位置 ' : ''}${side.toUpperCase()}：${rows.filter(r => r.passed).length} / ${rows.length} 未命中静态问题，累计 ${rows.reduce((n, r) => n + (r.seconds || 0), 0).toFixed(1)} 秒`;
      }).join('；') + '</p>' + run.cases.map(c => {
        const pair = run.results[c.id] || {};
        return `<section class="review-card ab-case"><h3>${esc(c.scenario)}</h3><blockquote>输入：${esc(c.prompt)}</blockquote><p>期望接法：${esc(c.expected_move)}</p>` +
          `<div class="ab-grid">${['a', 'b'].map(side => `<div><h4>${side.toUpperCase()} · ${esc(run.revealed_models?.[c.id]?.[side] || run.configs[side].model)}</h4><p class="ab-reply">${esc(pair[side]?.reply || '尚未运行')}</p>` +
            (pair[side]?.turns?.length > 1 ? '<details><summary>查看连续追问</summary>' + pair[side].turns.slice(1).map((t, i) => `<blockquote>${esc(t.prompt)}</blockquote><p>${esc(t.reply)}</p><small>${esc(pair[side].turn_checks?.[i + 1]?.reasons.join('；') || '未命中静态问题，需人工检查一致性')}</small>`).join('') + '</details>' : '') +
            (pair[side] ? `<small>${pair[side].seconds} 秒 · ${esc(pair[side].passed ? '未命中静态问题' : pair[side].reasons.join('；'))}</small>` : '') + '</div>').join('')}</div>` +
          `<div class="review-actions">${Object.keys(labels).map(choice => `<button class="review-button${run.choices[c.id] === choice ? ' is-chosen' : ''}" data-ab-case="${esc(c.id)}" data-ab-choice="${choice}" ${run.stale || !pair.a || !pair.b || comparing ? 'disabled' : ''}>${labels[choice]}</button>`).join('')}</div></section>`;
      }).join('');
  }

  function keepAbRun(run) {
    cache.ab.runs = [run, ...cache.ab.runs.filter(r => r.id !== run.id)];
    abSelected = run.id;
  }

  async function compare() {
    if (comparing) return;
    const run = cache.ab.runs.find(r => r.id === abSelected);
    if (!run || run.stale) return;
    const keys = {a: $('ab-key-a').value.trim(), b: $('ab-key-b').value.trim()};
    if (!keys.a || !keys.b) throw new Error('请填写两侧的 API Key。运行使用这份对比保存的配置；修改配置请新建对比。');
    const turn = epoch, name = selected;
    comparing = true; stopComparison = false;
    $('ab-start').disabled = $('ab-run').disabled = true; $('ab-stop').disabled = false;
    $('ab-history').disabled = true;
    let failure = '', latest = run;
    try {
      for (const c of run.cases) {
        for (const side of ['a', 'b']) {
          if (turn !== epoch || stopComparison) break;
          if (latest.results[c.id]?.[side]) continue;
          $('ab-progress').textContent = `${side.toUpperCase()} 正在回复：${c.scenario} · 已完成 ${latest.completed} 次`;
          latest = await post('ab', {mode: 'run', run: run.id, case: c.id, side, api_key: keys[side], api_key_a: keys.a, api_key_b: keys.b}, name);
          if (turn !== epoch) break;
          keepAbRun(latest); renderAbResults(latest);
        }
        if (turn !== epoch || stopComparison) break;
      }
    } catch (err) { failure = err.message + '；已完成的结果已保存，可继续运行。'; }
    finally {
      comparing = false;
      if (turn === epoch) {
        renderAbResults(latest);
        $('ab-start').disabled = false; $('ab-run').disabled = latest.stale; $('ab-stop').disabled = true;
        $('ab-history').disabled = false;
        $('ab-key-a').value = $('ab-key-b').value = '';
        if (failure) $('ab-progress').textContent = failure;
      }
    }
  }

  function renderEvaluation(data) {
    const held = cache.holdout || {enabled: false};
    if (evaluationPool === 'holdout') data = held;
    $('view-evaluation').innerHTML = '<h2>情境回归测评</h2><p>用真实输入检查新的回复；原聊天答案只作参考。静态检查会找空回复、客服话术和路由冲突，是否像本人需要你对照判断。</p>' +
      '<label>用例来源<select id="eval-pool"><option value="regression"' + (evaluationPool === 'regression' ? ' selected' : '') + '>生成示范回归</option><option value="holdout"' + (evaluationPool === 'holdout' ? ' selected' : '') + '>留出会话（未参与生成）</option></select></label>' +
      (evaluationPool === 'holdout' ? (held.enabled ? `<p>训练 ${held.train_sessions} 段 · 留出 ${held.test_sessions} 段 · 测试集 ${esc(held.test_id)}；答案仅供对照，不发送给生成模型。</p>` : '<p>请在生成配置中勾选「留出测评」，用完整原记录重新生成。</p>') : '') +
      (data.stale ? '<p>' + badge('内容已变化，旧报告失效', true) + '</p>' : '') +
      `<p id="eval-progress" role="status">${data.total} 个用例 · 已检查 ${data.checked} 个 · 未命中静态问题 ${data.passed} 个</p>` +
      ((data.excluded_cases || []).length ? '<section class="review-card">' +
        `<h3>已排除 ${data.excluded_cases.length} 个证据不足的旧用例</h3><p>这些用例不计入结果，也不发送给模型。重新生成技能可更新情境与接话证据。</p>` +
        data.excluded_cases.map(c => `<p>${esc(c.scenario)}：${esc(c.reason)}</p>`).join('') + '</section>' : '') +
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
        sourceButton([...(c.incoming_messages || []), ...(c.reply_messages || [])]) +
        (c.note ? `<p>反馈备注：${esc(c.note)}</p>` : '') +
        `<label>待检查回复<textarea rows="3" data-reply="${esc(c.id)}" data-checked="${Boolean(c.checked)}" placeholder="填你试聊得到的回复">${esc(c.reply || '')}</textarea></label>` +
        `<p class="eval-result">${c.checked ? (c.passed ? '未命中静态问题，继续人工看语感' : esc(c.reasons.join('；'))) : '尚未运行'}</p></section>`).join('') || empty('这份技能未提供回归用例；重新生成，或在试聊中标注差评即可建立用例。'));
    $('eval-static').disabled = $('eval-model').disabled = evaluating || !data.total || (evaluationPool === 'holdout' && held.stale);
    $('eval-pool').disabled = evaluating;
  }

  async function evaluate(live) {
    if (evaluating) return;
    const name = selected, turn = epoch, held = evaluationPool === 'holdout', data = held ? cache.holdout : cache.evaluation;
    evaluating = true;
    $('eval-static').disabled = $('eval-model').disabled = true;
    $('eval-pool').disabled = true;
    const config = {base_url: $('eval-base').value.trim(), model: $('eval-model-name').value.trim(), api_key: $('eval-key').value.trim()};
    let failure = '';
    try {
      let report;
      if (!live) {
        const replies = {};
        document.querySelectorAll('[data-reply]').forEach(el => {
          if (el.value.trim() || el.dataset.checked === 'true') replies[el.dataset.reply] = el.value;
        });
        report = await post(held ? 'holdout' : 'evaluation', {replies, fingerprint: data.fingerprint}, name);
      } else {
        for (let i = 0; i < data.results.length; i++) {
          if (epoch !== turn) break;
          $('eval-progress').textContent = `模型测评：${i + 1} / ${data.total}，等待回复…`;
          const result = await post(held ? 'holdout-model' : 'evaluate-model', {case: data.results[i].id, fingerprint: data.fingerprint, ...config}, name);
          report = result.report;
          if (epoch !== turn) break;
          cache[held ? 'holdout' : 'evaluation'] = report;
          const textarea = Array.from(document.querySelectorAll('[data-reply]')).find(el => el.dataset.reply === result.case);
          if (textarea) textarea.value = result.reply;
        }
      }
      if (turn === epoch && report) cache[held ? 'holdout' : 'evaluation'] = report;
    } catch (err) {
      if (turn === epoch) {
        failure = err.message + '；已完成的用例已保存在本地。';
      }
    } finally {
      evaluating = false;
      if (turn === epoch) $('eval-static').disabled = $('eval-model').disabled = false;
      if (turn === epoch) $('eval-pool').disabled = false;
    }
    if (turn === epoch) {
      if (!failure || cache[held ? 'holdout' : 'evaluation'] !== data) renderEvaluation(cache.evaluation);
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
      if (button.dataset.claim) {
        const card = button.closest('[data-claim-card]');
        const result = await post('claims', {claim: button.dataset.claim, status: button.dataset.claimStatus,
          scope: card.querySelector('[data-claim-scope]').value, replacement: card.querySelector('[data-claim-replacement]').value,
          fingerprint: cache.evidence.claims.fingerprint});
        if (turn === epoch) { cache.evidence.claims = result; renderEvidence(cache.evidence); }
        return;
      }
      if (button.dataset.linkReply) {
        await post('quote-link', {reply: Number(button.dataset.linkReply),
          source: Number(document.querySelector(`[data-quote-source="${button.dataset.linkReply}"]`).value),
          fingerprint: cache.messages.fingerprint});
        if (turn === epoch) await select(selected);
        return;
      }
      if (button.dataset.source) { await jumpToMessages(button.dataset.source); return; }
      if (button.dataset.messagePage) {
        messagePage = Math.max(0, messagePage + Number(button.dataset.messagePage));
        showMessages();
        return;
      }
      if (button.id === 'message-all') {
        highlighted = []; messagePage = 0; showMessages(); return;
      }
      if (button.dataset.question) {
        button.disabled = true;
        const card = button.closest('[data-question-card]');
        const answer = card?.querySelector(`[data-answer="${CSS.escape(button.dataset.question)}"]`)?.value || '';
        const report = await post('questions', {question: button.dataset.question, status: button.dataset.answerStatus,
          answer, fingerprint: cache.updates?.questions?.fingerprint}, selected);
        if (turn === epoch) { cache.updates.questions = report; renderUpdates(cache.updates); }
        return;
      }
      if (button.id === 'incremental-preview' || button.id === 'incremental-apply') {
        button.disabled = true;
        const inc = cache.updates.incremental;
        let messages = [];
        const raw = $('incremental-json')?.value.trim();
        if (raw && raw !== '[]') {
          messages = JSON.parse(raw);
          if (!Array.isArray(messages)) throw new Error('消息 JSON 必须是数组');
        }
        const payload = {mode: button.id === 'incremental-apply' ? 'apply' : 'preview', messages,
          fingerprint: inc.fingerprint, use_llm: Boolean($('incremental-llm')?.checked),
          base_url: $('incremental-base')?.value.trim(), model: $('incremental-model')?.value.trim(),
          api_key: $('incremental-key')?.value.trim()};
        if (updateToken) payload.token = updateToken;
        if (button.id === 'incremental-apply' && !updatePreview) throw new Error('请先预览新增记录');
        const report = await post('incremental', payload);
        if (turn !== epoch) return;
        if (button.id === 'incremental-preview') {
          updatePreview = report; $('incremental-apply').disabled = !report.added_count;
          $('incremental-result').innerHTML = `<p>新增 ${report.added_count} 条 · 重复 ${report.duplicate_count} 条 · 潜在冲突 ${report.conflicts.length} 个</p>` +
            (report.conflicts.map(c => `<blockquote>${esc(c.memory)} ↔ ${esc(c.quote)}（待确认）</blockquote>`).join('') || '') +
            (report.requires_review ? '<p>' + badge('发现潜在冲突，合并后标记为待确认', true) + '</p>' : '<p>预览通过，可以合并。</p>');
        } else {
          cache = {}; packageData = null; await select(selected);
        }
        button.disabled = false;
        return;
      }
      if (button.id === 'ab-start') {
        const config = side => ({model: $('ab-model-' + side).value.trim(), base_url: $('ab-base-' + side).value.trim(),
          temperature: Number($('ab-temperature-' + side).value), recipe: $('ab-recipe-' + side).value});
        const draft = {a: config('a'), b: config('b')};
        const run = await post('ab', {mode: 'start', fingerprint: cache.ab.fingerprint, ...draft,
          blind: $('ab-blind').checked, pool: $('ab-pool').value,
          followups: $('ab-followups').value.split('\n').map(s => s.trim()).filter(Boolean)});
        if (turn !== epoch) return;
        abDraft = draft;
        cache.ab.runs = [run, ...(cache.ab.runs || []).filter(r => r.id !== run.id)]; abSelected = run.id; renderAb(cache.ab); return;
      }
      if (button.id === 'ab-run') { await compare(); return; }
      if (button.id === 'ab-stop') { stopComparison = true; $('ab-progress').textContent = '将在当前回复完成后停止。'; return; }
      if (button.dataset.abChoice) {
        const report = await post('ab', {mode: 'choose', run: abSelected, case: button.dataset.abCase, choice: button.dataset.abChoice});
        if (turn !== epoch) return;
        keepAbRun(report); renderAb(cache.ab); return;
      }
      if (button.id === 'ab-history') return;
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
  document.querySelector('.views').addEventListener('input', ev => {
    if (ev.target.id === 'message-search') { messageQuery = ev.target.value; messagePage = 0; showMessages(); }
    if (ev.target.closest('#incremental-form')) {
      updatePreview = null;
      if ($('incremental-apply')) $('incremental-apply').disabled = true;
      if (ev.target.id === 'incremental-json') {
        updateToken = ''; $('incremental-file').value = ''; $('incremental-file-status').textContent = '';
      }
    }
  });
  document.querySelector('.views').addEventListener('change', async ev => {
    if (ev.target.id === 'eval-pool' && !evaluating) { evaluationPool = ev.target.value; renderEvaluation(cache.evaluation); }
    if (ev.target.id === 'ab-history' && !comparing) { abSelected = ev.target.value; renderAb(cache.ab); }
    if (ev.target.id !== 'incremental-file' || !ev.target.files?.[0]) return;
    const file = ev.target.files[0];
    const turn = epoch;
    const status = $('incremental-file-status');
    status.textContent = '正在解析增量文件…';
    try {
      const response = await api(`/api/parse?name=${encodeURIComponent(file.name)}`, {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: await file.arrayBuffer()});
      if (turn !== epoch) return;
      if (response.error) throw new Error(response.error);
      updateToken = response.token;
      $('incremental-json').value = '[]';
      status.textContent = `已读取 ${response.total} 条消息；点击预览去重结果。`;
    } catch (err) { if (turn === epoch) { status.textContent = err.message; updateToken = ''; } }
  });
  window.addEventListener('message', ev => {
    if (ev.origin !== location.origin || ev.source !== $('playframe').contentWindow || ev.data?.type !== 'kith-feedback' || ev.data.skill !== selected) return;
    delete cache.feedback; delete cache.evaluation; delete cache.evidence; delete cache.updates; delete cache.ab;
    if (['feedback', 'evaluation', 'evidence', 'updates', 'ab'].includes(active())) open(active());
  });
  sections.forEach(s => { $('view-' + s).innerHTML = empty('先生成技能，或在左侧选择已有技能。'); });
  refreshList().then(skills => { if (skills.length) select(skills[0].name); }).catch(err => { $('review-status').textContent = err.message; });
  return {select, open};
})();
