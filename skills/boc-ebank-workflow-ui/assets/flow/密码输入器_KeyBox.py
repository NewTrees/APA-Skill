"""使用 KeyBox 硬件的密码输入器实现。

本模块把内置的 ``KeyBox.InputPassword`` 和 ``KeyBox.Press`` 转换成
``公共_网银能力`` 规定的密码输入器接口。流程代码只通过
``ebank.use_password_input_device(密码输入器_KeyBox)`` 选择本实现，不直接调用运行时命令。
"""

from collections.abc import Sequence
from typing import Any

from apa_runtime import *
import 公共_数据契约 as contract


def input_password(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    password_kind: str,
    delay_ms: int = 600,
) -> Any:
    """从内置 KeyBox 的受控槽位输入密码。

    Args:
        password_input_device_info: 已校验的密码输入器连接和密码槽位模型。
            证书密码读取 ``device.certificate_password_index``，网银登录密码
            读取 ``device.login_password_index``。
        password_kind: ``certificate`` 表示证书密码，``login`` 表示网银
            登录密码。当前模板没有支付密码槽位，传入 ``payment`` 会报错。
        delay_ms: 开始输入前的等待时间，单位为毫秒，默认 600。

    Returns:
        Any: ``KeyBox.InputPassword`` 的原始返回值。

    Raises:
        ValueError: 密码用途不支持，或当前任务没有提供所需的密码槽位。
    """

    device_info = password_input_device_info.device
    index_values = {
        "certificate": device_info.certificate_password_index,
        "login": device_info.login_password_index,
    }
    normalized_kind = str(password_kind).lower()
    if normalized_kind not in index_values:
        raise ValueError(
            "内置 KeyBox 不支持密码用途：{}。当前支持 certificate、login。".format(
                password_kind
            )
        )

    password_index = index_values[normalized_kind]
    if password_index is None:
        raise ValueError(
            "当前登录实现需要输入{}，但任务没有提供对应的密码输入器槽位。".format(
                "网银登录密码" if normalized_kind == "login" else "U盾证书密码"
            )
        )
    return KeyBox.InputPassword(
        str(device_info.device_number),
        password_index,
        int(delay_ms),
    )


def press(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    key: str,
    action: str = "press",
    modifiers: Sequence[str] = (),
) -> Any:
    """通过内置 KeyBox 发送按键。

    Args:
        password_input_device_info: 已校验的密码输入器连接和密码槽位模型；
            设备编号读取 ``device.device_number``。
        key: 按键名称，例如 ``Enter``。
        action: 内置按键动作，默认 ``press``。
        modifiers: Ctrl、Alt、Shift 等组合键，无组合键时传空序列。

    Returns:
        Any: ``KeyBox.Press`` 的原始返回值。
    """

    device_info = password_input_device_info.device
    return KeyBox.Press(
        str(device_info.device_number),
        key,
        action,
        list(modifiers),
    )


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """保留 KeyBox 密码输入器实现在流程图中的维护入口。

    密码输入器的实际能力由 ``公共_网银能力`` 通过具名函数调用。该入口不会操作
    设备，也不应连接到主流程；仅用于让文件能够作为未连线节点显示和同步。

    Args:
        argument: 当前流程参数字典，本入口不会读取或修改其中的内容。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    return argument
