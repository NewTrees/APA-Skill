from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


# 这是密码错误后的客户处置策略。数据库表或通知方式变化时，Agent只修改本模块。
PASSWORD_ERROR_TEXT = "密码错误"
DISABLE_RETRY_COUNT = 3
MAIL_RETRY_COUNT = 3


def _disable_ukey_task(state: contract.EbankStateModel) -> bool:
    """在客户数据库中停用当前银行和U盾对应的任务。"""

    config = state.config
    source_task = state.source_task
    if config is None or source_task is None:
        raise RuntimeError("密码错误处置前必须先读取运行配置和任务数据")
    database_config = contract.require_config_section(
        config.database,
        "密码错误数据库处置",
    )
    database = None
    last_error = ""
    for attempt in range(1, DISABLE_RETRY_COUNT + 1):
        try:
            database = Database.CreateDB("MySQL", {
                "host": database_config.host,
                "port": str(database_config.port),
                "user": database_config.username,
                "password": database_config.password,
                "database": database_config.database,
                "charset": "utf8",
            })
            sql = "UPDATE {} SET status = 0 WHERE status = 1 AND bank_name = '{}' AND ukey_no = '{}';".format(
                database_config.table,
                state.bank_name,
                source_task.ukey_number,
            )
            Database.ExecuteSQL(database, sql, {"args": []})
            Database.CloseDB(database)
            database = None
            last_error = ""
            Log.Info("[密码错误处置] 已停用当前U盾任务")
            return True
        # apa-lint: disable-next-line preserve-exception-traceback -- 停用任务按固定次数重试，最终错误通过返回值和告警邮件表达。
        except Exception as error:
            last_error = str(error)
            Log.Warn("[密码错误处置] 第{}次停用U盾失败：{}".format(attempt, error))
            if database is not None:
                try:
                    Database.CloseDB(database)
                # apa-lint: disable-next-line preserve-exception-traceback -- 关闭失败不覆盖触发重试的停用任务错误。
                except Exception:
                    pass
                database = None
            if attempt < DISABLE_RETRY_COUNT:
                Delay(2000)
    Log.Warn("[密码错误处置] U盾任务停用未确认成功：{}".format(last_error))
    return False


def _notify_operations(
    state: contract.EbankStateModel,
    error_message: str,
) -> None:
    """通知运维人员检查已经发生密码错误的U盾。"""

    config = state.config
    source_task = state.source_task
    if config is None or source_task is None:
        raise RuntimeError("密码错误通知前必须先读取运行配置和任务数据")
    mail = contract.require_config_section(config.mail, "密码错误通知邮件")
    ebank.send_email_with_retry(
        mail.server,
        mail.port,
        mail.account,
        mail.password,
        mail.account,
        str(mail.receiver).split(","),
        "{}的{} U盾账号报密码错误".format(
            state.bank_name,
            source_task.ukey_number,
        ),
        "已尝试在数据库关闭该任务，请运维立即检查。\r\n{}".format(error_message),
        MAIL_RETRY_COUNT,
    )


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """密码错误时停用当前U盾任务，并发送专门的运维通知。

    没有发生密码错误时本模块直接返回。它不负责一般异常邮件、结果汇总或
    设备断开；这些职责由其他收尾模块和公共生命周期分别完成。

    Args:
        argument: 流程块之间传递的共享字典；异常说明由框架写入运行状态。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 确认发生密码错误，但运行配置或原始任务不完整。
    """

    # @step 判断本次异常是否属于密码错误。
    state = GlobalVariables["ebank"]
    error_message = state.run.error_message
    if PASSWORD_ERROR_TEXT not in error_message:
        return argument
    if state.config is None or state.source_task is None:
        raise RuntimeError("密码错误处置需要完整的运行配置和原始任务。")

    # @step 在客户数据库中停用当前U盾任务。
    _disable_ukey_task(state)

    # @step 通知运维人员处理密码错误。
    _notify_operations(state, error_message)
    return argument
