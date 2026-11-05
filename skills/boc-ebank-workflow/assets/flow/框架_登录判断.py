from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


def _build_login_argument(
    task: contract.StandardTaskModel,
    source_task: contract.SourceTaskModel,
    state: contract.EbankStateModel,
) -> contract.LoginArgumentModel:
    """根据标准任务构造登录模块的统一参数。

    网银助手路径取自运行方案设置的 ``state.assistant_path``，
    框架本身不保存银行特定的路径值。
    """

    ukey = task.devices.ukey
    password_input_device = task.devices.password_input_device
    password_input_device_argument = None
    if password_input_device is not None:
        password_input_device_argument = contract.PasswordInputDeviceLoginInfoModel(
            hub=password_input_device.hub,
            device=contract.PasswordInputDeviceInfoModel(
                device_number=password_input_device.device_number,
                login_password_index=password_input_device.login_password_index,
                certificate_password_index=password_input_device.certificate_password_index,
            ),
        )
    return contract.LoginArgumentModel(
        ukey=contract.UkeyLoginInfoModel(
            hub=ukey.hub,
            login=contract.LoginInfoModel(
                username=source_task.ukey_username,
                assistant_path=state.assistant_path,
            ),
            ukey_number=ukey.ukey_number,
        ),
        password_input_device=password_input_device_argument,
    )


def _mark_login_failure(
    task: contract.StandardTaskModel,
    status: str,
    message: str,
    retry_count: int,
) -> None:
    """统一记录登录失败状态。"""

    task.login.status = status
    task.login.is_logged_in = False
    task.login.error_message = message
    task.login.retry_count = retry_count


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """按照运行配置重试登录，并把结果写入标准任务。

    证书密码错误和网银登录密码错误分别计数；重试次数不包含首次执行。
    U盾证书密码已经提交但结果不明确时，为避免设备被锁定，不再自动登录。
    其他页面或设备异常按完整登录重试次数继续尝试。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 尚未完成任务初始化，或登录最终失败。
    """

    # @step 检查登录所需的配置、任务和设备信息。
    state = GlobalVariables["ebank"]
    if state.config is None or state.source_task is None or state.task is None:
        raise RuntimeError("登录前必须先完成任务接入和环境初始化。")

    config = state.config
    source_task = state.source_task
    task = state.task
    ukey = task.devices.ukey
    login_attempt_limit = config.retry.login + 1
    certificate_password_error_count = 0
    login_password_error_count = 0
    last_error = ""
    # 记录最后一次原始异常对象，供最终重抛时保留异常链；正常返回但 code!=0 的路径没有异常对象，保持 None。
    last_error_object = None

    # @step 按配置次数尝试登录并处理密码错误。
    Log.Info(
        "[登录控制] 开始，银行={}，最多尝试{}次".format(
            state.bank_name,
            login_attempt_limit,
        )
    )
    if config.retry.certificate_password > 0:
        Log.Warn(
            "[登录控制] U盾证书密码允许自动重试{}次；连续输错可能锁定U盾。".format(
                config.retry.certificate_password
            )
        )
    for attempt in range(1, login_attempt_limit + 1):
        Log.Info("[登录控制] 正在执行第{}次登录".format(attempt))
        try:
            login_argument = _build_login_argument(task, source_task, state)
            result = ebank.run_login(login_argument)
        # apa-lint: disable-next-line preserve-exception-traceback -- 单次登录异常需要转为重试状态；密码错误仍会立即带原异常终止。
        except Exception as error:
            # 公共能力模块函数：提取根因文件与行号拼接进失败原因，避免最终报错只显示本块重抛位置。
            last_error = "{}{}".format(str(error), ebank.extract_root_location(error))
            last_error_object = error
            task.login.error_message = last_error
            ebank.save_exception_screenshot("登录控制_第{}次异常".format(attempt))
            if "不得自动重试" in last_error:
                _mark_login_failure(task, "certificate_status_unknown", last_error, attempt - 1)
                ebank.cleanup_login_resources(argument)
                raise RuntimeError(last_error) from error
            if "密码错误" in last_error:
                _mark_login_failure(task, "exception", last_error, attempt - 1)
                ebank.cleanup_login_resources(argument)
                raise RuntimeError(last_error) from error
            Log.Warn("[登录控制] 第{}次登录异常，将继续重试：{}".format(attempt, last_error))
            continue

        # 登录实现正常返回失败结果时，异常路径无法覆盖；把登录实现写入的根因位置拼进 last_error。
        result_root_location = getattr(result, "root_location", "") or ""
        last_error = "{}{}".format(result.message, result_root_location)
        task.login.error_message = "登录结果：code={}，message={}".format(
            result.code,
            result.message,
        )
        if result.code == 1:
            certificate_password_error_count += 1
            Log.Warn(
                "[登录控制] U盾证书密码错误，第{}次提交失败".format(
                    certificate_password_error_count
                )
            )
            if certificate_password_error_count > config.retry.certificate_password:
                message = (
                    "U盾证书密码错误，已按配置停止自动重试；本次允许重试{}次。"
                ).format(config.retry.certificate_password)
                _mark_login_failure(task, "certificate_error", message, attempt - 1)
                ebank.cleanup_login_resources(argument)
                raise RuntimeError(message)
            continue
        if result.code == 2:
            login_password_error_count += 1
            Log.Warn(
                "[登录控制] 网银登录密码错误，第{}次提交失败".format(
                    login_password_error_count
                )
            )
            if login_password_error_count > config.retry.login_password:
                message = (
                    "网银登录密码错误，已按配置停止自动重试；本次允许重试{}次。"
                ).format(config.retry.login_password)
                _mark_login_failure(task, "password_error", message, attempt - 1)
                ebank.cleanup_login_resources(argument)
                raise RuntimeError(message)
            continue
        if result.code == 4:
            message = "{}；为避免锁定U盾，本次不再自动重试。".format(result.message)
            _mark_login_failure(task, "certificate_status_unknown", message, attempt - 1)
            ebank.cleanup_login_resources(argument)
            raise RuntimeError(message)
        if result.code != 0:
            Log.Warn("[登录控制] 登录返回失败：{}".format(result.message))
            continue

        task.login.status = "success"
        task.login.is_logged_in = True
        task.login.ever_logged_in = True
        task.login.rounds_logged_in = task.login.rounds_logged_in + 1
        task.login.error_message = ""
        task.login.retry_count = attempt - 1
        task.login.login_time = Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss")
        for account in task.accounts:
            account.execution_log.append(contract.ExecutionLogEntryModel(
                stage="login",
                status="success",
                timestamp=task.login.login_time,
                detail="U盾登录成功（第{}次尝试）".format(attempt),
            ))
        Log.Info("[登录控制] 登录成功")
        return argument

    # @step 记录最终登录失败并释放登录资源。
    message = "登录{}次仍未成功，最后原因：{}".format(login_attempt_limit, last_error)
    _mark_login_failure(task, "failed", message, config.retry.login)
    ebank.cleanup_login_resources(argument)
    # apa-lint: disable-next-line preserve-exception-traceback -- 重试耗尽后转为登录失败业务异常；last_error 已拼接根因位置，有原始异常时保留异常链。
    if last_error_object is not None:
        raise RuntimeError(message) from last_error_object
    raise RuntimeError(message)
