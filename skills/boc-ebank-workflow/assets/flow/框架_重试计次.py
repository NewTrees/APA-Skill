from typing import Any
from apa_runtime import *
import 公共_网银能力 as ebank


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """重试计次。

    对重试次数加 1 并复位异常标记，通知用户当前重试进度。

    Args:
        argument: 流程块共享字典。本步骤通过 ``GlobalVariables`` 读取和更新
            重试及异常状态，不要求字典包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """
    state = GlobalVariables["ebank"]
    bank_name = state.bank_name
    retry_count = state.run.retry_count
    max_retry_count = state.run.max_retry_count
    run_state = state.run

    Log.Info("[整体重试] 开始准备下一轮，银行={}".format(bank_name))

    # @step 清理上一轮可能残留的会话、设备和进程。
    ebank.cleanup_for_retry(argument)

    # @step 增加重试次数。
    run_state.retry_count = retry_count + 1
    Log.Debug(
        "[整体重试] retry_count: {} -> {}".format(
            str(retry_count),
            str(run_state.retry_count),
        )
    )

    # @step 复位全局异常标记。
    run_state.has_error = False
    run_state.has_delivery_error = False
    run_state.error_message = ""
    Log.Debug("[整体重试] 异常状态已复位")

    # @step 通知重试进度。
    Log.Info(
        "[整体重试] 即将执行第{}/{}次重试".format(
            str(run_state.retry_count),
            str(max_retry_count),
        )
    )
    return argument
