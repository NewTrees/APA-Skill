import calendar
import json
from datetime import date
from typing import Any
from apa_runtime import *
import 公共_数据契约 as contract
import 公共_网银能力 as ebank
import 公共_网银页面操作 as pageop


def __UNIT_TEST_FUNCTION__(argument):
    """为单独运行当前回单查询和下载流程块准备测试上下文。

    单独运行本流程块时，用真实测试数据构造统一业务上下文，
    再走真实 main 入口。数据来源：任务数据和Asset配置User段输出目录。
    """
    test_argument = {
        "business_type": 3,                                    # BusinessType: 回单查询和下载
        "business_name": "回单查询和下载",
        "account": {
            "account_id": 12,                                  # 上游任务 id
            "bank_account": "595080967721",
            "account_name": "来也科技项目经理部",
            "open_bank_name": "中国银行",
            "open_unit": "来也科技",
            "keeper": "邓",
        },
        "query_dates": {
            "start_date": "2026.09.01",                        # 无数据测试（9月无交易，预期 code=2）
            "end_date": "2026.09.15",
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


# 回单产物规则随回单业务页面一起维护，不放进固定框架。
FOLDER_NAME = "回单"
FILE_LABEL = "回单"


def _build_output_location(
    business_argument: contract.BusinessArgumentModel,
) -> tuple[str, str]:
    """根据回单业务规则生成保存目录和文件名。

    中行回单为整期合并PDF，一次下载一份文件，固定文件名可覆盖。
    """

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


def _select_receipt_account(account_number: str) -> bool:
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


def query_and_download_receipts(
    start_date: str,
    end_date: str,
    account_number: str,
    output_folder: str,
    file_name: str,
) -> contract.BusinessResultModel:
    """查询回单并下载回单。

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

    query_result = query_receipts(start_date, end_date, account_number)
    Log.Info("查询回单结果：\r\n{}".format(str(query_result)))

    # @step 检查回单查询是否成功。
    if query_result.code == -1 or query_result.code == 1:
        result.code = 1
        result.message = query_result.message
        return result
    # @step 判断回单查询结果是否为空。
    if query_result.code == 2:
        result.code = 2
        result.message = query_result.message
        return result

    # @step 下载查询到的电子回单。
    download_result = download_receipts(output_folder, file_name)
    Log.Info("下载回单结果：\r\n{}".format(str(download_result)))
    # @step 检查电子回单是否下载成功。
    if download_result.code == -1 or download_result.code == 1:
        result.code = 1
        result.message = download_result.message
        return result

    # @step 判断是否存在可以下载的电子回单。
    if download_result.code == 2:
        result.code = 2
        result.message = download_result.message
        return result

    # @step 返回电子回单下载结果。
    if download_result.code == 0:
        result.outputs = [contract.BusinessOutputModel(
            output_type="folder",
            category="回单",
            path=download_result.file_path,
            name=file_name,
        )]
        result.code = 0
        result.message = download_result.message
        return result

    return result


def query_receipts(
    start_date: str,
    end_date: str,
    account_number: str,
) -> contract.OperationResultModel:
    """查询回单。

    Args:
        start_date: 查询起始日期。
        end_date: 查询结束日期。
        account_number: 查询的子账号。

    Returns:
        contract.OperationResultModel: 查询结果，code 0 成功，1 失败，2 查询结果为空。
    """
    query_result = contract.OperationResultModel(code=-1)

    # @step 进入回单查询页面：信息服务-中行账户与回单-交易/回单。
    Mouse.Hover(Hover_ElementSelect("段落<p>_信息服务"), 10000, {"bContinueOnError": False, "iDelayAfter": 800, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    ebank.wait_for_element(Hover_ElementSelect("段落<p>_中行账户与回单"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("段落<p>_中行账户与回单"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    ebank.wait_for_element(Hover_ElementSelect("文本<span>_交易/回单"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("文本<span>_交易/回单"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 选择需要查询回单的银行账号。
    account_number = StringLib.Replace(account_number, "-", "", False)
    if not _select_receipt_account(account_number):
        Log.Error("连续6次仍无法选择目标账户。")
        query_result.code = 1
        query_result.message = "无法选择目标账户"
        return query_result

    # @step 校验回单查询日期。
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

    # @step 校验回单查询日期范围不超过六个月。
    range_error_message = _validate_date_range_months(
        start_date,
        end_date,
        6,
        "回单",
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

    # @step 通过日历面板设置回单查询开始和结束日期。
    browser_handle = WebBrowser.BindBrowser("chrome", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    pageop.select_panel_date(browser_handle, panel_start_date, "流水查询_开始日期输入框")
    pageop.select_panel_date(browser_handle, panel_end_date, "流水查询_结束日期输入框")

    # @step 提交电子回单查询。
    Mouse.Action(Hover_ElementSelect("按钮<button>_查询"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 1500, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 查询后回读日期确认页面接受的目标日期。
    actual_start_date = UiElement.GetValue(Hover_ElementSelect("流水查询_开始日期输入框"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    actual_end_date = UiElement.GetValue(Hover_ElementSelect("流水查询_结束日期输入框"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    if str(actual_start_date) != start_date or str(actual_end_date) != end_date:
        date_mismatch_message = "查询日期与目标日期不一致，目标开始日期: {}，回读开始日期: {}，目标结束日期: {}，回读结束日期: {}".format(str(start_date), str(actual_start_date), str(end_date), str(actual_end_date))
        Log.Error(date_mismatch_message)
        query_result.code = 1
        query_result.message = "查询日期与目标日期不一致"
        return query_result

    # @step 确认回单查询已经返回结果。
    # 流水与回单在同一个交易/回单页面，复用流水查询_结果数据行_通配元素。
    has_result_row = ebank.wait_for_element(Hover_ElementSelect("流水查询_结果数据行_通配"), 5, 1000)
    if has_result_row:
        Log.Info("查询成功")
        query_result.code = 0
        query_result.message = "查询成功"
        return query_result

    # @step 判断电子回单查询结果是否为空。
    has_no_records = ebank.wait_for_element(Hover_ElementSelect("回单查询_无匹配记录提示"), 5, 1000)
    if has_no_records:
        Log.Info("查询结果为空。")
        query_result.code = 2
        query_result.message = "查询结果为空"
        return query_result

    query_result.code = 1
    query_result.message = "查询后未识别到成功或无数据状态"
    return query_result


def download_receipts(output_folder: str, file_name: str) -> contract.OperationResultModel:
    """下载回单。

    中行回单通过点击「下载回单」并确认后，由浏览器自动下载文件；
    下载过程中页面出现「文件生成中」加载提示，完成后出现悬浮通知。
    中行回单为整期合并PDF，一次下载一份文件，固定文件名可覆盖。

    Args:
        output_folder: 下载文件保存路径。
        file_name: 下载文件命名。

    Returns:
        contract.OperationResultModel: 下载结果，code 0 成功，1 失败，2 没有待下载的数据。
    """
    download_result = contract.OperationResultModel(code=-1)

    # @step 生成回单文件名。
    file_extension = "pdf"
    save_path = "{}\\{}.{}".format(output_folder, file_name, file_extension)
    Log.Info("文件保存路径：{}".format(save_path))

    # @step 确认页面存在可下载的电子回单。
    # 流水与回单在同一个交易/回单页面，复用流水查询_结果数据行_通配元素。
    has_result_row = ebank.wait_for_element(Hover_ElementSelect("流水查询_结果数据行_通配"), 5, 1000)
    if has_result_row:
        Log.Info("回单有待下载的数据")
        # @step 点击下载回单并确认提交。
        Mouse.Action(Hover_ElementSelect("按钮<button>_下载回单"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        Mouse.Action(Hover_ElementSelect("按钮<button>_确定1"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

        # @step 等待文件生成完成的悬浮通知出现。
        # 提交成功后页面显示「文件生成中，请稍等」加载提示，文件生成
        # 完成后出现「逐笔回单已生成，请及时查看」悬浮通知，浏览器自动下载。
        receipt_generated = ebank.wait_for_element(Hover_ElementSelect("块级元素<div>_逐笔回单已生成，请及时查看。"), 30, 2000)
        if not receipt_generated:
            download_result.code = 1
            download_result.message = "下载失败，未等到回单生成通知"
            return download_result

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
    """按中行回单规则生成产物并查询下载电子回单。

    Args:
        argument: 统一业务上下文字典，包含业务编号和名称、当前账号、查询日期、
            U盾编号以及输出根目录。执行完成后写入 ``business_result``；
            回单产物是包含多份PDF的目录，因此 ``output_type`` 为 ``folder``。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        ValueError: 参数不符合统一业务上下文数据契约。
        Exception: 页面操作或文件下载出现未处理异常。
    """
    # @step 校验回单查询参数。
    business_argument = contract.BusinessArgumentModel.model_validate(argument)

    # @step 生成回单输出目录和文件名。
    output_folder, file_name = _build_output_location(business_argument)

    # @step 查询并下载当前账号的电子回单。
    result = query_and_download_receipts(
        business_argument.query_dates.start_date,
        business_argument.query_dates.end_date,
        business_argument.account.bank_account,
        output_folder,
        file_name,
    )
    # @step 写回标准业务结果。
    argument["business_result"] = result.model_dump(mode="python")
    return argument
