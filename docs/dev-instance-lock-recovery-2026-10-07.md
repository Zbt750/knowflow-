# 本地后端 instance_lock_lost 恢复修复

日期：2026-10-07，Asia/Shanghai。结果：当前开发服务恢复，真实今日学习页面通过只读检查。

## 原因与证据

用户执行 start-dev 后看到“已在运行、全部就绪”，但8000的健康接口实际返回503、`instance_lock_lost`。旧脚本在端口已监听时跳过健康检查。

失效实例PID 20920于09:22启动，启动清单为 `tmp/phase4c_20261007/runtime-frozen-manifest.json`。数据库日志 `tmp/phase4c_20261007/postgres.log` 记录10:57:42持锁会话被管理员命令终止；对应后端日志 `runtime-frozen-stderr.log` 在10:57:43记录持锁连接执行SELECT 1失败。该实例按现有保护策略停止接受请求，但进程和端口仍存在。现存日志不足以确定是谁发起了终止命令，不能据此归因于某个具体操作者。

因此需要修正“已监听=已就绪”的启动判断和失效实例恢复。独占锁丢失后的503保护仍然保留；不让已失去所有权的进程继续写业务数据。

## 修改

- `scripts/dev-service-health.ps1`：健康响应必须满足ok、database connected、environment dev；HTTP 503保留业务错误码。重启前核对本项目启动器、tmp内清单、workspace、module、bind、PID和实际创建时间。
- `scripts/start-dev.ps1`：既有监听进程也要检查health；仅对确认为本项目的instance_lock_lost实例停止并重新启动。其他来源进程不能仅因占用8000就被结束。启动后再确认健康，失败不会报全部就绪。健康实例重复执行脚本时保持原PID。
- `scripts/run-backend.cmd`：复用现有launch helper写唯一启动清单，后续丢锁时能确定归属；后台运行，保留追加日志，不删除旧日志。
- `backend/errors.py`：失锁提示改为中文，说明需要重新运行启动脚本。错误码和503契约不变。

没有修改独占锁、Evidence、Grading、Planner、题库可信度或毕业规则。

## 实际恢复与验证

修复后的原启动脚本识别并重启失效PID 20920，新后端PID 28196。PostgreSQL和前端保持运行。健康接口约14.8秒恢复ok/connected；retrieval ready，worker running。

真实Chrome只读访问 `http://127.0.0.1:5173/study`：study区域可见，页面未显示instance_lock_lost；page error、console error、API失败均为0。页面未提交作答或奶蛙请求，也未调用模型。再次执行start-dev后后端仍为28196，验证健康服务不会被重复重启。

相关回归28 passed、0 skipped，包含健康/503、未知进程与外部清单拒绝、PID复用/时间不匹配、PowerShell5语法及后端丢锁拒绝请求/重复实例拒绝。首次受限环境无法建立pytest临时目录，普通权限下以新的项目tmp目录运行完整组通过；不是业务逻辑失败。OpenAPI 46路径和git diff --check通过。

生产 `protected-before.json` 与 `protected-after.json` 中学习状态、Attempt、Evidence、DailyPlan/PracticeItem、策略、人审戳和题库trust指纹一致；库存及策略源码hash一致。题库依然518总题、160可练题。日志、浏览器核对与回归输出位于 `tmp/instance_lock_repair_20261007/`。

## 保护报告的边界

业务数据指纹一致可以证明相应记录未被改变，不能证明运行中的数据库连接从未受影响。本次明确查到旧后端从10:57起失锁；此前测试报告不能作为“生产服务一直可用”的证据。当前服务已恢复，但本次修复不改变之前Evidence-driven Planner事实解释失败的结论。
