# 普通 Windows PowerShell 前端验证

在普通、非提权 Windows PowerShell 中运行。请不要从 Codex 内置命令环境代跑这组命令，因为该环境此前对 Node 原生 realpath 的表现与普通 PowerShell 不同。

```powershell
Set-Location -LiteralPath 'D:\考研跑通项目'
.\scripts\verify-frontend-ordinary.ps1
```

脚本会创建一个新的目录：

`storage/quality-audits/naiwa-frontend-ordinary-<运行时间>-r1/`

其中保存 Node/npm 版本、项目正式目录检查、项目根目录/main.ts/node_modules 的 `realpathSync.native` 与 `fs.promises.realpath` 结果，以及指定的两个学习状态回归文件、完整 Vitest、TypeScript 检查和 Vite 生产构建的独立 stdout、stderr、退出码与耗时。Vite 构建输出写入该次审计目录，不覆盖 `frontend/dist`。任何一个步骤失败后，脚本仍会运行其余步骤；Vitest 若未实际收集测试会单独判失败。

执行完请把 `results.json` 和相应失败日志交给开发者。脚本不启动服务、不访问数据库、不调用模型，也不会清理历史审计记录。
