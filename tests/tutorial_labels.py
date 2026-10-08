"""Documentation-only translations; original evidence and app files are untouched."""

LABELS = {
    '聊天记录 → 人设技能包': 'Chat logs → Persona skill pack',
    '文件': 'File', '消息': 'Messages', '关系': 'Relation', '未选择': 'No file',
    '待命': 'Idle', '就绪': 'Ready', '完成': 'Done', '朋友': 'Friend',
    '进料': 'Intake', '配置': 'Configure', '执行': 'Run', '已有技能': 'Existing skills',
    '拖入或点击选择聊天记录': 'Drop or choose a chat log',
    '识别为': 'Detected as', '解析结果': 'Parsed', '时间跨度': 'Time span', '可用编码': 'Encoding',
    '说话人': 'Speakers', '各解析器命中': 'Parser matches',
    '对不上号的格式会静默降级，这里能看到是谁接走的': 'Check which parser handled the file',
    'JSON 消息数组': 'JSON messages', '通用「昵称: 内容」文本': 'Nickname: message text',
    'QQ 消息管理器导出': 'QQ export', 'WhatsApp 导出': 'WhatsApp export', '实际采用': 'Selected',
    '技能名': 'Skill name', '英文，决定文件名': 'ASCII; controls the filename',
    '我是谁': 'Who am I', '蒸馏谁': 'Who to distil', '可选可填': 'Choose or type',
    '我（默认）': 'Me (default)', '自动（消息最多的非本人）': 'Auto (most active other speaker)',
    '关系类型': 'Relationship', '自动判断': 'Auto-detect', '恋人': 'Partner',
    '同事': 'Colleague', '家人': 'Family', '补充描述': 'Description', '可选': 'Optional',
    'ENFP，双子座': 'ENFP, Gemini',
    '蒸馏方式': 'Distillation', '本地抽取': 'Offline extraction', 'LLM 蒸馏': 'LLM distillation',
    '不联网 · 不需要 Key · 默认脱敏，直接读全部记录': 'Offline · no key · all messages · redacted by default',
    '调用 OpenAI 兼容接口，需要 Key，叙述更细腻': 'OpenAI-compatible endpoint; requires an API key',
    '严格模式': 'Strict mode', '不过的直接删': 'Drop failed claims', '跳过校验': 'Skip verification',
    '同时蒸馏双方': 'Distil both sides', '多一份你自己的画像': 'Also creates your profile',
    '公开使用': 'Public use', '给别人用，主技能扮演你': 'Main skill plays you',
    '开始蒸馏': 'Start distillation', '下载技能包': 'Download pack', '打开试聊页': 'Open try-chat',
    '上传到设备': 'Upload to device', '可选，例 192.168.1.10:8080': 'Optional; e.g. 192.168.1.10:8080',
    'IP:端口': 'IP:port', '选择产物': 'Choose artifact', '还没有技能': 'No skills yet',
    '刷新技能列表': 'Refresh skills', '生成后可查看场景、测评、版本和隐私。': 'Generate a skill to review situations, tests, versions and privacy.',
    '运行日志': 'Run log', '校验': 'Verify', '关系记忆': 'Memory', '试聊': 'Try-chat',
    '情境路由': 'Situations', '证据质量': 'Evidence', '原话索引': 'Messages',
    '补标与更新': 'Annotate & update', 'A/B 对比': 'A/B compare', '回归测评': 'Regression',
    '试聊反馈': 'Feedback', '版本': 'Versions', '隐私检查': 'Privacy',
    '等待输入': 'Waiting for input', '还没有开始': 'Not started',
    '左侧放入聊天记录 → 检查诊断结果 → 点击「开始蒸馏」': 'Choose a chat log → review the diagnosis → start distillation',
    '六步流水线会实时输出到这里': 'The six-step pipeline appears here in real time',
    '先生成技能，或在左侧选择已有技能。': 'Generate a skill or choose an existing one.',
    '全过': 'Passed', '有据可查': 'Quotes verified', '共核验': 'Checked', '条结论': 'claims',
    '原文命中': 'Exact matches', '· 改写命中': '· Paraphrases',
    '· 未找到依据': '· Missing evidence', '· 时间不符': '· Date mismatch',
    '本次检查的引用与日期通过核验；是否正确理解语境、是否像本人，还需要对照接话片段和试聊判断。':
        'Quotes and dates passed these checks. Review the exchanges and try-chat to judge context and likeness.',
    '按相邻的真实接话归纳。先判断眼前的语境；单次观察只用于相似情境。':
        'Derived from adjacent exchanges. Match the current context; a single observation has limited scope.',
    '被指出说法或承诺有问题': 'A claim or promise is challenged',
    '被催或被提醒': 'Being reminded', '对方表达感谢': 'Receiving thanks',
    '对方抱怨没被叫上': 'Someone feels left out', '对方要求正经一点': 'Asked to be serious',
    '对方给出答应或确认': 'Agreement or confirmation', '对方报告进度或结果': 'Progress or results',
    '单次观察': 'Single observation', '接法：': 'Response move:',
    '抓住对方说法中的一点，短句修正或换个说法接回去': 'Pick up one detail and correct or rephrase it briefly',
    '先回应催促本身，再按当前进度接话；保留原话里的顶嘴或缓冲语气': 'Acknowledge the reminder, then describe progress with the original tone',
    '用原话里的回礼要求或简短答语接住感谢': 'Answer thanks with a short reply or a request to return the favor',
    '顺着抱怨回应下一次的安排，用短句补一句承诺': 'Respond to feeling left out with a brief plan for next time',
    '沿着刚才的话题继续接梗，保留原话中一本正经的措辞': 'Continue the joke with the original deadpan wording',
    '把对方的确认接成具体约定或下一步': 'Turn agreement into a concrete arrangement or next step',
    '接上对方的进度，报自己的状态或给一个下一步': 'Respond to progress with your own status or a next step',
    '不要把旧地点、旧承诺或单次玩笑当成当前事实': 'Keep old places, promises and one-off jokes in their original context.',
    '具体性分数衡量目标人物的原话数量、会话覆盖和独特措辞。它不是性格准确率，点击出处可核对判断。':
        'Scores measure quote count, session coverage and distinctive wording. Open the source to review each interpretation.',
    '人物特点的具体性': 'Trait specificity', '情境覆盖矩阵': 'Situation coverage matrix',
    '至少两段会话有可用接法才算已覆盖。出现过输入但没有可用接法，会标为缺失接法；未观察到或仅一次观察，保留为证据不足。':
        'Covered means usable replies in at least two sessions. Other situations need more evidence or a usable reply.',
    '已覆盖': 'Covered', '证据不足': 'Insufficient evidence', '缺失接法': 'Missing response',
    '待补充真实接法': 'Needs a real response example', '逐条原话索引': 'Message index',
    '消息保留时间、说话人、会话和稳定编号。当前技能的脱敏设置同样适用于这里。':
        'Messages retain times, speakers, sessions and stable numbers, with the same redaction settings as the skill.',
    '搜索文字、日期、说话人或消息编号': 'Search text, dates, speakers or message numbers',
    '显示全部原话': 'Show all messages', '上一页': 'Previous', '下一页': 'Next',
    '主动补标与增量更新': 'Annotations and incremental updates',
    '证据薄弱的观察先提问。你的补标会影响本地试聊，保持为人工标注；不会冒充聊天原话或进入 ZIP。内容变化后需要重新确认。':
        'Confirm weak observations before use. Annotations guide local try-chat, stay outside the ZIP and expire after edits.',
    '人物特点': 'Trait', '情境': 'Situation', '记忆': 'Memory', '冲突记忆': 'Memory conflict',
    '待确认': 'Pending', '已确认': 'Confirmed', '已否定': 'Rejected',
    '适用范围或当前情况': 'Scope or current status', '确认时请填写范围或当前情况': 'Describe scope or current status before confirming',
    '加入新聊天': 'Add new chat',
    '先预览去重结果和潜在冲突，再合并新增观察。合并前保留历史版本；冲突记忆保持待确认。':
        'Preview duplicates and possible conflicts, then merge additions. Versions are retained and conflicts need confirmation.',
    '选择完整记录或新增记录': 'Choose a full export or new messages',
    '也可填写消息数组': 'Or enter a message array', '使用模型分析新增内容': 'Use a model to analyze additions',
    '增量模型接口（勾选后会发送新增聊天）': 'Model endpoint (sends new chat when enabled)',
    '预览新增与冲突': 'Preview additions and conflicts', '合并预览中的新增记录': 'Merge previewed additions',
    '发现潜在冲突，合并后标记为待确认': 'Possible conflict: merging marks affected memories as pending',
    '接口地址': 'Endpoint', '模型': 'Model', '只留在本机内存': 'Memory only', '必填': 'Required',
    '发送': 'Send', '重开': 'Restart', '接口': 'Endpoint settings',
    '跟 TA 说点什么…（Enter 发送）': 'Say something… (Enter to send)',
    '可以开始了': 'Ready to chat', 'TA 回了': 'Reply received',
    '这句像吗？': 'Does this sound like them?', '像本人': 'Sounds like them', '太客气': 'Too polite',
    '答非所问': 'Off topic', '场景用错': 'Wrong situation', '事实错误': 'Factual error', '其他': 'Other',
    '保存反馈': 'Save feedback', '反馈类型': 'Feedback type', '反馈备注': 'Feedback note',
    '哪里不对，或本人会怎么接（可选）': 'What is wrong, or how would they reply? (optional)',
    '这份产物没带 Key，得填一个': 'Enter a key for this offline-generated skill',
    '聊天温度': 'Temperature', '越高越松，太高会开始说飘话': 'Higher values make replies less restrained',
    '0.7 · 稳（像在回消息但克制）': '0.7 · Restrained', '1.1 · 默认': '1.1 · Default',
    '1.3 · 活跃': '1.3 · Lively', '1.6 · 很飘': '1.6 · Loose',
    '生成人设的那次运行若带了 Key，这里留空就直接用它（不落盘、不写日志）；':
        'If generation included a key, leaving this blank reuses it from memory.',
    '离线蒸馏出来的产物没有 Key，得自己填一个才能试聊。': 'Offline-generated skills need a key for try-chat.',
    '模型与配方 A/B 对比': 'Model and recipe A/B comparison',
    '两侧使用同一份人设和同一组回归用例。比较静态问题、耗时和语感，最后逐条选你更认可的回复。配置与结果留在本地，Key 只用于当前请求。':
        'Both sides share the persona and regression cases. Compare checks, timing and wording, then choose each reply. Keys are used only for the current request.',
    '温度': 'Temperature', '配方（附加回复指令）': 'Recipe (additional reply instructions)',
    '保存配置并新建对比': 'Save configs and start comparison', '运行未完成的用例': 'Run unfinished cases',
    '完成当前调用后停止': 'Stop after current reply',
    '先保存两侧配置，再填写本次运行的 Key；运行使用已保存的配置。': 'Save both configs first, then enter keys for this run.',
    '历史对比': 'Comparison history', '选择对比': 'Choose a comparison',
    '相当': 'Tie', '都不合适': 'Neither', '未命中静态问题': 'No static issues',
    '尚未运行': 'Not run', '尚无对比，请先保存两侧配置。': 'Save two configurations to start a comparison.',
}

# Full phrases and anchored formatters avoid changing characters inside quotes
# (e.g. replacing 中 in 原文命中). The translation is restored after every shot.
LOCALIZE = r"""({labels, english, temporary}) => {
  const saved = [], unknown = [];
  const keep = (node, value) => { saved.push([node, node.nodeValue]); node.nodeValue = value; };
  const source = (el) => el.closest(
    '#view-skill, #diag-speakers, datalist, #message-results h3, #message-results p, ' +
    '.ab-reply, .bubble--me, #view-evidence > .review-card h3, textarea'
  ) || (el.closest('.bubble--ta') && !el.closest('.chat-feedback, .bubble__meta'));
  const convert = (text) => {
    if (Object.hasOwn(labels, text)) return labels[text];
    const countLabel = (n, label) => `${n} ${label}${Number(n) === 1 ? '' : 's'}`;
    const rules = [
      [/^\[\s*(.*?)\s*\]$/, (_, t) => `[ ${labels[t] || t} ]`],
      [/^当前技能：(.*)$/, (_, t) => `Current skill: ${t}`],
      [/^下载技能包 · (.*)$/, (_, t) => `Download pack · ${t}`],
      [/^(\d+) 条 · 第 (\d+) \/ (\d+) 页$/, (_, n,a,b) => `${n} messages · Page ${a} / ${b}`],
      [/^(\d+) 条 · (.*)$/, (_, n, s) => `${n} messages · ${s}`],
      [/^查看原话 · (.*)$/, (_, ids) => `Open source · ${ids.replaceAll('、', ', ')}`],
      [/^泛化风险：(低|中|高)$/, (_, t) => `Generalization risk: ${{低:'Low',中:'Medium',高:'High'}[t]}`],
      [/^原话 (\d+) 条 · 会话 (\d+) 段$/, (_, a, b) => `${countLabel(a, 'quote')} · ${countLabel(b, 'session')}`],
      [/^独特词：(.*)$/, (_, t) => `Distinctive terms: ${t}`],
      [/^输入 (\d+) 条 · 会话 (\d+) 段 · 示例 (\d+) 个$/, (_, a,b,c) => `${countLabel(a, 'input')} · ${countLabel(b, 'session')} · ${countLabel(c, 'example')}`],
      [/^(\d+) 段会话重复$/, (_, n) => `Observed in ${countLabel(n, 'session')}`],
      [/^触发信号：(.*)$/, (_, t) => `Trigger signals: ${t}`],
      [/^接法：(.*)$/, (_, t) => `Response move: ${labels[t] || t}`],
      [/^期望接法：(.*)$/, (_, t) => `Expected move: ${labels[t] || t}`],
      [/^(对方|本人|输入)：(.*)$/, (_, who,t) => `${{对方:'Other',本人:'Target',输入:'Input'}[who]}: ${t}`],
      [/^(.*) · 会话 (\d+)$/, (_, t,n) => `${t} · Session ${n}`],
      [/^待补标 (\d+) 个$/, (_, n) => `${n} observations to review`],
      [/^“(.*)”是否有你希望保留的接法？目前只有 (\d+) 段证据。$/, (_, t,n) => `Do you have a preferred response for “${labels[t] || t}”? Evidence: ${countLabel(n, 'session')}.`],
      [/^记忆“(.*)”现在仍然有效吗？$/, (_, t) => `Is the memory “${t}” still valid?`],
      [/^主人物：(.*) · 对话方：(.*)$/, (_, a,b) => `Target: ${a} · Other speaker: ${b}`],
      [/^已读取 (\d+) 条消息；点击预览去重结果。$/, (_, n) => `${n} messages loaded; preview duplicates next.`],
      [/^新增 (\d+) 条 · 重复 (\d+) 条 · 潜在冲突 (\d+) 个$/, (_, a,b,c) => `${a} added · ${countLabel(b, 'duplicate')} · ${countLabel(c, 'possible conflict')}`],
      [/^(.*)（待确认）$/, (_, t) => `${t} (pending)`],
      [/^正在跟 (.*) 对话$/, (_, t) => `Chatting with ${t}`],
      [/^(\d+) 份 · (.*) · (\d+) 段示范$/, (_, n,t,m) => `${n} files · ${t} · ${m} examples`],
      [/^人设来自 (.*) 的 (.*)$/, (_, t,f) => `Persona from ${t}: ${f}`],
      [/^([\d.]+) 秒$/, (_, n) => `${n} s`],
      [/^([AB]) 配置$/, (_, side) => `${side} configuration`],
      [/^已完成 (\d+) \/ (\d+) 次回复$/, (_, a,b) => `${a} / ${b} replies completed`],
      [/^(相当|都不合适) (\d+)$/, (_, t,n) => `${labels[t]} ${n}`],
      [/^A：(\d+) \/ (\d+) 未命中静态问题，累计 ([\d.]+) 秒；B：(\d+) \/ (\d+) 未命中静态问题，累计 ([\d.]+) 秒$/,
        (_,a,b,t,c,d,u) => `A: ${a} / ${b} without static issues; ${t} s total · B: ${c} / ${d} without static issues; ${u} s total`],
      [/^([AB])：(\d+) \/ (\d+) 未命中静态问题，累计 ([\d.]+) 秒$/, (_, s,a,b,t) => `${s}: ${a} / ${b} without static issues; ${t} s total`],
      [/^([\d.]+) 秒 · 未命中静态问题$/, (_, t) => `${t} s · No static issues`],
      [/^([\d.]+) 秒 · 泛化客服话术：(.*)$/, (_, t,q) => `${t} s · Generic service language: ${q}`],
      [/^解析聊天记录：(.*)$/, (_, t) => `Parse chat log: ${t}`],
      [/^统计画像$/, () => 'Profile'],
      [/^挑选代表片段$/, () => 'Select representative excerpts'],
      [/^本地抽取式蒸馏（.*）$/, () => 'Offline extraction (no model call)'],
      [/^校验结论$/, () => 'Verify conclusions'],
      [/^打包$/, () => 'Package'],
      [/^共 (\d+) 条消息；说话者 (.*)$/, (_, n,t) => `${n} messages; speakers ${t}`],
      [/^蒸馏对象：(.*)$/, (_, t) => `Target: ${t}`],
      [/^关系类型：朋友（.*）$/, () => 'Relationship: friend (auto-detected)'],
      [/^(.*) 口头禅候选：(.*)$/, (_, t,q) => `${t} — phrase candidates: ${q}`],
      [/^深夜消息占比：(.*)$/, (_, t) => `Late-night messages: ${t}`],
      [/^跳过：本地抽取模式直接读全部记录，不采样、不联网（脱敏照做，见第 6 步）$/, () => 'Uses the entire log offline, with redaction; no model sampling.'],
      [/^(.*?)：说话风格 (\d+) 条、口头禅 (\d+) 条、接话方式 (\d+) 条、情感模式 (\d+) 条、温度与分寸 (\d+) 条、关系行为 (\d+) 条、典型例句 (\d+) 条、关系记忆 (\d+) 条$/, (_,t,a,b,c,d,e,f,g,h) => `${t}: ${a} style notes, ${b} phrases, ${c} response examples, ${d} emotion notes, ${e} restraint rules, ${f} relationship notes, ${g} quotes, ${h} memories`],
      [/^内容检查：保留 (\d+) 条有原话的人物特点、(\d+) 条情境接法、(\d+) 段接话示范；.*$/, (_,a,b,c) => `Grounding: ${a} traits, ${b} situation strategies, ${c} exchanges. Quotes alone do not prove likeness.`],
      [/^(\d+) 条可核验结论：原文命中 (\d+)、改写命中 (\d+)、未找到依据 (\d+)、时间不符 (\d+)$/, (_,n,a,b,c,d) => `${n} claims: ${a} exact, ${b} paraphrases, ${c} missing sources, ${d} date mismatches`],
      [/^参考资料：(\d+) 个月.*共 ([\d.]+) MB（--corpus-mb ([\d.]+)，0 可关；已脱敏）$/, (_,n,s,b) => `References: ${n} months, topics, evidence and source export; ${s} MB (budget ${b} MB; redacted)`],
      [/^参考文献：(\d+) 条原话（.*）$/, (_,n) => `Citations: ${n} original messages; each [n] has a source.`],
      [/^脱敏：手机号 \/ 身份证 \/ 银行卡 \/ 邮箱 \/ 详细地址 已替换成 \[标签\]（.*）$/, () => 'Redaction: phones, IDs, cards, emails and addresses replaced with labels.'],
      [/^情境路由 (\d+) 类 · 带状态记忆 (\d+) 条 · 回归用例 (\d+) 条$/, (_,a,b,c) => `${a} situations · ${b} dated memories · ${c} regression cases`],
      [/^发布前隐私检查：(\d+) 条待确认[，；]在 Web 工作台可逐条查看$/, (_,n) => `Privacy review: ${n} items to review in the workbench`],
      [/^下一步：$/, () => 'Next steps:'],
      [/^1\) 打开设备控制台.*$/, () => '1) Open your device console (Settings → Assistant, or http://<DEVICE_IP>:8080).'],
      [/^2\) 上传 (.*)$/, (_,t) => `2) Upload ${t}`],
      [/^3\) 在技能列表里把它设为.*$/, () => '3) Set it as the main persona skill in the device skill list.'],
      [/^4\) 想改口味.*$/, () => '4) Edit SKILL.md / references/memory.md or use try-chat to refine the wording.'],
    ];
    for (const [pattern, fn] of rules) if (pattern.test(text)) return text.replace(pattern, fn);
    return null;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, el = node.parentElement;
    if (!el || el.closest('script, style') || source(el)) continue;
    const original = node.nodeValue;
    let text = original.trim();
    if (!text) continue;
    if (el.closest('#log')) text = text
      .replace(temporary + '\\zh\\out\\', 'out/')
      .replace(temporary + '\\en\\out\\', 'out/')
      .replace(new RegExp(temporary.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\\\uploads\\\\[^\\\\]+\\\\', 'g'), '');
    let translated = text;
    if (english) {
      // renderLog may place several complete lines in the same text node.
      translated = text.split('\n').map(line => {
        const trimmed = line.trim();
        const value = convert(trimmed);
        if (value !== null) return line.replace(trimmed, value);
        if (/[\u4e00-\u9fff]/.test(trimmed)) {
          const data = el.closest('#message-results h3, #diag-speakers, blockquote') ||
                       ['潘小雨', '小蒯'].includes(trimmed);
          if (!data) {
            const rect = el.getBoundingClientRect();
            if (rect.width && rect.bottom > 0 && rect.top < innerHeight && !el.closest('.view:not(.is-active)')) unknown.push(trimmed);
          }
        }
        return line;
      }).join('\n');
    }
    if (translated !== original.trim()) keep(node, original.replace(original.trim(), translated));
  }
  if (english) {
    for (const el of document.querySelectorAll('input, textarea, button, select')) {
      for (const attr of ['placeholder', 'title', 'aria-label']) {
        const value = el.getAttribute(attr);
        if (value && labels[value]) {
          saved.push([el, attr, value]); el.setAttribute(attr, labels[value]);
        }
      }
    }
  }
  window.__tutorialRestore = saved;
  return unknown;
}"""

RESTORE = """() => {
  for (const [el, value, attributeValue] of window.__tutorialRestore || []) {
    if (attributeValue !== undefined) el.setAttribute(value, attributeValue);
    else el.nodeValue = value;
  }
  delete window.__tutorialRestore;
}"""
