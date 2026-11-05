import calendar
import json
from datetime import date
from typing import Any
from apa_runtime import *
import 公共_数据契约 as contract
import 公共_网银能力 as ebank
import 公共_网银页面操作 as pageop


def __UNIT_TEST_FUNCTION__(argument):
    """为单独运行当前流水查询和下载流程块准备测试上下文。

    单独运行本流程块时，用这里的示例数据构造统一业务上下文，
    再走真实 main 入口。补充真实数据时只改本函数内的取值，
    不要修改 main 和业务函数。
    """
    # 真实测试数据（来源：任务数据 + Asset 配置 User 段输出目录）。
    test_argument = {
        "business_type": 1,                                    # BusinessType: [1]
        "business_name": "流水查询和下载",
        "account": {
            "account_id": 12,                                  # 上游任务 id
            "bank_account": "595080967721",
            "account_name": "来也科技项目经理部",
            "open_bank_name": "中国银行",
            "open_unit": "来也科技",
            "keeper": "邓",
        },
        "query_dates": {
            "start_date": "2026.06.20",                        # 有数据测试（近半年内实际交易：06/20 结息、06/26 转账支出）
            "end_date": "2026.06.26",
        },
        "ukey_number": "535309484561",                         # ukey_no
        "output_folder": "D:\\网银场景架构设计\\output\\中国银行",  # OutputFolder
    }
    return main(test_argument)
def _validate_date_range_months(
    start_date: str,
    end_date: str,
    max_months: int,
    business_label: str,
) -> str | None:
    """校验查询日期先后关系和允许的最大日历月跨度。"""

    start_value = date.fromisoformat(str(start_date).replace(".", "-"))
    end_value = date.fromisoformat(str(end_date).replace(".", "-"))
    if end_value < start_value:
        return "日期范围不对，起始日期不能晚于结束日期"

    total_months = start_value.year * 12 + start_value.month - 1 + max_months
    limit_year, limit_month_index = divmod(total_months, 12)
    limit_day = min(
        start_value.day,
        calendar.monthrange(limit_year, limit_month_index + 1)[1],
    )
    limit_date = date(limit_year, limit_month_index + 1, limit_day)
    if end_value > limit_date:
        return "日期范围不对，{}查询日期范围不能超过{}个月".format(
            business_label,
            max_months,
        )
    return None


def _count_result_rows() -> int:
    """统计当前页面流水结果的数据条数，并排除固定列造成的重复行。"""

    row_texts: set[str] = set()
    for row_selector in IterateUiElements(
        Hover_ElementSelect("流水查询_结果数据行_通配")
    ):
        row_text = str(
            UiElement.GetValue(
                row_selector,
                {
                    "bContinueOnError": True,
                    "iDelayAfter": 100,
                    "iDelayBefore": 100,
                },
            )
        ).strip()
        if row_text:
            row_texts.add(row_text)
    return len(row_texts)


# 这组规则属于中行流水业务。客户要求改变目录、文件名或校验位置时，
# Agent只修改本文件，不需要修改框架_业务调度.py。
FOLDER_NAME = "原始流水"
FILE_LABEL = "流水"


def _build_output_location(
    business_argument: contract.BusinessArgumentModel,
) -> tuple[str, str]:
    """根据流水业务规则生成保存目录和文件名。"""

    month_text = Time.Format(
        Time.CDate(business_argument.query_dates.start_date, "yyyy.mm.dd"),
        "yyyymm",
    )
    file_name = "{}-{}-{}-{}-{}".format(
        business_argument.ukey_number,
        business_argument.account.account_name,
        business_argument.account.bank_account[-4:],
        month_text,
        FILE_LABEL,
    )
    output_folder = business_argument.output_folder + "\\" + FOLDER_NAME

    if not File.FolderExists(output_folder):
        File.CreateFolder(output_folder)
    return output_folder, file_name


def _select_transaction_account(account_number: str) -> bool:
    """在交易/回单页面顶部平铺账号中选择目标账号。

    中行账户不是下拉框，而是平铺在页面顶部的账号文本。当前界面库
    登记的是单一账号元素；出现多个账号时需要补充账号通配元素。

    Args:
        account_number: 已去掉分隔符的银行账号。

    Returns:
        bool: 六次尝试内选中目标账号返回 ``True``，否则返回 ``False``。
    """


    for _attempt in range(6):
        # @step 读取当前顶部账号文本并与目标账号比对。
        current_account_text = UiElement.GetValue(Hover_ElementSelect("网银_顶部账号文本"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
        Log.Info("当前顶部账号：{}，目标账号：{}".format(str(current_account_text), str(account_number)))
        if account_number in str(current_account_text):
            # @step 点击目标账号完成选择。
            Mouse.Action(Hover_ElementSelect("网银_顶部账号选中容器"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
            Log.Info("当前账户匹配")
            return True
        Log.Info("当前账户不匹配，重新读取顶部账号")
        Delay(1000)
    # TODO(中行页面操作): 页面顶部存在多个账号时，需要补充账号_通配元素后
    #   遍历匹配目标账号再点击，逻辑与农行账户_列表项_通配一致。
    return False


def _validate_downloaded_transaction(file_path: str, account_number: str) -> None:
    """确认流水文件可打开，且文件中的账号就是本次查询账号。

    使用 xlrd 纯Python解析，不依赖本机安装Office或WPS。
    """

    import xlrd

    workbook = xlrd.open_workbook(file_path)
    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 2:
        raise RuntimeError("流水文件中没有可校验的数据行。")
    value = str(sheet.cell_value(1, 0))
    # 中行流水 A2 为“查询账号[...]:595080967721”或直接是账号本身；
    # 农行格式为“账号:xxx”。兼容两种格式提取账号。
    text = StringLib.Replace(value, "：", ":", False)
    parts = text.split(":", 1)
    file_account = parts[1].strip() if len(parts) == 2 else ""
    if not file_account:
        # A2 无冒号前缀时，B2 承载账号（中行：A1 标签 + B1 值布局）。
        file_account = str(sheet.cell_value(1, 1)).strip()
    expected = StringLib.Replace(account_number, "-", "", False)
    actual = StringLib.Replace(file_account, "-", "", False)
    if actual != expected:
        raise RuntimeError("流水文件账号与当前子账号不一致。")


def query_and_download_transactions(
    start_date: str,
    end_date: str,
    account_number: str,
    output_folder: str,
    file_name: str,
) -> contract.BusinessResultModel:
    """查询流水并下载流水。

    Args:
        start_date: 查询起始日期。
        end_date: 查询结束日期。
        account_number: 查询的子账号。
        output_folder: 下载文件保存路径。
        file_name: 下载文件命名。

    Returns:
        contract.BusinessResultModel: 统一业务结果，code 0 成功，1 查询失败，2 查询结果为空。
    """
    result = contract.BusinessResultModel(code=-1, message="")

    query_result = query_transactions(start_date, end_date, account_number)
    Log.Info("查询流水结果：\r\n{}".format(str(query_result)))

    # @step 检查流水查询是否成功。
    if query_result.code == -1 or query_result.code == 1:
        result.code = 1
        result.message = query_result.message
        return result
    # @step 判断流水查询结果是否为空。
    if query_result.code == 2:
        result.code = 2
        result.message = query_result.message
        return result

    # @step 下载查询到的流水文件。
    download_result = download_transactions(output_folder, file_name)
    download_result.record_count = query_result.record_count
    Log.Info("下载流水结果：\r\n{}".format(str(download_result)))
    # @step 检查流水文件是否下载成功。
    if download_result.code == -1 or download_result.code == 1:
        result.code = 1
        result.message = download_result.message
        return result

    # @step 判断是否存在可以下载的流水数据。
    if download_result.code == 2:
        result.code = 2
        result.message = download_result.message
        return result

    # @step 返回流水下载结果。
    if download_result.code == 0:
        result.outputs = [contract.BusinessOutputModel(
            output_type="file",
            category="流水",
            path=download_result.file_path,
            name=file_name,
        )]
        result.values = [contract.BusinessValueModel(
            name="总笔数",
            value=str(query_result.record_count),
            unit="笔",
        )]
        result.code = 0
        result.message = download_result.message
        return result

    return result


def query_transactions(
    start_date: str,
    end_date: str,
    account_number: str,
) -> contract.OperationResultModel:
    """查询流水。

    Args:
        start_date: 查询起始日期。
        end_date: 查询结束日期。
        account_number: 查询的子账号。

    Returns:
        contract.OperationResultModel: 查询结果，code 0 成功，1 失败，2 查询结果为空。
    """
    query_result = contract.OperationResultModel(code=-1)

    # @step 进入流水查询页面：信息服务-中行账户与回单-交易/回单。
    Mouse.Hover(Hover_ElementSelect("段落<p>_信息服务"), 10000, {"bContinueOnError": False, "iDelayAfter": 800, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    ebank.wait_for_element(Hover_ElementSelect("段落<p>_中行账户与回单"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("段落<p>_中行账户与回单"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    ebank.wait_for_element(Hover_ElementSelect("文本<span>_交易/回单"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("文本<span>_交易/回单"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 选择需要查询流水的银行账号。
    account_number = StringLib.Replace(account_number, "-", "", False)
    if not _select_transaction_account(account_number):
        Log.Error("连续6次仍无法选择目标账户。")
        query_result.code = 1
        query_result.message = "无法选择目标账户"
        return query_result

    # @step 校验流水查询日期。
    Log.Info("开始日期：{}".format(start_date))
    is_start_date_valid = Time.IsDate(start_date, "yyyy.mm.dd")
    if not is_start_date_valid:
        Log.Error("起始日期格式不正确。")
        query_result.code = 1
        query_result.message = "查询失败"
        return query_result

    Log.Info("结束日期：{}".format(end_date))
    is_end_date_valid = Time.IsDate(end_date, "yyyy.mm.dd")
    if not is_end_date_valid:
        Log.Error("结束日期格式不正确。")
        query_result.code = 1
        query_result.message = "查询失败"
        return query_result

    # @step 校验流水查询日期范围不超过六个月。
    range_error_message = _validate_date_range_months(
        start_date,
        end_date,
        6,
        "流水",
    )
    if range_error_message is not None:
        Log.Error(range_error_message)
        query_result.code = 1
        query_result.message = range_error_message
        return query_result

    # 日期格式转换：中行页面使用 yyyy/mm/dd，日历面板脚本使用 yyyy-mm-dd。
    start_date = Time.Format(Time.CDate(start_date, "yyyy.mm.dd"), "yyyy/mm/dd")
    end_date = Time.Format(Time.CDate(end_date, "yyyy.mm.dd"), "yyyy/mm/dd")
    panel_start_date = Time.Format(Time.CDate(start_date, "yyyy/mm/dd"), "yyyy-mm-dd")
    panel_end_date = Time.Format(Time.CDate(end_date, "yyyy/mm/dd"), "yyyy-mm-dd")

    # @step 通过日历面板设置流水查询开始和结束日期。
    browser_handle = WebBrowser.BindBrowser("chrome", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    pageop.select_panel_date(browser_handle, panel_start_date, "流水查询_开始日期输入框")
    pageop.select_panel_date(browser_handle, panel_end_date, "流水查询_结束日期输入框")

    # @step 提交流水查询。
    Mouse.Action(Hover_ElementSelect("按钮<button>_查询"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 1500, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 查询后回读日期，确认页面接受的目标日期。
    actual_start_date = UiElement.GetValue(Hover_ElementSelect("流水查询_开始日期输入框"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    actual_end_date = UiElement.GetValue(Hover_ElementSelect("流水查询_结束日期输入框"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    if str(actual_start_date) != start_date or str(actual_end_date) != end_date:
        date_mismatch_message = "查询日期与目标日期不一致，目标开始日期: {}，回读开始日期: {}，目标结束日期: {}，回读结束日期: {}".format(str(start_date), str(actual_start_date), str(end_date), str(actual_end_date))
        Log.Error(date_mismatch_message)
        query_result.code = 1
        query_result.message = "查询日期与目标日期不一致"
        return query_result

    # @step 确认流水查询已经返回结果。
    has_result_row = ebank.wait_for_element(Hover_ElementSelect("流水查询_结果数据行_通配"), 5, 1000)
    if has_result_row:
        Log.Info("查询成功")
        record_count = _count_result_rows()
        Log.Info("流水查询结果条数：{}".format(record_count))
        query_result.code = 0
        query_result.message = "查询成功"
        query_result.record_count = record_count
        return query_result

    # @step 判断流水查询结果是否为空。
    has_no_records = ebank.wait_for_element(Hover_ElementSelect("流水查询_无匹配记录提示"), 5, 1000)
    if has_no_records:
        Log.Info("查询结果为空。")
        query_result.code = 2
        query_result.message = "查询结果为空"
        return query_result

    query_result.code = 1
    query_result.message = "查询后未识别到成功或无数据状态"
    return query_result


def download_transactions(output_folder: str, file_name: str) -> contract.OperationResultModel:
    """下载流水文件。

    Args:
        output_folder: 下载文件保存路径。
        file_name: 下载文件命名。

    Returns:
        contract.OperationResultModel: 下载结果，code 0 成功，1 失败，2 没有待下载的数据。
    """
    download_result = contract.OperationResultModel(code=-1)

    # @step 准备流水下载目录。
    folder_exists = File.FolderExists(output_folder)
    if not folder_exists:
        Log.Info("创建文件夹：{}".format(str(output_folder)))
        File.CreateFolder(output_folder)

    # @step 生成流水下载文件名。
    file_extension = "xls"
    save_path = "{}\\{}.{}".format(output_folder, file_name, file_extension)
    Log.Info("文件保存路径：{}".format(save_path))

    # @step 确认页面存在可下载的流水。
    has_result_row = ebank.wait_for_element(Hover_ElementSelect("流水查询_结果数据行_通配"), 5, 1000)
    if has_result_row:
        Log.Info("流水有待下载的数据")
        # @step 点击下载余额及交易，格式选择EXCEL并确认。
        Mouse.Action(Hover_ElementSelect("按钮<button>_下载余额及交易"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

        # @step 勾选下载内容“全部交易”，否则确定按钮不可点击。
        ebank.wait_for_element(Hover_ElementSelect("对话框_勾选全部交易"), 10, 1000)
        Mouse.Action(Hover_ElementSelect("对话框_勾选全部交易"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

        # @step 在导出格式下拉中选择EXCEL。
        Mouse.Action(Hover_ElementSelect("输入控件<input>_CSV"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        Mouse.Action(Hover_ElementSelect("列表项<li>_EXCEL"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 1000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

        # @step 点击确定提交导出。
        Mouse.Action(Hover_ElementSelect("按钮<button>_确定"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

        # @step 等待浏览器下载完成并保存到目标路径。
        is_downloaded = ebank.save_chrome_download(save_path)
        if is_downloaded:
            download_result.code = 0
            download_result.message = "下载成功"
            download_result.file_path = save_path
        else:
            download_result.code = 1
            download_result.message = "下载失败"
    else:
        download_result.code = 2
        download_result.message = "没有待下载的数据"
        Log.Info("没有待下载的数据")
    return download_result


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """按中行流水规则生成产物、查询下载并校验账号。

    Args:
        argument: 统一业务上下文字典，包含业务编号和名称、当前账号、查询日期、
            U盾编号以及输出根目录。执行完成后写入
            ``business_result``，其中流水文件放在 ``outputs`` 列表中。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        ValueError: 参数不符合统一业务上下文数据契约。
        Exception: 页面操作或文件下载出现未处理异常。
    """
    # @step 校验流水查询参数。
    business_argument = contract.BusinessArgumentModel.model_validate(argument)

    # @step 生成流水输出目录和文件名。
    output_folder, file_name = _build_output_location(business_argument)

    # @step 查询并下载当前账号的流水文件。
    result = query_and_download_transactions(
        business_argument.query_dates.start_date,
        business_argument.query_dates.end_date,
        business_argument.account.bank_account,
        output_folder,
        file_name,
    )
    # @step 校验下载文件中的银行账号。
    if result.code == 0:
        output = result.first_output("流水")
        if output is None:
            raise RuntimeError("流水下载成功但没有返回流水文件。")
        _validate_downloaded_transaction(output.path, business_argument.account.bank_account)
    # @step 写回标准业务结果。
    argument["business_result"] = result.model_dump(mode="python")
    return argument
