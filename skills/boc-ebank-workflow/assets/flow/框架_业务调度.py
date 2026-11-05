from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


def _finish_time(business: contract.BusinessExecutionModel) -> None:
    """记录一项业务的结束时间和耗时。"""

    business.end_time = Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss")
    if business.start_time:
        business.duration_seconds = Time.DateDiff(
            "s",
            Time.CDate(business.start_time, "yyyy-mm-dd hh:mm:ss"),
            Time.Now(),
        )


def _append_log(
    account: contract.StandardAccountModel,
    business: contract.BusinessExecutionModel,
    status: str,
    detail: str,
) -> None:
    """向账号执行记录中追加一条容易阅读的业务事件。"""

    account.execution_log.append(contract.ExecutionLogEntryModel(
        timestamp=Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss"),
        stage="business_{}".format(business.business_type),
        status=status,
        detail=detail,
    ))


def _update_account_status(account: contract.StandardAccountModel) -> None:
    """根据账号实际启用的全部业务更新总体状态。"""

    statuses = [business.status for business in account.businesses]
    account.error_message = "；".join(
        business.error_message
        for business in account.businesses
        if business.status == "failed" and business.error_message
    )
    if not statuses or all(status == "skipped" for status in statuses):
        account.status = "skipped"
    elif all(status in ("success", "no_data", "skipped") for status in statuses):
        account.status = "success"
    elif all(status == "failed" for status in statuses):
        account.status = "failed"
    elif any(status == "failed" for status in statuses):
        account.status = "partial_success"
    else:
        account.status = "pending"


def _run_business(
    business_type: int,
    accounts: list[contract.StandardAccountModel],
    task: contract.StandardTaskModel,
) -> None:
    """执行一个已注册业务；本函数不解释业务编号和产物内容。"""

    for account in accounts:
        business = account.require_business(business_type)
        if business.status in ("skipped", "success", "no_data"):
            continue

        business.status = "processing"
        business.start_time = Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss")
        business.attempt_count += 1
        business.result = None
        _append_log(account, business, "processing", "开始执行{}".format(business.business_name))

        try:
            context = contract.BusinessArgumentModel(
                business_type=business.business_type,
                business_name=business.business_name,
                account=account.info,
                query_dates=account.query_dates,
                ukey_number=task.devices.ukey.ukey_number,
                output_folder=task.output.business_folder,
            )
            result = ebank.run_business(business_type, context)
            business.result = result
            business.error_code = result.code
            business.error_message = "" if result.code == 0 else result.message
            _finish_time(business)

            if result.code == 0:
                business.status = "success"
                _append_log(account, business, "success", "{}执行成功".format(business.business_name))
            elif result.code == 2:
                business.status = "no_data"
                _append_log(account, business, "no_data", "{}没有可处理数据".format(business.business_name))
            else:
                business.status = "failed"
                _append_log(account, business, "failed", "{}执行失败".format(business.business_name))
        # apa-lint: disable-next-line preserve-exception-traceback -- 单项业务失败需记录结果并继续执行同一账号的后续业务。
        except Exception as error:
            ebank.save_exception_screenshot("业务调度_{}_{}".format(account.info.bank_account, business.business_name))
            _finish_time(business)
            business.status = "failed"
            business.error_code = 3
            business.error_message = str(error)
            _append_log(account, business, "failed", "{}执行异常：{}".format(business.business_name, error))
            Log.Error("[业务调度] 账号{}的{}异常：{}".format(
                account.info.bank_account,
                business.business_name,
                error,
            ))
        _update_account_status(account)


def _accounts_to_process(
    task: contract.StandardTaskModel,
    retry_count: int,
) -> list[contract.StandardAccountModel]:
    """首次处理待处理账号，整轮重试只处理仍有失败业务的账号。"""

    if retry_count == 0:
        return [account for account in task.accounts if account.status == "pending"]
    return [
        account
        for account in task.accounts
        if any(business.status == "failed" for business in account.businesses)
    ]


def _business_error_message(task: contract.StandardTaskModel) -> str:
    """汇总本轮失败业务，供异常收尾和通知直接读取。"""

    messages: list[str] = []
    for account in task.accounts:
        for business in account.businesses:
            if business.status != "failed":
                continue
            messages.append("{}的{}失败：{}".format(
                account.info.bank_account,
                business.business_name,
                business.error_message or "未取得具体原因",
            ))
    return "；".join(messages)


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """按任务列出的业务编号依次执行已注册模块，并释放网银会话。

    框架只负责遍历、状态、重试和异常，不识别流水、余额等具体业务。
    新增业务时只需新增 ``业务_*.py`` 并在运行方案中调用 ``use_business``。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 尚未生成标准任务，或任务中的业务没有注册实现。
    """

    # @step 检查标准任务并筛选本轮待处理账号。
    state = GlobalVariables["ebank"]
    if state.task is None:
        raise RuntimeError("业务调度前必须先完成环境初始化。")

    task = state.task
    accounts = _accounts_to_process(task, state.run.retry_count)
    Log.Info("[业务调度] 开始，银行={}，待处理账号数={}".format(state.bank_name, len(accounts)))

    # @step 按任务顺序执行已启用的网银业务。
    for business_type in dict.fromkeys(task.business_types):
        _run_business(business_type, accounts, task)

    # @step 汇总本轮业务错误。
    state.run.has_error = any(
        business.status == "failed"
        for account in task.accounts
        for business in account.businesses
    )
    state.run.error_message = _business_error_message(task) if state.run.has_error else ""

    # @step 释放网银会话、设备和相关进程。
    Log.Info("[业务调度] 业务执行结束，开始释放网银会话")
    if not ebank.cleanup_login_resources(argument):
        state.run.has_error = True
        state.run.error_message = "；".join(
            message
            for message in (state.run.error_message, "网银会话或设备清理失败")
            if message
        )

    # @step 校验并保存更新后的标准任务。
    state.task = contract.parse_standard_task(task)
    Log.Info("[业务调度] 完成，存在失败业务={}".format(state.run.has_error))
    return argument
