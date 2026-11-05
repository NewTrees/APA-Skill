import calendar
import json
import os
from datetime import date
from typing import Any
from apa_runtime import *
import 公共_数据契约 as contract
import 公共_网银能力 as ebank


def __UNIT_TEST_FUNCTION__(argument):
    """为单独运行当前对账单查询和下载流程块准备测试上下文。

    单独运行本流程块时，用真实测试数据构造统一业务上下文，
    再走真实 main 入口。数据来源：任务数据和Asset配置User段输出目录。
    """
    test_argument = {
        "business_type": 4,                                    # BusinessType: 对账单查询和下载
        "business_name": "对账单查询和下载",
        "account": {
            "account_id": 12,                                  # 上游任务 id
            "bank_account": "595080967721",
            "account_name": "来也科技项目经理部",
            "open_bank_name": "中国银行",
            "open_unit": "来也科技",
            "keeper": "邓",
        },
        "query_dates": {
            "start_date": "2026.06.01",                        # 有数据测试（6月有交易；9月账单未出）
            "end_date": "2026.06.30",
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


# 对账单产物规则随对账单业务一起维护，不放进固定框架。
FOLDER_NAME = "对账单"
FILE_LABEL = "对账单"


def _build_output_location(
    business_argument: contract.BusinessArgumentModel,
) -> tuple[str, str]:
    """根据对账单业务规则生成保存目录和文件名。

    文件名不附加时间戳，同账号同月重跑时覆盖旧文件；同一轮的多份
    对账单由下载循环拼对账单序号区分。
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


def query_and_download_statements(
    start_date: str,
    end_date: str,
    account_number: str,
    output_folder: str,
    file_name: str,
) -> contract.BusinessResultModel:
    """查询并下载电子对账单。

    Args:
        start_date: 查询起始日期。
        end_date: 查询结束日期。
        account_number: 查询的子账号。
        output_folder: 下载文件保存路径。
        file_name: 下载文件命名。

    Returns:
        contract.BusinessResultModel: 统一业务结果。
    """
    result = contract.BusinessResultModel(code=-1, message="")

    query_result = query_statements(start_date, end_date, account_number)
    Log.Info("查询电子对账单结果：\r\n{}".format(str(query_result)))
    if query_result is None:
        result.code = 1
        result.message = "查询电子对账单未返回结果"
        return result

    # @step 检查对账单查询是否成功。
    if query_result.code == -1 or query_result.code == 1:
        result.code = 1
        result.message = query_result.message
        return result
    # @step 判断对账单查询结果是否为空。
    if query_result.code == 2:
        result.code = 2
        result.message = query_result.message
        return result

    # @step 逐条下载查询到的电子对账单。
    download_items = download_statements(output_folder, file_name)
    Log.Info("下载电子对账单结果：\r\n{}".format(str(download_items)))
    # @step 判断是否存在可下载的电子对账单。
    if not download_items:
        result.code = 2
        result.message = "没有匹配到目标账号的电子对账单"
        return result

    # @step 返回当前子账号的全部电子对账单文件。
    result.outputs = download_items
    result.code = 0
    result.message = "下载成功，共下载 {} 份对账单".format(len(download_items))
    return result


def query_statements(
    start_date: str,
    end_date: str,
    account_number: str,
) -> contract.OperationResultModel:
    """查询电子对账单。

    中行对账单页面按账单月份查询，输入账号后点查询。

    Args:
        start_date: 查询起始日期。
        end_date: 查询结束日期。
        account_number: 查询的子账号。

    Returns:
        contract.OperationResultModel: 查询结果。
    """
    query_result = contract.OperationResultModel(code=-1)

    # @step 进入对账单查询页面：信息服务-银企对账-明细对账单查询。
    Mouse.Hover(Hover_ElementSelect("段落<p>_信息服务"), 10000, {"bContinueOnError": False, "iDelayAfter": 800, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    ebank.wait_for_element(Hover_ElementSelect("段落<p>_银企对账"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("段落<p>_银企对账"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    statement_page_ready = ebank.wait_for_element(Hover_ElementSelect("块级元素<div>_明细对账单查询"), 10, 1000)
    if not statement_page_ready:
        Log.Error("页面未加载成功。")
        query_result.code = 1
        query_result.message = "查询失败"
        return query_result
    Mouse.Action(Hover_ElementSelect("块级元素<div>_明细对账单查询"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 校验对账单查询日期。
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

    # @step 校验对账单查询日期范围：中行页面只有一个月份输入框，
    #   开始和结束必须落在同一个月内。
    range_error_message = _validate_date_range_months(
        start_date,
        end_date,
        1,
        "对账单",
    )
    if range_error_message is not None:
        Log.Error(range_error_message)
        query_result.code = 1
        query_result.message = range_error_message
        return query_result

    # 对账单页面按账单月份查询，只输入到 yyyy/mm。
    start_month = Time.Format(Time.CDate(start_date, "yyyy.mm.dd"), "yyyy/mm")

    # @step 输入查询账号。
    account_number = StringLib.Replace(account_number, "-", "", False)
    Mouse.Action(Hover_ElementSelect("输入控件<input>对账单下载输入账号的输入框"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    Keyboard.Press("A", "press", ["Ctrl"], {"iDelayAfter": 300, "iDelayBefore": 200, "sSimulate": "simulate"})
    Keyboard.Input(account_number, 30, {"iDelayAfter": 300, "iDelayBefore": 200, "sSimulate": "message"})

    # @step 设置对账单查询月份。中行月份输入框为只读，需要点击后
    #   从月份面板中先切换年份再点选目标月份单元格。
    Mouse.Action(Hover_ElementSelect("输入控件<input>1"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 500, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    target_year = int(start_month.split("/", 1)[0])
    target_month_index = int(start_month.split("/", 1)[1])
    for _year_attempt in range(12):
        year_text = str(UiElement.GetValue(Hover_ElementSelect("对账单_月份面板_年份文本"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200}))
        year_digits = "".join(ch for ch in year_text if ch.isdigit())
        panel_year = int(year_digits) if year_digits else None
        if panel_year is None:
            Log.Error("无法读取月份面板年份文本：{}".format(year_text))
            query_result.code = 1
            query_result.message = "查询失败"
            return query_result
        if panel_year == target_year:
            break
        if panel_year > target_year:
            Mouse.Action(Hover_ElementSelect("对账单_月份面板_上一年按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 500, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        else:
            Mouse.Action(Hover_ElementSelect("对账单_月份面板_下一年按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 500, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    else:
        Log.Error("月份面板年份切换失败，未到达目标年份 {}。".format(target_year))
        query_result.code = 1
        query_result.message = "查询失败"
        return query_result

    # @step 在月份表格中点选目标月份（td 顺序即 1-12 月）。
    month_cells = list(IterateUiElements(Hover_ElementSelect("对账单_月份面板_月份单元格_通配")))
    if len(month_cells) < target_month_index:
        Log.Error("月份面板月份单元格数量不足。")
        query_result.code = 1
        query_result.message = "查询失败"
        return query_result
    Mouse.Action(month_cells[target_month_index - 1], "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 500, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 提交电子对账单查询。
    Mouse.Action(Hover_ElementSelect("按钮<button>_查询1"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 1500, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 查询后回读月份，确认页面接受的目标月份。页面月份格式为 yyyy-MM。
    actual_month = UiElement.GetValue(Hover_ElementSelect("输入控件<input>1"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    actual_month_normalized = str(actual_month).replace("-", "/")
    if actual_month_normalized != start_month:
        date_mismatch_message = "查询月份与目标月份不一致，目标月份: {}，回读月份: {}".format(str(start_month), str(actual_month))
        Log.Error(date_mismatch_message)
        query_result.code = 1
        query_result.message = "查询月份与目标月份不一致"
        return query_result

    # @step 判断电子对账单查询结果是否为空。
    # 中行页面在无数据时弹出“无查询结果”提示框，而不是页面内提示。
    has_no_records = ebank.wait_for_element(Hover_ElementSelect("对账单查询_无数据提示"), 3, 2000)
    if has_no_records:
        Log.Info("查询结果为空。")
        # @step 关闭“无查询结果”提示弹窗，避免模态层阻塞后续模块导航。
        Mouse.Action(Hover_ElementSelect("对账单查询_无数据弹窗确定按钮"), "left", "click", 10000, {"bContinueOnError": True, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        query_result.code = 2
        query_result.message = "查询结果为空"
        return query_result

    # @step 确认电子对账单查询已经返回结果。
    # 无数据时页面弹出“无查询结果”提示框；有数据时表格中出现结果数据行。
    has_result_row = ebank.wait_for_element(Hover_ElementSelect("对账单查询_结果数据行_通配"), 3, 2000)
    if has_result_row:
        Log.Info("查询成功")
        query_result.code = 0
        query_result.message = "查询成功"
        return query_result

    query_result.code = 1
    query_result.message = "查询后未识别到成功或无数据状态"
    return query_result


def download_statements(
    output_folder: str,
    file_name: str,
) -> list[contract.BusinessOutputModel]:
    """逐条下载查询结果中的电子对账单。

    中行对账单列表中每条记录带有下载入口；多条时逐条点击下载，
    由浏览器自动保存文件。文件名由公共部分加序号组成，同账号同月
    重跑时覆盖旧文件。

    Args:
        output_folder: 对账单文件的保存目录。
        file_name: 文件名的公共部分，实际文件名还会附加序号。

    Returns:
        list[contract.BusinessOutputModel]: 已下载的标准文件产物列表；
        没有可下载的对账单时返回空列表。

    Raises:
        RuntimeError: 对账单文件下载失败。
    """

    downloads: list[contract.BusinessOutputModel] = []
    sequence = 0

    # @step 遍历对账单列表的下载入口，逐条下载。
    download_entries = IterateUiElements(Hover_ElementSelect("对账单下载_下载按钮_通配"))
    for download_selector in download_entries:
        sequence += 1
        # @step 生成当前对账单的文件名。
        file_extension = "pdf"
        save_path = os.path.join(
            output_folder,
            "{}-{}.{}".format(file_name, sequence, file_extension),
        )
        Log.Info("文件保存路径：{}".format(save_path))

        # @step 点击下载，等待浏览器下载完成并保存到目标路径。
        Mouse.Action(download_selector, "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 2000, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        is_downloaded = ebank.save_chrome_download(save_path)
        if is_downloaded:
            downloads.append(contract.BusinessOutputModel(
                output_type="file",
                category="对账单",
                path=save_path,
                name="{}-{}".format(file_name, sequence),
            ))
            Log.Info("下载成功：{}".format(save_path))
        else:
            raise RuntimeError("电子对账单下载失败：{}".format(save_path))

    return downloads


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """按中行对账单规则生成产物并查询下载电子对账单。

    Args:
        argument: 统一业务上下文字典，包含业务编号和名称、当前账号、查询日期、
            U盾编号以及输出根目录。执行完成后写入 ``business_result``，
            对账单文件放在 ``outputs`` 列表中。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        ValueError: 参数不符合统一业务上下文数据契约。
        Exception: 页面操作或文件下载出现未处理异常。
    """
    # @step 校验对账单查询参数。
    business_argument = contract.BusinessArgumentModel.model_validate(argument)

    # @step 生成对账单输出目录和文件名。
    output_folder, file_name = _build_output_location(business_argument)

    # @step 查询并下载当前账号的电子对账单。
    result = query_and_download_statements(
        business_argument.query_dates.start_date,
        business_argument.query_dates.end_date,
        business_argument.account.bank_account,
        output_folder,
        file_name,
    )
    # @step 写回标准业务结果。
    argument["business_result"] = result.model_dump(mode="python")
    return argument
