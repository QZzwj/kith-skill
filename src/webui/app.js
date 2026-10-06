/* kith-skill 工作台 —— 前端逻辑
   没有框架、没有构建步骤：一个文件搞定上传、诊断、执行、预览。 */

const $ = (id) => document.getElementById(id);

const state = { token: null, info: null, jobId: null, timer: null, findings: 0 };

/* ───────────────────────── 工具 ───────────────────────── */

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

const humanSize = (n) =>
  n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + " MB"
  : n > 1024 ? (n / 1024).toFixed(1) + " KB"
  : n + " B";

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `请求失败（${res.status}）`);
  return data;
}

function setState(text, cls) {
  $("state-text").textContent = text;
  $("chip-state").className = "state" + (cls ? " is-" + cls : "");
}

/* 从日志里回读关系类型，填进顶栏 */
const RELATION_LINE = /关系类型：(\S+?)（/;
function syncRelation(log) {
  const found = log.match(RELATION_LINE);
  if (found) $("chip-relation").textContent = found[1];
}

/* ───────────────────────── 投放与解析 ───────────────────────── */

const dropzone = $("dropzone");
const fileInput = $("file");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("is-over"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-over"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("is-over");
  if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) upload(fileInput.files[0]);
});

async function upload(file) {
  $("parse-error").hidden = true;
  setState("解析中…", "running");
  $("run").disabled = true;
  $("diagnosis").hidden = true;

  try {
    const info = await api(`/api/parse?name=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file,
    });
    state.token = info.token;
    state.info = info;
    renderDiagnosis(info);

    if (info.error || !info.total) {
      showError(info.error || "没有解析出任何消息。若是纯文本，请写成「昵称: 内容」每行一条。");
      setState("解析失败", "failed");
      return;
    }
    $("run").disabled = false;
    setState("就绪", "done");
    $("chip-file").textContent = file.name;
    $("chip-count").textContent = info.total;
    $("chip-relation").textContent = "—";
  } catch (err) {
    showError(err.message);
    setState("解析失败", "failed");
  }
}

function showError(message) {
  const box = $("parse-error");
  box.textContent = message;
  box.hidden = false;
}

function renderDiagnosis(info) {
  $("diagnosis").hidden = false;
  $("diag-parser").textContent = info.parser || "未识别";
  $("diag-total").textContent = `${info.total} 条 · ${humanSize(info.size)}`;
  $("diag-range").textContent = info.first ? `${info.first} → ${info.last}` : "无时间戳";
  $("diag-enc").textContent = (info.encodings || []).join(" / ") || "—";

  /* 两个字段都是「可选 + 可填」：input + datalist 管取值，右侧 ▾ 负责把候选摊开。
     中间两种做法各有毛病，这里分别治：
       ① 纯 <select>：记录里没出现的名字填不进去。而微信这类记录里，
          会话名（备注）和说话人昵称常常不是同一个词，本人也可能不带「我」
          这个字 —— 必须允许手填；
       ② 裸 <input list>：预填的 value 会让 Chrome 按前缀把候选过滤光
          （"选择不了"就是这么来的），而不弹出时又和普通输入框没区别，
          没人知道这里能选。所以输入框默认留空（空=后端默认值），
          箭头交给 .combo__pick 显式提供。 */
  const meInput = $("f-me");
  const targetInput = $("f-target");
  const speakers = $("diag-speakers");
  speakers.innerHTML = "";

  /* 重新上传文件时别丢掉已经填过的值 */
  const keepMe = meInput.value;
  const keepTarget = targetInput.value;

  const meList = $("sp-me");
  const targetList = $("sp-target");
  meList.innerHTML = "";
  targetList.innerHTML = "";

  (info.speakers || []).forEach((sp) => {
    // datalist 里 value 是填进去的值，label 才是给人看的那行
    const opt = `<option value="${esc(sp.name)}" label="${esc(sp.name)}（${sp.count} 条）"></option>`;
    meList.insertAdjacentHTML("beforeend", opt);
    targetList.insertAdjacentHTML("beforeend", opt);
    speakers.insertAdjacentHTML("beforeend",
      `<button class="speaker" type="button" data-name="${esc(sp.name)}"` +
      ` title="点击 → 蒸馏谁｜Alt+点击 → 我是谁">` +
      `<b>${esc(sp.name)}</b> <span>${sp.count}</span></button>`);
  });

  if (keepMe) meInput.value = keepMe;
  if (keepTarget) targetInput.value = keepTarget;

  /* ▾：Chrome 99+ 能 showPicker() 直接摊开候选；不支持的浏览器退回聚焦输入框 */
  document.querySelectorAll(".combo__pick").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = $(btn.dataset.pick);
      input.focus();
      try { input.showPicker?.(); } catch { /* 老浏览器忽略 */ }
    });
  });

  /* chip 作为快捷方式：点击填「蒸馏谁」，Alt+点击填「我是谁」 */
  speakers.querySelectorAll(".speaker").forEach((el) => {
    el.addEventListener("click", (ev) => {
      (ev.altKey ? meInput : targetInput).value = el.dataset.name;
    });
  });

  const max = Math.max(1, ...(info.candidates || []).map((c) => c.count));
  const bars = $("diag-bars");
  bars.innerHTML = "";
  [...(info.candidates || [])].sort((a, b) => b.count - a.count).forEach((c) => {
    const hit = c.count > 0;
    bars.insertAdjacentHTML("beforeend",
      `<div class="bar ${hit ? "bar--hit" : ""} ${c.used ? "bar--used" : ""}">` +
      `<span class="bar__name"><span>${esc(c.parser)}` +
      `${c.used ? '<em class="bar__used">实际采用</em>' : ""}</span>` +
      `<span class="bar__track"><span class="bar__fill" style="width:${(c.count / max) * 100}%"></span></span></span>` +
      `<span class="bar__n">${c.count || "—"}</span></div>`);
  });
}

/* ───────────────────────── 执行与轮询 ───────────────────────── */

$("run").addEventListener("click", async () => {
  if (!state.token) return;
  const offline = document.querySelector('input[name="mode"]:checked').value === "offline";

  $("run").disabled = true;
  $("artifact").hidden = true;
  $("log").innerHTML = "";
  $("placeholder").hidden = true;
  setState("运行中", "running");
  // 新一轮开始：把试聊收回空态，否则会对着上一轮的人设说话
  resetPlayTab();
  switchTab("log");

  const payload = {
    token: state.token,
    name: $("f-name").value.trim() || "persona",
    me: $("f-me").value.trim(),
    target: $("f-target").value.trim(),
    desc: $("f-desc").value.trim(),
    relation: $("f-relation").value,
    no_llm: offline,
    strict: $("f-strict").checked,
    no_verify: $("f-noverify").checked,
    both: $("f-both").checked,
    // 公开使用必须有两份画像（主技能扮演你、背景放对方），所以勾了它就把双方打开
    audience: $("f-public").checked ? "公开" : "本人",
  };
  if (!offline) {
    payload.base_url = $("f-baseurl").value.trim();
    payload.model = $("f-model").value.trim();
    payload.api_key = $("f-apikey").value.trim();
  }

  try {
    const { job } = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.jobId = job;
    poll();
  } catch (err) {
    $("log").innerHTML = `<span class="log-bad">${esc(err.message)}</span>`;
    setState("启动失败", "failed");
    $("run").disabled = false;
  }
});

async function poll() {
  clearTimeout(state.timer);
  let snapshot;
  try {
    snapshot = await api(`/api/job/${state.jobId}`);
  } catch {
    state.timer = setTimeout(poll, 1200);
    return;
  }

  // 渲染这段单独兜住异常：它一旦抛出来，轮询就断了，
  // 界面会永远停在"运行中"——标签也就一直是灰的，看起来就是"点不动"。
  try {
    const view = $("view-log");
    const stick = view.scrollHeight - view.scrollTop - view.clientHeight < 48;
    const hasLog = Boolean(snapshot.log.trim());
    $("placeholder").hidden = hasLog;
    $("log").innerHTML = hasLog ? renderLog(snapshot.log) : "";
    syncRelation(snapshot.log);
    if (stick) view.scrollTop = view.scrollHeight;
  } catch (err) {
    showPaneError(err);
  }

  if (snapshot.state === "queued" || snapshot.state === "running") {
    state.timer = setTimeout(poll, 500);
    return;
  }

  $("run").disabled = false;
  await finish(snapshot);
}

async function finish(snapshot) {
  const ok = snapshot.state === "done";
  setState(ok ? "完成" : "有失败", ok ? "done" : "failed");

  // 先把标签放出来，再去渲染内容。
  // 顺序反过来过：渲染任何一步抛异常，用户连"点开看看怎么了"都做不到——
  // 界面看起来就是死掉了，而真正的原因只躺在 F12 里。
  const tabs = (view) => document.querySelector(`.tab[data-view="${view}"]`);
  tabs("verify").disabled = false;

  let result;
  try {
    result = await api(`/api/result/${state.jobId}`);
  } catch (err) {
    // 拿不到产物也要让标签可用，并把原因写在面板里，而不是静默卡住
    tabs("skill").disabled = tabs("memory").disabled = true;
    showPaneError(err);
    return;
  }

  tabs("skill").disabled = !result.skill;
  tabs("memory").disabled = !result.memory;

  try {
    renderVerify(result.verify);
    $("view-skill").innerHTML = renderMarkdown(result.skill);
    $("view-memory").innerHTML = renderMarkdown(result.memory);
  } catch (err) {
    showPaneError(err);          // 渲染炸了也不影响标签可用
  }

  const tabVerify = tabs("verify");
  tabVerify.textContent = state.findings ? `校验 · ${state.findings}` : "校验";

  /* 试聊页认的是产物目录名：job 只活在进程里（工作台重启就没了），
     所以链接都带上 skill=<技能名>，重启后照样能打开。 */
  const skillName = encodeURIComponent(snapshot.name);

  if (result.has_zip) {
    $("artifact").hidden = false;
    const link = $("download");
    link.href = `/api/zip/${state.jobId}`;
    link.download = result.zip_name;
    /* 这里必须重建整个 innerHTML（连图标），因为 JS 会覆盖掉 HTML 里写的内容 */
    $("download").innerHTML =
      `<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor"
           stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true"><path d="M8 2.6v7.3M5.3 7.2L8 9.9l2.7-2.7"/>
       <path d="M2.9 11.2v1.3c0 .8.6 1.4 1.4 1.4h7.4c.8 0 1.4-.6 1.4-1.4v-1.3"/></svg>`
      + `下载技能包 <span class="btn__meta">${result.zip_name} · ${humanSize(result.zip_size)}</span>`;
    $("play").href = `/play?job=${encodeURIComponent(state.jobId)}&skill=${skillName}`;
  }

  /* 试聊标签**始终可点**，跟这次跑没跑成、有没有产物无关：
     有这次的产物就挂上它，没有就让试聊页列出 out/ 下之前生成过的 skill。
     （页面在这里内嵌一份：?embed=1 会收掉它自己的顶栏。） */
  tabs("play").disabled = false;
  playUrl = result.skill
    ? `/play?job=${encodeURIComponent(state.jobId)}&skill=${skillName}&embed=1`
    : "/play?embed=1";
  if (result.skill) openPlayFrame(playUrl);
  if (result.skill) await window.Review?.select(snapshot.name);
}

/* ───────────────────────── 标签与出错兜底 ───────────────────────── */

function switchTab(view) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("is-active", v.id === "view-" + view));
  const tab = document.querySelector(`.tab[data-view="${view}"]`);
  if (tab) {
    const nav = $('tabs');
    if (tab.offsetLeft < nav.scrollLeft) nav.scrollLeft = tab.offsetLeft;
    else if (tab.offsetLeft + tab.offsetWidth > nav.scrollLeft + nav.clientWidth)
      nav.scrollLeft = tab.offsetLeft + tab.offsetWidth - nav.clientWidth;
  }
  // 试聊页等到点开才加载：还没跑过蒸馏也能用（它会列出 out/ 下的历史 skill）
  if (view === "play") openPlayFrame(playUrl);
  window.Review?.open(view);
}

/* 试聊的地址：跑完一次蒸馏就指向这次运行；否则指向"去挑一份磁盘上的 skill" */
let playUrl = "/play?embed=1";
let playLoaded = "";

function openPlayFrame(url) {
  const frame = $("playframe");
  if (!frame || !url || playLoaded === url) return;
  playLoaded = url;                 // frame.src 读回来是绝对地址，只能自己记
  frame.src = url;
  frame.hidden = false;
  $("play-empty").hidden = true;
}

function resetPlayTab() {
  /* 新一轮开始：把试聊收回空态（免得对着上一轮的人设说话），但**标签不置灰**——
     点开时照样会加载 /play?embed=1，让试聊页列出 out/ 下之前生成过的 skill。 */
  playLoaded = "";
  playUrl = "/play?embed=1";
  const frame = $("playframe");
  if (frame) { frame.hidden = true; frame.src = "about:blank"; }
  $("play-empty").hidden = false;
  const tab = document.querySelector('.tab[data-view="play"]');
  if (tab) tab.disabled = false;
}

/* 界面自己出错时，把话说在面板里：以前这类异常只出现在 F12 控制台，
   用户看到的是"点不动、没反应"，只能靠猜。 */
function showPaneError(err) {
  const text = `[界面] 渲染出错：${(err && err.message) || err}`;
  $("log").innerHTML += `<p class="log-bad">${esc(text)}</p>`;
  $("verify").innerHTML = `<p class="empty">${esc(text)}</p>`;
  $("view-skill").innerHTML = `<p class="empty">${esc(text)}</p>`;
  $("view-memory").innerHTML = `<p class="empty">${esc(text)}</p>`;
  setState("界面出错", "failed");
}

/* ───────────────────────── 日志渲染 ───────────────────────── */

function renderLog(text) {
  if (!text.trim()) return '<p class="empty">等待输出…</p>';
  const out = [];
  for (const line of text.replace(/\r\n/g, "\n").split("\n")) {
    if (!line.trim()) { out.push(""); continue; }
    const step = line.match(/^\[(\d)\/6\]\s*(.*)$/);
    if (step) {
      out.push(`<span class="log-step"><span class="n">${step[1]}⁄6</span>${esc(step[2])}</span>`);
      continue;
    }
    // 只有"待人工确认的条目"和真正的报错才标红。
    // 汇总行里的「未找到依据 0」是字段名，不是警报，标红反而误导。
    // 条目长这样：  · [章节] 「结论」 说明——注意 `·` 后面紧跟方括号。
    // 不能只凭 `·` 开头就标红：LLM 蒸馏的进度行同样是 `·` 开头
    // （  · 第 1/3 批：人格分析… ），会被误标成红色警报，
    // 看起来像出错了，而不是像"正在跑"——这正是用户看不出进度的原因之一。
    const finding = /^\s+·\s*\[[^\]]+\]/.test(line);
    const broken = /失败|异常|没有解析出|找不到输入/.test(line);
    const cls = finding || broken ? "log-bad"
      : /^\s+·\s/.test(line) ? "log-prog"      // 其余的 `·` 行是进度/状态
      : /^\s{4,}/.test(line) ? "log-dim" : "";
    out.push(cls ? `<span class="${cls}">${esc(line)}</span>` : esc(line));
  }
  return out.join("\n");
}

/* ───────────────────────── 校验渲染 ───────────────────────── */

const VERIFY_SUMMARY =
  /(\d+)\s*条可核验结论：原文命中\s*(\d+)、改写命中\s*(\d+)、未找到依据\s*(\d+)、时间不符\s*(\d+)/;
const FINDING = /^\s*·\s*\[([^\]]+)\]\s*「([\s\S]*?)」\s*(.*)$/;
const FINDING_MORE = /另有\s*(\d+)\s*条/;

function renderVerify(text) {
  const box = $("verify");
  const raw = (text || "").trim();

  if (!raw) {
    box.innerHTML = '<p class="empty">这次没有产生校验报告。</p>';
    state.findings = 0;
    return;
  }
  if (/跳过/.test(raw) && !VERIFY_SUMMARY.test(raw)) {
    box.innerHTML = '<p class="verify__line">本次跳过了校验（--no-verify）。</p>';
    state.findings = 0;
    return;
  }

  const summary = raw.match(VERIFY_SUMMARY);
  const problems = raw.split("\n").map((l) => l.match(FINDING)).filter(Boolean);
  // 印章上的数字要和下面真正列出来的条目对得上：报告最多列 12 条，
  // 其余收在「另有 N 条」里，也要算进去。
  const truncated = raw.match(FINDING_MORE);
  const flagged = problems.length + (truncated ? Number(truncated[1]) : 0);
  state.findings = flagged;

  const parts = [];
  if (summary) {
    const [, total, exact, fuzzy, missing, dates] = summary;
    parts.push(
      `<div class="stamp ${flagged ? "" : "stamp--ok"}">` +
      `<span class="stamp__big">${flagged || "全过"}</span>` +
      `<span class="stamp__small">${flagged ? "条待确认" : "有据可查"}</span></div>`);
    parts.push(`<p class="verify__line">共核验 <b>${total}</b> 条结论</p>`);
    parts.push(`<p class="verify__line">原文命中 <b>${exact}</b> · 改写命中 <b>${fuzzy}</b> · ` +
               `未找到依据 <b>${missing}</b> · 时间不符 <b>${dates}</b></p>`);
  }

  if (problems.length) {
    parts.push('<h3 class="verify__label">需要人工确认</h3>');
    parts.push(problems.map((m) => {
      const [, section, claim, tail] = m;
      const split = tail.split(" ← ");
      const note = (split[0] || "").trim();
      const near = split.slice(1).join(" ← ").replace(/^最相近的原话：/, "").trim();
      return `<div class="finding">` +
        `<div class="finding__head"><span class="finding__sec">${esc(section)}</span>` +
        `<span class="finding__claim">「${esc(claim)}」</span></div>` +
        (note ? `<p class="finding__note">${esc(note.replace(/^（|）$/g, ""))}</p>` : "") +
        (near ? `<p class="finding__near">最相近的原话 <code>${esc(near)}</code></p>` : "") +
        `</div>`;
    }).join(""));
  } else if (summary) {
    parts.push('<p class="verify__line" style="margin-top:22px">' +
               '本次检查的引用与日期通过核验；是否正确理解语境、是否像本人，还需要对照接话片段和试聊判断。</p>');
  }

  box.innerHTML = parts.join("\n") || `<pre class="log">${esc(raw)}</pre>`;
}

/* ───────────────────────── Markdown 渲染 ───────────────────────── */

const FLAGS = ["（未在记录中找到依据）", "（记录中查无此时间）"];

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function highlightFlags(html) {
  let out = html;
  for (const flag of FLAGS) out = out.split(flag).join(`<span class="flag">${flag}</span>`);
  return out;
}

function renderMarkdown(src) {
  if (!src) return '<p class="empty">没有内容。</p>';
  let text = src.replace(/\r\n/g, "\n");

  let front = "";
  const fm = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (fm) {
    front = `<div class="frontmatter">${esc(fm[1])}</div>`;
    text = text.slice(fm[0].length);
  }

  const out = [];
  let list = null;
  let quote = null;
  const flush = () => {
    if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
    if (quote) { out.push(`<blockquote>${quote.join("<br>")}</blockquote>`); quote = null; }
  };

  for (const line of text.split("\n")) {
    if (/^- /.test(line)) {
      if (quote) flush();
      list = list || [];
      list.push(`<li>${inline(esc(line.slice(2)))}</li>`);
      continue;
    }
    if (/^> /.test(line)) {
      if (list) flush();
      quote = quote || [];
      quote.push(inline(esc(line.slice(2))));
      continue;
    }
    flush();
    if (!line.trim()) continue;
    if (/^### /.test(line)) { out.push(`<h3>${inline(esc(line.slice(4)))}</h3>`); continue; }
    if (/^## /.test(line)) { out.push(`<h2>${inline(esc(line.slice(3)))}</h2>`); continue; }
    if (/^# /.test(line)) { out.push(`<h1>${inline(esc(line.slice(2)))}</h1>`); continue; }
    out.push(`<p>${inline(esc(line))}</p>`);
  }
  flush();
  return highlightFlags(front + out.join("\n"));
}

/* ───────────────────────── 选项卡与开关 ───────────────────────── */

$("tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (!tab || tab.disabled) return;
  switchTab(tab.dataset.view);
});

document.querySelectorAll('input[name="mode"]').forEach((el) => {
  el.addEventListener("change", () => {
    const offline = document.querySelector('input[name="mode"]:checked').value === "offline";
    $("llm-config").hidden = offline;
  });
});

/* 公开使用必须有两份画像（主技能扮演你、背景放对方），勾上它就顺手把
   「同时蒸馏双方」也点开——后端会兜底，但界面先说清楚，免得用户以为少给了什么。 */
$("f-public").addEventListener("change", (e) => {
  if (e.target.checked) $("f-both").checked = true;
});

/* ───────────────────────── 启动 ───────────────────────── */

setState("待命");

/* 试聊一开始就能点：还没生成过任何东西时，点开它会列出 out/ 下已有的 skill */
const playTab = document.querySelector('.tab[data-view="play"]');
if (playTab) playTab.disabled = false;
