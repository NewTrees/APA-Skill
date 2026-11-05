"""网银流程异常结束入口。"""

from typing import Any, NoReturn

from apa_runtime import *
import 公共_网银能力 as ebank


def _original_error(argument: dict[str, Any]) -> BaseException:
    """取得需要在清理完成后继续抛出的原始异常。"""

    # Message/File/Line/CallStack 这几个键承载真实错误信息。
    message = argument.get("Message")
    file_name = argument.get("File")
    line_number = argument.get("Line")
    if str(message) != "" and str(message) != "None":
        location = ""
        if file_name or line_number is not None:
            location = "（位置：{} 第{}行）".format(
                file_name or "",
                line_number or "",
            )
        return RuntimeError("{}{}".format(message, location))

    # 运行方案可能在第一个公共入口执行前就因模块导入失败。此时项目变量仍是
    # main.prjp 中的空占位字典，不能假设它已经转换为 EbankStateModel。
    state = GlobalVariables["ebank"]
    run_state = getattr(state, "run", None)
    global_error = getattr(run_state, "error_message", "")
    if str(global_error) != "":
        return RuntimeError(str(global_error))
    return RuntimeError("流程异常结束（未捕获到具体异常信息）")


def main(argument: dict[str, Any]) -> NoReturn:
    """执行异常收尾和最终清理，然后重新抛出原始异常。

    Args:
        argument: 异常连线传入的错误字典，包含 ``Message``、``File``、
            ``Line`` 和 ``CallStack``。

    Raises:
        BaseException: 原始业务异常。收尾阶段的错误附加为补充信息。
    """

    # @step 保留触发异常分支的原始错误。
    error = _original_error(argument)
    # @step 执行异常收尾、释放资源并重新抛出原始错误。
    ebank.finish_failure(argument, error)
