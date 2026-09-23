# Windows 打包版白屏：一次性取证

这是一份诊断入口，不是白屏修复版。最初客户日志缺少入口资源响应类型和首条前端异常；后来返回的现场报告已确认 JS 被标成 text/plain，浏览器拒绝执行。对应源码修复与验证见 [白屏修复记录](windows-white-screen-mime-fix.md)。诊断工具本身仍不改产品。

## 发给故障用户

请先正常退出 Lumina Studio 本体，然后完整解压诊断工具到一个可写目录。打开安装目录下该版本的文件夹，将 **Lumina Studio.exe** 拖到工具包中的 `diagnose_packaged_startup.cmd` 上。不要拖小启动器 EXE，也不需要重新安装或激活。

工具会用现有本体打开一份全新的临时资料，在工具目录生成独立 `report-…` 文件夹。原安装文件、原设置、项目和授权不会被修改。请不要在诊断窗口处理实际作品。

等约 30 秒，命令窗口显示 `Evidence saved` 后，记录本体是正常界面还是白屏；若正常，试一下切到设置页再返回。然后正常退出这个测试本体并确认退出。超过提示后的 120 秒仍未退出，工具会关闭仅由它启动的测试进程树。

请只发回该文件夹中的 **startup-report.json**，并说明“白屏/正常、是否能切换页面”。不要发送 `data` 子目录。报告保存在本机，不会自动上传；发送前可自行查看。无需再发之前那批相同日志。

报告不包含回执、激活码、请求头、接口响应内容或页面完整文本；URL 去掉查询和签名参数。错误文本进行了路径/常见凭证脱敏，但自由格式错误可能包含额外内容，因此仍应在分享前检查。

## 维护者使用

将 `scripts/diagnose_packaged_startup.cmd`、`scripts/diagnose_packaged_startup.cjs` 与锁定的 Playwright 1.58.2 / playwright-core 1.58.2 放在工具包中。`node_modules` 必须是完整实体目录，不能包含指向打包机器的 pnpm junction。保留依赖许可证。无需 Chromium 下载；工具使用目标包自带的 Electron 35.7.5 / Node 22.16.0。若发行包禁用了 Electron RunAsNode 或调试支持，此入口不适用，应明确记录工具启动失败，不能计为本体白屏。

工具可由 Node 直接调用：

```text
node scripts/diagnose_packaged_startup.cjs <本体EXE绝对路径> <不存在的输出目录绝对路径> <node_modules绝对路径>
```

采集实际 HTTP JS/CSS 响应状态、Content-Type、字节数、哈希和包内文件一致性；主页的 `documentProbe` 是另一次 GET，明确不冒充首次导航响应。Console/异常按页面 URL 分开，隐藏的旧存储迁移 file:// 页错误不能当作实际 HTTP 主界面的错误。

同时记录根节点布局、已知设置/转换入口、文件输入是否出现，以及握手状态、Electron/GPU 特性状态、preload/renderer 退出信息。字段只描述观察，不自动认定界面可用或客户根因；实际页面切换由用户确认。监听安装前发生的事件、超出观察期的故障及未复现的旧资料问题仍可能漏采。新资料正常时，保留原资料，不擅自清空或迁移。

## 当前定位范围

故障包：`2.0.0-beta.20260922055719`，ZIP SHA-256 `8b5a8435e9165558f1fe8bad964d0d5605987dba820b2e65c08eaf59abacf628`。

Studio 源码 `eb1c5ffb01eb8f979403f44ad6ae16db1ed142aa`，发行记录 buildId `eb1c5ffb-2a6fc79-20260922`。本机原包实际 HTTP JS/CSS 类型正确、响应字节匹配包内文件，界面初始化和设置页交互通过；这不等于故障用户已恢复，也不能据此判定 GPU 根因。

此诊断入口不修改产品启动、支付、安装、增量、资料迁移或安全策略。现场根因确认后的静态资源类型修复位于 api/app.py；本工具仍可用于收集候选包复测结果。
