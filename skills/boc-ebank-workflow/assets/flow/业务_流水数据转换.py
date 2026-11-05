import os, json, copy, decimal, random
import re
from typing import Any

from apa_runtime import *
from openpyxl import load_workbook
import 公共_数据契约 as contract


def _value_or_empty(data: dict[str, Any], key: str) -> Any:
    """安全取字典值，不存在返回空字符串。

    Args:
        data: 一行流水或字段映射字典。
        key: 要读取的字段名。

    Returns:
        str: 对应的值或空字符串。
    """
    value = data.get(key)
    return "" if value is None else value


def _format_trade_date(date_time: str) -> str:
    """交易时间转换为 yyyy-mm-dd 格式。

    支持两种输入：完整时间字符串（yyyy-mm-dd hh:mm:ss）和中行流水的
    8位紧凑日期（yyyymmdd）；Time.CDate不识别紧凑格式，需手工解析。

    Args:
        date_time: 交易时间或日期字符串。

    Returns:
        str: 格式化后的日期。
    """
    if date_time == "":
        return ""
    text = str(date_time).strip()
    if len(text) == 8 and text.isdigit():
        return "{}-{}-{}".format(text[0:4], text[4:6], text[6:8])
    d = Time.CDate(text, "yyyy-mm-dd hh:mm:ss")
    return Time.Format(d, "yyyy-mm-dd")


def _build_transaction_number(
    bank_account: str,
    date_time: str,
    income: str,
    expense: str,
    balance: str,
) -> str:
    """生成银行流水号。

    按“银行卡号 + 时间 + 收入 + 支出 + 余额”拼接生成流水号。

    Args:
        bank_account: 银行账号。
        date_time: 交易时间。
        income: 收入金额。
        expense: 支出金额。
        balance: 账户余额。

    Returns:
        str: 拼接生成的流水号。
    """
    bank_account = ''.join(re.findall(r'\d', str(bank_account)))
    date_time = ''.join(re.findall(r'\d', str(date_time)))
    income = ''.join(re.findall(r'\d', str(income)))
    expense = ''.join(re.findall(r'\d', str(expense)))
    balance = ''.join(re.findall(r'\d', str(balance)))

    return bank_account + date_time + income + expense + balance


def _copy_transaction_template(
    source_file: str,
    template_file: str,
    output_folder: str,
) -> str:
    """复制转换模板，并按原始流水文件名生成输出文件。

    Args:
        source_file: 银行下载的原始流水文件路径。
        template_file: 流水数据转换模板路径。
        output_folder: 转换后文件的保存目录。

    Returns:
        str: 已生成的转换结果文件路径。
    """
    template_name = File.BaseName(template_file, False)
    template_extension = File.ExtensionName(template_file)
    source_name = File.BaseName(source_file, False)
    output_file = output_folder + "\\" + source_name + template_extension

    File.CopyFile(template_file, output_folder, True)
    if File.FileExists(output_file):
        File.DeleteFile(output_file)
    File.RenameEx(
        output_folder + "\\" + template_name + template_extension,
        source_name + template_extension,
    )
    return output_file


def _read_field_mapping(field_map_file: str, bank_name: str) -> dict[str, str]:
    """读取当前银行字段与目标字段的对应关系。

    Args:
        field_map_file: 银行字段到目标字段的映射文件路径。
        bank_name: 映射文件中当前银行对应的工作表名称。

    Returns:
        dict[str, str]: 以目标字段名为键、银行字段名为值的映射。

    Raises:
        RuntimeError: 映射文件中不存在当前银行的工作表。
        Exception: 打开或读取映射文件失败。
    """
    workbook = load_workbook(field_map_file, read_only=True, data_only=True)
    try:
        if bank_name not in workbook.sheetnames:
            raise RuntimeError(
                "字段映射文件中不存在[{}]工作表。".format(bank_name)
            )

        worksheet = workbook[bank_name]
        field_mapping: dict[str, str] = {}
        for raw_target_field, raw_bank_field in worksheet.iter_rows(
            min_row=2,
            max_col=2,
            values_only=True,
        ):
            target_field = (
                "" if raw_target_field is None else str(raw_target_field).strip()
            )
            if target_field == "":
                continue
            bank_field = "" if raw_bank_field is None else str(raw_bank_field).strip()
            field_mapping[target_field] = bank_field
        return field_mapping
    finally:
        workbook.close()


def _read_source_transactions(
    source_file: str,
    header_row: int,
) -> tuple[str, list[dict[str, Any]]]:
    """读取银行流水中的币种和交易明细。

    使用 xlrd 纯Python解析源文件，不依赖本机安装Office或WPS。
    兼容两种文件结构：农行（标题行固定、靠"总收入笔数"汇总行定位末行、
    C2冒号拆分取币种）和中行（标题行含"交易类型"特征、数据区直到文件
    末尾、币种在"交易货币"列）。

    Args:
        source_file: 银行下载的原始流水文件路径。
        header_row: 流水文件标题所在行号；中行文件自动探测，该参数被忽略。

    Returns:
        tuple[str, list[dict[str, Any]]]: 币种，以及按标题组织的流水行列表。
    """
    import xlrd

    source_workbook = xlrd.open_workbook(source_file)
    sheet = source_workbook.sheet_by_index(0)

    # 自动探测标题行：第1列文本以"交易类型"开头即为中行布局；
    # 未探测到时退回调用方传入的农行标题行号。
    detected_header_row = header_row
    for row_index in range(sheet.nrows):
        first_cell = str(sheet.cell_value(row_index, 0))
        if first_cell.startswith("交易类型"):
            detected_header_row = row_index + 1
            break

    source_titles = [
        str(sheet.cell_value(detected_header_row - 1, column_index))
        for column_index in range(sheet.ncols)
    ]

    # 定位数据末行：优先按原逻辑找"总收入笔数"汇总行（农行）；
    # 中行文件没有该汇总行，数据区直接延伸到文件末尾。
    last_data_row = 0
    for row_index in range(sheet.nrows):
        for column_index in range(sheet.ncols):
            if "总收入笔数" in str(sheet.cell_value(row_index, column_index)):
                last_data_row = row_index + 1 - 1
                break
        if last_data_row > 0:
            break
    if last_data_row <= 0:
        last_data_row = sheet.nrows

    # 币种：优先农行C2冒号拆分；中行从数据行"交易货币"列取第一行值。
    currency = ""
    if sheet.nrows >= 2 and sheet.ncols >= 3:
        currency_parts = str(sheet.cell_value(1, 2)).split(":")
        if len(currency_parts) > 1:
            currency = currency_parts[1]
    if currency == "":
        for column_index in range(sheet.ncols):
            if "交易货币" in source_titles[column_index]:
                currency = str(sheet.cell_value(detected_header_row, column_index)).strip()
                break

    transactions: list[dict[str, Any]] = []
    for row_index in range(detected_header_row, last_data_row):
        transaction: dict[str, Any] = {}
        for column_index in range(0, len(source_titles)):
            transaction[source_titles[column_index]] = (
                sheet.cell_value(row_index, column_index)
                if column_index < sheet.ncols
                else ""
            )
        transactions.append(transaction)
    return currency, transactions


def _convert_transaction_rows(
    bank_account: str,
    currency: str,
    transactions: list[dict[str, Any]],
    output_columns: list[Any],
    field_mapping: dict[str, str],
) -> list[list[Any]]:
    """把银行流水行转换为目标模板要求的列顺序和字段值。

    Args:
        bank_account: 仅保留数字后的银行账号。
        currency: 从银行流水文件读取的币种。
        transactions: 按银行流水标题组织的交易行。
        output_columns: 目标模板的输出列顺序。
        field_mapping: 目标字段到银行字段的对应关系。

    Returns:
        list[list[Any]]: 可以直接写入目标模板的二维数据。
    """
    converted_rows: list[list[Any]] = []
    for transaction in transactions:
        # 中行文件按交易类型切换对方列：来账对方是付款人，往账对方是收款人。
        boc_transaction_type = _value_or_empty(transaction, "交易类型[ Transaction Type ]")
        is_boc_incoming = boc_transaction_type == "来账"
        is_boc_layout = boc_transaction_type in ("来账", "往账")
        converted_row: list[Any] = []
        for output_column in output_columns:
            source_field = _value_or_empty(field_mapping, output_column)
            if source_field != "":
                converted_row.append(_value_or_empty(transaction, source_field))
            elif output_column == "银行流水号":
                if is_boc_layout:
                    converted_row.append(
                        _build_transaction_number(
                            bank_account,
                            "{} {}".format(
                                _value_or_empty(transaction, "交易日期[ Transaction Date ]"),
                                _value_or_empty(transaction, "交易时间[ Transaction time ]"),
                            ),
                            _value_or_empty(transaction, "交易金额[ Trade Amount ]"),
                            "",
                            _value_or_empty(transaction, "交易后余额[ After-transaction balance ]"),
                        )
                    )
                else:
                    converted_row.append(
                        _build_transaction_number(
                            bank_account,
                            _value_or_empty(transaction, "交易时间"),
                            _value_or_empty(transaction, "收入金额"),
                            _value_or_empty(transaction, "支出金额"),
                            _value_or_empty(transaction, "账户余额"),
                        )
                    )
            elif output_column == "银行账户":
                converted_row.append(bank_account)
            elif output_column == "币种":
                converted_row.append(currency)
            elif output_column == "摘要":
                if is_boc_layout:
                    # 中行：摘要为空时用业务类型（如"结息"）兜底。
                    transaction_reference = _value_or_empty(transaction, "摘要[ Reference ]")
                    if transaction_reference != "":
                        converted_row.append(transaction_reference)
                    else:
                        converted_row.append(_value_or_empty(transaction, "业务类型[ Business type ]"))
                else:
                    transaction_purpose = _value_or_empty(transaction, "交易用途")
                    if transaction_purpose != "" and len(transaction_purpose) > 1:
                        converted_row.append(transaction_purpose)
                    else:
                        converted_row.append(_value_or_empty(transaction, "摘要"))
            elif output_column == "结算金额":
                if is_boc_layout:
                    # 中行：金额单列带正负号，保留原样（收入正、支出负）。
                    converted_row.append(_value_or_empty(transaction, "交易金额[ Trade Amount ]"))
                else:
                    income_amount = _value_or_empty(transaction, "收入金额")
                    if income_amount != "":
                        converted_row.append(income_amount)
                    else:
                        converted_row.append(_value_or_empty(transaction, "支出金额"))
            elif output_column == "收付属性":
                if is_boc_layout:
                    # 中行：来账=收款，往账=付款。
                    converted_row.append("收款" if is_boc_incoming else "付款")
                else:
                    income_amount = _value_or_empty(transaction, "收入金额")
                    expense_amount = _value_or_empty(transaction, "支出金额")
                    if len(Regex.Find(income_amount, "\\d+(\\.\\d+)?")) > 0:
                        converted_row.append("收款")
                    elif len(Regex.Find(expense_amount, "\\d+(\\.\\d+)?")) > 0:
                        converted_row.append("付款")
                    else:
                        converted_row.append("")
            elif output_column == "交易日期":
                if is_boc_layout:
                    converted_row.append(
                        _format_trade_date(_value_or_empty(transaction, "交易日期[ Transaction Date ]"))
                    )
                else:
                    converted_row.append(
                        _format_trade_date(_value_or_empty(transaction, "交易时间"))
                    )
            elif output_column == "对方账号":
                if is_boc_layout:
                    converted_row.append(
                        _value_or_empty(transaction, "付款人账号[ Debit Account No. ]")
                        if is_boc_incoming
                        else _value_or_empty(transaction, "收款人账号[ Payee's Account Number ]")
                    )
                else:
                    converted_row.append("")
            elif output_column == "对方户名":
                if is_boc_layout:
                    converted_row.append(
                        _value_or_empty(transaction, "付款人名称[ Payer's Name ]")
                        if is_boc_incoming
                        else _value_or_empty(transaction, "收款人名称[ Payee's Name ]")
                    )
                else:
                    converted_row.append("")
            elif output_column == "对方开户行名":
                if is_boc_layout:
                    converted_row.append(
                        _value_or_empty(transaction, "付款人开户行名[ Payer account bank ]")
                        if is_boc_incoming
                        else _value_or_empty(transaction, "收款人开户行名[ Beneficiary account bank ]")
                    )
                else:
                    converted_row.append("")
            elif output_column == "对方开户行行号":
                if is_boc_layout:
                    converted_row.append(
                        _value_or_empty(transaction, "付款人开户行号[ Account holding bank number of payer ]")
                        if is_boc_incoming
                        else _value_or_empty(transaction, "收款人开户行行号[ Account holding bank number of beneficiary ]")
                    )
                else:
                    converted_row.append("")
            else:
                converted_row.append("")
        converted_rows.append(converted_row)
    return converted_rows


def convert_transaction_file(
    bank_account: str,
    source_file: str,
    header_row: int,
    template_file: str,
    field_map_file: str,
    bank_name: str,
    output_folder: str,
) -> contract.TransactionConvertResultModel:
    """将银行流水文件转换为指定模板格式。

    Args:
        bank_account: 子账号。
        source_file: 银行流水文件路径。
        header_row: 流水文件标题所在行号。
        template_file: 流水数据转换模板路径。
        field_map_file: 银行字段到目标字段的映射文件路径。
        bank_name: 当前处理的银行名称。
        output_folder: 转换后文件的保存目录。

    Returns:
        contract.TransactionConvertResultModel: 转换结果，code 0 成功。
    """
    normalized_account = "".join(re.findall(r"\d", str(bank_account)))
    # 纯Python读写（xlrd/openpyxl）不再拉起Office/WPS进程，无需预清理。

    # @step 复制转换模板，并按银行流水文件名生成输出文件。
    output_file = _copy_transaction_template(source_file, template_file, output_folder)

    # @step 读取目标模板规定的输出列顺序。
    import openpyxl

    output_workbook = openpyxl.load_workbook(output_file, keep_vba=True)
    output_worksheet = output_workbook["银行交易明细"]
    output_columns = [
        output_worksheet.cell(1, column_index).value
        for column_index in range(1, output_worksheet.max_column + 1)
    ]

    # @step 读取当前银行字段与目标字段的对应关系。
    field_mapping = _read_field_mapping(field_map_file, bank_name)

    # @step 读取银行下载的流水明细和币种。
    currency, transactions = _read_source_transactions(source_file, header_row)

    # @step 按目标模板转换每一行流水。
    converted_rows = _convert_transaction_rows(
        normalized_account,
        currency,
        transactions,
        output_columns,
        field_mapping,
    )

    # @step 将转换后的流水写入结果文件。
    for row_index, converted_row in enumerate(converted_rows, start=2):
        for column_index, cell_value in enumerate(converted_row, start=1):
            output_worksheet.cell(row_index, column_index, cell_value)
    output_workbook.save(output_file)

    return contract.TransactionConvertResultModel(
        code=0,
        message="转换成功",
        file_path=output_file,
        record_count=len(converted_rows),
    )


def _transaction_output(
    account: contract.StandardAccountModel,
) -> contract.BusinessOutputModel | None:
    """取得流水业务返回的第一个流水文件；账号未启用流水时返回空。"""

    transaction = account.get_business(1)
    if transaction is None or transaction.status != "success" or transaction.result is None:
        return None
    output = transaction.result.first_output("流水")
    if output is None or output.output_type != "file":
        return None
    return output


def _record_convert(
    account: contract.StandardAccountModel,
    status: str,
    message: str,
) -> None:
    """更新账号的流水数据转换状态和执行记录。"""

    convert = account.delivery.transaction_convert
    convert.status = status
    convert.error_message = "" if status == "success" else message
    account.execution_log.append(contract.ExecutionLogEntryModel(
        stage="convert_transaction",
        status=status,
        timestamp=Time.Format(Time.Now(), "yyyy-mm-dd hh:mm:ss"),
        detail=message,
    ))


def _convert_account(
    account: contract.StandardAccountModel,
    transaction_file_path: str,
    templates: contract.ConvertTemplateFilesModel,
    bank_name: str,
    output_folder: str,
) -> bool:
    """把一个账号的银行流水转换为目标模板格式。"""

    convert = account.delivery.transaction_convert
    try:
        result = contract.TransactionConvertResultModel.model_validate(
            convert_transaction_file(
                account.info.bank_account,
                transaction_file_path,
                3,
                templates.transaction,
                templates.field_map,
                bank_name,
                output_folder,
            )
        )
        if result.code != 0:
            raise RuntimeError(result.message)

        convert.converted_file_path = result.file_path
        convert.record_count = result.record_count
        _record_convert(account, "success", "流水数据转换成功")
        return True
    # apa-lint: disable-next-line preserve-exception-traceback -- 单个账号转换失败写入标准交付结果，由调度层继续处理其他账号。
    except Exception as error:
        convert.converted_file_path = ""
        convert.record_count = 0
        _record_convert(account, "failed", "流水数据转换失败：{}".format(error))
        return False


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """把流水文件转换为指定模板格式，结果写回标准账号。

    任务未启用流水模板转换时不执行；业务阶段已有错误时也不进入转换。整轮重试时只处理
    上一轮流水数据转换失败的账号。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 尚未完成标准任务初始化。
    """

    # @step 检查流水数据转换所需的任务、配置和业务结果。
    state = GlobalVariables["ebank"]
    if state.task is None or state.config is None:
        raise RuntimeError("流水数据转换前必须先完成标准任务初始化。")
    if state.run.has_error:
        Log.Info("[流水数据转换] 业务阶段仍有错误，跳过本轮转换")
        return argument

    task = state.task
    config = state.config
    if not task.enable_convert_template:
        Log.Info("[流水数据转换] 当前任务未启用流水模板转换")
        return argument

    # @step 读取并校验流水数据转换配置。
    convert_templates = contract.require_config_section(
        config.convert_templates,
        "流水数据转换",
    )
    if not convert_templates.enabled:
        Log.Info("[流水数据转换] 当前运行配置已停用流水数据转换")
        return argument

    # @step 筛选本轮需要转换流水的账号。
    accounts = [
        account
        for account in task.accounts
        if _transaction_output(account) is not None
        and (
            state.run.retry_count == 0
            or account.delivery.transaction_convert.status in ("pending", "failed")
        )
    ]
    if not accounts:
        Log.Info("[流水数据转换] 没有需要转换的流水文件")
        return argument

    # @step 准备转换结果文件输出目录。
    output_folder = task.output.business_folder + "\\转换格式后的流水"
    if not File.FolderExists(output_folder):
        File.CreateFolder(output_folder)

    # @step 转换每个账号的流水文件。
    has_error = False
    for account in accounts:
        transaction_output = _transaction_output(account)
        if transaction_output is None:
            continue
        if not _convert_account(
            account,
            transaction_output.path,
            convert_templates,
            state.bank_name,
            output_folder,
        ):
            has_error = True

    # @step 汇总转换结果并保存标准任务。
    state.run.has_delivery_error = has_error
    if has_error:
        state.run.error_message = "；".join(
            "{}的流水数据转换失败：{}".format(
                account.info.bank_account,
                account.delivery.transaction_convert.error_message or "未取得具体原因",
            )
            for account in accounts
            if account.delivery.transaction_convert.status == "failed"
        )
    elif not state.run.has_error:
        state.run.error_message = ""
    state.task = contract.parse_standard_task(task)
    Log.Info("[流水数据转换] 完成，存在转换失败={}".format(has_error))
    return argument
