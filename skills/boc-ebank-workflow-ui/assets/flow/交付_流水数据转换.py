import re
from typing import Any

from apa_runtime import *
from openpyxl import load_workbook
import 公共_数据契约 as contract


TRANSACTION_TEMPLATE = RES("config/模板/交易明细批量模板.xlsm")
FIELD_MAPPING = RES("config/映射/字段映射.xlsx")


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


def _normalize_cell_text(value: Any) -> str:
    """把Excel单元格值统一转换为下游可用的字符串。

    金额等数值单元格在 xlrd/openpyxl 中返回 float，整数浮点去掉小数点，
    保持与原COM读取行为一致。

    Args:
        value: 单元格原始值，可能为 None、str、int、float。

    Returns:
        str: 统一后的文本值。
    """
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _read_source_transactions(
    source_file: str,
    header_row: int,
) -> tuple[str, list[dict[str, Any]]]:
    """读取银行流水中的币种和交易明细。

    按文件扩展名自动选择解析方式：``.xls`` 使用 xlrd，``.xlsx`` 使用
    openpyxl（read_only 模式流式读取，大文件内存占用低）；两者都不依赖
    Office/WPS COM 组件。

    Args:
        source_file: 银行下载的原始流水文件路径（.xls 或 .xlsx）。
        header_row: 流水文件标题所在行号（1基）。

    Returns:
        tuple[str, list[dict[str, Any]]]: 币种，以及按标题组织的流水行列表。

    Raises:
        RuntimeError: 流水文件没有工作表、未找到汇总行或格式不支持。
    """
    extension = (File.ExtensionName(source_file) or "").lower()

    source_titles: list[str] = []
    source_rows: list[list[str]] = []
    currency = ""

    if extension == ".xls":
        import xlrd

        workbook = xlrd.open_workbook(source_file)
        if not workbook.sheets():
            raise RuntimeError("流水文件中没有工作表。")
        worksheet = workbook.sheet_by_index(0)

        # 自动探测标题行：第1列文本以“交易类型”开头即为中行布局；
        # 未探测到时使用调用方传入的标题行号（农行等）。
        detected_header_row = header_row
        for row_index in range(worksheet.nrows):
            if str(worksheet.cell_value(row_index, 0)).startswith("交易类型"):
                detected_header_row = row_index + 1
                break

        if worksheet.ncols >= 3:
            currency_parts = str(worksheet.cell_value(1, 2)).split(":")
            if len(currency_parts) > 1:
                currency = currency_parts[1]

        source_titles = [
            _normalize_cell_text(worksheet.cell_value(detected_header_row - 1, column_index))
            for column_index in range(worksheet.ncols)
        ]

        # 中行流水无“总收入笔数”汇总行：数据从标题行之后直到工作表末尾。
        # 兼容两种格式：有汇总行（农行等）止于汇总行，否则读到末行。
        summary_row_index = worksheet.nrows
        for row_index in range(worksheet.nrows):
            if "总收入笔数" in str(worksheet.cell_value(row_index, 0)):
                summary_row_index = row_index
                break

        # 汇总行之前的一行即最后一条数据行（xlrd 0 基行号）。
        for row_index in range(detected_header_row, summary_row_index):
            source_rows.append([
                _normalize_cell_text(worksheet.cell_value(row_index, column_index))
                for column_index in range(worksheet.ncols)
            ])

        # 中行币种在“交易货币”列；C2冒号拆分取不到时从数据行补取。
        if currency == "":
            for column_index in range(worksheet.ncols):
                if "交易货币" in source_titles[column_index]:
                    currency = str(worksheet.cell_value(detected_header_row, column_index)).strip()
                    break
    elif extension == ".xlsx":
        # read_only 模式按行流式读取，大流水文件不会一次性展开全部单元格。
        workbook = load_workbook(source_file, read_only=True, data_only=True)
        try:
            if not workbook.sheetnames:
                raise RuntimeError("流水文件中没有工作表。")
            worksheet = workbook[workbook.sheetnames[0]]

            summary_row_index = -1
            header_row_index_0 = header_row - 1
            for row_index, row_values in enumerate(worksheet.iter_rows(values_only=True)):
                first_cell_text = _normalize_cell_text(row_values[0] if len(row_values) > 0 else None)
                if row_index == 1 and len(row_values) >= 3:
                    currency_parts = str(row_values[2]).split(":")
                    if len(currency_parts) > 1:
                        currency = currency_parts[1]
                if row_index == header_row_index_0:
                    source_titles = [_normalize_cell_text(value) for value in row_values]
                if "总收入笔数" in first_cell_text:
                    summary_row_index = row_index
                    break
            if summary_row_index < 0:
                raise RuntimeError("流水文件中未找到“总收入笔数”汇总行。")
            if not source_titles:
                raise RuntimeError("流水文件标题行不存在或为空。")

            # 重新流式读取数据行：标题行之后到汇总行之前（行号均为0基）。
            for row_index, row_values in enumerate(worksheet.iter_rows(values_only=True)):
                if header_row_index_0 < row_index < summary_row_index:
                    source_rows.append([
                        _normalize_cell_text(row_values[column_index])
                        for column_index in range(len(source_titles))
                    ])
        finally:
            workbook.close()
    else:
        raise RuntimeError(
            "流水文件格式不支持（{}），仅支持 .xls 和 .xlsx。".format(extension)
        )

    transactions: list[dict[str, Any]] = []
    for source_row in source_rows:
        transaction: dict[str, Any] = {}
        for column_index in range(0, len(source_titles)):
            transaction[source_titles[column_index]] = source_row[column_index]
        transactions.append(transaction)
    return currency, transactions


def _rewrite_output_rows(
    worksheet: Any,
    converted_rows: list[list[Any]],
) -> None:
    """把转换后的流水整行写入目标工作表，并清除模板残留数据行。

    使用 openpyxl 的 ``append`` 逐行整批写入，相比逐单元格赋值减少了
    每个单元格的坐标解析和样式查找开销，大数据量流水转换时速度更快。
    写入前先删除模板中第2行起的全部残留行，保证输出只包含本次数据。

    Args:
        worksheet: 目标工作簿中的“银行交易明细”工作表。
        converted_rows: 转换后的二维流水数据。
    """
    if worksheet.max_row > 1:
        worksheet.delete_rows(2, worksheet.max_row - 1)
    for converted_row in converted_rows:
        worksheet.append(converted_row)


def _convert_transaction_rows(
    bank_account: str,
    currency: str,
    transactions: list[dict[str, Any]],
    output_columns: list[Any],
    field_mapping: dict[str, str],
) -> list[list[Any]]:
    """把银行流水行转换为目标模板要求的列顺序和字段值。

    兼容两种流水布局：农行（收入/支出双金额列、交易时间含日期）和中行
    （交易类型来账/往账、单交易金额列带正负号、8位紧凑交易日期、
    对方信息按来账取付款人/往账取收款人切换、摘要空时用业务类型兜底）。

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
        # 中行布局特征：交易类型列为来账/往账；农行布局该列不存在。
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
                    # 中行：摘要为空时用业务类型（如结息）兜底。
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
            elif output_column == "交易时间":
                if is_boc_layout:
                    converted_row.append(
                        _value_or_empty(transaction, "交易时间[ Transaction time ]")
                    )
                else:
                    converted_row.append(
                        _value_or_empty(transaction, "交易时间")
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
    App.Kill("excel.exe")
    App.Kill("wps.exe")

    # @step 复制转换模板，并按银行流水文件名生成输出文件。
    output_file = _copy_transaction_template(source_file, template_file, output_folder)

    # @step 读取目标模板规定的输出列顺序（openpyxl 读取，不依赖 COM）。
    output_workbook = load_workbook(output_file, keep_vba=True)
    output_columns = [
        "" if cell.value is None else cell.value
        for cell in output_workbook["银行交易明细"][1]
    ]
    output_workbook.close()

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

    # @step 将转换后的流水写入结果文件（openpyxl 批量写入，keep_vba 保留模板宏）。
    # 逐行 append 整行数据，避免逐单元格写大开销；模板残留的示例数据行一并清除。
    output_workbook = load_workbook(output_file, keep_vba=True)
    worksheet = output_workbook["银行交易明细"]
    _rewrite_output_rows(worksheet, converted_rows)
    output_workbook.save(output_file)
    output_workbook.close()

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
    template_file: str,
    field_map_file: str,
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
                template_file,
                field_map_file,
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

    任务未启用流水模板转换时不执行；转换按账号执行，业务失败的账号没有流水产物会被自然过滤，其他成功账号照常转换。整轮重试时只处理
    上一轮流水数据转换失败的账号。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 尚未完成标准任务初始化；或块内重试一次后流水数据
            转换仍失败，沿异常连线交给框架异常结束处理。
    """

    # @step 检查流水数据转换所需的任务、配置和业务结果。
    state = GlobalVariables["ebank"]
    if state.task is None or state.config is None:
        raise RuntimeError("流水数据转换前必须先完成标准任务初始化。")

    task = state.task
    config = state.config
    if not task.enable_convert_template:
        Log.Info("[流水数据转换] 当前任务未启用流水模板转换")
        return argument

    # @step 读取并校验流水数据转换配置。
    convert_templates = config.convert_templates
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

    # @step 独立解析模板和映射覆盖值，省略时回退到项目内置资源。
    template_file = convert_templates.transaction or TRANSACTION_TEMPLATE
    field_map_file = convert_templates.field_map or FIELD_MAPPING
    for label, file_path in (("流水转换模板", template_file), ("字段映射", field_map_file)):
        if not File.FileExists(file_path):
            raise RuntimeError("{}不存在：{}".format(label, file_path))

    # @step 准备转换结果文件输出目录。
    output_folder = task.output.business_folder + "\\转换格式后的流水"
    if not File.FolderExists(output_folder):
        File.CreateFolder(output_folder)

    # @step 转换每个账号的流水文件；失败时在块内固定重试一次。
    has_error = False
    for account in accounts:
        transaction_output = _transaction_output(account)
        if transaction_output is None:
            continue
        if _convert_account(
            account,
            transaction_output.path,
            template_file,
            field_map_file,
            state.bank_name,
            output_folder,
        ):
            continue
        Log.Warn(
            "[流水数据转换] {}首次转换失败，块内固定重试一次：{}".format(
                account.info.bank_account,
                account.delivery.transaction_convert.error_message or "未取得具体原因",
            )
        )
        if not _convert_account(
            account,
            transaction_output.path,
            template_file,
            field_map_file,
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

    # @step 重试后仍失败时抛出异常，沿异常连线交给框架异常结束处理。
    # 转换是纯本地文件处理，重登网银对结果毫无帮助；主流程"重试？"判断
    # 读取has_delivery_error后走否分支，直接进入异常结束，不再整轮重跑。
    if has_error:
        raise RuntimeError(state.run.error_message)
    return argument
