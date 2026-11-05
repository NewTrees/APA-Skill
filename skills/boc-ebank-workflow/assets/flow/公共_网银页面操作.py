import json
from typing import Any
from apa_runtime import *


# 中行BFE日期面板选择脚本（独立JS，试运行验证通过）。
# 面板机制：点击日期输入框弹出单月日历；页面同时存在多个同class面板
# （隐藏的带 display: none），入库元素 流水查询_日期面板 已排除隐藏面板。
# 翻页必须用 .bfe-date-picker__next-btn.bfe-icon-arrow-right 精确选单月
# 按钮（否则先命中双箭头年按钮）；连续点击之间需 sleep 等待Vue异步渲染。
JS_PANEL_DATE = """async function(element, input){
    var panel = element;
    if (!panel) return {status: 'error', message: 'panel element is null'};
    var sleep = function(ms){ return new Promise(function(r){ setTimeout(r, ms); }); };
    var dateStr = input.dateStr;
    var parts = dateStr.split('-');
    var year = parseInt(parts[0], 10), month = parseInt(parts[1], 10), day = parseInt(parts[2], 10);

    // 读取面板当前年月：头部两个readonly input，年份在前、月份在后。
    var readPanel = function(){
        var inputs = panel.querySelectorAll('input[readonly]');
        var y = parseInt(inputs[0].value.replace(/[^0-9]/g, ''), 10);
        var m = parseInt(inputs[1].value.replace(/[^0-9]/g, ''), 10);
        return {y: y, m: m};
    };
    // 单月前进/后退按钮（排除双箭头年按钮）。
    var clickMonthBtn = async function(dir){
        var cls = dir > 0 ? '.bfe-date-picker__next-btn.bfe-icon-arrow-right' : '.bfe-date-picker__prev-btn.bfe-icon-arrow-left';
        panel.querySelector(cls).click();
        await sleep(250);
    };
    var maxLoops = 40, guard = 0;
    while (guard++ < maxLoops) {
        var cur = readPanel();
        var diff = (cur.y - year) * 12 + (cur.m - month);
        if (diff === 0) break;
        await clickMonthBtn(diff > 0 ? -1 : 1);
    }
    if (guard >= maxLoops) return {status: 'error', message: 'month navigation failed: ' + dateStr};
    await sleep(200);
    // 查找目标日期格：排除disabled和前后月借位格。
    var tds = function(){ return Array.prototype.slice.call(panel.querySelectorAll('.bfe-date-table td')); };
    var target = null;
    for (var i = 0; i < 10; i++) {
        var all = tds();
        for (var j = 0; j < all.length; j++) {
            var td = all[j];
            if (td.classList.contains('disabled')) continue;
            if (td.classList.contains('prev-month') || td.classList.contains('next-month')) continue;
            if (parseInt((td.textContent || '').trim(), 10) === day) { target = td; break; }
        }
        if (target) break;
        await sleep(200);
    }
    if (!target) return {status: 'error', message: 'day cell not found or disabled: ' + dateStr};
    target.click();
    await sleep(500);
    return {status: 'ok'};
}"""


def select_panel_date(
    browser_handle: str,
    date_str: str,
    date_input_element: str,
) -> str:
    """在BFE日历面板上选择一个日期（单框单日期）。

    点击日期输入框元素弹出日历面板后，通过 ``WebBrowser.Evaluate``
    执行独立JS脚本翻月并点击目标日期格。一个日期输入框对应一次调用。

    Args:
        browser_handle: ``WebBrowser.BindBrowser`` 返回的浏览器句柄。
        date_str: 目标日期，格式 ``yyyy-mm-dd``。
        date_input_element: 日期输入框界面库元素名，例如
            ``流水查询_开始日期输入框``。

    Returns:
        str: 执行结果消息，成功返回 ``ok``。

    Raises:
        RuntimeError: 面板未弹出、翻月失败或目标日期不可选时抛出。
    """
    # @step 点击日期输入框，弹出BFE日历面板。
    Mouse.Action(Hover_ElementSelect(date_input_element), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    Delay(500)

    # @step 在日历面板上翻月并点击目标日期。
    result = WebBrowser.Evaluate(
        browser_handle,
        JS_PANEL_DATE,
        {"dateStr": date_str},
        Hover_ElementSelect("流水查询_日期面板"),
        {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "iTimeOut": 15000},
    )
    if not isinstance(result, dict) or result.get("status") != "ok":
        message = str(result)
        raise RuntimeError("日期面板选择失败，目标日期：{}，脚本返回：{}".format(date_str, message))
    return "ok"


def main(argument):
    """网银页面公共JS操作能力占位入口。

    本文件是独立流程块，提供 ``select_panel_date`` 等页面操作函数供业务
    模块 import 调用，不参与主流程连线。

    Args:
        argument: 上一个流程块的返回值；普通路径中非代码块节点相连时为 None。

    Returns:
        dict: 原样返回传入的参数。
    """
    return argument
