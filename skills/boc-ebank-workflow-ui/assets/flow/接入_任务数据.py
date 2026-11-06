import json
from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


# 按数字员工平台中的实际资源名称修改。
PLATFORM_PARAMETER_NAME = "EbankConfig"
PLATFORM_QUEUE_NAME = "中国银行"


def _present_field_names(
    source_task: contract.SourceTaskModel,
    fields: tuple[tuple[str, str], ...],
) -> list[str]:
    """返回任务中实际提供的外部字段名。"""

    return [
        external_name
        for attribute_name, external_name in fields
        if getattr(source_task, attribute_name) is not None
    ]


def _validate_device_configuration(source_task: contract.SourceTaskModel) -> None:
    """核对任务设备参数与 ``配置_运行方案.py`` 中的实际选择。"""

    password_input_device_fields = (
        ("password_input_device_number", "keybox_no"),
        ("password_input_device_ip_address", "keybox_ip"),
        ("password_input_device_service_port", "keybox_port"),
        ("password_input_device_id", "keybox_hub_port"),
        ("login_password_index", "login_pwd_keybox_group"),
        ("certificate_password_index", "cert_pwd_keybox_group"),
    )
    provided_password_input_device_fields = _present_field_names(
        source_task,
        password_input_device_fields,
    )
    if not ebank.has_password_input_device():
        if provided_password_input_device_fields:
            raise RuntimeError(
                "任务提供了密码输入器参数{}，但配置_运行方案.py没有调用"
                "ebank.use_password_input_device(...)。".format(
                    "、".join(provided_password_input_device_fields)
                )
            )
    else:
        required_password_input_device_fields = (
            ("password_input_device_number", "keybox_no"),
            ("certificate_password_index", "cert_pwd_keybox_group"),
        )
        missing_fields = [
            external_name
            for attribute_name, external_name in required_password_input_device_fields
            if getattr(source_task, attribute_name) is None
        ]
        if missing_fields:
            raise RuntimeError(
                "当前运行方案启用了密码输入器，但任务缺少{}。".format(
                    "、".join(missing_fields)
                )
            )

    hub_field_groups = (
        (
            "U盾",
            (
                ("ukey_ip_address", "ukey_ip"),
                ("ukey_service_port", "ukey_port"),
                ("ukey_device_id", "ukey_hub_port"),
            ),
        ),
        (
            "密码输入器",
            (
                ("password_input_device_ip_address", "keybox_ip"),
                ("password_input_device_service_port", "keybox_port"),
                ("password_input_device_id", "keybox_hub_port"),
            ),
        ),
    )
    provided_hub_fields = [
        field_name
        for _device_name, fields in hub_field_groups
        for field_name in _present_field_names(source_task, fields)
    ]
    if not ebank.has_hub():
        if provided_hub_fields:
            raise RuntimeError(
                "任务提供了HUB连接参数{}，但配置_运行方案.py没有调用"
                "ebank.use_hub(...)。".format("、".join(provided_hub_fields))
            )
        return

    if not provided_hub_fields:
        raise RuntimeError(
            "当前运行方案启用了HUB，但任务中的U盾和密码输入器都没有HUB连接信息。"
        )

    for device_name, fields in hub_field_groups:
        provided_fields = _present_field_names(source_task, fields)
        if provided_fields and len(provided_fields) != len(fields):
            missing_fields = [
                external_name
                for attribute_name, external_name in fields
                if getattr(source_task, attribute_name) is None
            ]
            raise RuntimeError(
                "{}通过HUB连接时缺少{}；HUB地址、端口和设备标识必须同时提供。".format(
                    device_name,
                    "、".join(missing_fields),
                )
            )


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """读取外部配置和队列任务，并保存到统一运行状态。

    本模块属于外部接入层。队列名称、平台参数名称、XTS配置来源或外部字段
    发生变化时修改本文件；稳定框架不直接理解这些外部契约。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 未读取到队列数据，或外部数据不是有效JSON。
    """

    # @step 获取当前网银运行状态。
    state = GlobalVariables["ebank"]
    run_state = state.run
    bank_name = state.bank_name

    # @step 读取并校验网银运行配置。
    Log.Info("[任务接入] 开始读取运行配置")
    raw_config = Asset.GetAsset(Hover_GetAssetsList(PLATFORM_PARAMETER_NAME))
    try:
        config_data = json.loads(raw_config)
    except Exception as error:
        raise RuntimeError(
            "平台参数“{}”不是有效JSON：{}".format(
                PLATFORM_PARAMETER_NAME,
                str(error),
            )
        ) from error
    try:
        asset_config = contract.parse_asset_config(config_data)
    except ValueError as error:
        raise RuntimeError(str(error)) from error

    # @step 按运行方案读取可选的XTS配置并建立类型化运行配置。
    # 未选择HUB表示设备直连本机，不读取HUB鉴权文件。
    xts_config = None
    if ebank.has_hub():
        xts_config_path = asset_config.base.xts_config_path
        if xts_config_path is None:
            raise RuntimeError(
                "当前运行方案启用了HUB，但平台参数缺少Base.XTSConfigPath。"
            )
        try:
            xts_config = contract.parse_xts_config(
                ebank.load_excel_config(xts_config_path)
            )
        except ValueError as error:
            raise RuntimeError(str(error)) from error
    try:
        config = contract.build_runtime_config(asset_config, xts_config)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    state.config = config

    run_state.max_retry_count = config.retry.workflow
    applied_level = ebank.apply_runtime_log_level(config)
    Log.Info(
        "[任务接入] 运行配置读取完成，最大重试次数={}，日志级别={}".format(
            str(run_state.max_retry_count),
            applied_level,
        )
    )
    # @step 从队列拉取并校验本次任务。
    Log.Info("[任务接入] 开始拉取队列任务")
    raw_task = DataQueue.PullEx(Hover_GetDataQueuesList(PLATFORM_QUEUE_NAME))
    if raw_task is None or raw_task == "":
        raise RuntimeError(
            "未从队列“{}”读取到任务，流程结束".format(PLATFORM_QUEUE_NAME)
        )

    try:
        source_task_data = json.loads(raw_task)
    except Exception as error:
        raise RuntimeError(
            "队列“{}”中的任务不是有效JSON：{}".format(
                PLATFORM_QUEUE_NAME,
                str(error),
            )
        ) from error
    try:
        source_task = contract.parse_source_task(source_task_data)
    except ValueError as error:
        raise RuntimeError(str(error)) from error

    # @step 核对运行方案与任务中的设备接入方式。
    _validate_device_configuration(source_task)

    # @step 保存任务并复位本轮运行状态。
    state.source_task = source_task
    run_state.retry_count = 0
    run_state.has_error = False
    run_state.has_delivery_error = False
    run_state.error_message = ""

    Log.Info(
        "[任务接入] 任务读取完成，task_id={}，银行={}，业务={}，启用流水模板转换={}，账号数={}".format(
            str(source_task.task_id),
            bank_name,
            str(source_task.business_types),
            source_task.enable_convert_template,
            str(len(source_task.accounts)),
        )
    )
    return argument
