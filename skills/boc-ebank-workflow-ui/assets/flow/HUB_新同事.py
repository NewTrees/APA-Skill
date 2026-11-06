"""新同事 CloudUSB HUB 实现。

本模块负责把新同事厂商接口转换成 ``公共_网银能力`` 规定的通用 HUB 接口。
普通流程代码通过 ``import 公共_网银能力 as ebank`` 使用这些能力，不需要调用本模块中的厂商接口细节。
密码输入能力已经独立到 ``密码输入器_新同事.py``。
"""

import json
import time
from typing import Any
from urllib.parse import urlencode

from apa_runtime import *
import 公共_数据契约 as contract


HubPort = str | int


def _parse_response(raw_result: Any, action_name: str) -> contract.VendorResponseModel:
    """把新同事接口原始文本立即转换为统一厂商响应模型。"""

    response_text = str(raw_result).lstrip()
    if response_text.startswith("operationResult="):
        response_text = response_text[len("operationResult="):].lstrip()
    try:
        payload = json.loads(response_text)
        if not isinstance(payload, dict):
            raise ValueError("接口返回值必须是JSON对象")
        if not payload.get("msg"):
            payload["msg"] = payload.get("message") or ""
        return contract.VendorResponseModel.model_validate(payload)
    # apa-lint: disable-next-line preserve-exception-traceback -- 厂商返回无法解析时转换为统一失败结果，供上层决定是否重试。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="{}返回值解析失败（{}）".format(action_name, type(error).__name__),
        )


def _request(
    ip_address: str,
    port: HubPort,
    endpoint: str,
    parameters: dict[str, str],
    action_name: str,
) -> contract.VendorResponseModel:
    """发送一次GET请求，不自动重发；参数逐值编码，异常不回显含令牌的URL。

    Args:
        ip_address: 运行CloudUSBClient的执行机地址。
        port: CloudUSBClient服务端口。
        endpoint: cloudUSBAgent下的固定接口名。
        parameters: 查询参数键值，例如ukId、appCode和token；不写入日志。
        action_name: 用于中文日志和错误说明的动作名称。

    Returns:
        contract.VendorResponseModel: 保留厂商结果码和data；请求异常返回-1。
    """
    url = "http://{}:{}/cloudUSBAgent/{}".format(ip_address, port, endpoint)
    if parameters:
        url += "?" + urlencode(parameters)
    try:
        result = _parse_response(HTTP.Get(url, {}, 60000), action_name)
        Log.Info("{}返回码：{}".format(action_name, result.code))
        return result
    # apa-lint: disable-next-line preserve-exception-traceback -- 设备请求异常转统一失败，避免异常文本回显带token的请求地址。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="{}请求失败（{}）".format(action_name, type(error).__name__),
        )


def _device_has_status(
    response: contract.VendorResponseModel,
    device_id: str,
    expected_status: str,
) -> bool:
    """从成功查询的data.list精确选中唯一ukId，再对currentState做等值判断。

    Args:
        response: queryUkInfo的原始类型化响应，data应包含设备list。
        device_id: 完整设备编号，不做前缀或模糊匹配。
        expected_status: 连接类（连接/已连接）或断开类（断开/已断开）状态。

    Returns:
        bool: 唯一目标的状态匹配时为True；失败、缺失、重复、未知均为False。
    """
    if response.code != 0 or not isinstance(response.data, dict) or not device_id:
        return False
    records = response.data.get("list")
    if not isinstance(records, list):
        return False
    matches = [
        item for item in records
        if isinstance(item, dict) and item.get("ukId") == device_id
    ]
    if len(matches) != 1:
        return False
    if expected_status in ("连接", "已连接"):
        allowed_states = ("连接", "已连接")
    elif expected_status in ("断开", "已断开"):
        allowed_states = ("断开", "已断开")
    else:
        return False
    return matches[0].get("currentState") in allowed_states


def _request_token(ip_address: str, port: HubPort, app_key: str) -> str:
    """按照新同事接口要求生成一次性访问令牌。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        app_key: 新同事 HUB 分配的应用密钥。

    Returns:
        str: 用于访问新同事 HUB 接口的一次性令牌。
    """
    random_data = _request(ip_address, port, "getRandom", {}, "获取HUB随机数")
    if random_data.code != 0:
        raise RuntimeError("获取新同事HUB令牌随机数失败：{}".format(random_data.msg))
    if isinstance(random_data.data, bool) or not isinstance(random_data.data, (str, int)) or str(random_data.data) == "":
        raise RuntimeError("获取新同事HUB令牌随机数失败：data不是有效随机数")
    token = StringLib.StrHash(str(random_data.data) + app_key)
    return str(token).upper()


def _wait_device_status(
    ip_address: str,
    port: HubPort,
    keyword: str,
    expected_keyword: str,
    max_attempts: int,
    interval_ms: int,
    action_name: str,
) -> bool:
    """轮询精确目标设备状态；次数及间隔沿用原值，HTTP耗时另计。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        keyword: 完整设备编号；查询结果中仍须按ukId等值筛选。
        expected_keyword: 期望的连接/断开状态枚举，不是字符串搜索关键字。
        max_attempts: 最多查询次数。
        interval_ms: 两次查询之间的间隔毫秒数。
        action_name: 日志中使用的等待动作名称。

    Returns:
        bool: 唯一目标状态确认时为True，次数耗尽仍未确认时为False。
    """
    started_at = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        result = query_device(ip_address, port, keyword)
        if _device_has_status(result, keyword, expected_keyword):
            Log.Info("{}：第{}次确认设备{}为{}，实际耗时{}ms".format(
                action_name, attempt, keyword, expected_keyword,
                int((time.monotonic() - started_at) * 1000)))
            return True
        if attempt < max_attempts:
            Delay(interval_ms)
    Log.Warn("{}：设备{}在{}次查询后仍未确认{}，最后查询码={}，实际耗时{}ms（含HTTP）".format(
        action_name, keyword, max_attempts, expected_keyword,
        result.code if max_attempts > 0 else "未查询",
        int((time.monotonic() - started_at) * 1000)))
    return False


def connect_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
    app_code: str,
    app_key: str,
) -> contract.VendorResponseModel:
    """连接新同事 HUB 上的指定 USB 设备。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。
        app_code: 新同事 HUB 分配的应用编码。
        app_key: 新同事 HUB 分配的应用密钥。

    Returns:
        contract.VendorResponseModel: 厂商失败时保留原码；成功码0还需精确确认
            目标连接状态，请求异常或状态未确认返回-1。
    """
    try:
        token = _request_token(ip_address, port, app_key)
        result = _request(
            ip_address, port, "connect",
            {"ukId": device_id, "appCode": app_code, "token": token},
            "连接USB设备",
        )
        if result.code != 0:
            return result
        # 只确认CloudUSB的目标设备连接状态；不代替操作系统驱动/证书识别验证。
        if not _wait_device_status(
            ip_address,
            port,
            device_id,
            "已连接",
            20,
            500,
            "连接USB设备后等待就绪",
        ):
            return contract.VendorResponseModel(
                code=-1, msg="连接USB设备{}请求成功，但目标连接状态未确认".format(device_id),
                data=result.data,
            )
        return result
    # apa-lint: disable-next-line preserve-exception-traceback -- 厂商连接异常转换为统一设备结果，登录框架负责重试。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="连接USB设备{}失败：{}".format(device_id, str(error)),
        )


def disconnect_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> contract.VendorResponseModel:
    """断开新同事 HUB 上的指定 USB 设备。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。

    Returns:
        contract.VendorResponseModel: 厂商失败时保留原码；成功码0表示唯一目标
            已确认断开，请求异常或状态未确认返回-1。
    """
    try:
        # 设备本就处于断开状态时跳过断开请求和等待，避免无谓的HTTP调用与延时。
        current_status = query_device(ip_address, port, device_id)
        if _device_has_status(current_status, device_id, "断开"):
            Log.Info("USB设备{}已是断开状态，跳过断开请求".format(device_id))
            return contract.VendorResponseModel(code=0, msg="设备已断开")

        result = _request(
            ip_address, port, "disconnect", {"ukId": device_id}, "断开USB设备",
        )
        if result.code != 0:
            return result
        # 查询失败或其他设备已断开，均不能作为目标已释放的证据。
        if not _wait_device_status(
            ip_address,
            port,
            device_id,
            "断开",
            20,
            500,
            "断开USB设备后等待释放",
        ):
            return contract.VendorResponseModel(
                code=-1, msg="断开USB设备{}请求成功，但目标断开状态未确认".format(device_id),
                data=result.data,
            )
        return result
    # apa-lint: disable-next-line preserve-exception-traceback -- 厂商断开异常转换为统一设备结果，最终清理会汇总该错误。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="断开USB设备{}失败：{}".format(device_id, str(error)),
        )


def power_on_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> contract.VendorResponseModel:
    """给新同事 HUB 上的指定 USB 设备上电。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。

    Returns:
        contract.VendorResponseModel: 已解析的上电结果；调用失败时 ``code`` 为-1。
    """
    return _change_device_power(ip_address, port, device_id, "INSERT")


def power_off_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> contract.VendorResponseModel:
    """给新同事 HUB 上的指定 USB 设备下电。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。

    Returns:
        contract.VendorResponseModel: 已解析的下电结果；调用失败时 ``code`` 为-1。
    """
    return _change_device_power(ip_address, port, device_id, "DRAW")


def _change_device_power(
    ip_address: str,
    port: HubPort,
    device_id: str,
    operation: str,
) -> contract.VendorResponseModel:
    """调用新同事接口给指定 USB 设备上电或下电。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。
        operation: 新同事接口规定的电源操作值。

    Returns:
        contract.VendorResponseModel: 已解析的电源操作结果；失败时 ``code`` 为-1。
    """
    try:
        return _request(
            ip_address, port, "insertOrDrawUkey",
            {"ukId": device_id, "operType": operation}, "USB设备电源操作",
        )
    # apa-lint: disable-next-line preserve-exception-traceback -- 厂商电源操作异常转换为统一设备结果，由调用方决定恢复方式。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="USB设备电源操作失败：{}".format(str(error)),
        )


def query_device(
    ip_address: str,
    port: HubPort,
    keyword: str,
) -> contract.VendorResponseModel:
    """根据编号或名称查询新同事 HUB 上的 USB 设备状态。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        keyword: 用于查询 USB 设备的编号或名称。

    Returns:
        contract.VendorResponseModel: 已解析的查询结果，厂商数据保存在 ``data``。
    """
    try:
        return _request(
            ip_address, port, "queryUkInfo", {"keyWords": keyword}, "查询USB设备",
        )
    # apa-lint: disable-next-line preserve-exception-traceback -- 查询异常作为设备不可用结果返回，不在厂商适配层中止流程。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="查询USB设备{}失败：{}".format(keyword, str(error)),
        )


def query_connected_devices(
    ip_address: str,
    port: HubPort,
) -> contract.VendorResponseModel:
    """查询当前CloudUSB客户端自己连接的全部USB设备。

    对应新同事 ``getMyConnected`` 接口，返回当前客户端名下处于连接状态的
    设备清单（含 ``ukId`` 与 ``workGroup`` 等字段），供登录前清场使用。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。

    Returns:
        contract.VendorResponseModel: 已解析的查询结果；文档的data为设备数组，
            每条记录含ukId。保留原结构，不改为queryUkInfo的data.list。
    """
    try:
        return _request(
            ip_address, port, "getMyConnected", {}, "查询已连接USB设备",
        )
    # apa-lint: disable-next-line preserve-exception-traceback -- 查询异常作为清场不可用结果返回，清场尽力而为不阻断主流程。
    except Exception as error:
        return contract.VendorResponseModel(
            code=-1,
            msg="查询已连接USB设备失败：{}".format(str(error)),
        )


def disconnect_all_devices(
    ip_address: str,
    port: HubPort,
) -> contract.VendorResponseModel:
    """断开当前CloudUSB客户端自己连接的全部USB设备（登录前清场）。

    先通过 ``getMyConnected`` 查询已连接清单，再逐台调用断开并轮询确认
    释放。执行机被当前任务独占，清场目的是消除残留连接，确保后续只有
    本任务需要的设备在线，避免选错 U 盾。单台断开失败只记录告警并继续
    处理下一台；汇总如实标记部分失败，是否继续登录仍由原调用方决定。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。

    Returns:
        contract.VendorResponseModel: 清场汇总结果；``data`` 为已断开的
            ``ukId`` 列表。查询失败保留厂商码，结构异常或部分失败返回-1，
            由调用方按原有尽力而为策略决定是否继续。
    """
    query_result = query_connected_devices(ip_address, port)
    if query_result.code != 0:
        Log.Warn("[HUB清场] 查询已连接设备失败，跳过清场：{}".format(query_result.msg))
        return contract.VendorResponseModel(
            code=query_result.code,
            msg=query_result.msg,
        )

    # 文档为data数组；仅为已部署版本兼容显式data.list对象，不把异常结构当空清单。
    connected_data = query_result.data
    device_list = connected_data.get("list") if isinstance(connected_data, dict) else connected_data
    if not isinstance(device_list, list):
        return contract.VendorResponseModel(code=-1, msg="已连接设备清单结构无效，未执行清场")
    Log.Info("[HUB清场] 当前已连接USB设备{}台".format(len(device_list)))
    if not device_list:
        Log.Info("[HUB清场] 没有已连接设备，无需清场")
        return contract.VendorResponseModel(code=0, msg="没有已连接设备", data=[])

    disconnected_ids: list[str] = []
    failed_ids: list[str] = []
    seen_ids: set[str] = set()
    for device in device_list:
        uk_id = device.get("ukId") if isinstance(device, dict) else None
        if not isinstance(uk_id, str) or uk_id.strip() == "":
            failed_ids.append("缺少ukId的记录")
            Log.Warn("[HUB清场] 设备记录缺少有效ukId，跳过该记录")
            continue
        if uk_id in seen_ids:
            continue
        seen_ids.add(uk_id)
        Log.Info("[HUB清场] 断开已连接设备：{}".format(uk_id))
        disconnect_result = disconnect_device(ip_address, port, uk_id)
        if disconnect_result.code == 0:
            disconnected_ids.append(uk_id)
            Log.Info("[HUB清场] 设备{}已断开".format(uk_id))
        else:
            failed_ids.append(uk_id)
            Log.Warn("[HUB清场] 设备{}断开失败：{}".format(uk_id, disconnect_result.msg))
    Log.Info("[HUB清场] 清场完成，共断开{}台：{}".format(
        len(disconnected_ids),
        "、".join(disconnected_ids) if disconnected_ids else "无",
    ))
    return contract.VendorResponseModel(
        code=-1 if failed_ids else 0,
        msg="共确认断开{}台{}".format(
            len(disconnected_ids),
            "；未确认或失败：{}".format("、".join(failed_ids)) if failed_ids else "",
        ),
        data=disconnected_ids,
    )


def press_ukey_ok(
    ip_address: str,
    port: HubPort,
    ukey_id: str,
    app_code: str,
    app_key: str,
) -> contract.VendorResponseModel:
    """远程按下新同事 HUB 上指定 U 盾的确认键。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        ukey_id: U 盾在 HUB 中的编号。
        app_code: 新同事 HUB 分配的应用编码。
        app_key: 新同事 HUB 分配的应用密钥。

    Returns:
        contract.VendorResponseModel: 单击、立即执行的接口结果；厂商失败保留
            原码，请求异常返回-1。是否推动银行页面由登录实现判断，不重复按键。
    """

    try:
        token = _request_token(ip_address, port, app_key)
        # 沿用原单次立即执行；接口成功不等于银行已完成确认，由登录页面后置判断。
        return _request(
            ip_address, port, "okPress",
            {"ukId": ukey_id, "appCode": app_code, "token": token,
             "clickCount": "1", "delay": "0"},
            "按下U盾确认键",
        )
    # apa-lint: disable-next-line preserve-exception-traceback -- 确认键操作异常转换为统一设备结果，由业务层记录失败。
    except Exception as error:
        return contract.VendorResponseModel(code=-1, msg="按下U盾{}确认键失败：{}".format(ukey_id, str(error)))


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """保留新同事 HUB 实现在流程图中的维护入口。

    HUB 的实际能力由 ``公共_网银能力`` 通过具名函数调用。该入口不会操作设备，
    也不应连接到主流程；仅用于让文件能够作为未连线节点显示和同步。

    Args:
        argument: 当前流程参数字典，本入口不会读取或修改其中的内容。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    return argument
