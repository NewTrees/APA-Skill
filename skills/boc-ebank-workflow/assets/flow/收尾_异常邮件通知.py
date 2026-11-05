from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


# 客户的邮件标题或正文格式变化时，Agent只修改本模块。
MAIL_SUBJECT = "{bank_name}运行失败"
MAIL_RETRY_COUNT = 3


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """发送包含任务、账号和登录状态的异常通知邮件。

    本模块只负责一般异常通知，不写汇总表、不停用U盾，也不释放设备。

    Args:
        argument: 流程块之间传递的共享字典；异常说明由框架写入运行状态。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    # @step 检查异常通知所需的配置和任务数据。
    state = GlobalVariables["ebank"]
    if state.config is None or state.source_task is None:
        Log.Warn("[异常邮件] 配置或原始任务尚未读取，无法发送异常邮件")
        return argument

    # @step 汇总任务、账号和登录错误信息。
    task = state.task
    account_errors = [] if task is None else [
        "{}：{}".format(account.info.bank_account, account.error_message)
        for account in task.accounts
        if account.error_message
    ]
    error_message = state.run.error_message or "流程异常结束，但没有取得具体错误信息。"
    content = (
        "{}流程异常中断\r\n"
        "异常信息：{}\r\n"
        "账户错误：{}\r\n"
        "任务ID：{}\r\n"
        "启用流水模板转换：{}\r\n"
        "U盾编号：{}\r\n"
        "登录状态：{}\r\n"
        "发生时间：{}"
    ).format(
        state.bank_name,
        error_message,
        "；".join(account_errors),
        state.source_task.task_id,
        state.source_task.enable_convert_template,
        state.source_task.ukey_number,
        task.login.status if task is not None else "尚未初始化",
        Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss"),
    )
    # @step 发送异常通知邮件。
    config = state.config
    mail = contract.require_config_section(config.mail, "异常邮件")
    ebank.send_email_with_retry(
        mail.server,
        mail.port,
        mail.account,
        mail.password,
        mail.account,
        str(mail.receiver).split(","),
        MAIL_SUBJECT.format(bank_name=state.bank_name),
        content,
        MAIL_RETRY_COUNT,
    )
    return argument
