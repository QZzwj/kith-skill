# 教程截图 / Tutorial screenshots

这组图从当前工作台实际操作中截取，使用仓库合成样例 `samples/demo-chat.json`（123 条消息，潘小雨 / 小蒯）离线生成 `demo-persona`。中文图在本目录，英文图在 `en/`；原有 7 张的文件名和尺寸保留，另增加 7 张功能图。

These captures show the current workbench with `demo-persona` generated offline from the synthetic sample (123 messages, 潘小雨 / 小蒯). Chinese images live here and English images in `en/`. The original seven filenames and dimensions are preserved, with seven additional feature images per language.

| 内容 / View | 中文 / Chinese | English | 尺寸 / Pixels |
| --- | --- | --- | --- |
| 工作台首页 / Empty workbench | [workbench.png](workbench.png) | [workbench.png](en/workbench.png) | 1440 × 960 |
| 解析诊断 / Parsing diagnosis | [tutorial-a2-diagnose.png](tutorial-a2-diagnose.png) | [tutorial-a2-diagnose.png](en/tutorial-a2-diagnose.png) | 1440 × 960 |
| 配置 / Configuration | [tutorial-a3-config.png](tutorial-a3-config.png) | [tutorial-a3-config.png](en/tutorial-a3-config.png) | 1440 × 960 |
| 运行完成日志 / Completed run | [tutorial-a4-log.png](tutorial-a4-log.png) | [tutorial-a4-log.png](en/tutorial-a4-log.png) | 1440 × 960 |
| 试聊回复 / Try-chat reply | [tutorial-a5-play.png](tutorial-a5-play.png) | [tutorial-a5-play.png](en/tutorial-a5-play.png) | 2880 × 2000 |
| 技能预览 / Skill preview | [skill-preview.png](skill-preview.png) | [skill-preview.png](en/skill-preview.png) | 1440 × 3000 |
| 结论校验 / Verification | [verify.png](verify.png) | [verify.png](en/verify.png) | 1440 × 3000 |
| 情境路由 / Situation routing | [scenarios.png](scenarios.png) | [scenarios.png](en/scenarios.png) | 1440 × 960 |
| 具体性评分 / Specificity scores | [evidence.png](evidence.png) | [evidence.png](en/evidence.png) | 1440 × 960 |
| 覆盖矩阵 / Coverage matrix | [coverage.png](coverage.png) | [coverage.png](en/coverage.png) | 1440 × 960 |
| 原话高亮与前后文 / Highlighted source and context | [messages.png](messages.png) | [messages.png](en/messages.png) | 1440 × 960 |
| 补标确认 / Scoped annotation | [updates.png](updates.png) | [updates.png](en/updates.png) | 1440 × 960 |
| 新增、重复与冲突预览 / Additions, duplicates and conflicts | [incremental.png](incremental.png) | [incremental.png](en/incremental.png) | 1440 × 960 |
| A/B 回复与人工选择 / A/B replies and human choice | [ab.png](ab.png) | [ab.png](en/ab.png) | 1440 × 960 |

## 演示约定 / Capture details

- 英文版仅在截图时翻译控件、提示和日志。应用尚未提供英文界面；聊天原话、人物特点和生成的 Markdown 保留中文，方便核对出处。
- 试聊和 A/B 请求由本地模型替身响应，不调用外部模型。A 复用合成样例中的接话，B 返回固定礼貌答语，展示静态检查和人工选择流程，不能视为模型性能结论。Key 是临时测试值，截图前清空，脚本检查它未写入产物。
- 增量截图加入 1 条重复消息和 2 条合成的新消息，展示去重和旧承诺的潜在冲突，只预览、不合并。补标内容是演示用人工说明。
- 日志中的临时输出目录仅在显示时缩写为 `out/`，上传目录缩写为原文件名。其他计数、引用、回复和检查结果均来自实际操作。

- English controls, notices and logs are translated only during capture. The app has no English UI yet; original chat, traits and generated Markdown remain Chinese for source review.
- Local model substitutes answer try-chat and A/B requests without contacting an external model. A replays sample exchanges; B returns a fixed polite reply to demonstrate static checks and human preference, not model performance. A disposable test key is cleared before capture and checked for absence from generated files.
- Incremental preview uses one duplicate and two synthetic new messages to show deduplication and a possible conflict with an old promise. No merge is applied. Annotations are illustrative human input.
- Displayed temporary output paths are shortened to `out/`, and upload paths to the source filename; counts, sources, replies and checks come from actual workbench actions.

## 重新截图 / Regenerate

在项目根目录运行 / Run from the repository root:

```powershell
python -m pip install playwright
python tests/capture_tutorials.py --browser-channel msedge
```

没有 Edge 时可安装 Playwright Chromium，然后省略通道参数 / Without Edge, install Playwright Chromium and omit the channel:

```powershell
python -m playwright install chromium
python tests/capture_tutorials.py
```

脚本使用无头浏览器与临时 HTTP 工作台，等候各页面完成加载及操作结果，验证全部 28 张尺寸和浏览器错误后统一替换图片；上传、产物、进程和临时目录在结束时清理。Playwright 仅用于开发截图，不改变项目运行时的标准库依赖。

The script uses a headless browser and temporary HTTP workbench, waits for rendered actions, validates all 28 image sizes and browser errors, then publishes the set. Uploads, generated artifacts, server and temporary directories are cleaned up. Playwright is a development-only capture dependency.
