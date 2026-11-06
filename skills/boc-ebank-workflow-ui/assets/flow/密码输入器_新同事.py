"""新同事密码输入器实现。

本模块保留原 ``新同事HUB.py`` 中的文本输入、回车和安全密码输入接口，
并把厂商参数转换成 ``公共_网银能力`` 规定的密码输入器接口。
"""

from collections.abc import Sequence
import json
from typing import Any

from apa_runtime import *
import 公共_数据契约 as contract


HubPort = str | int


def _require_hub(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
) -> contract.HubConnectionModel:
    """取得新同事密码输入器必须使用的厂商服务连接信息。"""

    return contract.require_config_section(
        password_input_device_info.hub,
        "新同事密码输入器服务连接",
    )


def _parse_response(raw_result: Any, action_name: str) -> contract.VendorResponseModel:
    """把新同事密码输入器原始文本立即转换为统一厂商响应模型。"""

    response_text = StringLib.Replace(str(raw_result), "operationResult=", "", False)
    try:
        return contract.VendorResponseModel.model_validate(json.loads(response_text))
    # apa-lint: disable-next-line preserve-exception-traceback -- 厂商返回无法解析时转换为统一失败结果，供登录逻辑处理。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="{}返回值解析失败：{}".format(action_name, error),
            data=response_text,
        )


def _request_token(ip_address: str, port: HubPort, app_key: str) -> str:
    """按照新同事接口要求生成一次性访问令牌。"""

    random_result = HTTP.Get(
        "http://{}:{}/cloudUSBAgent/getRandom".format(ip_address, port),
        {},
        60000,
    )
    TracePrint(random_result)
    random_result = StringLib.Replace(
        random_result,
        "operationResult=",
        "",
        False,
    )
    random_data = contract.VendorTokenSeedModel.model_validate(json.loads(random_result))
    if random_data.code not in (None, 0):
        raise RuntimeError("获取新同事密码输入器令牌随机数失败：{}".format(random_data.msg))
    token = StringLib.StrHash(str(random_data.data) + app_key)
    return str(token).upper()


def _to_seconds(milliseconds: int) -> int | float:
    """把公共接口使用的毫秒转换成新同事接口使用的秒。"""

    seconds = int(milliseconds) / 1000
    return int(seconds) if seconds.is_integer() else seconds


def input_text(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    text: str,
    delay_ms: int = 0,
    gap_ms: int = 0,
) -> contract.VendorResponseModel:
    """使用新同事密码输入器输入受控文本。

    Args:
        password_input_device_info: 已校验的密码输入器连接和密码槽位模型，使用其中的服务地址和端口。
        text: 要输入的受控文本。
        delay_ms: 开始输入前的等待时间，单位为毫秒。
        gap_ms: 相邻字符之间的间隔，单位为毫秒。

    Returns:
        contract.VendorResponseModel: 已解析的厂商结果；异常或解析失败时 ``code`` 为-1。
    """

    try:
        hub = _require_hub(password_input_device_info)
        url = (
            "http://{}:{}/cloudUSBAgent/KeyMouseInput?str={}&delay={}&gap={}"
        ).format(
            hub.ip_address,
            hub.port,
            text,
            _to_seconds(delay_ms),
            _to_seconds(gap_ms),
        )
        return _parse_response(HTTP.Get(url, {}, 60000), "密码输入器文本输入")
    # apa-lint: disable-next-line preserve-exception-traceback -- 文本输入异常转换为密码输入器失败结果，避免泄露密码输入细节。
    except Exception as error:
        return contract.VendorResponseModel(code=-1, msg="HUB文本输入失败：{}".format(str(error)))


def press(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    key: str,
    action: str = "press",
    modifiers: Sequence[str] = (),
) -> contract.VendorResponseModel:
    """使用新同事密码输入器发送按键。

    厂商现有接口只支持无组合键的 Enter，因此其他按键会明确报错，不进行
    软件键盘降级。

    Args:
        password_input_device_info: 已校验的密码输入器模型；``device.press_delay_ms``控制
            按键前等待时间，默认立即执行。
        key: 当前只支持 ``Enter``。
        action: 当前只支持 ``press``。
        modifiers: 当前不支持组合键，必须为空。

    Returns:
        contract.VendorResponseModel: 已解析的厂商结果；异常或解析失败时 ``code`` 为-1。

    Raises:
        ValueError: 请求了厂商接口尚不支持的按键形态。
    """

    if str(key).lower() != "enter" or action != "press" or modifiers:
        raise ValueError("新同事密码输入器当前只支持无组合键的 Enter press。")

    try:
        hub = _require_hub(password_input_device_info)
        delay_ms = password_input_device_info.device.press_delay_ms
        url = (
            "http://{}:{}/cloudUSBAgent/KeyMouseInputEnter?delay={}"
        ).format(
            hub.ip_address,
            hub.port,
            _to_seconds(int(delay_ms)),
        )
        return _parse_response(HTTP.Get(url, {}, 60000), "密码输入器按键输入")
    # apa-lint: disable-next-line preserve-exception-traceback -- 按键输入异常转换为密码输入器失败结果，由登录逻辑决定后续动作。
    except Exception as error:
        return contract.VendorResponseModel(code=-1, msg="HUB回车输入失败：{}".format(str(error)))


def input_password(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    password_kind: str,
    delay_ms: int = 600,
) -> contract.VendorResponseModel:
    """使用新同事 CloudUSB 安全保存的密码。

    Args:
        password_input_device_info: 已校验的密码输入器模型，包含厂商服务地址、
            应用密钥和密码槽位；``device.key_interval_ms``控制相邻按键间隔。
        password_kind: ``certificate``、``login`` 或 ``payment``，分别映射
            为厂商密码类型 1、2、3。
        delay_ms: 开始输入前的等待时间，单位为毫秒。

    Returns:
        contract.VendorResponseModel: 已解析的厂商结果；异常或解析失败时 ``code`` 为-1。

    Raises:
        ValueError: 密码用途不支持。
    """

    password_types = {
        "certificate": 1,
        "login": 2,
        "payment": 3,
    }
    password_type = password_types.get(str(password_kind).lower())
    if password_type is None:
        raise ValueError(
            "新同事密码输入器不支持密码用途：{}。".format(password_kind)
        )

    try:
        hub = _require_hub(password_input_device_info)
        gap_ms = password_input_device_info.device.key_interval_ms
        token = _request_token(
            hub.ip_address,
            hub.port,
            hub.app_key,
        )
        TracePrint("开始输入密码")
        url = (
            "http://{}:{}/cloudUSBAgent/inputPasswordForRpa?"
            "type={}&delay={}&gap={}&token={}"
        ).format(
            hub.ip_address,
            hub.port,
            password_type,
            _to_seconds(delay_ms),
            _to_seconds(int(gap_ms)),
            token,
        )
        return _parse_response(HTTP.Get(url, {}, 60000), "密码输入器密码输入")
    # apa-lint: disable-next-line preserve-exception-traceback -- 密码输入异常转换为密码输入器失败结果，避免在适配层输出敏感上下文。
    except Exception as error:
        return contract.VendorResponseModel(code=-1, msg="HUB密码输入失败：{}".format(str(error)))


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """保留新同事密码输入器实现在流程图中的维护入口。

    密码输入器的实际能力由 ``公共_网银能力`` 通过具名函数调用。该入口不会操作
    设备，也不应连接到主流程；仅用于让文件能够作为未连线节点显示和同步。

    Args:
        argument: 当前流程参数字典，本入口不会读取或修改其中的内容。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    return argument
