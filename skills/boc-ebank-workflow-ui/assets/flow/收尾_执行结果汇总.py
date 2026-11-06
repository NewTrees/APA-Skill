from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


# 这些是客户可见的交付规则。需要改变文件夹、文件名或汇总字段时，
# Agent只修改本模块，不需要修改环境初始化和结束框架。
SUMMARY_TEMPLATE = RES("config/模板/执行汇总模板.xlsx")
SUMMARY_FOLDER = "1、执行汇总"
SUMMARY_FILE = "执行汇总表_{date}.xlsx"

STATUS_TEXT = {
    "success": "成功",
    "partial_success": "部分成功",
    "failed": "失败",
    "skipped": "未启用",
    "no_data": "无数据",
    "pending": "待处理",
    "processing": "待处理",
}


def _business(
    account: contract.StandardAccountModel,
    business_type: int,
) -> contract.BusinessExecutionModel | None:
    """读取客户汇总表关心的业务；本次任务未启用时返回空。"""

    return account.get_business(business_type)


def _business_status(business: contract.BusinessExecutionModel | None) -> str:
    """把业务状态翻译为统一的中文枚举；未启用的业务显示“未启用”。"""

    status = business.status if business is not None else "skipped"
    return STATUS_TEXT.get(status, status)


def _business_error(business: contract.BusinessExecutionModel | None) -> str:
    """读取业务失败原因；仅失败时填写，成功、无数据等正常状态一律为空。"""

    if business is None or business.status != "failed":
        return ""
    return business.error_message


def _output_path(
    business: contract.BusinessExecutionModel | None,
    category: str,
) -> str:
    """读取指定类别的全部产物路径；多个产物时换行拼接。

    对账单可能按月下载多份文件；汇总表必须登记全部产物路径，
    只取第一个会漏掉其余文件。单个产物（流水文件、回单目录）时
    保持原样，行为不变。
    """

    if business is None or business.result is None:
        return ""
    paths = [
        output.path
        for output in business.result.outputs
        if output.category == category and str(output.path).strip() != ""
    ]
    return "\n".join(paths)


def _business_value(
    business: contract.BusinessExecutionModel | None,
    name: str,
) -> str:
    """读取指定名称的业务结果值。"""

    if business is None or business.result is None:
        return ""
    return business.result.get_value(name)


def _create_from_template(template_path: str, folder: str, file_name: str) -> str:
    """从Excel模板创建汇总文件；已有同名文件时直接复用。"""

    if not File.FileExists(template_path):
        raise RuntimeError("执行结果汇总模板不存在：{}".format(template_path))
    if not File.FolderExists(folder):
        File.CreateFolder(folder)

    summary_path = folder + "\\" + file_name
    if File.FileExists(summary_path):
        return summary_path

    File.CopyFile(template_path, folder, True)
    copied_name = File.BaseName(template_path, True)
    File.RenameEx(folder + "\\" + copied_name, file_name)
    Log.Info("[结果汇总] 已创建汇总表：{}".format(summary_path))
    return summary_path


def _ensure_summary_file(
    task: contract.StandardTaskModel,
    config: contract.RuntimeConfigModel,
) -> str:
    """创建或复用本次执行的汇总文件，并把路径写回标准任务。

    Raises:
        RuntimeError: 配置指定的模板或回退使用的项目内置模板不存在。
    """

    template_path = config.summary_templates.summary or SUMMARY_TEMPLATE
    folder = config.output.business + "\\" + SUMMARY_FOLDER
    # @note 汇总目录与银行名称目录同级，即 Output\1、执行汇总。
    file_name = SUMMARY_FILE.format(
        date=Time.Format(Time.Now(), "yyyy_mm_dd")
    )
    task.output.summary_file = _create_from_template(
        template_path,
        folder,
        file_name,
    )
    return task.output.summary_file


def _log_account(account: contract.StandardAccountModel) -> None:
    """输出一个账号的业务结果，便于流程开发人员现场排查。"""

    Log.Info("[结果汇总] 账号={}，户名={}，总体状态={}".format(
        account.info.bank_account,
        account.info.account_name,
        account.status,
    ))
    for business in account.businesses:
        if business.status == "skipped":
            continue
        Log.Info("[结果汇总]   业务={}，状态={}，耗时={}秒".format(
            business.business_name,
            business.status,
            business.duration_seconds,
        ))
        if business.error_message:
            Log.Warn("[结果汇总]   原因={}".format(business.error_message))
        if business.result is None:
            continue
        for output in business.result.outputs:
            Log.Info("[结果汇总]   产物={}：{}".format(output.category, output.path))
        for value in business.result.values:
            Log.Info("[结果汇总]   结果={}：{}{}".format(value.name, value.value, value.unit))


def _rpa_status(task: contract.StandardTaskModel, account: contract.StandardAccountModel) -> str:
    """按本账号自身结果计算RPA状态，固定三种：成功、部分成功、失败。

    无数据属于正常完成，计入成功类；流水转换失败计入失败类。
    从未登录成功时该账号没有执行任何业务，直接判失败。
    登录轮次等任务级信息不进状态列，只写入备注。
    """

    active = [b for b in account.businesses if b.status != "skipped"]
    # 从未登录成功：账号什么都没执行，失败。
    if not task.login.ever_logged_in:
        return "失败"
    if not active:
        return "失败"
    convert_failed = (
        task.enable_convert_template
        and account.delivery.transaction_convert.status == "failed"
    )
    has_ok = any(b.status in ("success", "no_data") for b in active)
    all_ok = all(b.status in ("success", "no_data") for b in active)
    if all_ok and not convert_failed:
        return "成功"
    if has_ok:
        return "部分成功"
    return "失败"


def _build_note(
    task: contract.StandardTaskModel,
    account: contract.StandardAccountModel,
    workflow_error: str,
) -> str:
    """生成备注列内容，全场景统一以U盾编号开头。

    格式：``U盾编号为{编号}：<账号视角结论>；<过程补充信息>``。

    场景与文案（2026-10-10 与负责人对齐定案，2026-10-11 补转换与单账号口径）：
    1. 任务成功+首轮完成：任务执行成功；
    2. 任务成功+有重试：任务执行成功；共执行N轮；其中M轮登录成功；
    3. 任务异常+本账号业务和转换全部成功且存在其他账号：当前账号全部
       业务执行成功，该U盾下其它子账号存在失败（不带"异常中断"等歧义
       前缀；单账号任务不虚构其他子账号）；
    4/5. 任务异常+本账号有业务或转换失败：任务异常中断：<业务名>失败：
       <原因>／流水数据转换失败：<原因> 逐项罗列（与RPA状态口径一致）；
    6. 从未登录成功：登录失败：<原因>；全部轮次均未登录成功；
    有重试的场景追加轮次说明；末轮登录失败时再追加累计说明。

    Args:
        task: 标准任务，读取U盾编号、任务状态和登录状态。
        account: 当前账号，读取本账号业务结果。
        workflow_error: 框架传入的任务级异常信息，仅在登录失败兜底时使用。

    Returns:
        str: 完整备注文本。
    """

    state = GlobalVariables["ebank"]
    retry_count = state.run.retry_count
    ukey_number = task.devices.ukey.ukey_number
    note_parts = []

    failed = task.status == "failed"
    if not failed:
        # 任务整体成功：本账号必然已随任务成功。
        note_parts.append("任务执行成功")
    elif not task.login.ever_logged_in:
        # 从未登录成功：本账号什么都没执行，说明登录失败原因。
        reason = task.login.error_message or workflow_error or "未取得具体错误信息"
        note_parts.append("登录失败：{}".format(reason))
        note_parts.append("全部轮次均未登录成功")
    else:
        business_errors = [
            "{}失败：{}".format(business.business_name, business.error_message)
            for business in account.businesses
            if business.status == "failed" and business.error_message
        ]
        # 流水转换失败与业务失败同级别纳入备注，与RPA状态列口径一致。
        convert = account.delivery.transaction_convert
        convert_error = (
            "流水数据转换失败：{}".format(convert.error_message)
            if task.enable_convert_template and convert.status == "failed" and convert.error_message
            else ""
        )
        if business_errors or convert_error:
            note_parts.append("任务异常中断：" + "；".join(
                part for part in [*business_errors, convert_error] if part
            ))
        elif len(task.accounts) > 1:
            # 本账号业务与转换全部成功，且任务确有其他账号——异常由其他
            # 子账号引起；单账号任务不会走到这里（本账号全成任务即成功），
            # 避免对单账号任务虚构"其它子账号存在失败"。
            note_parts.append("当前账号全部业务执行成功，该U盾下其它子账号存在失败")
        else:
            # 兜底：单账号、业务与转换全成但任务仍异常（理论上罕见）。
            reason = workflow_error or "未取得具体错误信息"
            note_parts.append("任务异常中断：{}".format(reason))

    # 过程补充：重试轮次说明（首轮即成功且任务成功时不产生冗余）。
    has_retry = retry_count > 0 or task.login.status != "success"
    if has_retry:
        total_rounds = retry_count + 1
        if task.login.ever_logged_in:
            note_parts.append("共执行{}轮；其中{}轮登录成功".format(total_rounds, task.login.rounds_logged_in))
            if task.login.status != "success":
                note_parts.append("最后一轮登录失败，业务结果为之前轮次累计")
        else:
            note_parts.append("共执行{}轮".format(total_rounds))

    return "U盾编号为{}：{}".format(ukey_number, "；".join(note_parts))


def _convert_status(account: contract.StandardAccountModel, task: contract.StandardTaskModel) -> str:
    """读取流水数据转换状态，统一为中文枚举；未启用或未进入转换时显示对应状态。

    Returns:
        str: 转换状态中文枚举：成功/失败/待处理/未启用/未执行等。
    """

    convert = account.delivery.transaction_convert
    # 任务未启用流水模板转换时，状态列只写“未启用”，原因细节写入失败原因列。
    if not task.enable_convert_template:
        return "未启用"
    # 状态仍为初始 pending：无流水产物等原因没有进入转换，与业务列口径
    # 统一显示“待处理”。
    if convert.status == "pending":
        return "待处理"
    return STATUS_TEXT.get(convert.status, convert.status)


def _convert_error(account: contract.StandardAccountModel) -> str:
    """读取流水数据转换的失败原因；仅失败时填写，其余状态为空。"""

    convert = account.delivery.transaction_convert
    if convert.status == "failed":
        return convert.error_message
    return ""


def _write_summary(
    task: contract.StandardTaskModel,
    workflow_error: str,
) -> None:
    """按客户当前报表列写入银行、账号、流水、余额、回单和对账单结果。

    模板表头顺序为：银行名称、账号、处理时间、RPA状态、下载流水状态、
    流水保存路径、失败原因、流水转换状态、流水转换保存路径、失败原因、
    余额查询状态、余额查询值、失败原因、回单下载状态、回单保存路径、失败原因、
    对账单下载状态、对账单保存路径、失败原因、开户行、户名、资金岗、备注。
    """

    if not task.output.summary_file:
        raise RuntimeError("执行汇总表路径尚未生成。")
    submit_time = Time.Format(Time.Now(), "yyyy/mm/dd hh:mm")
    for account in task.accounts:
        transaction = _business(account, 1)
        balance = _business(account, 2)
        receipt = _business(account, 3)
        statement = _business(account, 4)
        failed = task.status == "failed"
        # RPA状态统一按本账号自身结果计算（成功/部分成功/失败三种），
        # 任务整体是否异常不影响状态取值。
        # 备注列统一以U盾编号开头：任务成功记"任务执行成功"；任务异常时
        # 本账号有失败记逐项失败原因，本账号全部成功则说明其他子账号存在
        # 失败；过程信息（轮次/登录）按需追加。
        note = _build_note(task, account, workflow_error)

        ebank.append_excel_row(task.output.summary_file, [
            task.bank_name,
            account.info.bank_account,
            submit_time,
            _rpa_status(task, account),
            _business_status(transaction),
            _output_path(transaction, "流水"),
            _business_error(transaction),
            _convert_status(account, task),
            account.delivery.transaction_convert.converted_file_path,
            _convert_error(account),
            _business_status(balance),
            _business_value(balance, "可用余额"),
            _business_error(balance),
            _business_status(receipt),
            _output_path(receipt, "回单"),
            _business_error(receipt),
            _business_status(statement),
            _output_path(statement, "对账单"),
            _business_error(statement),
            account.info.open_bank_name,
            account.info.account_name,
            account.info.keeper,
            note,
        ])


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """创建结果汇总文件，并写入本次正常或异常执行结果。

    本模块同时注册在正常和异常收尾列表中。框架会先设置任务最终状态，再调用
    本模块；本模块不判断主流程该走成功还是失败，也不释放设备。

    Args:
        argument: 流程块之间传递的共享字典。本模块不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 标准任务存在但运行配置或汇总模板不可用。
    """

    # @step 检查结果汇总所需的任务和配置。
    state = GlobalVariables["ebank"]
    if state.task is None:
        Log.Warn("[结果汇总] 标准任务尚未建立，无法生成账号结果汇总")
        return argument
    if state.config is None:
        raise RuntimeError("执行结果汇总前必须读取运行配置。")

    # @step 创建本次执行对应的汇总文件。
    task = state.task
    _ensure_summary_file(task, state.config)

    # @step 记录每个账号的执行结果。
    Log.Info("[结果汇总] 开始，任务状态={}".format(task.status))
    for account in task.accounts:
        _log_account(account)

    # @step 写入本次执行结果汇总。
    workflow_error = state.run.error_message
    _write_summary(task, workflow_error)

    # @step 校验并保存更新后的标准任务。
    state.task = contract.parse_standard_task(task)
    Log.Info("[结果汇总] 完成")
    return argument
