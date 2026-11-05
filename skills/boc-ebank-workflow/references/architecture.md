# 中国银行企业网银流程架构

来源：中国银行_Google 项目（v2.1.0，2026-09 四业务验收通过）。本文件是快速参考；完整业务规则、元素清单、部署前提见 `assets/docs/需求流程说明文档.md`。

## 模块分层

| 层 | 流程块 | 选择方式 |
|---|---|---|
| 框架编排（连线） | `配置_运行方案` → `接入_任务数据` → `框架_环境初始化` → `框架_登录判断` → `框架_业务调度` → `框架_交付调度` → 异常/重试/结束判断 | `main.prjp` 主链路 |
| 公共（未连线） | `公共_数据契约`（Pydantic 契约）、`公共_网银能力`（use_* 注册）、`公共_网银页面操作`（BFE 日历面板 JS 函数） | 具名函数调用 |
| 会话 | `会话_登录`、`会话_网银安全退出` | `use_login` / `use_logout` |
| 业务 | 1=流水、2=余额、3=回单、4=对账单（`业务_其它` 为占位） | `use_business(编号, 模块)` |
| 交付 | `交付_流水数据转换` | `use_delivery([...])` |
| 收尾 | `收尾_执行结果汇总`、`收尾_密码错误处置`、`收尾_异常邮件通知` | `use_finish_handlers(success=, failure=)` |
| 设备 | `HUB_新同事`、`密码输入器_KeyBox`、`密码输入器_新同事` | `use_hub` / `use_password_input_device` |

调整运行方案只改 `配置_运行方案.py` 的 `use_*` 调用，不改 `框架_*`。

## 全局状态

唯一流程变量 `GlobalVariables["ebank"]`（`公共_网银能力` 首次调用时建立）：
- `config`：整理后的运行配置（重试上限、输出、邮件、模板等，来自 Asset `EbankConfig`）。
- `source_task`：DataQueue 队列原始任务（`SourceTaskModel`）。
- `run`：运行状态；`main.prjp` 的"异常？"节点读 `run.has_error or run.has_delivery_error`，"重试？"节点读 `retry_count < max_retry_count`（上限 `Base.MaxRetryNum`）。

## 输入契约要点

- Asset `EbankConfig`（JSON，`AssetConfigModel` 校验）：`Base`（重试次数、`OutputFolder`、`XTSConfigPath`、模板路径等）、`Set`（SMTP、MySQL、XTS 鉴权）、`User`（邮件收件人）。
- DataQueue 任务（`SourceTaskModel`）：`BusinessType` 列表、U盾/密码输入器参数（HUB 接入需 `ukey_ip/port/hub_port`）、`accounts[]`（账号、起止日期必填）。
- `接入_任务数据` 会核对任务设备参数与运行方案选择的一致性，不匹配即报错终止。

## 登录链路要点

设备接入 → 清理残留进程（chrome、BOCAssistant、CryptoKitHost 等）→ 启动网银助手"一键修复" → Chrome 打开 iGTB 登录页 → 数字证书登录 → Windows 证书选择框（桌面元素）→ KeyBox 输入证书密码 → 等待用户名自动刷新 → 输入登录密码 → 登录。

登录结果码：0 成功；1 证书密码错误；2 登录密码错误；3 可重试错误；4 密码已提交结果不明确（**禁止重试**）。

## 维护边界

不许修改：`框架_*` 流程块；`公共_数据契约.py` 既有字段语义；密码安全约束路径；`main.prjp` 既有节点 ID 与连线。可修改：`配置_运行方案.py`、`接入_任务数据.py` 的平台参数/队列名、各业务/会话/设备/交付/收尾实现（保持统一契约）、Asset 配置。

## 界面库说明

界面库（`ui/`）是二进制资源，不在本 Skill 内。新建项目后需按 `assets/docs/需求流程说明文档.md` 第 5 章的元素清单（如 `块级元素<div>_数字证书登录`、`流水查询_日期面板`、`网银_顶部账号文本`、`对账单_月份面板_月份单元格_通配` 等）重新探索、验证并拾取入库，再运行流程。
