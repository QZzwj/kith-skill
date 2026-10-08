# 当前质量增强任务

- 已完成：七项质量功能、工作台操作、双语说明和 CI，见 docs/quality-roadmap.md。
- 实现文件：src/quote_links.py、semantic.py、claims.py、holdout.py、retrieval.py、checkpoint.py；生成、增量、试聊、A/B 和原有 14 个标签均已接入。
- 验证：新增 27 项边界及本地 HTTP 测试；浏览器新旧流程全部通过，无浏览器错误、控制台错误或失败请求；冒烟验证退出码 0 与临时目录清理。
- 约束：标准库运行，旧包兼容，默认脱敏，本地评审/留出/检查点不进 ZIP；不覆盖用户改动。
- 本地收尾：92 项单测、独立进程冒烟、Edge 浏览器验收、JS 语法、Python 编译及 Git 差异检查通过。CI 配置已完成，远端 Windows/Linux 执行结果尚待 GitHub Actions 验证。未使用真实模型判断语感。
