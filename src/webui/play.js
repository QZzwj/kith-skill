/* kith-skill 试聊页 —— 拿刚生成的那套产物当人设，当场对话。
   没有框架、没有构建步骤；跟 app.js 一样，$ / esc / api 这几个小工具自己带着。 */

const $ = (id) => document.getElementById(id);

/* #hello 是消息区里的空态块，而它是 #scroll 的**子节点**：清空消息区那句
   innerHTML="" 会把它的 DOM 节点一起销毁。销毁之后再用 $("hello") 去取就是 null，
   而 bubble() 每次都要动它（hidden = true）——于是**每发一条消息都在 bubble() 里抛
   异常**，看起来就是"重开之后再也发不出消息"。
   所以一直握着这个节点本身：节点脱离文档也还活着，放回去即可。 */
const hello = $("hello");

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const humanSize = (n) =>
  n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + " MB"
  : n > 1024 ? (n / 1024).toFixed(1) + " KB"
  : n + " B";

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败（${res.status}）`);
  return data;
}

function setState(text, cls) {
  $("state-text").textContent = text;
  $("chip-state").className = "state" + (cls ? " is-" + cls : "");
}

/* 给模型看的历史（只留 role/content），和屏幕上的气泡分开维护：
   气泡可以清掉重开，历史也能跟着清，两者不会错位。 */
const history = [];
let busy = false;
let job = "";
let skill = "";        // 当前人设的目录名（out/<skill>/），磁盘上的历史产物靠它
let info = null;

/* ───────────────────────── 气泡 ───────────────────────── */

function bubble(kind, text, meta) {
  if (hello) hello.hidden = true;
  const el = document.createElement("div");
  el.className = "bubble bubble--" + kind;
  el.innerHTML = esc(text) + (meta ? `<span class="bubble__meta">${esc(meta)}</span>` : "");
  $("scroll").appendChild(el);
  $("scroll").scrollTop = $("scroll").scrollHeight;
  return el;
}

/* ───────────────────────── 开局 ───────────────────────── */

async function boot() {
  const params = new URLSearchParams(location.search);
  job = params.get("job") || "";
  // embed=1：被工作台的「试聊」标签用 iframe 嵌进去时，收掉自己的顶栏
  if (params.get("embed") === "1") document.body.classList.add("embed");

  /* 磁盘上之前生成过的 skill。产物本来就落在 out/ 下，所以这份列表既是
     "导入之前的 skill" 的入口，也是 job 失效（工作台重启过）时的退路。 */
  let skills = [];
  try {
    skills = (await api("/api/skills")).skills || [];
  } catch { /* 拿不到列表也不该挡住试聊 */ }
  fillSkillPicker(skills);

  if (job) {
    try {
      info = await api(`/api/play/${encodeURIComponent(job)}`);
      skill = info.name;
    } catch {
      info = null;            // job 只活在进程里：重启过就退回磁盘上的 skill
    }
  }

  if (!info) {
    const want = params.get("skill") || (skills[0] && skills[0].name) || "";
    if (!want) {
      return fatal("还没有任何 skill 可用：先在工作台跑一次蒸馏（产物会落在 out/ 下），再回来试聊。");
    }
    try {
      info = await api(`/api/play-skill/${encodeURIComponent(want)}`);
      skill = info.name;
    } catch (err) {
      return fatal(err.message);
    }
  }

  apply(info);
  bubble("sys", `人设来自 out/${info.name}/ 的 ${info.files.join("、")}`);
}

/* 温度是口味不是正确性：记住用户挑过的档位，刷新、重开页面都还在。
   服务端给的值（环境变量或默认档）只在没有记忆时当起点。 */
const TEMP_KEY = "kith-skill.chat.temperature";

function pickTemperature(serverValue) {
  try {
    return localStorage.getItem(TEMP_KEY) || String(serverValue ?? "");
  } catch {
    return String(serverValue ?? "");     // localStorage 被浏览器禁掉时别把整页拖崩
  }
}

/* 首次进来或换人设时，把表头、接口默认值、输入框状态一起铺好 */
function apply(data) {
  info = data;
  document.title = `试聊 · ${info.title}`;
  $("who").textContent = `正在跟 ${info.title} 对话`;
  $("ctx").textContent = `${info.files.length} 份 · ${humanSize(info.chars)}`
    + (info.examples ? ` · ${info.examples} 段示范` : "");
  $("f-baseurl").value = info.base_url;
  $("f-model").value = info.model;
  // 温度 = 上次选的 > 服务端给的。服务端的值也可能不在预设档里：临时补一个选项，
  // 免得下拉框悄悄显示成别的档位、让人以为设置没生效。
  const temp = pickTemperature(info.temperature);
  if (temp && !Array.from($("f-temp").options).some((o) => o.value === temp)) {
    $("f-temp").add(new Option(`${temp} · 自定义`, temp));
  }
  if (temp) $("f-temp").value = temp;
  $("f-apikey").placeholder = info.has_key ? "留空＝用这次蒸馏的 Key" : "这份产物没带 Key，得填一个";
  $("key-hint").textContent = info.has_key ? "留空＝用本次运行的" : "必填";
  if (!info.has_key) $("cfg").open = true;      // 没 Key 的话直接把配置摊开
  if ($("skill").value !== info.name) $("skill").value = info.name;
  $("say").disabled = false;
  $("send").disabled = false;
  $("say").focus();
  setState("可以开始了", "done");
}

function fillSkillPicker(skills) {
  const sel = $("skill");
  sel.innerHTML = "";
  if (!skills.length) {
    sel.innerHTML = '<option value="">（磁盘上还没有 skill）</option>';
    return;
  }
  skills.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.name;
    opt.textContent = s.title && s.title !== s.name ? `${s.title}（${s.name}）` : s.name;
    sel.appendChild(opt);
  });
}

/* 清空这一轮对话（气泡 + 给模型看的历史），人设相关的东西不动 */
function resetConversation() {
  history.length = 0;
  $("scroll").innerHTML = "";
  if (hello) {
    hello.hidden = false;
    $("scroll").appendChild(hello);     // 节点还在手里，放回消息区
  }
}

/* 换人设＝换一份产物：清空对话、重读文件，并把 ?skill= 写回地址栏
   （刷新、分享、或换个人打开，都还指在这份人设上）。 */
$("skill").addEventListener("change", async () => {
  if (busy || !$("skill").value) return;
  const name = $("skill").value;
  try {
    const data = await api(`/api/play-skill/${encodeURIComponent(name)}`);
    job = "";                 // 已经切到磁盘上那份，不再依赖这次运行的 job
    skill = name;
    resetConversation();
    apply(data);
    bubble("sys", `已换成人设 ${data.title}（out/${name}/）`);
    const url = new URL(location.href);
    url.searchParams.delete("job");
    url.searchParams.set("skill", name);
    window.history.replaceState(null, "", url);   // 注意：history 这个变量被对话数组占了
  } catch (err) {
    bubble("err", err.message);
  }
});

function fatal(message) {
  bubble("err", message);
  setState("打不开", "failed");
  if (hello) hello.hidden = true;
}

/* ───────────────────────── 发送 ───────────────────────── */

async function ask() {
  busy = true;
  setState("TA 正在想…", "running");
  $("say").disabled = true;
  $("send").disabled = true;
  const thinking = bubble("sys", "…");

  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job,
        skill,
        messages: history,
        base_url: $("f-baseurl").value.trim(),
        model: $("f-model").value.trim(),
        // Key 只在这一次请求里出现，服务端不存它
        api_key: $("f-apikey").value.trim(),
        // 口味参数：改档位下一条消息就生效，不用重启工作台
        temperature: $("f-temp").value,
      }),
    });
    thinking.remove();
    if (res.error) throw new Error(res.error);
    bubble("ta", res.reply, res.seconds ? `${res.seconds} 秒` : "");
    history.push({ role: "assistant", content: res.reply });
    setState("TA 回了", "done");
  } catch (err) {
    thinking.remove();
    bubble("err", err.message);
    setState("这次没成", "failed");
  } finally {
    busy = false;
    $("say").disabled = false;
    $("send").disabled = false;
    $("say").focus();
  }
}

/* 挑了档位就记住：下次进页面（哪怕换了个人设）还用这个档 */
$("f-temp").addEventListener("change", () => {
  try {
    localStorage.setItem(TEMP_KEY, $("f-temp").value);
  } catch { /* 存不进去就算了，别影响聊天 */ }
});

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("say").value.trim();
  if (!text || busy || !info) return;
  bubble("me", text);
  history.push({ role: "user", content: text });
  $("say").value = "";
  ask();
});

$("reset").addEventListener("click", () => {
  if (busy || !info) return;
  resetConversation();
  bubble("sys", `人设来自 out/${info.name}/ 的 ${info.files.join("、")}`);
  setState("重新开始", "done");
  $("say").focus();
});

boot();
