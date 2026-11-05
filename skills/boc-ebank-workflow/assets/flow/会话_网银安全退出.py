import os, json, copy, decimal, random  # noqa: F401
from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


def _click_logout_entry() -> None:
    """在网银页面点击右上角的安全退出入口。

    Raises:
        Exception: 点击安全退出链接失败时抛出，由上层记录后继续尝试收尾。
    """
    # @step 点击右上角“退出-安全退出”。
    ebank.wait_for_element(Hover_ElementSelect("文本<span>_退出-安全退出"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("文本<span>_退出-安全退出"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 500, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})


def _confirm_logout_dialog() -> bool:
    """在安全退出确认弹窗中点击确定。

    Returns:
        bool: 确定按钮出现并点击成功时返回 ``True``，否则返回 ``False``。
    """
    # @step 在安全退出确认弹窗中点击“确定”。
    confirm_visible = ebank.wait_for_element(Hover_ElementSelect("按钮<button>_确定2-安全退出"), 10, 1000)
    if not confirm_visible:
        Log.Warn("未出现安全退出确认弹窗。")
        return False
    Mouse.Action(Hover_ElementSelect("按钮<button>_确定2-安全退出"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 500, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    return True


def _release_ukey(argument: dict[str, Any]) -> bool:
    """断开HUB上的U盾连接并下电（界面操作待实现）。

    Args:
        argument: 当前流程参数字典，仅透传给公共生命周期清理逻辑。

    Returns:
        bool: U盾断开成功且页面确认成功时返回 ``True``。
    """
    errors = ebank.release_ukey_connection(argument)
    for error in errors:
        Log.Warn("U盾断开或下电失败：{}".format(str(error)))
    if errors:
        return False

    # TODO(中行页面操作): 如中行退出页面要求确认U盾已拔出（如“我已拔出”提示），
    # 拾取对应元素后在此等待并点击；不需要时直接返回True。
    return True


def _close_browser_and_window() -> None:
    """关闭网银窗口并结束Chrome浏览器进程。

    单项失败只记录警告，不阻止其余清理动作。
    """
    # @step 结束Chrome浏览器进程。
    App.Kill("chrome.exe")
    bRet = UiElement.Exists(Hover_ElementSelect("窗口_温馨提示"),{"bContinueOnError":False,"iDelayAfter":300,"iDelayBefore":200,"bWaitDOMReady":True})
    if bRet:
        Mouse.Action(Hover_ElementSelect("窗口_确定"),"left","click",10000,{"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [],"sSimulate": "simulate", "bMoveSmoothly": False})
        Log.Info("点击了证书拔出提示框")
    Log.Info("已结束浏览器进程。")


def _safe_logout_page(argument: dict[str, Any]) -> bool:
    """按网银要求的顺序执行安全退出。

    顺序为：点击右上角安全退出并在确认弹窗点确定，断开HUB上的U盾并确认
    成功，最后结束Chrome浏览器进程并关闭网银窗口。

    Args:
        argument: 当前流程参数字典，用于公共生命周期释放U盾。

    Returns:
        bool: 页面安全退出全流程成功时返回 ``True``，否则返回 ``False``。
    """
    logout_succeeded = False
    try:
        _click_logout_entry()

        # 点击安全退出后，在确认弹窗中点击确定提交退出。
        confirm_succeeded = _confirm_logout_dialog()

        # 页面确认退出后，先断开HUB上的U盾，确认断开成功后再结束浏览器。
        ukey_released = _release_ukey(argument)
        if not ukey_released:
            Log.Warn("U盾断开未确认成功，继续尝试完成页面退出。")

        # 结束Chrome浏览器进程并关闭网银窗口。
        _close_browser_and_window()

        logout_succeeded = ukey_released and confirm_succeeded
    # apa-lint: disable-next-line preserve-exception-traceback -- 页面退出失败后仍需尝试关闭窗口和释放硬件资源。
    except Exception as ex:
        Log.Warn("页面安全退出失败：{}".format(str(ex)))
        _close_browser_and_window()

    # 密码输入器和相关进程由公共生命周期统一释放。这里在U盾提前释放后，
    # 仅处理网页会话、网银窗口和浏览器进程，避免正常结束与异常结束重复操作设备。
    return logout_succeeded


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """执行网银安全退出，并把退出结果写回参数字典。

    Args:
        argument: 本次退出参数。调用前可以传入空字典；执行完成后写入
            ``result``，页面安全退出成功时为 ``True``。
            U盾已在退出过程中提前断开；密码输入器和相关进程由公共生命
            周期另行释放，不包含在该值中。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        Exception: 清理过程中出现模块未处理的异常。
    """
    # @step 校验安全退出参数。
    contract.parse_logout_argument(argument)

    # @step 在网银页面按顺序执行安全退出。
    argument["result"] = _safe_logout_page(argument)

    # @step 确认安全退出实现已经返回结果。
    if contract.parse_logout_argument(argument).result is None:
        raise RuntimeError("安全退出实现没有返回result。")
    return argument
