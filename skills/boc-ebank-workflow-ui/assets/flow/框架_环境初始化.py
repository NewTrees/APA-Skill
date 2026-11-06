from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


def _normalize_date_text(date_text: Any) -> str:
    """把常见日期格式统一为框架内部使用的 yyyy.mm.dd 文本。"""

    text = str(date_text).strip()
    from datetime import datetime as _datetime

    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return _datetime.strptime(text, pattern).strftime("%Y.%m.%d")
        except ValueError:
            continue
    return text


def _create_account(
    index: int,
    source_task: contract.SourceTaskModel,
    source_account: contract.SourceAccountModel,
) -> contract.StandardAccountModel:
    """把一个队列账号转换为框架统一使用的标准账号。"""

    query_dates = contract.QueryDatesModel(
        start_date=_normalize_date_text(source_account.start_date),
        end_date=_normalize_date_text(source_account.end_date),
    )

    return contract.StandardAccountModel(
        index=index,
        info=contract.AccountInfoModel(
            account_id=source_task.task_id,
            bank_account=source_account.bank_account,
            account_name=source_account.account_name,
            open_bank_name=source_account.open_bank_name,
            open_unit=source_account.open_unit,
            keeper=source_account.keeper,
        ),
        query_dates=query_dates,
        status="pending",
        error_message="",
        businesses=[
            ebank.create_business_execution(business_type)
            for business_type in dict.fromkeys(source_task.business_types)
        ],
        delivery=contract.AccountDeliveryModel(
            transaction_convert=contract.TransactionConvertStateModel(
                status="pending",
                error_message="",
                converted_file_path="",
                record_count=0,
                skip_reason="",
            ),
        ),
        execution_log=[],
    )


def _create_device_hub(
    ip_address: str | None,
    port: int | None,
    device_id: str | None,
    hub_config: contract.HubConfigModel | None,
    device_name: str,
) -> contract.HubConnectionModel | None:
    """为通过HUB连接的设备建立连接信息；直连设备返回None。"""

    if ip_address is None and port is None and device_id is None:
        return None
    if ip_address is None or port is None or device_id is None:
        raise RuntimeError(
            "{}的HUB地址、端口和设备标识必须同时提供。".format(device_name)
        )
    if hub_config is None:
        raise RuntimeError(
            "{}配置了HUB连接信息，但当前运行方案没有启用HUB。".format(
                device_name
            )
        )
    return contract.HubConnectionModel(
        ip_address=ip_address,
        port=port,
        device_id=device_id,
        app_code=hub_config.app_code,
        app_key=hub_config.app_key,
    )


def _create_password_input_device(
    source_task: contract.SourceTaskModel,
    config: contract.RuntimeConfigModel,
) -> contract.PasswordInputDeviceModel | None:
    """按实际 ``use_password_input_device`` 选择装配密码输入器。"""

    if not ebank.has_password_input_device():
        return None
    if (
        source_task.password_input_device_number is None
        or source_task.certificate_password_index is None
    ):
        raise RuntimeError(
            "启用密码输入器时任务必须提供keybox_no和cert_pwd_keybox_group。"
        )

    return contract.PasswordInputDeviceModel(
        device_number=source_task.password_input_device_number,
        hub=_create_device_hub(
            source_task.password_input_device_ip_address,
            source_task.password_input_device_service_port,
            source_task.password_input_device_id,
            config.hub,
            "密码输入器",
        ),
        login_password_index=source_task.login_password_index,
        certificate_password_index=source_task.certificate_password_index,
        connection_status=(
            "本机直连"
            if source_task.password_input_device_ip_address is None
            else "未连接"
        ),
    )


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """清理旧进程，并把已校验的队列任务转换为标准任务。

    首次执行会创建全部账号状态；整轮重试时沿用上一轮账号和业务结果，只更新
    任务元信息中的重试次数。这样失败业务可由后续业务调度块决定是否重做。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 尚未完成任务接入。
    """

    # @step 检查运行配置和外部任务数据。
    state = GlobalVariables["ebank"]
    if state.config is None or state.source_task is None:
        raise RuntimeError("环境初始化前必须先执行接入_任务数据。")

    config = state.config
    source_task = state.source_task
    run = state.run
    Log.Info("[环境初始化] 开始，银行={}，启用流水模板转换={}，账号数={}".format(
        state.bank_name,
        source_task.enable_convert_template,
        len(source_task.accounts),
    ))

    # @step 关闭上一轮可能残留的相关应用。
    ebank.close_apps(config.related_apps)

    # @step 建立或恢复标准任务和账号状态。
    if run.retry_count > 0 and state.task is not None:
        task = state.task
        task.status = "running"
        Log.Info("[环境初始化] 当前为第{}次整轮重试，沿用账号执行状态".format(run.retry_count))
    else:
        business_folder = (
            config.output.business
            + "\\"
            + state.bank_name
            + "\\"
            + Time.Format(Time.Date(), "yyyymmdd")
        )
        if not File.FolderExists(business_folder):
            File.CreateFolder(business_folder)

        task = contract.StandardTaskModel(
            task_id=source_task.task_id,
            bank_name=state.bank_name,
            process_name=source_task.process_name,
            worker_name=source_task.worker_name,
            enable_convert_template=source_task.enable_convert_template,
            business_types=source_task.business_types,
            start_time=Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss"),
            status="running",
            devices=contract.DevicesModel(
                ukey=contract.UkeyDeviceModel(
                    ukey_number=source_task.ukey_number,
                    hub=_create_device_hub(
                        source_task.ukey_ip_address,
                        source_task.ukey_service_port,
                        source_task.ukey_device_id,
                        config.hub,
                        "U盾",
                    ),
                    connection_status=(
                        "本机直连"
                        if source_task.ukey_ip_address is None
                        else "未连接"
                    ),
                ),
                password_input_device=_create_password_input_device(
                    source_task,
                    config,
                ),
            ),
            login=contract.LoginStateModel(
                status="pending",
                is_logged_in=False,
                error_message="",
                login_time="",
                retry_count=0,
                browser_handle=None,
                login_retry_limit=config.retry.login,
                certificate_password_retry_limit=config.retry.certificate_password,
                login_password_retry_limit=config.retry.login_password,
            ),
            output=contract.TaskOutputModel(
                business_folder=business_folder,
                summary_file="",
                screenshots_folder=config.output.screenshots or business_folder + "\\异常截图",
            ),
            accounts=[
                _create_account(index, source_task, account)
                for index, account in enumerate(source_task.accounts)
            ],
        )

    # @step 校验并保存标准任务。
    state.task = contract.parse_standard_task(task)
    Log.Info("[环境初始化] 完成，标准账号数={}".format(len(state.task.accounts)))
    return argument
