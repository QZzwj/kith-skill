# kith-skill

<div align="center"><img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg"><img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg"></div>

<p align="center">🇺🇸 <a href="./README.en.md">English</a> | 🇨🇳 <a href="./README.md">简体中文</a></p>

<p align="center">
<img src="assets/readme/hero.svg" width="100%" alt="kith-skill：把一份聊天记录，变成能装进设备的人设技能包；产物为 SKILL.md、references/memory.md 与 name.zip，下方是解析 → 统计画像 → 挑选片段 → 蒸馏 → 校验结论 → 打包 六步流水线">
</p>

**把一份聊天记录，变成一个能装进设备的人设技能包**：`SKILL.md` + `references/memory.md` + `<name>.zip`。

只用 Python 3.10+ 标准库：不用 `pip install`，不下载模型，不显式启用 LLM 就不联网。产物可用于支持 Skill 格式或同类技能包机制的工具，当前主要适配 QZdesk（项目待开源）。

> 文中的昵称、技能名、路径和 API Key 都是占位符。请换成你自己的值，上传前检查产物里的个人信息。

怎么读：[它给你什么](#它给你什么) · [六步流水线](#六步流水线每一步都能单独核对) · [图文教程](#图文教程) · [常用参数](#常用参数) · [排错](#排错) · [隐私与安全](#隐私与安全)

## 先看结果

<p align="center">
<img src="docs/images/tutorial-a4-log.png" width="100%" alt="先看结果：离线跑一遍的运行日志，六步流水线、结论校验与包体积都在里面">
</p>

一个网页工作台，两条命令，两条路。左边把包造出来，右边立刻验收：跑完就能在「试聊」里跟 TA 说两句，不满意就手改产物或换配方重跑。

## 它给你什么

| 产物 | 是什么 |
| --- | --- |
| `SKILL.md` | 人设：身份、说话风格、口头禅、**接话方式**、情感模式、**温度与分寸**、关系行为、典型例句 |
| `references/memory.md` | 关系记忆：时间线、共同地点、内部玩笑、争吵模式、称呼 |
| `references/` | 参考资料层：逐月原记录 `transcript/`、主题档案 `topics.md`、结论依据 `evidence.md`、原始导出脱敏副本 `source/` |
| `<name>.zip` | 以上打包体。传进设备控制台、设为「主技能」，之后唤醒即生效 |

<p align="center">
<img src="assets/readme/pack-anatomy.svg" width="100%" alt="技能包结构：扮演层 SKILL.md、检索层 references/ 目录（memory.md、transcript/、topics.md、evidence.md）与打包体 name.zip；整包默认脱敏">
</p>

目录长这样，每一层都有自己的活：

```text
<out>/<name>/SKILL.md                          人设（扮演指令）
<out>/<name>/references/memory.md              关系记忆
<out>/<name>/references/transcript/YYYY-MM.md  逐月逐条原记录（默认已脱敏）
<out>/<name>/references/topics.md              按主题重组的原话档案
<out>/<name>/references/evidence.md            每条结论 ← 原话 的对照表
<out>/<name>/references/source/                原始导出的脱敏副本（--no-source 可关）
<out>/<name>.zip                               以上打包，通常 1~3 MB
```

人设文档只有十几 KB——那是提炼过的结论；「哪天说的、原话是什么」靠检索 `references/`。校验不过的条目会标注 `（未在记录中找到依据）`；由回退或补齐得到的部分会写在 `SKILL.md` 顶部（例如「LLM 蒸馏 + 本地抽取式蒸馏补齐」）。

## 六步流水线，每一步都能单独核对

<p align="center">
<img src="assets/readme/workflow.svg" width="100%" alt="六步流水线说明卡：解析聊天记录、统计画像、挑选代表片段、蒸馏、校验结论、打包，每步列出产出与可核对的点；底部说明 LLM 失败时退回离线抽取式蒸馏">
</p>

中间是六步流水线，日志里就是这六个标题：
`[1/6] 解析` → `[2/6] 统计画像` → `[3/6] 挑选代表片段` → `[4/6] 蒸馏` → `[5/6] 校验结论` → `[6/6] 打包`。

下面是仓库自带合成样例 `samples/demo-chat.json` 的离线运行实录（原样粘贴，只有路径改成占位符）：

```text
[1/6] 解析聊天记录：demo-chat.json
      共 123 条消息；说话者 {'潘小雨': 66, '小蒯': 57}
      蒸馏对象：潘小雨
      关系类型：恋人（自动判断：恋人信号最密（每千字命中 2.5 次））
[2/6] 统计画像
      潘小雨 口头禅候选：下次一定、牛嘿、我擦、食堂二楼、行吧、在干嘛、出来吃烧烤不、我这都烤上了
      深夜消息占比：32%
[3/6] 挑选代表片段
      跳过：本地抽取模式直接读全部记录，不采样、不联网（脱敏照做，见第 6 步）
[4/6] 本地抽取式蒸馏（内置 n-gram 分词，不调用 LLM）
      潘小雨：说话风格 8 条、口头禅 4 条、接话方式 8 条、情感模式 3 条、温度与分寸 5 条、关系行为 6 条、典型例句 8 条、关系记忆 6 条
[5/6] 校验结论
      35 条可核验结论：原文命中 35、改写命中 0、未找到依据 0、时间不符 0
[6/6] 打包
      参考资料：2 个月的原记录 + 主题档案 + 结论依据 + 带路文件 + 原始导出，共 0.0 MB（--corpus-mb 8，0 可关；已脱敏）
      参考文献：24 条原话（正文里的 [n] 都能在记录里搜到原句）
      脱敏：手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址 已替换成 [标签]（想保留原样加 --no-redact）
      <out>/demo-persona.zip（13.5 KB）
```

蒸馏有两个引擎，字段结构完全一致、随时可切：

| | `--no-llm`（离线，建议先跑） | LLM（默认） |
| --- | --- | --- |
| 速度 / 依赖 | 几秒，不联网、不要 Key | 分钟级，需要联网 |
| 结论来源 | 统计数字 + 从记录里原样抽出的原话 | 模型归纳，可能过度概括或改写 |
| 适用 | 先确认解析和说话人对不对 | 要更细腻的事件叙述 |

## 图文教程

两条路产出完全一致，**选一条走到底**：不想碰命令行走路线 A，要脚本化走路线 B。

<p align="center">
<img src="assets/readme/routes.svg" width="100%" alt="路线对照：路线 A 用 python -m src.web 打开网页工作台，路线 B 用 python3 ex_distill.py 写脚本；两条路产出同一份 SKILL.md、references/ 与 name.zip">
</p>

### 路线 A：网页工作台

```bash
python -m src.web            # 默认 http://127.0.0.1:8765/，自动打开浏览器
python -m src.web --port 9000 --no-open
```

界面是**左栏三张卡**（进料 → 配置 → 执行）、**右栏五个标签**（运行日志 / 校验 / SKILL.md / 关系记忆 / 试聊）：

<p align="center">
<img src="assets/readme/workbench-map.svg" width="100%" alt="工作台界面地图：左栏进料、配置、执行三张卡；右栏运行日志、校验、SKILL.md、关系记忆、试聊五个标签及各自要看的东西">
</p>

> [!IMPORTANT]
> 工作台是常驻进程：改完 `src/` 下的代码要**重启**才生效；端口已被占用时它**拒绝启动**（不会并排跑两个）。

**A1 · 拖入聊天记录，先看诊断。** 解析成功后：顶栏显示文件名与条数、投放区下方展开诊断、「开始蒸馏」才变可点（没解出消息时它一直是灰的）。

> 下图是仓库自带的合成样例 `samples/demo-chat.json`（123 条，潘小雨 / 小蒯）拖进去之后的样子。

<p align="center">
<img src="docs/images/tutorial-a2-diagnose.png" width="880" alt="解析诊断面板：解析器、条数、时间跨度与候选列表">
</p>

养成看两个数的习惯：**带时间戳的条数**（通用解析器可能解出上千条却一条时间都没有，后面所有按时间的统计都会失效）和**说话人数**。条数明显不对就换文件、或另存成 UTF-8 再拖一次。

**A2 · 填配置。** 技能名（英文，决定目录名和 zip 名）、我是谁、蒸馏谁都可从候选中选，也可手填；蒸馏方式选「本地抽取」或「LLM 蒸馏」（选后者才出现接口地址、模型、API Key）。可选：补充描述、关系类型、严格模式、同时蒸馏双方、公开使用。

<p align="center">
<img src="docs/images/tutorial-a3-config.png" width="880" alt="配置卡：技能名、我是谁、蒸馏谁、关系类型、蒸馏方式">
</p>

**A3 · 点「开始蒸馏」，看日志。** 右栏实时输出上面那种 `[N/6]` 步骤，离线那趟几秒结束。

<p align="center">
<img src="docs/images/tutorial-a4-log.png" width="880" alt="运行日志：六步流水线实时输出，末尾给出包体积与下一步">
</p>

换成 LLM 后第 4 步变慢，但会报清三件事：总共几批几次请求、当前在第几批、每次实际用时。看到 `改用本地抽取式蒸馏` 说明 LLM 那一环失败、已自动用离线补齐——**产物照样完整**，接口恢复后重跑即可。

**A4 · 下载并上传。** 左栏「执行」下载 `<技能名>.zip` → 设备控制台（板子 → 设置 → 助手 扫码，或 `http://<设备IP>:8080`）上传 → 在技能列表里设为「主技能」。

### 路线 B：命令行

上面快速开始那两条就是主线命令，这里是可叠加的组合：

```bash
python3 ex_distill.py ... --device '<DEVICE_IP>:8080'   # 生成后直接传设备
python3 ex_distill.py ... --both                        # 也蒸馏你自己 → references/self.md
python3 ex_distill.py ... --audience 公开                # 主技能换成你自己 + 自动脱敏
python3 ex_distill.py ... --dry-run-llm                 # 只打印将发出的请求，不真发
python3 ex_distill.py ... --llm-chars 12000 --llm-batches 1   # 缩小请求、省时间
```

命令行跑完也能试聊：产物在 `out/` 下，用 `/play?skill=<技能名>` 打开，或在试聊页表头的下拉里挑。

### 验收：看这三处

| 看哪里 | 该看到什么 |
| --- | --- |
| 右栏「校验」 | 印章上的数字＝待人工确认的条数（**0 最好**）。跑 LLM 时出现几条「未找到依据」很正常，重点看它给的**最相近的原话** |
| 右栏「SKILL.md」/「关系记忆」 | 扫「硬规则」「口头禅」像不像，再看时间线里的事件有没有写错人名和时间（可疑条目朱红标出） |
| 右栏「试聊」 | 跟 TA 说两句。这一步花的时间最少、暴露的问题最多 |


试聊读的是**磁盘上的产物**：手改 `out/<名字>/SKILL.md` 或 `references/memory.md` 后刷新页面即生效，不用重跑蒸馏。它也不改动产物本身。

<p align="center">
<img src="docs/images/tutorial-a5-play.png" width="880" alt="右栏「试聊」标签：直接拿刚生成的产物当人设对话，右上角显示用了几份文件、几段示范">
</p>

### 不像本人：三种改法

1. **手改产物**（最快）：删掉它老挂在嘴边的那句、补上口癖、换掉不像的例句 → 刷新试聊页。反复几轮通常比重新蒸馏管用。
2. **换配方重跑**：`--desc '话少，爱抬杠'`、`--relation 同事`、`--both` 都会改变模型看到的输入。
3. **剔除没依据的条目**：确认是编的就加 `--strict` 重跑，让它直接删而不是标注。

> [!TIP]
> 试聊里若仍显得书面、爱解释、礼貌过头，先怀疑**模型**（换非思考型或更大的模型），再怀疑人设文本——「说话风格」「典型例句」那几行对腔调的影响，比字数预算大得多。

## 常用参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--input` | 必填 | 聊天记录文件或目录（目录会递归读取）。 |
| `--name` | 必填 | 技能目录名和 zip 名。 |
| `--me` | `我` | 你在记录里的昵称，逗号分隔可填多个。 |
| `--target` | 自动 | 蒸馏对象：除你之外说话最多的人。 |
| `--out` | `<工具目录>/dist` | 输出目录，建议显式指定。 |
| `--no-llm` | 关闭 | 离线抽取式蒸馏，不联网、不要 Key。 |
| `--desc` | 空 | 关系 / 性格 / 背景的补充描述，例如 `ENFP，双子座`。 |
| `--relation` | `auto` | `auto` / `恋人` / `朋友` / `同事` / `家人`，只改标题和措辞。 |
| `--both` | 关闭 | 双向蒸馏：多出一份你的画像 `references/self.md`。 |
| `--audience` | `本人` | `公开` 时主技能扮演你自己、自动脱敏并标注只有本人接得住的指代。 |
| `--corpus-mb` | `8` | 参考资料层体积预算（MB），`0` = 不生成。 |
| `--strict` | 关闭 | 校验不过的条目直接剔除，而不是标注保留。 |
| `--no-redact` | 关闭 | 关闭脱敏（默认对整包脱敏：手机号 / 身份证 / 卡号 / 邮箱 / 详细地址）。 |
| `--device` | 无 | 生成后上传到 `<设备IP>:8080`。 |
| `--timeout` / `--max-tokens` | `600` / `0` | LLM 单次请求等待上限（秒）/ 输出上限。 |

完整参数见 `python3 ex_distill.py --help`。

## 排错

| 现象 | 多半是 | 怎么办 |
| --- | --- | --- |
| 没解出消息 / 只解出很少几条 | 格式或编码没对上，被别的解析器抢走 | 看工作台解析诊断（各候选分别解出多少条）；文本类另存 UTF-8 再试 |
| `LLM 返回的不是 JSON` | 模型没按 JSON 说话 | 换一个非思考型模型 |
| `等待 N 秒仍没等到响应` | 读超时 | `--timeout 1200`；若每次卡在 200 秒上下，是网关上限，换模型 |
| `输出被截断（finish_reason=length）` | 思考型模型把预算花在推理上 | `--max-tokens 8192` 或更大 |
| 工作台行为没变 / 端口被占用 | 常驻进程拿着旧代码 / 上次的还没关 | 重启工作台；换 `--port 9000` |
| 条目带 `（未在记录中找到依据）` | 模型可能编了原话 | 看「最相近的原话」，去源文件里搜那句；确认没用就 `--strict` |
| 试聊说「找不到这次运行」/「没有 API Key」 | 任务号只活在进程里 / 离线产物没有 Key | 用表头下拉直接挑 `out/` 下的产物；在「接口」里填一个 Key |
| 试聊里 TA 答得像客服 | 模型太"助手"，或风格行太笼统 | 换模型；或手改「说话风格 / 口头禅 / 典型例句」再刷新 |
| 话都对，就是不像本人 | 少了语境与温度 | 先看「接话方式」（对方说 → TA 回）够不够典型；再调「温度与分寸」那一档 |

## 隐私与安全

> [!WARNING]
> 聊天记录可能包含高度敏感的个人信息。上传或调用外部 LLM 前，请确认数据授权和服务商政策。

- `--no-llm` 时聊天内容只在本机处理；LLM 模式的样本在送出前就已脱敏。
- **默认整包脱敏**：手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址 → `[标签]`，覆盖 `SKILL.md`、`memory.md` 和 `references/`。`--no-redact` 保留原样，**这份包别外发**。
- `--audience 公开` 的产物会被别人读到：程序只标注只有本人对得上的指代，**不替你改写**——发布前逐条确认。
- 试聊页的 API Key 不落盘、不写日志；不要把 Key 写进 README、源码或 Git 提交。
- 工作台只监听 `127.0.0.1`，前端是纯静态文件、不加载 CDN，断网可用。

> [!CAUTION]
> 本文截图用的是仓库自带的合成样例 `samples/demo-chat.json`（昵称「潘小雨 / 小蒯」）。真实产物里是真实昵称和对话，公开任何输出前请检查。

## 进阶

<details>
<summary><b>支持的输入格式</b></summary>

#### 支持的输入

| 类型 | 示例 | 解析行为 |
| --- | --- | --- |
| JSON | `chat.json` | 查 `messages`、`list`、`items`、`data` 等消息数组；正文认 `text`/`content`/`message`/`body`，发送者认 `name`/`remark`/`nickname`。 |
| CSV | `chat.csv` | 自动识别时间、发送者、正文与 `IsSender` 等列名。 |
| TXT | `chat.txt` | `昵称: 内容`、带时间的消息行、QQ 导出文本、WhatsApp 导出。 |
| HTML / MHT / MHTML | `chat.html` | 剥掉 MIME 信封、还原 quoted-printable 后取纯文本（QQ 消息管理器导出走这条）。 |
| 微信 SQLite | `EnMicroMsg.db` | 读已解密库的 `MSG` 表，`--channel` 过滤 `StrTalker`。 |
| Twitter / X | `tweets.js` | 归档里的 `tweets.js`、`direct-messages.js`。 |
| mbox | `archive.mbox` | 邮箱归档，取正文、发件人、日期。 |
| 目录 | `exports/` | 递归读取 `.txt` `.csv` `.json` `.js` `.mbox` `.html` `.htm` `.mht` `.mhtml`。 |

编码按 `utf-8-sig → utf-8 → gb18030 → utf-16` 依次回落；识别靠「后缀 + 内容特征」双重判定，**对不上号会静默降级**，所以第 1 步的诊断才是关键。

微信 PC 4.x 用 wx-cli / WeChatExporter 导出的 `chat.json` 走 JSON 路径，但要把「谁是谁」掰回来：对方的消息 `sender` 是空串（只有本人发言才填昵称），私聊里空串补成会话名、另一侧归一为「我」。

</details>

<details>
<summary><b>LLM 配置与失败回退</b></summary>

#### LLM 配置

| 配置 | 读取顺序 |
| --- | --- |
| API Key | `--api-key` → `LLM_API_KEY` → `MODELSCOPE_API_KEY` → `DASHSCOPE_API_KEY` → `OPENAI_API_KEY` |
| 接口地址 | `--base-url` → `LLM_BASE_URL` → ModelScope 默认地址 |
| 模型名 | `--model` → `LLM_MODEL` → `Qwen/Qwen3-235B-A22B` |

请求是非流式的，要等模型把整段 JSON 写完才返回，所以「慢」是常态：人设那次跑一两分钟很常见，关系记忆要写的 JSON 更长。

跑不动了也不会两手空空：

- **整批失败**（没 Key / 连不上 / 限流 / 返回的不是 JSON）→ 退回离线抽取式蒸馏，产物照样完整。
- **只挂一半**（人设成、关系记忆超时）→ 保住成功的那半，缺的那半用离线补，并在文件里注明来历。
- **上游抖动**（HTTP 200 空壳、读超时）→ 先退避重试，再把这一批对半拆开各跑一次，结果照常合并。
- **一段坏 JSON 不会带走整轮**：只丢那一批。
- **网关抽风**（响应带 BOM、被裹成 SSE、对象后面粘了别的 JSON、裸返回补全文本）→ 四种都能抢救。

</details>

<details>
<summary><b>关系类型</b></summary>

#### 关系类型

`--relation` 只改章节标题和措辞，**不改事实**：`auto` / `恋人` / `朋友` / `同事` / `家人`。默认 `auto` 用称呼与话题词密度判断并打印依据（例如「同事信号最密（每千字命中 5.3 次）」），判断错了 `--relation` 随时覆盖。

| 内部字段 | 恋人 | 朋友 | 同事 | 家人 |
| --- | --- | --- | --- | --- |
| 关系时间线 | 关系时间线 | 认识与相处时间线 | 共事时间线 | 关系时间线 |
| 甜蜜瞬间 | 甜蜜瞬间 | 相处高光 | 配合默契的瞬间 | 温暖瞬间 |
| 争吵模式 | 争吵模式 | 闹别扭的时候 | 分歧与摩擦 | 争执模式 |
| inside_jokes | inside jokes | inside jokes | 你们之间的固定说法 | 家里的梗 |

</details>

<details>
<summary><b>结论校验怎么核</b></summary>

#### 结论校验

每条声称「这是原话」或「这时发生过什么」的结论都会拿回原始记录核对一遍（只用标准库，不联网）：引用核验（原文 / 改写覆盖率 ≥ 0.75 / 未找到）、日期核验、依据核验。引用前常被模型加上「时间 说话人:」前缀，核验会先剥掉再比。

人工核对时，看程序给出的**记录里最相近的那句原话**：

| 你看到的情况 | 说明 | 怎么办 |
| --- | --- | --- |
| 和你的引用是同一句 | 命中，只是前缀或标点差异 | 不用管 |
| 两段文字对不上 | 模型改写了原意，这是真正要核的 | 去源文件里搜那句话，搜不到就是编的 |
| 是一条不相关的系统行 | 记录里确实找不到相近内容 | 重点怀疑 |

处理三选一：不管（产物已带标注）／手改文件／加 `--strict` 重跑（误报也会一起删）。

刻意的边界：**只验「引用是否为真」，不验「语义是否成立」**。「我那天没说」被洗成「我那天说了」这类反转，字符串核验看不出来——那需要几百 MB 的语义模型，与零依赖定位冲突。好在「整段编出来」比「改写反转」常见得多。

</details>

## 开发与验证

```bash
python3 -m py_compile ex_distill.py
python3 ex_distill.py --help

python3 ex_distill.py --input /path/to/chat.json --me '你的昵称' \
  --name smoke-test --out ./dist-smoke --no-llm
unzip -l ./dist-smoke/smoke-test.zip

python3 -m src.web --no-open     # 网页工作台自检：http://127.0.0.1:8765/
```

项目当前未检测到独立测试套件；上述命令覆盖语法、导入、参数解析和无 LLM 打包路径。

## 贡献

欢迎 Issue 和 PR，提交前请：

- [ ] 运行 `python3 -m py_compile ex_distill.py`
- [ ] 用脱敏或合成数据验证解析行为
- [ ] 不提交聊天记录、API Key 或生成的人设文件
- [ ] 同步更新相关文档

## 致谢

- [agenmod/immortal-skill](https://github.com/agenmod/immortal-skill)：数字分身、分维度蒸馏与证据意识的思路来源。
- [shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter)：QQ 聊天记录 JSON 导出。
- [93857536-pixel/WeChatExporter](https://github.com/93857536-pixel/WeChatExporter)：微信聊天记录导出。

## 许可证

MIT
