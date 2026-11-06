"""网银流程公共能力。

流程开发人员通过 import 公共_网银能力 as ebank 使用本文件。
本文件集中提供配置、下载、Excel、邮件、任务查询、HUB通用规范、U盾、
密码输入器和会话清理能力，避免开发人员理解内部包结构。
具体设备实现位于独立模块，例如 HUB_新同事.py 和 密码输入器_KeyBox.py。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from typing import Any, NoReturn, Protocol, TypeAlias, cast

from apa_runtime import *
import ddddocr
from openpyxl import load_workbook
import 公共_数据契约 as contract


# ==================== 会话与业务模块选择 ====================

class WorkflowModule(Protocol):
    """可由网银框架调用的会话或业务模块。

    模块不需要继承本类，只要提供同样的 ``main`` 函数即可。
    """

    def main(self, argument: dict[str, Any]) -> dict[str, Any]:
        """执行模块，并返回传入的同一个参数字典。"""
        ...


_login_in_use: WorkflowModule | None = None
_logout_in_use: WorkflowModule | None = None
_businesses_in_use: dict[int, WorkflowModule] = {}
_deliveries_in_use: list[WorkflowModule] = []
_success_handlers_in_use: list[WorkflowModule] = []
_failure_handlers_in_use: list[WorkflowModule] = []


def unuse_all() -> None:
    """取消当前运行方案已经选择的全部可插拔实现。

    在 ``配置_运行方案.py`` 的所有 ``use_*`` 调用之前执行，使完整流程和
    重复执行的代码片段都从当前文件声明的运行方案重新开始。这里只清除模块
    选择，不清除任务状态、生命周期动作或 ``GlobalVariables["ebank"]``。

    Returns:
        None
    """

    ensure_state()
    global _login_in_use, _logout_in_use, _hub_in_use, _password_input_device_in_use
    _login_in_use = None
    _logout_in_use = None
    _hub_in_use = None
    _password_input_device_in_use = None
    _businesses_in_use.clear()
    _deliveries_in_use.clear()
    _success_handlers_in_use.clear()
    _failure_handlers_in_use.clear()


def _check_workflow_module(module: WorkflowModule, module_name: str) -> None:
    """检查会话或业务模块是否提供统一入口。"""

    if not callable(getattr(module, "main", None)):
        raise TypeError("选择{}失败：模块缺少 main(argument) 函数。".format(module_name))


def _run_workflow_module(
    module: WorkflowModule,
    argument: dict[str, Any],
    module_name: str,
) -> dict[str, Any]:
    """执行统一模块，并检查它没有替换参数对象。"""

    result = module.main(argument)
    if result is not argument:
        raise RuntimeError(
            "{}违反入口契约：main(argument) 必须返回传入的同一个字典。".format(
                module_name
            )
        )
    return result


def use_login(login: WorkflowModule) -> None:
    """选择当前流程使用的登录实现。

    Args:
        login: 提供 ``main(argument)`` 的登录模块。参数字典的具体键由该
            模块的 ``main`` 文档说明。

    Returns:
        None

    Raises:
        TypeError: 模块缺少 ``main`` 函数。
    """

    ensure_state()
    _check_workflow_module(login, "登录实现")
    global _login_in_use
    _login_in_use = login


def extract_root_location(error: BaseException) -> str:
    """从异常的 traceback 中提取最深层（根因）文件名和行号。

    公共能力模块函数：供登录实现等下游模块在把异常转为业务结果时调用，
    避免最终报错只显示框架层重抛位置。

    Args:
        error: 已经捕获的原始异常对象。

    Returns:
        str: 格式为“（位置：文件名 第N行）”的根因位置；异常没有 traceback 时返回空字符串。
    """

    traceback_obj = error.__traceback__
    if traceback_obj is None:
        return ""
    # 逐帧下钻到最深层，即真正抛出异常的业务函数行。
    frame = traceback_obj.tb_next if traceback_obj.tb_next is not None else traceback_obj
    while frame.tb_next is not None:
        frame = frame.tb_next
    root_file = frame.tb_frame.f_code.co_filename
    root_name = root_file.split("\\")[-1] if root_file else "未知文件"
    return "（位置：{} 第{}行）".format(root_name, frame.tb_lineno)


def run_login(argument: contract.LoginArgumentModel) -> contract.LoginResultModel:
    """使用当前登录实现执行登录。

    Args:
        argument: 已校验的登录参数模型。

    Returns:
        LoginResultModel: 登录实现返回并再次校验后的结果模型。

    Raises:
        RuntimeError: 尚未选择登录实现，或登录模块替换了参数对象。
    """

    if _login_in_use is None:
        raise RuntimeError(
            "尚未选择登录实现。请先在配置_运行方案.py中调用 "
            "ebank.use_login(登录模块)。"
        )
    login_argument = contract.parse_login_argument(argument)
    module_argument = login_argument.model_dump(
        by_alias=True,
        mode="python",
        exclude_none=True,
    )
    _run_workflow_module(_login_in_use, module_argument, "登录实现")
    login_argument = contract.parse_login_argument(module_argument)
    if login_argument.result is None:
        raise RuntimeError("登录模块结果不符合数据契约：缺少result。")
    if login_argument.result.code == 0:
        _remember_banking_session(contract.LogoutArgumentModel())
    return login_argument.result


def use_logout(logout: WorkflowModule) -> None:
    """选择当前流程使用的安全退出实现。

    Args:
        logout: 提供 ``main(argument)`` 的安全退出模块。

    Returns:
        None

    Raises:
        TypeError: 模块缺少 ``main`` 函数。
    """

    ensure_state()
    _check_workflow_module(logout, "安全退出实现")
    global _logout_in_use
    _logout_in_use = logout


def run_logout(argument: contract.LogoutArgumentModel) -> bool:
    """使用当前安全退出实现释放网银会话。

    Args:
        argument: 已校验的安全退出参数模型。

    Returns:
        bool: 页面安全退出是否成功。

    Raises:
        RuntimeError: 尚未选择安全退出实现，或退出模块替换了参数对象。
    """

    if _logout_in_use is None:
        raise RuntimeError(
            "尚未选择安全退出实现。请先在配置_运行方案.py中调用 "
            "ebank.use_logout(退出模块)。"
        )
    logout_argument = contract.parse_logout_argument(argument)
    module_argument = logout_argument.model_dump(
        by_alias=True,
        mode="python",
        exclude_none=True,
    )
    _run_workflow_module(_logout_in_use, module_argument, "安全退出实现")
    logout_argument = contract.parse_logout_argument(module_argument)
    if logout_argument.result is None:
        raise RuntimeError("安全退出模块结果不符合数据契约：缺少result。")
    return logout_argument.result


def use_business(business_type: int, business: WorkflowModule) -> None:
    """为一个业务编号选择实现；业务编号不受框架固定枚举限制。

    Args:
        business_type: 上游任务中的正整数 ``BusinessType``。新增业务可以直接
            使用新的编号，无需修改公共契约或业务调度框架。
        business: 提供 ``main(argument)`` 的业务模块。

    Returns:
        None

    Raises:
        TypeError: ``business_type`` 不是正整数，或模块缺少 ``main`` 函数。
    """

    ensure_state()
    if type(business_type) is not int or business_type <= 0:
        raise TypeError("选择业务实现失败：business_type 必须是正整数。")
    _check_workflow_module(business, "业务{}实现".format(str(business_type)))
    _businesses_in_use[business_type] = business


def get_business_name(business_type: int) -> str:
    """读取已注册业务的中文名称。

    名称直接取业务模块文件名，自动去掉 ``业务_`` 前缀，避免流程开发人员
    另外维护一份业务名称或稳定ID。

    Args:
        business_type: 上游任务中的正整数业务编号。

    Returns:
        str: 适合日志和汇总展示的业务名称。

    Raises:
        RuntimeError: 当前业务编号尚未在运行方案中注册。
    """

    business = _businesses_in_use.get(business_type)
    if business is None:
        raise RuntimeError(
            "业务类型{}尚未选择实现。请在配置_运行方案.py中调用 "
            "ebank.use_business({}, 业务模块)。".format(business_type, business_type)
        )
    module_name = getattr(business, "__name__", "业务_{}".format(business_type))
    short_name = module_name.rsplit(".", 1)[-1]
    if short_name.startswith("业务_"):
        short_name = short_name[len("业务_"):]
    return short_name.replace("_", " ")


def create_business_execution(business_type: int) -> contract.BusinessExecutionModel:
    """为账号创建一项尚未执行的业务状态。

    Args:
        business_type: 上游任务中的正整数业务编号，必须已经通过
            ``use_business`` 注册。

    Returns:
        BusinessExecutionModel: 可直接放入账号 ``businesses`` 列表的状态。
    """

    return contract.BusinessExecutionModel(
        business_type=business_type,
        business_name=get_business_name(business_type),
    )


def run_business(
    business_type: int,
    argument: contract.BusinessArgumentModel,
) -> contract.BusinessResultModel:
    """使用指定业务类型当前选择的实现执行业务。

    Args:
        business_type: 上游任务中的正整数 ``BusinessType``。
        argument: 已校验的统一业务上下文模型。

    Returns:
        BusinessResultModel: 业务模块写回并再次校验后的统一结果模型。

    Raises:
        RuntimeError: 当前业务类型没有选择实现，或业务模块替换了参数对象。
    """

    business = _businesses_in_use.get(business_type)
    if business is None:
        raise RuntimeError(
            "业务类型{}尚未选择实现。请先在配置_运行方案.py中调用 "
            "ebank.use_business({}, 业务模块)。".format(
                str(business_type),
                str(business_type),
            )
        )
    module_name = getattr(business, "__name__", "业务{}实现".format(str(business_type)))
    framework = _framework_state()
    module_state = get_business_state(module_name)
    framework.current_business = module_name
    module_state.status = "running"

    try:
        business_argument = contract.parse_business_argument(business_type, argument)
        module_argument = business_argument.model_dump(by_alias=True, mode="python")
        _run_workflow_module(
            business,
            module_argument,
            "业务{}实现".format(str(business_type)),
        )
        result = contract.parse_business_module_result(business_type, module_argument)
        module_state.status = "completed"
        return result
    except Exception:
        module_state.status = "failed"
        raise
    finally:
        framework.current_business = None


def use_delivery(deliveries: Sequence[WorkflowModule]) -> None:
    """设置业务完成后需要执行的交付模块及顺序。

    Args:
        deliveries: 交付模块列表。每个模块必须提供 ``main(argument)``；
            列表顺序就是交付顺序。

    Returns:
        None

    Raises:
        TypeError: 任一交付模块缺少 ``main`` 函数。
    """

    ensure_state()
    checked = list(deliveries)
    for index, module in enumerate(checked, start=1):
        _check_workflow_module(module, "第{}个交付实现".format(index))

    global _deliveries_in_use
    _deliveries_in_use = checked


def run_delivery(argument: dict[str, Any]) -> dict[str, Any]:
    """按照配置顺序执行全部交付模块。

    Args:
        argument: 传给交付模块的流程参数字典。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    state = ensure_state()
    if state.config is None or state.source_task is None or state.task is None:
        raise RuntimeError("交付前必须先完成任务接入和环境初始化。")
    state.config = contract.parse_runtime_config(state.config)
    state.source_task = contract.parse_source_task(state.source_task)
    state.task = contract.parse_standard_task(state.task)
    state.run = contract.parse_run_state(state.run)

    for index, module in enumerate(_deliveries_in_use, start=1):
        _run_workflow_module(module, argument, "第{}个交付实现".format(index))
    return argument


def use_finish_handlers(
    success: Sequence[WorkflowModule],
    failure: Sequence[WorkflowModule],
) -> None:
    """设置正常结束和异常结束时需要执行的处理模块。

    Args:
        success: 正常结束处理模块，按照列表顺序执行。
        failure: 异常结束处理模块，按照列表顺序执行。

    Returns:
        None

    Raises:
        TypeError: 任一模块缺少 ``main`` 函数。
    """

    ensure_state()
    success_modules = list(success)
    failure_modules = list(failure)

    for index, module in enumerate(success_modules, start=1):
        _check_workflow_module(module, "第{}个正常收尾模块".format(index))
    for index, module in enumerate(failure_modules, start=1):
        _check_workflow_module(module, "第{}个异常收尾模块".format(index))

    global _success_handlers_in_use, _failure_handlers_in_use
    _success_handlers_in_use = success_modules
    _failure_handlers_in_use = failure_modules


# ==================== 跨流程块运行状态 ====================

def ensure_state() -> contract.EbankStateModel:
    """取得本次运行状态；首次调用时自动替换项目中的空占位变量。

    ``main.prjp`` 只需预先定义名为 ``ebank`` 的空字典。第一个公共入口会把它
    转换为类型化状态；同一次运行中的后续调用直接复用，不会清除任务、重试或
    生命周期记录。使用代码片段单独调试网银流程块时，应先调用本函数补齐主流程
    原本会建立的类型化状态。

    Returns:
        contract.EbankStateModel: 同一次项目运行中跨流程块共享的状态对象。

    Raises:
        RuntimeError: ``ebank`` 已被其他代码写成无法识别的非空对象。
    """

    try:
        value = GlobalVariables["ebank"]
    except KeyError:
        value = None

    if isinstance(value, contract.EbankStateModel):
        return value
    if value is not None and not (isinstance(value, dict) and not value):
        raise RuntimeError(
            "GlobalVariables['ebank']必须是main.prjp定义的空字典，"
            "或已经初始化的EbankStateModel。"
        )

    state = contract.create_ebank_state()
    GlobalVariables["ebank"] = state
    return state


def set_bank_name(bank_name: str) -> None:
    """设置当前流程对应的银行名称。

    Args:
        bank_name: 流程开发人员看到的完整银行名称，例如 ``中国农业银行``。

    Returns:
        None

    Raises:
        ValueError: 银行名称为空。
    """

    normalized = str(bank_name).strip()
    if normalized == "":
        raise ValueError("银行名称不能为空。")
    ensure_state().bank_name = normalized


def set_assistant_path(assistant_path: str) -> None:
    """设置当前银行的网银助手程序完整路径。

    Args:
        assistant_path: 网银助手程序的完整路径；目标机器没有助手程序时
            允许传空字符串，由登录实现在需要时校验。

    Returns:
        None
    """

    ensure_state().assistant_path = str(assistant_path or "").strip()


_SENSITIVE_LOG_KEYWORDS = (
    "password",
    "passwd",
    "appkey",
    "app_key",
    "secret",
    "token",
    "authorization",
    "smtp_password",
    "db_password",
)


def _is_sensitive_log_key(key: object) -> bool:
    """判断一个字段名是否可能包含不应写入日志的认证信息。"""

    normalized = str(key).replace("-", "_").lower()
    return any(keyword in normalized for keyword in _SENSITIVE_LOG_KEYWORDS)


def mask_sensitive(value: Any) -> Any:
    """递归复制数据，并隐藏密码、AppKey和Token等敏感字段。

    Args:
        value: 准备写入调试日志的数据，可以是字典、列表、元组或普通值。

    Returns:
        Any: 可安全用于调试日志的副本；原对象不会被修改。
    """

    if isinstance(value, Mapping):
        return {
            key: "***"
            if _is_sensitive_log_key(key)
            else mask_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_sensitive(item) for item in value)
    return value


def _normalize_log_level(level: object, fallback: str) -> str:
    """把日志级别规范为APA支持的0到4。"""

    try:
        normalized = str(int(str(level)))
    except (TypeError, ValueError):
        normalized = fallback
    if normalized not in {"0", "1", "2", "3", "4"}:
        return fallback
    return normalized


def configure_logging(
    default_level: str = "2",
    use_external_level: bool = True,
) -> None:
    """保存当前项目的日志策略。

    Args:
        default_level: 外部配置缺失时使用的APA日志级别，允许0到4。
        use_external_level: 是否优先读取外部配置中的 ``Base.LogLevel``。
    Returns:
        None

    Raises:
        ValueError: ``default_level`` 不是0到4。
    """

    normalized = _normalize_log_level(default_level, "")
    if normalized == "":
        raise ValueError("default_level必须是0到4。")

    state = ensure_state()
    state.logging = contract.LoggingStateModel(
        default_level=normalized,
        use_external_level=bool(use_external_level),
        current_level="3",
    )


def apply_runtime_log_level(external_config: contract.RuntimeConfigModel) -> str:
    """根据运行方案和外部配置设置正式运行阶段日志级别。

    Args:
        external_config: 已合并并校验的运行配置；启用外部级别时读取
            ``log_level``。

    Returns:
        str: 最终应用的APA日志级别。
    """

    logging_state = ensure_state().logging
    default_level = _normalize_log_level(
        logging_state.default_level,
        "2",
    )
    requested_level: object = default_level
    if logging_state.use_external_level:
        requested_level = external_config.log_level
        if requested_level is None:
            requested_level = default_level

    level = _normalize_log_level(requested_level, default_level)
    Log.SetLevel(level)
    logging_state.current_level = level
    Log.Debug("[日志] 正式运行日志级别已设置为{}".format(level))
    return level


def _framework_state() -> contract.FrameworkStateModel:
    """取得网银框架自身的运行状态。"""

    return ensure_state().framework


def get_business_state(module_name: str) -> contract.BusinessModuleStateModel:
    """取得指定业务模块的运行状态。

    Args:
        module_name: 业务模块名，例如 ``业务_余额查询``。

    Returns:
        BusinessModuleStateModel: 该业务在本次项目运行中的状态模型。
    """

    businesses = ensure_state().business
    module_state = businesses.get(module_name)
    if module_state is None:
        module_state = contract.BusinessModuleStateModel()
        businesses[module_name] = module_state
    return module_state


# ==================== 成对进入与逆序退出 ====================

def _active_actions() -> list[contract.LifecycleActionModel]:
    """取得尚未退出的资源动作列表。"""

    return _framework_state().active_actions


def _push_action(
    owner: str,
    name: contract.LifecycleActionName,
    data: contract.DeviceActionDataModel
    | contract.AppsActionDataModel
    | contract.LogoutArgumentModel,
) -> None:
    """在进入成功后，把对应的退出动作压入活动列表。"""

    actions = _active_actions()
    # 登录内部重试可能重新进入同一资源。旧动作已由登录逻辑主动释放，
    # 因此登记新动作前移除同名旧记录，避免最终重复退出。
    actions[:] = [
        action
        for action in actions
        if not (action.owner == owner and action.name == name)
    ]
    actions.append(contract.LifecycleActionModel(owner=owner, name=name, data=data))


def _forget_action(name: str) -> None:
    """移除已经由当前模块自行释放的动作记录。"""

    actions = _active_actions()
    actions[:] = [action for action in actions if action.name != name]


def mark_ukey_released() -> None:
    """告知框架上一条U盾连接已经由登录模块主动释放。

    登录实现为了处理其他机器遗留的设备连接，可能在重新连接前主动断开并
    下电。完成这些动作后调用本函数，最终清理就不会重复操作同一条旧连接。
    """

    _forget_action("U-Key设备")


def remember_ukey_connection(
    ip_address: str,
    port: HubPort,
    ukey_id: str,
) -> None:
    """记录本次流程已经成功连接的U-Key。"""

    _push_action(
        "HUB",
        "U-Key设备",
        contract.DeviceActionDataModel(
            ip_address=ip_address,
            port=port,
            device_id=ukey_id,
        ),
    )


def remember_password_input_device_connection(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> None:
    """记录本次登录已经通过HUB连接的密码输入器。"""

    _push_action(
        "密码输入器",
        "密码输入器",
        contract.DeviceActionDataModel(
            ip_address=ip_address,
            port=port,
            device_id=device_id,
        ),
    )


def remember_apps(app_names: Sequence[str]) -> None:
    """记录本次流程启动或使用的相关进程。"""

    _push_action(
        "框架",
        "相关进程",
        contract.AppsActionDataModel(app_names=list(app_names)),
    )


def _remember_banking_session(logout_argument: contract.LogoutArgumentModel) -> None:
    """记录已经登录成功、结束时需要安全退出的网银会话。"""

    _push_action("会话_登录", "网银会话", logout_argument)


def _disconnect_and_power_off(data: contract.DeviceActionDataModel) -> None:
    """断开一个HUB设备并下电；两步都尝试执行。"""

    errors: list[Exception] = []
    ip_address = data.ip_address
    port = data.port
    device_id = data.device_id

    try:
        disconnect_device(ip_address, port, device_id)
    # apa-lint: disable-next-line preserve-exception-traceback -- 断开失败仍需继续尝试下电，错误会在全部清理完成后统一返回。
    except Exception as error:
        errors.append(error)

    try:
        power_off_device(ip_address, port, device_id)
    # apa-lint: disable-next-line preserve-exception-traceback -- 下电失败与断开失败一起汇总，由调用方统一处理。
    except Exception as error:
        errors.append(error)

    if errors:
        raise RuntimeError("设备断开或下电失败：{}".format(str(errors)))


def _run_exit(argument: dict[str, Any], action: contract.LifecycleActionModel) -> None:
    """执行一个活动动作对应的退出操作。"""

    name = action.name
    data = action.data

    if name == "网银会话":
        if not isinstance(data, contract.LogoutArgumentModel):
            raise RuntimeError("网银会话退出参数类型不正确。")
        run_logout(data)
    elif name == "密码输入器" or name == "U-Key设备":
        if not isinstance(data, contract.DeviceActionDataModel):
            raise RuntimeError("设备退出参数类型不正确。")
        _disconnect_and_power_off(data)
    elif name == "相关进程":
        if not isinstance(data, contract.AppsActionDataModel):
            raise RuntimeError("进程清理参数类型不正确。")
        close_apps(data.app_names)
    else:
        raise RuntimeError("未知的网银退出动作：{}".format(name))


def _exit_action(argument: dict[str, Any], name: str) -> list[Exception]:
    """退出一个仍处于活动状态的指定动作。"""

    actions = _active_actions()
    for index in range(len(actions) - 1, -1, -1):
        action = actions[index]
        if action.name != name:
            continue

        actions.pop(index)
        try:
            _run_exit(argument, action)
            return []
        # apa-lint: disable-next-line preserve-exception-traceback -- 中途释放以错误列表返回，登录模块会附加到原始异常。
        except Exception as error:
            return [error]
    return []


def _exit_all(argument: dict[str, Any]) -> list[Exception]:
    """按照进入顺序的相反顺序释放全部活动资源。"""

    errors: list[Exception] = []
    actions = _active_actions()

    while actions:
        action = actions.pop()
        try:
            _run_exit(argument, action)
        # apa-lint: disable-next-line preserve-exception-traceback -- 最终清理必须继续释放剩余资源，全部错误在结束后汇总。
        except Exception as error:
            errors.append(error)

    _framework_state().cleanup_errors = [str(error) for error in errors]
    return errors


def release_ukey_connection(argument: dict[str, Any]) -> list[Exception]:
    """立即断开通过HUB连接的U盾并下电。

    没有成功连接或已经释放时直接返回空列表；最终清理不会重复释放。
    供安全退出实现在点击"我已拔出"前调用，等效物理拔出K宝。
    """

    return _exit_action(argument, "U-Key设备")


def release_password_input_device(argument: dict[str, Any]) -> list[Exception]:
    """密码输入结束后立即断开通过HUB连接的密码输入器并下电。

    没有成功连接或已经释放时直接返回空列表；最终清理不会重复释放。
    """

    return _exit_action(argument, "密码输入器")


def cleanup_login_resources(argument: dict[str, Any]) -> bool:
    """清理登录阶段取得的网银会话、相关进程和U盾。

    本函数通过框架已经记录的生命周期动作清理资源。没有成功取得的资源不会
    执行清理，已经清理并移除记录的资源也不会重复执行。登录失败和业务结束都
    可以调用本函数。

    Args:
        argument: 当前流程参数字典，仅透传给安全退出模块。

    Returns:
        bool: 全部已登记资源均清理成功时返回 ``True``；某项失败时记录日志并
        返回 ``False``，其余资源仍会继续清理。
    """

    errors: list[Exception] = []
    for name in ("网银会话", "相关进程", "U-Key设备"):
        errors.extend(_exit_action(argument, name))

    _framework_state().cleanup_errors = [str(error) for error in errors]
    for error in errors:
        Log.Warn("网银会话清理失败：{}".format(str(error)))
    return not errors


def cleanup_for_retry(argument: dict[str, Any]) -> None:
    """重试前释放上一轮残留资源。"""

    errors = _exit_all(argument)
    if errors:
        raise RuntimeError("重试前资源清理失败：{}".format(str(errors)))
    _framework_state().current_business = None


def _run_handlers(
    handlers: Sequence[WorkflowModule],
    argument: dict[str, Any],
    stage_name: str,
) -> list[Exception]:
    """依次执行收尾模块；一个失败不阻止后续模块。"""

    errors: list[Exception] = []
    for index, module in enumerate(handlers, start=1):
        try:
            _run_workflow_module(
                module,
                argument,
                "{}第{}个处理模块".format(stage_name, index),
            )
        # apa-lint: disable-next-line preserve-exception-traceback -- 收尾模块彼此独立，错误需汇总且不能阻止后续模块执行。
        except Exception as error:
            errors.append(error)
            Log.Error("{}处理模块执行失败：{}".format(stage_name, str(error)))
    return errors


def finish_success(argument: dict[str, Any]) -> dict[str, Any]:
    """执行正常收尾，并保证全部活动资源得到释放。"""

    framework = _framework_state()
    if framework.finished:
        return argument

    state = ensure_state()
    if state.task is None:
        raise RuntimeError("正常收尾前必须先生成标准任务。")
    state.task.status = "success"
    state.task = contract.parse_standard_task(state.task)
    state.run = contract.parse_run_state(state.run)

    errors = _run_handlers(_success_handlers_in_use, argument, "正常收尾")
    errors.extend(_exit_all(argument))

    # 正常结束兜底：无论相关进程是否已登记并清理成功，都确保关闭Chrome浏览器，
    # 避免配置遗漏或清理失败时浏览器进程残留。App.Kill 不会抛出异常，无需包裹。
    App.Kill("chrome.exe")

    framework.finished = True

    if errors:
        raise RuntimeError("正常结束阶段发生错误：{}".format(str(errors)))
    return argument


def finish_failure(
    argument: dict[str, Any],
    error: BaseException,
) -> NoReturn:
    """执行异常收尾、释放全部资源，然后重新抛出原始异常。"""

    state = ensure_state()
    state.run.has_error = True
    state.run.error_message = str(error)
    save_exception_screenshot("异常结束处理器_流程异常")
    if state.task is not None:
        state.task.status = "failed"
        state.task = contract.parse_standard_task(state.task)

    framework = _framework_state()
    secondary_errors = _run_handlers(_failure_handlers_in_use, argument, "异常收尾")
    secondary_errors.extend(_exit_all(argument))

    # 异常结束兜底：无论是否记录过相关进程，都确保关闭Chrome浏览器，
    # 避免异常发生在登录阶段之前时浏览器进程残留。App.Kill 不会抛出异常，无需包裹。
    App.Kill("chrome.exe")

    framework.finished = True

    for secondary_error in secondary_errors:
        try:
            error.add_note("收尾阶段发生错误：{}".format(str(secondary_error)))
        # apa-lint: disable-next-line preserve-exception-traceback -- 个别异常对象不支持add_note，错误文本会改写到日志中。
        except Exception:
            Log.Error("收尾阶段发生错误：{}".format(str(secondary_error)))
    raise error




# ==================== HUB通用规范、USB设备与U盾专用能力 ====================

# 不同项目中的端口可能来自 Excel、队列或配置文件，因此可能是数字或文本。
HubPort = str | int


class Hub(Protocol):
    """所有 HUB 实现都必须提供的 USB 设备控制接口。

    实现 HUB 时不需要继承这个类，只要提供同名函数和相同参数即可。
    例如，当前的 ``HUB_新同事.py`` 就是新同事厂商提供的一个符合该接口的模块。
    """

    def connect_device(
        self,
        ip_address: str,
        port: HubPort,
        device_id: str,
        app_code: str,
        app_key: str,
    ) -> contract.VendorResponseModel:
        """连接指定 USB 设备。

        Args:
            ip_address: HUB 的 IP 地址。
            port: HUB 的服务端口。
            device_id: USB 设备在 HUB 中的编号。
            app_code: HUB 分配的应用编码。
            app_key: HUB 分配的应用密钥。

        Returns:
            contract.VendorResponseModel: 已解析并校验的厂商连接结果。
        """
        ...

    def disconnect_device(
        self,
        ip_address: str,
        port: HubPort,
        device_id: str,
    ) -> contract.VendorResponseModel:
        """断开指定 USB 设备。

        Args:
            ip_address: HUB 的 IP 地址。
            port: HUB 的服务端口。
            device_id: USB 设备在 HUB 中的编号。

        Returns:
            contract.VendorResponseModel: 已解析并校验的厂商断开结果。
        """
        ...

    def power_on_device(
        self,
        ip_address: str,
        port: HubPort,
        device_id: str,
    ) -> contract.VendorResponseModel:
        """给指定 USB 设备上电。

        Args:
            ip_address: HUB 的 IP 地址。
            port: HUB 的服务端口。
            device_id: USB 设备在 HUB 中的编号。

        Returns:
            contract.VendorResponseModel: 已解析并校验的厂商上电结果。
        """
        ...

    def power_off_device(
        self,
        ip_address: str,
        port: HubPort,
        device_id: str,
    ) -> contract.VendorResponseModel:
        """给指定 USB 设备下电。

        Args:
            ip_address: HUB 的 IP 地址。
            port: HUB 的服务端口。
            device_id: USB 设备在 HUB 中的编号。

        Returns:
            contract.VendorResponseModel: 已解析并校验的厂商下电结果。
        """
        ...

    def query_device(
        self,
        ip_address: str,
        port: HubPort,
        keyword: str,
    ) -> contract.VendorResponseModel:
        """查询 USB 设备状态。

        Args:
            ip_address: HUB 的 IP 地址。
            port: HUB 的服务端口。
            keyword: 用于查询 USB 设备的编号或名称。

        Returns:
            contract.VendorResponseModel: 已解析并校验的厂商查询结果。
        """
        ...

    def disconnect_all_devices(
        self,
        ip_address: str,
        port: HubPort,
    ) -> contract.VendorResponseModel:
        """断开当前应用名下全部已连接 USB 设备（登录前清场，可选能力）。

        不是所有 HUB 都必须实现；未实现时登录流程按原方式仅断开本任务
        设备。实现方应保证单台失败不中断整体清场，查询失败返回失败结果
        而不抛异常。

        Args:
            ip_address: HUB 的 IP 地址。
            port: HUB 的服务端口。

        Returns:
            contract.VendorResponseModel: 清场汇总结果。
        """
        ...


# 一个网银流程在运行期间通常只使用一套 HUB。
# use_hub 会在流程开始时保存该实现，后续业务代码无需反复传入。
_hub_in_use: Hub | None = None


def use_hub(hub: Hub) -> None:
    """选择当前流程要使用的 HUB 实现。

    通常在 ``配置_运行方案.py`` 中调用一次。例如：

    ``import HUB_新同事``

    ``ebank.use_hub(HUB_新同事)``

    Args:
        hub: 已实现 HUB 规范的 Python 模块或对象。

    Returns:
        None

    Raises:
        TypeError: 传入的实现缺少 HUB 规范要求的函数。
    """
    ensure_state()
    required_functions = (
        "connect_device",
        "disconnect_device",
        "power_on_device",
        "power_off_device",
        "query_device",
    )
    missing_functions = [
        name for name in required_functions if not callable(getattr(hub, name, None))
    ]
    if missing_functions:
        raise TypeError(
            "选择HUB失败：当前HUB实现缺少函数：{}".format(
                "、".join(missing_functions)
            )
        )

    global _hub_in_use
    _hub_in_use = hub


def has_hub() -> bool:
    """判断当前运行方案是否选择了HUB实现。

    未选择HUB表示U盾和密码输入器可以直接连接当前执行机。设备接入和登录模块
    使用本函数跳过HUB配置、连接和清理逻辑。

    Returns:
        bool: 已通过 ``use_hub`` 选择HUB时为True，否则为False。
    """

    return _hub_in_use is not None


def _get_hub_in_use() -> Hub:
    """取得当前 HUB；未选择时给出流程开发人员可以直接理解的提示。"""
    if _hub_in_use is None:
        raise RuntimeError(
            "尚未选择HUB。请先在配置_运行方案.py中调用 ebank.use_hub(HUB实现)。"
        )
    return _hub_in_use


def connect_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
    app_code: str,
    app_key: str,
) -> contract.VendorResponseModel:
    """使用当前 HUB 连接指定 USB 设备。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。
        app_code: HUB 分配的应用编码。
        app_key: HUB 分配的应用密钥。

    Returns:
        contract.VendorResponseModel: 当前HUB实现返回的类型化连接结果。

    Raises:
        RuntimeError: 尚未通过 ``use_hub`` 选择 HUB 实现。
    """
    return _get_hub_in_use().connect_device(
        ip_address,
        port,
        device_id,
        app_code,
        app_key,
    )


def disconnect_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> contract.VendorResponseModel:
    """使用当前 HUB 断开指定 USB 设备。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。

    Returns:
        contract.VendorResponseModel: 当前HUB实现返回的类型化断开结果。

    Raises:
        RuntimeError: 尚未通过 ``use_hub`` 选择 HUB 实现。
    """
    return _get_hub_in_use().disconnect_device(ip_address, port, device_id)


def power_on_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> contract.VendorResponseModel:
    """使用当前 HUB 给指定 USB 设备上电。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。

    Returns:
        contract.VendorResponseModel: 当前HUB实现返回的类型化上电结果。

    Raises:
        RuntimeError: 尚未通过 ``use_hub`` 选择 HUB 实现。
    """
    return _get_hub_in_use().power_on_device(ip_address, port, device_id)


def power_off_device(
    ip_address: str,
    port: HubPort,
    device_id: str,
) -> contract.VendorResponseModel:
    """使用当前 HUB 给指定 USB 设备下电。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        device_id: USB 设备在 HUB 中的编号。

    Returns:
        contract.VendorResponseModel: 当前HUB实现返回的类型化下电结果。

    Raises:
        RuntimeError: 尚未通过 ``use_hub`` 选择 HUB 实现。
    """
    return _get_hub_in_use().power_off_device(ip_address, port, device_id)


def query_device(
    ip_address: str,
    port: HubPort,
    keyword: str,
) -> contract.VendorResponseModel:
    """使用当前 HUB 查询 USB 设备状态。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        keyword: 用于查询 USB 设备的编号或名称。

    Returns:
        contract.VendorResponseModel: 当前HUB实现返回的类型化查询结果。

    Raises:
        RuntimeError: 尚未通过 ``use_hub`` 选择 HUB 实现。
    """
    return _get_hub_in_use().query_device(ip_address, port, keyword)


def can_press_ukey_ok() -> bool:
    """判断当前 HUB 是否支持远程按下 U 盾确认键。

    Returns:
        bool: 已选择 HUB 且它提供 ``press_ukey_ok`` 时返回 ``True``。
    """

    return _hub_in_use_has_actions("press_ukey_ok")


def press_ukey_ok(
    ip_address: str,
    port: HubPort,
    ukey_id: str,
    app_code: str,
    app_key: str,
) -> contract.VendorResponseModel:
    """使用当前 HUB 远程按下指定 U 盾的确认键。

    不是所有 HUB 都支持该能力，调用前可以使用 :func:`can_press_ukey_ok`
    判断。新同事 CloudUSB 实现支持此操作。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。
        ukey_id: U 盾在 HUB 中的编号。
        app_code: HUB 分配的应用编码。
        app_key: HUB 分配的应用密钥。

    Returns:
        contract.VendorResponseModel: 当前HUB实现返回的类型化操作结果。

    Raises:
        RuntimeError: 尚未选择 HUB，或当前 HUB 不支持 U 盾确认键。
    """

    action = _get_optional_hub_action("press_ukey_ok", "远程按下U盾确认键")
    return action(ip_address, port, ukey_id, app_code, app_key)


def can_disconnect_all_devices() -> bool:
    """判断当前 HUB 是否支持断开全部已连接设备（登录前清场）。

    Returns:
        bool: 已选择 HUB 且它提供 ``disconnect_all_devices`` 时返回 ``True``。
    """

    return _hub_in_use_has_actions("disconnect_all_devices")


def disconnect_all_devices(
    ip_address: str,
    port: HubPort,
) -> contract.VendorResponseModel | None:
    """使用当前 HUB 断开全部已连接 USB 设备（登录前清场）。

    执行机被当前任务独占；清场消除上次运行或异常遗留的连接，确保后续
    只有本任务需要的设备在线，避免残留 U 盾导致选错设备。不是所有 HUB
    都支持该能力，调用前可以使用 :func:`can_disconnect_all_devices` 判断；
    未选择 HUB 或当前 HUB 不支持时返回 ``None``，由调用方按原流程继续。

    Args:
        ip_address: HUB 的 IP 地址。
        port: HUB 的服务端口。

    Returns:
        contract.VendorResponseModel | None: 当前HUB实现返回的类型化操作
            结果；HUB 不支持时为 ``None``（不抛异常，清场是尽力而为）。
    """

    if _hub_in_use is None or not _hub_in_use_has_actions("disconnect_all_devices"):
        Log.Info("[HUB清场] 当前未启用HUB或该HUB不支持清场能力，跳过")
        return None
    return _hub_in_use.disconnect_all_devices(ip_address, port)


def _hub_in_use_has_actions(*action_names: str) -> bool:
    """在不抛异常的情况下检查当前 HUB 的可选能力。"""

    if _hub_in_use is None:
        return False
    return all(callable(getattr(_hub_in_use, name, None)) for name in action_names)


def _get_optional_hub_action(
    action_name: str,
    capability_name: str,
) -> Callable[..., Any]:
    """取得当前 HUB 的可选动作，并提供流程开发人员可理解的错误。"""

    hub = _get_hub_in_use()
    action = getattr(hub, action_name, None)
    if not callable(action):
        raise RuntimeError(
            "当前 HUB 不支持{}。请改用支持该能力的 HUB，或使用KeyBox密码输入器。".format(
                capability_name
            )
        )
    return action


# ==================== 密码输入器通用规范与安全输入 ====================

class PasswordInputDevice(Protocol):
    """所有密码输入器实现必须提供的安全输入接口。

    实现模块不需要继承本类，只要提供同名函数即可。统一传入 ``password_input_device_info``，
    让不同实现自行读取所需配置，避免登录代码理解厂商参数差异。
    """

    def input_password(
        self,
        password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
        password_kind: str,
        delay_ms: int = 600,
    ) -> Any:
        """从安全槽位输入指定类型的密码。"""
        ...

    def press(
        self,
        password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
        key: str,
        action: str = "press",
        modifiers: Sequence[str] = (),
    ) -> Any:
        """通过密码输入器发送按键。"""
        ...


_password_input_device_in_use: PasswordInputDevice | None = None


def use_password_input_device(password_input_device: PasswordInputDevice) -> None:
    """选择当前流程使用的密码输入器实现。

    通常在 ``配置_运行方案.py`` 中与 :func:`use_hub` 一起调用。例如：

    ``import 密码输入器_KeyBox``

    ``ebank.use_password_input_device(密码输入器_KeyBox)``

    Args:
        password_input_device: 已实现密码输入器规范的 Python 模块或对象。

    Returns:
        None

    Raises:
        TypeError: 传入实现缺少 ``input_password`` 或 ``press``。
    """

    ensure_state()
    required_functions = ("input_password", "press")
    missing_functions = [
        name
        for name in required_functions
        if not callable(getattr(password_input_device, name, None))
    ]
    if missing_functions:
        raise TypeError(
            "选择密码输入器失败：当前实现缺少函数：{}".format(
                "、".join(missing_functions)
            )
        )

    global _password_input_device_in_use
    _password_input_device_in_use = password_input_device


def has_password_input_device() -> bool:
    """判断当前运行方案是否选择了密码输入器实现。

    Returns:
        bool: 已通过 ``use_password_input_device`` 选择实现时为True，否则为False。
    """

    return _password_input_device_in_use is not None


def _get_password_input_device_in_use() -> PasswordInputDevice:
    """取得当前密码输入器；未选择时提供可直接执行的修复提示。"""

    if _password_input_device_in_use is None:
        raise RuntimeError(
            "尚未选择密码输入器。请先在配置_运行方案.py中调用 "
            "ebank.use_password_input_device(密码输入器实现)。"
        )
    return _password_input_device_in_use


def input_password(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    password_kind: str,
    delay_ms: int = 600,
) -> Any:
    """使用当前密码输入器从安全槽位输入密码。

    Args:
        password_input_device_info: 登录模块收到并校验后的密码输入器连接和密码槽位模型。
        password_kind: 密码用途。当前支持 ``certificate``（证书密码）、
            ``login``（网银登录密码）和 ``payment``（支付密码）。
        delay_ms: 开始输入前的等待时间，单位为毫秒。

    Returns:
        Any: 当前密码输入器实现返回的原始结果。
    """

    checked_info = contract.parse_password_input_device_info(password_input_device_info)
    return _get_password_input_device_in_use().input_password(
        checked_info,
        password_kind,
        delay_ms,
    )


def press_key(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    key: str,
    action: str = "press",
    modifiers: Sequence[str] = (),
) -> Any:
    """使用当前密码输入器发送按键。

    Args:
        password_input_device_info: 登录模块收到并校验后的密码输入器连接和密码槽位模型。
        key: 按键名称，例如 ``Enter``。
        action: 内置按键动作，默认 ``press``。
        modifiers: Ctrl、Alt、Shift 等组合键；无组合键时传空序列。

    Returns:
        Any: 当前密码输入器实现返回的原始结果。
    """

    checked_info = contract.parse_password_input_device_info(password_input_device_info)
    return _get_password_input_device_in_use().press(
        checked_info,
        key,
        action,
        modifiers,
    )


def supports_text_input() -> bool:
    """判断当前密码输入器是否支持受控文本输入。"""

    return _password_input_device_in_use is not None and callable(
        getattr(_password_input_device_in_use, "input_text", None)
    )


def input_text(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    text: str,
    delay_ms: int = 0,
    gap_ms: int = 0,
) -> Any:
    """使用当前密码输入器输入受控文本。

    该能力是可选的。KeyBox实现当前模板只确认了密码和按键能力，
    新同事密码输入器实现支持文本输入。

    Args:
        password_input_device_info: 登录模块收到并校验后的密码输入器连接和密码槽位模型。
        text: 要输入的受控文本。
        delay_ms: 开始输入前的等待时间，单位为毫秒。
        gap_ms: 相邻字符之间的间隔，单位为毫秒。

    Returns:
        Any: 当前密码输入器实现返回的原始结果。

    Raises:
        RuntimeError: 当前密码输入器没有实现文本输入能力。
    """

    password_input_device = _get_password_input_device_in_use()
    action = getattr(password_input_device, "input_text", None)
    if not callable(action):
        raise RuntimeError("当前密码输入器不支持文本输入，请更换密码输入器实现。")
    checked_info = contract.parse_password_input_device_info(password_input_device_info)
    return action(checked_info, text, delay_ms, gap_ms)

# ==================== 网银任务查询 ====================

def query_enabled_bank_tasks(
    database_host: str,
    database_port: str | int,
    database_user: str,
    database_password: str,
    database_name: str,
    table_name: str,
    bank_name: str,
) -> list[dict[str, Any]]:
    """从 MySQL 查询指定银行当前启用的任务。

    筛选 ``status = 1`` 和指定 ``bank_name``，按 ``id`` 倒序；数据库操作
    失败时最多尝试4次，前3次失败后分别等待5秒。

    Args:
        database_host: MySQL 服务器地址。
        database_port: MySQL 服务端口。
        database_user: MySQL 登录用户名。
        database_password: MySQL 登录密码。
        database_name: MySQL 数据库名。
        table_name: 保存网银任务的数据表名。
        bank_name: 要查询的银行名称。

    Returns:
        list[dict[str, Any]]: 数据库运行时返回的字典行列表。

    Raises:
        RuntimeError: 连续 4 次仍无法完成查询。
    """

    last_error: Exception | None = None
    for attempt in range(4):
        database = None
        try:
            Log.Info("开始链接数据库")
            database = Database.CreateDB(
                "MySQL",
                {
                    "host": database_host,
                    "port": database_port,
                    "user": database_user,
                    "password": database_password,
                    "database": database_name,
                    "charset": "utf8",
                },
            )
            sql = (
                'SELECT * FROM {} WHERE status = 1 AND bank_name = "{}" '
                "ORDER BY id DESC;"
            ).format(table_name, bank_name)
            Log.Info(sql)
            rows = Database.QueryAll(database, sql, {"rdict": True, "args": []})
            Log.Debug(str(mask_sensitive(rows)))
            Database.CloseDB(database)
            database = None
            Log.Info("关闭数据库链接")
            return rows
        # apa-lint: disable-next-line preserve-exception-traceback -- 查询按约定重试三次，最后一次失败后重新抛出原始错误。
        except Exception as error:
            last_error = error
            Log.Warn(str(error))
            # 查询失败时也主动释放数据库连接，避免重试过程中累积连接。
            if database is not None:
                try:
                    Database.CloseDB(database)
                # apa-lint: disable-next-line preserve-exception-traceback -- 关闭失败不覆盖触发重试的数据库查询错误。
                except Exception as close_error:
                    Log.Warn("数据库异常后关闭连接失败：{}".format(str(close_error)))

        if attempt == 3:
            Log.Error("获取数据库中的银行数据信息异常：{}".format(str(last_error)))
            raise RuntimeError(str(last_error)) from last_error
        Delay(5000)

    # 循环的最后一次失败一定会在上方抛出；这一行只帮助静态类型检查。
    raise RuntimeError("获取数据库中的银行数据信息异常。")

# ==================== 配置读取 ====================

ConfigValue: TypeAlias = str | list[str]
ProjectConfig: TypeAlias = dict[str, dict[str, ConfigValue]]


def load_excel_config(config_path: str) -> ProjectConfig:
    """把 Excel 配置文件转换成分工作表保存的字典。

    每个工作表从第二行开始读取 A、B 两列：A 列作为配置名，B 列作为配置值。
    空配置名会被忽略；配置名为 ``AppsName`` 时，使用英文逗号把值拆成进程名
    列表；其他配置项统一转换为去除首尾空白的文本。

    Args:
        config_path: Excel 配置文件路径。

    Returns:
        ProjectConfig: 第一层 key 是工作表名，第二层 key 是配置名。

    Raises:
        RuntimeError: 配置文件不存在。
        Exception: 打开或读取工作簿失败。
    """

    if not os.path.isfile(config_path):
        raise RuntimeError("配置文件不存在，流程结束。")

    workbook = load_workbook(config_path, read_only=True, data_only=True)
    config: ProjectConfig = {}
    try:
        for worksheet in workbook.worksheets:
            sheet_config: dict[str, ConfigValue] = {}
            for raw_key, raw_value in worksheet.iter_rows(
                min_row=2,
                max_col=2,
                values_only=True,
            ):
                key = "" if raw_key is None else str(raw_key).strip()
                if key == "":
                    continue
                value = "" if raw_value is None else str(raw_value).strip()
                sheet_config[key] = value.split(",") if key == "AppsName" else value

            if not sheet_config:
                Log.Warn("配置文件的[{}]工作表无配置信息！".format(worksheet.title))
                continue
            config[worksheet.title] = sheet_config
    finally:
        workbook.close()

    return config


def load_ini_config(config_path: str) -> ProjectConfig:
    """把 INI 配置文件转换成分小节保存的字典。

    ``Base.AppsName`` 如果是字符串，会转换成单元素列表。该函数不按逗号拆分
    INI 中的 ``AppsName``，以保持原模板行为。

    Args:
        config_path: INI 配置文件路径。

    Returns:
        ProjectConfig: 第一层 key 是 INI 小节名，第二层 key 是配置名。

    Raises:
        RuntimeError: 配置文件不存在。
        KeyError: 配置缺少原模板要求的 ``Base.AppsName``。
        Exception: INI 运行时读取失败。
    """

    if not File.FileExists(config_path):
        message = "配置文件不存在，流程结束。"
        Log.Error(message)
        raise RuntimeError(message)

    config: ProjectConfig = {}
    for section in INI.EnumSection(config_path):
        section_config: dict[str, ConfigValue] = {}
        config[str(section)] = section_config
        for key in INI.EnumKey(config_path, section):
            section_config[str(key)] = INI.Read(config_path, section, key, "")

    apps_name = config["Base"]["AppsName"]
    if isinstance(apps_name, str):
        config["Base"]["AppsName"] = [apps_name]
    return config

# ==================== 浏览器下载 ====================

def save_edge_download(save_path: str) -> bool:
    """在 Edge 的“另存为”窗口中保存文件并等待下载完成。

    该函数依赖项目界面库中的 ``Edge下载_另存为按钮``、
    ``Edge另存为_文件名输入框``、``Edge另存为_保存按钮``、
    ``Edge另存为_覆盖确认窗口`` 和 ``Edge另存为_确认覆盖按钮`` 元素。

    Args:
        save_path: 包含文件名的绝对保存路径。

    Returns:
        bool: 最多检查 31 次、每次间隔 2 秒；发现文件后返回 ``True``，
        超时返回 ``False``。

    Raises:
        Exception: 鼠标、键盘、界面元素或文件运行时调用失败。
    """

    Mouse.Action(
        Hover_ElementSelect("Edge下载_另存为按钮"),
        "left",
        "click",
        10000,
        {
            "bContinueOnError": False,
            "iDelayAfter": 300,
            "iDelayBefore": 200,
            "bSetForeground": True,
            "sCursorPosition": "Center",
            "iCursorOffsetX": 0,
            "iCursorOffsetY": 0,
            "sKeyModifiers": [],
            "sSimulate": "simulate",
            "bMoveSmoothly": False,
        },
    )
    Keyboard.InputText(
        Hover_ElementSelect("Edge另存为_文件名输入框"),
        save_path,
        True,
        20,
        10000,
        {
            "bContinueOnError": False,
            "iDelayAfter": 300,
            "iDelayBefore": 500,
            "bSetForeground": True,
            "sSimulate": "message",
            "bValidate": False,
            "bClickBeforeInput": False,
        },
    )
    Mouse.Action(
        Hover_ElementSelect("Edge另存为_保存按钮"),
        "left",
        "click",
        10000,
        _mouse_options(),
    )

    if UiElement.Exists(
        Hover_ElementSelect("Edge另存为_覆盖确认窗口"),
        {
            "bContinueOnError": False,
            "iDelayAfter": 300,
            "iDelayBefore": 200,
        },
    ):
        Mouse.Action(
            Hover_ElementSelect("Edge另存为_确认覆盖按钮"),
            "left",
            "click",
            10000,
            _mouse_options(),
        )

    return _wait_for_download(save_path)


def save_chrome_download(save_path: str) -> bool:
    """在 Chrome 的“另存为”窗口中保存文件并等待下载完成。

    该函数依赖项目界面库中的 ``Chrome另存为_文件名输入框``、
    ``Chrome另存为_保存按钮``、``Chrome另存为_覆盖确认窗口`` 和
    ``Chrome另存为_确认覆盖按钮`` 元素。

    Args:
        save_path: 包含文件名的绝对保存路径。

    Returns:
        bool: 最多检查 31 次、每次间隔 2 秒；发现文件后返回 ``True``，
        超时返回 ``False``。

    Raises:
        Exception: 键盘、鼠标、界面元素或文件运行时调用失败。
    """

    Log.Info(save_path)
    Delay(3000)
    Keyboard.InputText(
        Hover_ElementSelect("Chrome另存为_文件名输入框"),
        save_path,
        True,
        20,
        10000,
        {
            "bContinueOnError": False,
            "iDelayAfter": 300,
            "iDelayBefore": 500,
            "bSetForeground": True,
            "sSimulate": "message",
            "bValidate": False,
            "bClickBeforeInput": False,
        },
    )
    Mouse.Action(
        Hover_ElementSelect("Chrome另存为_保存按钮"),
        "left",
        "click",
        10000,
        _mouse_options(),
    )

    if UiElement.Exists(
        Hover_ElementSelect("Chrome另存为_覆盖确认窗口"),
        {
            "bContinueOnError": False,
            "iDelayAfter": 300,
            "iDelayBefore": 200,
        },
    ):
        Mouse.Action(
            Hover_ElementSelect("Chrome另存为_确认覆盖按钮"),
            "left",
            "click",
            10000,
            _mouse_options(),
        )

    return _wait_for_download(save_path)


def _mouse_options() -> dict[str, object]:
    """返回原模板点击保存和覆盖按钮时使用的鼠标参数。"""

    return {
        "bContinueOnError": False,
        "iDelayAfter": 300,
        "iDelayBefore": 200,
        "bSetForeground": True,
        "sCursorPosition": "Center",
        "iCursorOffsetX": 0,
        "iCursorOffsetY": 0,
        "sKeyModifiers": [],
        "sSimulate": "simulate",
        "bMoveSmoothly": False,
    }


def _wait_for_download(save_path: str) -> bool:
    """按原模板的次数和间隔等待目标文件出现。"""

    for _ in range(31):
        if File.FileExists(save_path):
            return True
        Delay(2000)
    return False

# ==================== 邮件发送 ====================

MailRecipients: TypeAlias = str | list[str]


def send_email_with_retry(
    server: str,
    port: int,
    smtp_account: str,
    password: str,
    sender: str,
    recipients: MailRecipients,
    title: str,
    content: str,
    max_attempts: int = 3,
) -> bool:
    """发送邮件，并在失败时按原模板规则自动重试。

    每次失败后等待 2 秒；最后一次失败后不再等待。``max_attempts`` 为 0
    或其他假值时按 3 次处理。发送失败只返回 ``False``，不会把最后一次异常
    重新抛出，以保持原模板的通知容错行为。

    Args:
        server: SMTP 服务器地址。
        port: SMTP 服务器端口。
        smtp_account: SMTP 登录账号。
        password: SMTP 登录密码。
        sender: 发件人邮箱地址。
        recipients: 收件人邮箱地址，或收件人地址列表。
        title: 邮件标题。
        content: 邮件正文。
        max_attempts: 最多发送次数，默认 3 次。

    Returns:
        bool: 任意一次发送成功返回 ``True``，全部失败返回 ``False``。
    """

    if not max_attempts:
        max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            success = Mail.SendExt(
                {
                    "host": server,
                    "port": port,
                    "ssl": True,
                    "authentication": True,
                    "user": smtp_account,
                    "password": password,
                },
                sender,
                cast(Any, recipients),
                "",
                "",
                title,
                content,
                [],
            )
            if success:
                Log.Info("邮件发送成功（第{}次尝试）".format(attempt))
                return True
            Log.Warn("邮件发送返回失败，将重试（第{}次）".format(attempt))
        # apa-lint: disable-next-line preserve-exception-traceback -- 邮件通知按约定重试并最终返回False，错误文本已经记录到日志。
        except Exception as error:
            Log.Error("发送邮件第{}次失败: {}".format(attempt, str(error)))

        if attempt < max_attempts:
            Delay(2000)

    Log.Error("邮件发送重试{}次均失败，请检查SMTP配置".format(max_attempts))
    return False

# ==================== 异常截图 ====================

def _build_screenshots_folder() -> str:
    """返回当前任务的异常截图目录，不存在时自动创建。

    优先使用配置的 ``Base.ExScreenshotsFolderPath`` 自定义目录；
    未配置时使用 Output/银行名称/纯日期yyyymmdd/异常截图 默认层级，
    与原始流水等业务产物目录同级；截图直接保存，不再叠加日期子目录。
    目录缺失时按 ``os.makedirs`` 递归创建。

    Returns:
        str: 异常截图目录的绝对路径。

    Raises:
        RuntimeError: 任务尚未初始化，或目录创建失败。
    """

    state = ensure_state()
    if state.task is None or state.config is None:
        raise RuntimeError("异常截图前必须先完成环境初始化。")

    custom_folder = state.config.output.screenshots
    if custom_folder and str(custom_folder).strip():
        folder = str(custom_folder).strip()
    else:
        folder = os.path.join(
            state.task.output.business_folder,
            "异常截图",
        )
    # 父目录已含执行日期（银行名称/yyyymmdd），整轮重试沿用同一日期目录，
    # 截图直接保存到该层级，不再按天叠加子目录。
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        raise RuntimeError("创建异常截图目录失败：{}。".format(folder)) from error
    return folder


def save_exception_screenshot(step_name: str) -> str:
    """保存当前桌面的异常全屏截图。

    直接使用 PIL ``ImageGrab`` 截取整个桌面，不依赖浏览器页面状态。
    截图目录结构为 ``{screenshots_folder}/{yyyymmdd}/``，文件名格式为
    ``{异常模块_错误名称}_{HHmmss}.png``；同一秒重名时自动追加序号。
    任何截图失败只记录日志，绝不向调用方抛出异常，避免影响主流程。

    Args:
        step_name: 触发截图的业务步骤名（含异常模块和错误名称），用于文件名标识。

    Returns:
        str: 成功时返回截图文件完整路径；失败时返回空字符串。
    """

    forbidden_characters = "\\/:*?\"<>|"
    safe_step = "".join(
        character for character in str(step_name) if character not in forbidden_characters
    ).strip() or "异常"
    # apa-lint: disable-next-line preserve-exception-traceback -- 截图目录不可用时仅记录告警并跳过，不能影响主流程异常处理。
    try:
        folder = _build_screenshots_folder()
    # apa-lint: disable-next-line preserve-exception-traceback -- 同上，抑制说明见上一行。
    except Exception as error:
        Log.Warn("[异常截图] 无法确定截图目录：{}".format(str(error)))
        return ""

    timestamp = Time.Format(Time.Now(), "HHmmss")
    file_path = os.path.join(folder, "{}_{}.png".format(safe_step, timestamp))
    sequence = 1
    while os.path.exists(file_path):
        file_path = os.path.join(
            folder,
            "{}_{}_{}.png".format(timestamp, safe_step, sequence),
        )
        sequence += 1

    try:
        from PIL import ImageGrab

        ImageGrab.grab().save(file_path)
        Log.Info("[异常截图] 已保存全屏截图：{}".format(file_path))
        return file_path
    # apa-lint: disable-next-line preserve-exception-traceback -- 全屏截图失败仅记录错误，不能影响主流程异常处理。
    except Exception as screen_error:
        Log.Error("[异常截图] 全屏截图失败：{}".format(str(screen_error)))
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return ""


# ==================== 进程管理 ====================

def close_apps(app_names: list[str]) -> None:
    """关闭网银流程使用的应用程序。

    Args:
        app_names: 要关闭的进程名称，例如 ``["chrome.exe", "abc.exe"]``。

    Returns:
        None

    Raises:
        Exception: 流程运行时关闭应用失败时，保留并向调用方抛出原始异常。
    """
    Log.Info("准备关闭流程相关应用：{}".format(str(app_names)))
    errors: list[Exception] = []
    for app_name in app_names:
        # 忽略空名称，避免配置中多余的逗号导致误操作。
        if str(app_name).strip() == "":
            continue
        try:
            App.Kill(str(app_name).strip())
        # apa-lint: disable-next-line preserve-exception-traceback -- 结束单个进程失败不能阻止其余进程清理，错误会统一返回。
        except Exception as error:
            errors.append(error)
            Log.Warn("结束进程{}失败：{}".format(str(app_name), str(error)))

    if errors:
        raise RuntimeError("部分流程相关进程未能结束：{}".format(str(errors)))

# ==================== Excel汇总 ====================

def append_excel_row(path: str, row: Sequence[Any]) -> None:
    """向 Excel 第一个工作表的下一空行追加一行数据。

    Args:
        path: 汇总表文件路径。
        row: 按列顺序写入的一行数据。

    Returns:
        None

    Raises:
        Exception: 打开、写入或保存工作簿失败。
    """

    workbook = load_workbook(path)
    try:
        worksheet = workbook.worksheets[0]
        last_data_row: int = 0
        for cells in worksheet.iter_rows():
            if any(
                cell.value is not None and str(cell.value).strip() != ""
                for cell in cells
            ):
                current_row = cells[0].row
                if current_row is not None:
                    last_data_row = current_row

        target_row = last_data_row + 1
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=target_row, column=column, value=value)
        workbook.save(path)
    finally:
        workbook.close()

# ==================== 界面元素等待 ====================

def wait_for_element(
    selector: Any,
    max_attempts: int,
    interval_ms: int,
) -> bool:
    """等待界面元素出现。

    Args:
        selector: 界面元素选择对象，通常由 ``Hover_ElementSelect`` 取得。
        max_attempts: 最多检查多少次。
        interval_ms: 每次检查失败后等待多少毫秒。

    Returns:
        bool: 在限定次数内找到元素时返回 ``True``，否则返回 ``False``。
    """
    for _ in range(max_attempts):
        exists = UiElement.Exists(
            selector,
            {
                "bContinueOnError": False,
                "iDelayAfter": 300,
                "iDelayBefore": 200,
                "bWaitDOMReady": True,
            },
        )
        if exists:
            return True
        Delay(interval_ms)
    return False


# ==================== 验证码识别 ====================

def recognize_captcha(image_path: str, png_fix: bool = False) -> str:
    """识别图片中的字符验证码。

    流程运行环境已内置 ``ddddocr``。公共入口只负责读取图片并返回识别文本，
    不在公共能力中判断验证码长度或业务是否成功；这些规则由调用验证码的
    登录或交付模块决定。

    Args:
        image_path: 验证码图片的完整文件路径。
        png_fix: 图片为透明黑色 PNG 且普通识别失败时设为 ``True``；默认
            ``False``，保持 ddddocr 的普通识别方式。

    Returns:
        str: 识别得到的验证码文本；模型未返回内容时为空字符串。

    Raises:
        OSError: 图片文件不存在或无法读取。
        Exception: ddddocr 模型初始化或识别失败时保留原始异常。
    """

    with open(image_path, "rb") as image_file:
        image_data = image_file.read()
    recognizer = ddddocr.DdddOcr(show_ad=False)
    result = recognizer.classification(image_data, png_fix=png_fix)
    captcha_text = "" if result is None else str(result).strip()
    Log.Debug("验证码识别完成，字符数={}".format(len(captcha_text)))
    return captcha_text


# ==================== 流程图维护入口 ====================

def main(argument: dict[str, Any]) -> dict[str, Any]:
    """保留公共能力模块在流程图中的维护入口。

    本模块的实际能力由其他流程块通过具名函数调用。该入口不会执行任何业务动作，
    也不应连接到主流程；仅用于让文件能够作为未连线节点显示和同步。

    Args:
        argument: 当前流程参数字典，本入口不会读取或修改其中的内容。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    return argument


# ==================== 公共入口 ====================

__all__ = [
    "Hub",
    "PasswordInputDevice",
    "WorkflowModule",
    "append_excel_row",
    "apply_runtime_log_level",
    "get_business_state",
    "can_press_ukey_ok",
    "can_disconnect_all_devices",
    "disconnect_all_devices",
    "cleanup_login_resources",
    "cleanup_for_retry",
    "close_apps",
    "connect_device",
    "configure_logging",
    "set_assistant_path",
    "create_business_execution",
    "disconnect_device",
    "ensure_state",
    "finish_failure",
    "finish_success",
    "get_business_name",
    "has_hub",
    "has_password_input_device",
    "input_password",
    "input_text",
    "load_excel_config",
    "load_ini_config",
    "mask_sensitive",
    "power_off_device",
    "power_on_device",
    "press_key",
    "press_ukey_ok",
    "query_enabled_bank_tasks",
    "query_device",
    "recognize_captcha",
    "mark_ukey_released",
    "release_password_input_device",
    "release_ukey_connection",
    "remember_apps",
    "remember_password_input_device_connection",
    "remember_ukey_connection",
    "run_business",
    "run_delivery",
    "run_login",
    "run_logout",
    "save_chrome_download",
    "save_edge_download",
    "save_exception_screenshot",
    "send_email_with_retry",
    "set_bank_name",
    "supports_text_input",
    "unuse_all",
    "use_business",
    "use_delivery",
    "use_finish_handlers",
    "use_hub",
    "use_password_input_device",
    "use_login",
    "use_logout",
    "wait_for_element",
    "extract_root_location",
]
