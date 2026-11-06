from typing import Any
from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


def __UNIT_TEST_FUNCTION__(argument):
    """为单独运行当前余额查询流程块准备测试上下文。

    单独运行本流程块时，用真实测试数据构造统一业务上下文，
    再走真实 main 入口。数据来源：任务数据和Asset配置User段输出目录。
    """
    test_argument = {
        "business_type": 2,                                    # BusinessType: 余额查询
        "business_name": "余额查询",
        "account": {
            "account_id": 12,                                  # 上游任务 id
            "bank_account": "595080967721",
            "account_name": "来也科技项目经理部",
            "open_bank_name": "中国银行",
            "open_unit": "来也科技",
            "keeper": "邓",
        },
        "query_dates": {
            "start_date": "2026.09.01",                        # start_date
            "end_date": "2026.09.15",                          # end_date
        },
        "ukey_number": "535309484561",                         # ukey_no
        "output_folder": "D:\\网银场景架构设计\\output\\中国银行",  # OutputFolder
    }
    return main(test_argument)
def _format_account_number(account_number: str) -> str:
    """按中行页面格式整理账号。

    中行页面账号平铺显示为不带分隔符的数字串，这里去掉任务账号中
    可能存在的连字符，便于与页面文本匹配。

    Args:
        account_number: 任务中的银行账号。

    Returns:
        str: 可直接与页面账户文本匹配的账号。
    """
    return StringLib.Replace(account_number, "-", "", False)


def _select_balance_account(account_number: str) -> bool:
    """在余额查询页面顶部平铺账号中选择目标账号。

    中行账户不是下拉框，而是平铺在页面顶部的账号文本。当前界面库
    登记的是单一账号元素；出现多个账号时需要补充账号通配元素。

    Args:
        account_number: 已按页面格式整理的银行账号。

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


def query_account_balance(account_number: str) -> contract.BusinessResultModel:
    """查询账户余额。

    Args:
        account_number: 要查询的子账号。

    Returns:
        BusinessResultModel: 查询结果。成功时 ``values`` 中包含去除千分位
            逗号后的“可用余额”；失败时返回非0、非2结果码。
    """
    query_result = contract.BusinessResultModel(code=-1, message="")
    Log.Info("当前运行的账号是：{}".format(account_number))

    # @step 进入余额查询页面：信息服务-中行账户与回单。
    # 中行该页面为单页滚动结构（2026-09-29实测）：上半部分是"今日余额"卡片
    # （#trans，含当前余额/可用余额/透支限额）和"历史余额"表，下半部分是
    # "交易/回单"区（#da）；页面顶部的"余额/交易/回单"锚点仅做滚动定位，
    # 点击"交易/回单"后锚点条即卸载。从菜单进入后默认落在顶部余额区，
    # 直接等待余额内容就绪即可，不再点击"交易/回单"和"余额"锚点。
    Mouse.Hover(Hover_ElementSelect("段落<p>_信息服务"), 10000, {"bContinueOnError": False, "iDelayAfter": 800, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    ebank.wait_for_element(Hover_ElementSelect("段落<p>_中行账户与回单"), 10, 1000)
    Mouse.Action(Hover_ElementSelect("段落<p>_中行账户与回单"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    # @step 等待"今日余额"内容区就绪，确认页面已加载到余额区。
    balance_page_ready = ebank.wait_for_element(Hover_ElementSelect("余额查询_可用余额数值"), 10, 1000)
    Log.Info("余额页面就绪：{}".format(str(balance_page_ready)))
    if not balance_page_ready:
        Log.Error("进入余额页面失败，未识别到今日余额内容。")
        query_result.code = 1
        query_result.message = "进入余额页面失败"
        return query_result

    # @step 按中行页面格式整理目标账号。
    page_account_number = _format_account_number(account_number)

    # @step 选择需要查询余额的银行账号。
    if not _select_balance_account(page_account_number):
        Log.Error("连续6次仍无法选择目标账户。")
        query_result.code = 1
        query_result.message = "无法选择目标账户"
        return query_result

    # @step 等待选中账号后"今日余额"卡片刷新，读取可用余额。
    # 当日实时可用余额随账号选中自动刷新，无需点击查询按钮（页面上的
    # 查询按钮属交易区/历史余额表单，与今日余额卡片无关）。
    Delay(2000)
    # @step 读取可用余额。元素锚定“可用余额”标题后的数值段落（#trans区），
    #   不随账号或金额变化失效。
    balance_available = ebank.wait_for_element(Hover_ElementSelect("余额查询_可用余额数值"), 3, 1000)
    if not balance_available:
        Log.Error("查询失败，未识别到可用余额。")
        query_result.code = 1
        query_result.message = "查询失败"
        return query_result

    amount_text = UiElement.GetValue(Hover_ElementSelect("余额查询_可用余额数值"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    amount_text = Regex.FindStr(amount_text, "[\\d,.]+", 0)
    amount_text = StringLib.Replace(amount_text, ",", "", False)
    query_result.code = 0
    query_result.message = "查询成功"
    query_result.values = [contract.BusinessValueModel(
        name="可用余额",
        value=amount_text,
        unit="元",
    )]
    return query_result


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """执行余额查询，并把结果写回同一个流程参数字典。

    Args:
        argument: 统一业务上下文字典，包含业务编号和名称、当前账号、查询日期、
            U盾编号以及输出根目录。函数执行完成后写入 ``business_result``；
            可用余额放在 ``values`` 列表中。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        ValueError: 参数不符合统一业务上下文数据契约。
        Exception: 余额查询页面操作发生其他未处理异常。
    """
    # @step 校验余额查询参数。
    business_argument = contract.BusinessArgumentModel.model_validate(argument)

    # @step 查询当前账号余额。
    result = query_account_balance(business_argument.account.bank_account)

    # @step 写回标准业务结果。
    argument["business_result"] = result.model_dump(mode="python")
    return argument
