import os, json, copy, decimal, random  # noqa: F401
from typing import Any
from apa_runtime import *
import 公共_网银能力 as ebank
import 公共_数据契约 as contract


# 中国银行企业网银登录页地址。
EBANK_LOGIN_URL = "https://netc1.igtb.bankofchina.com/#/login-page?redirect=%2Findex"


def _open_login_page(assistant_path: str) -> None:
    """启动中国银行网银助手，并用Chrome打开企业网银登录页。

    网银助手只需启动，不需要界面操作。

    Args:
        assistant_path: 中国银行网银助手程序的完整路径。

    Returns:
        None
    """
    # @step 关闭上一轮可能残留的浏览器和全部中行网银助手相关进程。
    # 先杀Chrome再杀助手系进程：助手向Chrome注入安全控件，证书握手会话
    # 状态残留在CryptoKitHost等控件宿主进程里，重试时不清理会触发网银
    # "请先关闭所有浏览器窗口再重新打开"提示。Services类服务进程杀不掉
    # 也不该杀，杀完Console类进程后等待让服务侧状态自然回收。
    import subprocess
    App.Kill("chrome.exe")
    _boc_console_process_names = [
        "BOCAssistant.exe",
        "BOCUsertool.exe",
        "D4Svr_BOC.exe",
        "WDUIServer_Watchdata BOC CSP v3.3.exe",
        "InfoSuite.BOC.x86.exe",
        "CryptoKitHost.BOC.x86.exe",
    ]
    for _boc_process_name in _boc_console_process_names:
        App.Kill(_boc_process_name)

    # @step 轮询等待Chrome和助手系Console进程完全退出（最长30秒）。
    _watch_processes = ["chrome.exe"] + _boc_console_process_names
    for _process_exit_attempt in range(15):
        try:
            _task_output = subprocess.run(
                ["tasklist", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        # apa-lint: disable-next-line preserve-exception-traceback -- 查询进程命令失败时按仍有残留处理，继续等待。
        except Exception:
            _task_output = ",".join(_watch_processes)
        _remaining_processes = [
            name for name in _watch_processes if name in str(_task_output)
        ]
        if not _remaining_processes:
            break
        Log.Info("进程仍在退出中：{}".format(str(_remaining_processes)))
        Delay(2000)

    # @step 等待Services类服务的会话状态回收，再重启助手。
    Delay(5000)

    # @step 启动配置中指定的中国银行网银助手。
    Log.Debug("[登录实现] 网银助手路径={}".format(str(assistant_path)))
    assistant_process_id = App.Run(assistant_path, "1", "1")
    Log.Debug("[登录实现] 网银助手进程ID={}".format(str(assistant_process_id)))
    Log.Info("运行网银助手")
    ebank.remember_apps(GlobalVariables["ebank"].config.related_apps)

    # @step 等待网银助手安全控件初始化完成后再启动浏览器，降低控件状态异常概率。
    Delay(15000)
    try:
        # for i in range(10):
        #     bRet = Image.Exists({"wnd":[{"cls":"DirectUIMainWnd","title":" 中国银行网银助手","app":"BOCAssistant"}]},{"x": 0, "y": 0, "width": 0, "height": 0},RES("0d6b5de6-e0e7-418a-897b-bce31a83becc.png"),0.9,10000,{"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sMatchType":"GrayMatch"})
        #     if bRet:
        Image.Click({"wnd":[{"cls":"DirectUIMainWnd","title":" 中国银行网银助手","app":"BOCAssistant"}]},{"x": 0, "y": 0, "width": 0, "height": 0},RES("18c55ad7-2b93-4772-b461-f4d158fbbb38.png"),0.9,"left","click",10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [],"sSimulate": "simulate","sMatchType":"GrayMatch", "iSerialNo": 1})
        #         Delay(10000)
        #         break
        #     else:
        #         Delay(3000)
        Delay(5000)
    # apa-lint: disable-next-line preserve-exception-traceback -- 一键修复为可选的助手自愈动作，点击失败仅告警继续，不阻塞登录。
    except Exception:
        Log.Warn("未点击到一键修复")

    # @step 启动浏览器并等待中国银行企业网银登录页加载（以数字证书登录入口出现为标志）。
    browser = WebBrowser.Create("chrome", EBANK_LOGIN_URL, 30000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "sBrowserPath": "", "sStartArgs": ""})
    Log.Info("启动浏览器访问中国银行企业网银")
    page_loaded = WebBrowser.WaitPage(browser, Hover_ElementSelect("块级元素<div>_数字证书登录"), 60000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
    Log.Debug("[登录实现] 企业网银登录页加载结果={}".format(str(page_loaded)))

    # @step 关闭浏览器更新失败、意外关闭和页面恢复提示。
    update_failure_dialog_exists = UiElement.Exists(Hover_ElementSelect("浏览器更新失败_提示窗格"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bWaitDOMReady": True})
    Log.Debug("[登录实现] 浏览器更新失败提示存在={}".format(str(update_failure_dialog_exists)))
    if update_failure_dialog_exists:
        Mouse.Action(Hover_ElementSelect("浏览器更新失败_关闭按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    Delay(2000)
    for _recovery_attempt in range(4):
        unexpected_close_dialog_exists = UiElement.Exists(Hover_ElementSelect("网银登录_页面意外关闭提示"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bWaitDOMReady": True})
        if not unexpected_close_dialog_exists:
            break
        Mouse.Action(Hover_ElementSelect("网银登录_浏览器恢复关闭按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    recovery_prompt_exists = ebank.wait_for_element(Hover_ElementSelect("网银登录_浏览器恢复提示"), 2, 5000)
    Log.Debug("[登录实现] 浏览器页面恢复提示存在={}".format(str(recovery_prompt_exists)))
    if recovery_prompt_exists:
        Mouse.Action(Hover_ElementSelect("网银登录_浏览器恢复关闭按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})

    Window.Show(Hover_WindowSelect("窗口_iGTBNet（企业网银）-GoogleChrome"), "max")

def _check_and_confirm_windows_cert_dialog(expected_serial_no: str | None = None) -> bool:
    """检查Windows安全证书选择框是否存在，存在则确认并记录已确认状态。

    该弹窗出现时机不确定（打开登录页、点击数字证书登录、提交证书密码后
    都可能出现），但在输入登录密码前必须已被点击确认，否则网银会拒绝登录。
    本函数可在登录链路的任意阶段安全调用。

    提供期望证书序列号时（2026-09-29实测Text.Get通道可读，Watchdata控件
    的UIA/MSAA文本为乱码但Text命令正常）：先用Text.Get读取弹窗全部证书
    序列号，匹配则Text.Click按序列号文本点选目标证书行（单证书也验证），
    再点确定；无匹配时截图并抛出异常终止本次登录。未提供序列号时保持
    原行为（默认选中直接点确定）。

    Args:
        expected_serial_no: 任务提供的U盾证书序列号；None时按默认选中
            证书直接确定。

    Returns:
        bool: 本次检查发现并确认了弹窗时返回True；未发现返回False。

    Raises:
        RuntimeError: 提供了期望序列号但弹窗证书清单中无匹配时抛出。
    """
    global _cert_dialog_confirmed
    dialog_exists = False
    try:
        dialog_exists = ebank.wait_for_element(Hover_ElementSelect("对话框_Windows安全_选择证书"), 1, 500)
    # apa-lint: disable-next-line preserve-exception-traceback -- Windows安全证书选择框为可选桌面元素，识别失败按未出现处理。
    except Exception:
        dialog_exists = False
    if not dialog_exists:
        return False

    # @step 提供期望序列号时按文本匹配选中目标证书（单证书也验证）。
    # 匹配与点选均使用"windows安全框列表项目"元素（指向证书列表项）：
    # 2026-09-29实测该元素Text.Get返回列表内全部条目的聚合文本（多U盾时
    # 各盾序列号均在其中），Text.Exists可扫描全部证书行做子串匹配，完整
    # 序列号互不为子串不会误中；"对话框_Windows安全_选择证书"元素仅保留
    # 用于弹窗出现判断，其Text通道只吐出标题层文本、无法匹配序列号
    # （15:0x后实测失效，14:5x前可用，Watchdata控件行为不稳定）。
    if expected_serial_no is not None and str(expected_serial_no).strip() != "":
        target_serial = str(expected_serial_no).strip()
        # 弹窗刚出现时证书列表文本可能尚未就绪：先轮询等待列表项文本
        # 非空且含"序列号"字样（最长10秒），就绪后再做匹配判断。
        dialog_text = ""
        for _dialog_text_attempt in range(10):
            dialog_text = str(Text.Get(Hover_ElementSelect("windows安全框列表项目"), 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True}))
            if "序列号" in dialog_text:
                break
            Log.Info("Windows安全框文本尚未就绪（第{}次读取为空或无序列号），继续等待".format(_dialog_text_attempt + 1))
            Delay(1000)
        import re as _re
        serial_numbers = _re.findall(r"序列号[:：]\s*[\dA-Za-z]+", dialog_text)
        Log.Info("Windows安全证书选择框文本片段：{}".format(str(serial_numbers)[:200]))
        if not Text.Exists(
            Hover_ElementSelect("windows安全框列表项目"),
            target_serial,
            "instr",
            1,
            10000,
            {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True},
        ):
            message = "Windows安全证书选择框中未找到与证书序列号{}匹配的证书。请检查任务ukey_no配置或U盾是否正确插入。".format(target_serial)
            Log.Error(message)
            ebank.save_exception_screenshot("Windows安全框_未找到匹配证书")
            raise RuntimeError(message)
        # @step 按目标序列号文本点选证书行（Text.Click，列表项元素文本含全部证书行）。
        try:
            Text.Click(
                Hover_ElementSelect("windows安全框列表项目"),
                target_serial,
                "instr",
                1,
                "left",
                "click",
                10000,
                {"bContinueOnError": False, "iDelayAfter": 500, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate"},
            )
            Log.Info("Windows安全框已按序列号{}选中证书".format(target_serial))
        # apa-lint: disable-next-line preserve-exception-traceback -- 序列号已通过Text.Exists确认存在，文本点击失败仅告警，保持当前选中项继续点确定（Chrome证书框会再次核验兜底）。
        except Exception as click_error:
            Log.Warn("按序列号点击证书行失败，保持默认选中继续：{}".format(str(click_error)))

    try:
        Mouse.Action(Hover_ElementSelect("窗口_Windows安全_确定"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        _cert_dialog_confirmed = True
        Log.Info("已点击Windows安全证书选择框确定（贯穿式监测命中）")
        return True
    # apa-lint: disable-next-line preserve-exception-traceback -- 证书选择框确定按钮点击失败不阻断登录，等待后续阶段再次尝试。
    except Exception:
        Log.Warn("Windows安全证书选择框确定按钮点击失败，等待后续阶段再次尝试")
        return False


# Windows安全证书选择框是否已在本轮登录中确认过。
_cert_dialog_confirmed = False

# Chrome证书选择框证书行的定位前缀（2026-09-29实测）：Chrome自绘
# CertificateSelector > TableView > AXVirtualView 结构；行idx从1开始
# （idx0是表头），行内子格idx 0/1/2 分别为主题/颁发者/序列号，文本可读。
_CHROME_CERT_ROW_CTRL_PREFIX = [
    {"cid": 50033, "cls": "BrowserRootView", "idx": 0},
    {"cid": 50032, "name": "选择证书", "cls": "RootView", "idx": 0},
    {"cid": 50033, "cls": "NonClientView", "idx": 0},
    {"cid": 50033, "cls": "BubbleFrameView", "idx": 0},
    {"cid": 50033, "cls": "DialogClientView", "idx": 0},
    {"cid": 50033, "cls": "CertificateSelector", "idx": 0},
    {"cid": 50033, "cls": "ScrollView", "idx": 0},
    {"cid": 50033, "cls": "ScrollView::Viewport", "idx": 0},
    {"cid": 50028, "cls": "TableView", "idx": 0},
]


def _confirm_browser_certificate_prompt(expected_serial_no: str | None) -> bool:
    """按证书序列号确认浏览器顶部证书选择框；未提供期望序列号时直接确定。

    Chrome证书选择框为自绘控件，证书行(AXVirtualView idx从1开始)内
    子格idx0/1/2为主题/颁发者/序列号，文本可读。提供期望序列号时逐行
    读取并精确匹配（单证书也验证），匹配行点击选中后点确定；无匹配行
    抛出登录失败异常，避免使用错误证书继续登录。

    Args:
        expected_serial_no: 任务提供的U盾证书序列号；None时按默认选中
            证书直接点确定（兼容未配置场景）。

    Returns:
        bool: 本轮发现并确认了浏览器证书选择框时返回 ``True``；
        证书框不存在返回 ``False``。
    Raises:
        RuntimeError: 提供了期望序列号但所有证书行均不匹配时抛出，
        由登录框架按可重试错误处理。
    """
    browser_certificate_prompt_exists = ebank.wait_for_element(Hover_ElementSelect("分组_选择证书"), 1, 500)
    if not browser_certificate_prompt_exists:
        return False

    if expected_serial_no is None or str(expected_serial_no).strip() == "":
        # 任务未提供期望序列号：按默认选中证书直接确认（保持原行为）。
        Mouse.Action(Hover_ElementSelect("按钮_选择证书_确定"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        Log.Info("已点击浏览器证书选择框确定（任务未配置证书序列号，按默认选中证书）")
        return True

    # @step 遍历证书行，读取每行序列号（子格idx2）并匹配。
    import copy as _copy

    target_serial = str(expected_serial_no).strip()
    matched_row_index = None
    serial_numbers_read = []
    for row_index in range(1, 6):
        row_locator = {
            "wnd": [{"app": "chrome", "cls": "Chrome_WidgetWin_1", "title": "iGTB Net（企业网银） - Google Chrome"}],
            "ctrl": _copy.deepcopy(_CHROME_CERT_ROW_CTRL_PREFIX) + [
                {"cid": 50029, "cls": "AXVirtualView", "idx": row_index},
            ],
        }
        # 先读行内子格0（主题）判断该行是否存在；不存在说明证书行已遍历完。
        try:
            subject_text = UiElement.GetValue(
                dict(row_locator, ctrl=row_locator["ctrl"] + [{"cid": 50029, "cls": "AXVirtualView", "idx": 0}]),
                {"bContinueOnError": False, "iDelayAfter": 200, "iDelayBefore": 100},
            )
        # apa-lint: disable-next-line preserve-exception-traceback -- 主题格读取失败说明该行不存在（证书行已遍历完），按结束遍历处理。
        except Exception:
            break
        if str(subject_text).strip() == "":
            break
        # 读子格2（序列号）。
        try:
            serial_text = str(UiElement.GetValue(
                dict(row_locator, ctrl=row_locator["ctrl"] + [{"cid": 50029, "cls": "AXVirtualView", "idx": 2}]),
                {"bContinueOnError": False, "iDelayAfter": 200, "iDelayBefore": 100},
            )).strip()
        # apa-lint: disable-next-line preserve-exception-traceback -- 序列号格读取失败按空值处理，交由匹配判断兜底（无匹配时会抛出明确异常）。
        except Exception:
            serial_text = ""
        serial_numbers_read.append(serial_text)
        Log.Info("证书行{}：主题={}，序列号={}".format(row_index, str(subject_text)[:30], serial_text))
        if serial_text == target_serial:
            matched_row_index = row_index
            break

    if matched_row_index is None:
        message = "浏览器证书选择框中未找到与证书序列号{}匹配的证书，已读取的序列号：{}。请检查任务ukey_no配置或U盾是否正确插入。".format(
            target_serial,
            "、".join(serial_numbers_read) if serial_numbers_read else "（未读取到任何证书行）",
        )
        Log.Error(message)
        ebank.save_exception_screenshot("证书选择_未找到匹配证书")
        raise RuntimeError(message)

    # @step 点击匹配的证书行选中，再点确定提交。
    matched_row_locator = {
        "wnd": [{"app": "chrome", "cls": "Chrome_WidgetWin_1", "title": "iGTB Net（企业网银） - Google Chrome"}],
        "ctrl": _copy.deepcopy(_CHROME_CERT_ROW_CTRL_PREFIX) + [
            {"cid": 50029, "cls": "AXVirtualView", "idx": matched_row_index},
        ],
    }
    Mouse.Action(matched_row_locator, "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    Log.Info("证书序列号匹配成功，已点击选中第{}行证书".format(matched_row_index))
    Mouse.Action(Hover_ElementSelect("按钮_选择证书_确定"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    Log.Info("已确认匹配的浏览器证书")
    return True

# U盾证书密码弹窗特征（2026-09-24窗口监测实测）：U盾厂商安全控件进程
# WDUIServer_Watchdata BOC CSP v3.3 弹出的系统级模态对话框，类名#32770，
# 弹出期间独占焦点，其他软件不可点击；关闭后页面才继续刷新用户名。
_UKEY_PASSWORD_DIALOG_PROCESS = "WDUIServer_Watchdata BOC CSP v3.3"
_UKEY_PASSWORD_DIALOG_CLASS = "#32770"


def _ukey_password_dialog_exists() -> bool:
    """检测U盾证书密码弹窗当前是否在桌面上可见。

    通过 ctypes 枚举可见顶层窗口，按弹窗所属进程名和窗口类名匹配；
    该弹窗是系统级对话框，不属于网页DOM，不能用页面元素等待。
    注意：ctypes回调内抛出的异常不会传播到EnumWindows调用处，因此
    回调内只收集匹配结果，不在回调内raise。

    Returns:
        bool: U盾证书密码弹窗存在且可见时返回 ``True``。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    process_name = _UKEY_PASSWORD_DIALOG_PROCESS
    dialog_class = _UKEY_PASSWORD_DIALOG_CLASS
    matched_hwnds: list[int] = []

    def _enum_handler(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, class_name, 64)
        if class_name.value != dialog_class:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import subprocess
        try:
            task_output = subprocess.run(
                ["tasklist", "/FI", "PID eq {}".format(pid.value), "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        # apa-lint: disable-next-line preserve-exception-traceback -- 进程名查询失败时跳过该窗口继续枚举，不影响其余窗口判定。
        except Exception:
            return True
        if process_name.lower() in str(task_output).lower():
            matched_hwnds.append(hwnd)
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(callback(_enum_handler), 0)
    if matched_hwnds:
        Log.Debug("检测到U盾证书密码弹窗，hwnd={}".format(str(matched_hwnds)))
        return True
    return False


def _wait_ukey_password_dialog(
    timeout_seconds: int,
    expected_serial_no: str | None = None,
) -> bool:
    """等待U盾证书密码弹窗出现；期间按序列号确认浏览器顶部证书选择框。

    Args:
        timeout_seconds: 最长等待秒数。
        expected_serial_no: 任务提供的U盾证书序列号；传给证书框确认逻辑，
            None时按默认选中证书直接确定。

    Returns:
        bool: 弹窗出现返回 ``True``；超时未出现返回 ``False``。
    """
    import time as _time

    deadline = _time.time() + timeout_seconds
    while _time.time() < deadline:
        if _ukey_password_dialog_exists():
            return True
        if _confirm_browser_certificate_prompt(expected_serial_no):
            Log.Info("等待U盾密码弹窗期间已确认浏览器证书选择框")
        Delay(1000)
    return False


def _wait_ukey_password_dialog_closed(timeout_seconds: int) -> bool:
    """等待U盾证书密码弹窗关闭，确认密码提交已被安全控件处理。

    Args:
        timeout_seconds: 最长等待秒数。

    Returns:
        bool: 弹窗已消失返回 ``True``；超时仍存在返回 ``False``。
    """
    import time as _time

    deadline = _time.time() + timeout_seconds
    while _time.time() < deadline:
        if not _ukey_password_dialog_exists():
            return True
        Delay(1000)
    return not _ukey_password_dialog_exists()


def _enter_certificate_password(
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
    expected_cert_serial_no: str | None = None,
) -> bool:
    """在中国银行网银页面进入证书登录，并输入一次U盾证书密码。

    依次处理：数字证书登录入口、Windows安全证书选择框、浏览器证书选择框、
    证书密码输入框；证书密码只输入并提交一次。浏览器证书选择框按任务提供的
    证书序列号精确匹配（单证书也验证），无匹配时抛出异常终止本次登录。

    Args:
        password_input_device_info: 已校验的密码输入器连接信息和证书密码槽位。
        expected_cert_serial_no: 任务提供的U盾证书序列号；None时浏览器证书
            框按默认选中证书直接确定。

    Returns:
        bool: 证书密码已提交时为True；未进入证书登录阶段时为False。
    """
    device_number = password_input_device_info.device.device_number
    certificate_password_index = (
        password_input_device_info.device.certificate_password_index
    )

    # @step 等待并判断数字证书登录入口是否存在，存在则点击。
    certificate_login_entry_exists = ebank.wait_for_element(Hover_ElementSelect("块级元素<div>_数字证书登录"), 5, 1000)
    Log.Info("等待数字证书登录入口：{}".format(str(certificate_login_entry_exists)))
    if not certificate_login_entry_exists:
        return False

    Mouse.Action(Hover_ElementSelect("块级元素<div>_数字证书登录"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
    Log.Info("已点击数字证书登录")

    # @step 点击数字证书登录后等待Windows安全证书选择框出现并点击确定。
    # 弹窗出现时机不确定，最长轮询1分30秒（30次×3秒），每轮都尝试确认；
    # 期间顺带检查浏览器证书选择框，避免两个弹窗叠加遮挡。
    # U盾证书密码弹窗可能在本循环进行中提前弹出（时序竞态，2026-09-28实测）：
    # 该弹窗为系统级模态、独占焦点，网页元素判存和点击会被它卡住——因此每轮
    # 开头先用ctypes窗口检测（不受模态影响）判断弹窗是否已出现，出现立即跳出。
    for _cert_dialog_attempt in range(30):
        if _ukey_password_dialog_exists():
            Log.Info("补查循环中检测到U盾证书密码弹窗，跳出补查进入密码输入")
            break
        if _check_and_confirm_windows_cert_dialog(expected_cert_serial_no):
            break
        if _confirm_browser_certificate_prompt(expected_cert_serial_no):
            Log.Info("补查循环中已确认浏览器证书选择框")
        Delay(3000)
    Log.Info("数字证书登录后的Windows安全证书选择框确认状态：{}".format(str(_cert_dialog_confirmed)))

    # @step 等待U盾证书密码弹窗出现（系统级对话框，最长90秒）。
    # 弹窗由U盾安全控件进程弹出，不属于网页DOM；弹窗未出现前输入密码
    # 会落到错误目标。等待期间顺带确认浏览器顶部证书选择框。
    ukey_password_dialog_exists = _wait_ukey_password_dialog(90, expected_cert_serial_no)
    Log.Info("等待U盾证书密码弹窗：{}".format(str(ukey_password_dialog_exists)))
    if not ukey_password_dialog_exists:
        Log.Error("90秒内未出现U盾证书密码弹窗，本次登录停止")
        return False

    # @step 使用当前密码输入器向U盾证书密码弹窗输入一次证书密码。
    Log.Debug("[登录实现] 密码输入器编号={}".format(str(device_number)))
    Log.Debug("[登录实现] 证书密码索引={}".format(str(certificate_password_index)))
    # 安全约束：一次登录尝试只输入一次U盾证书密码。连续输错可能锁定U盾，
    # 未经用户明确允许，不得在这里增加循环或再次调用input_password。
    # 证书密码输入框弹出后固定等待3秒，确保输入框就绪后再开始输入密码。
    Delay(3000)
    ebank.input_password(password_input_device_info, "certificate", 600)
    Delay(1000)

    # @step 只提交一次证书密码：调用密码输入器模拟回车确认。
    # 安全约束：确认动作会真正校验U盾密码；提交后结果不明确时不得自动重试。
    try:
        ebank.press_key(password_input_device_info, "Enter", "press", [])
    # apa-lint: disable-next-line preserve-exception-traceback -- 确认动作异常时转换为明确的禁止重试错误，避免U盾被锁定。
    except Exception as error:
        raise RuntimeError(
            "U盾证书密码提交结果不明确，为避免锁定U盾，本次不得自动重试。"
        ) from error
    Log.Info("已提交证书密码")

    # @step 等待U盾证书密码弹窗关闭，确认密码已被安全控件处理。
    # 弹窗消失说明密码提交已被处理（正确或错误由后续页面状态判断）；
    # 超时仍存在说明提交未被接受，为避免重复输入锁定U盾，不再重试。
    ukey_password_dialog_closed = _wait_ukey_password_dialog_closed(60)
    Log.Info("U盾证书密码弹窗已关闭：{}".format(str(ukey_password_dialog_closed)))
    if not ukey_password_dialog_closed:
        raise RuntimeError(
            "U盾证书密码弹窗提交后未关闭，提交结果不明确，为避免锁定U盾，本次不得自动重试。"
        )

    # @step 证书密码提交后立马判断是否出现证书密码错误弹窗。
    # 弹窗出现时返回证书密码错误；未出现则等待后续用户名刷新。
    # 弹窗为WDUIServer安全控件的系统级模态窗（标题"校验USBKey密码"），
    # 2026-10-09实测：唯一按钮Button idx0（文本"确定"）即关闭按钮；
    # 点击确定关闭后页面才会继续，必须先关窗再返回，否则模态窗会卡住
    # 后续所有界面操作。
    certificate_password_error_exists = ebank.wait_for_element(Hover_ElementSelect("校验USBKey密码_密码错误提示窗"), 3, 1000)
    Log.Info("证书密码提交后判断是否出现证书密码错误弹窗：{}".format(str(certificate_password_error_exists)))
    if certificate_password_error_exists:
        Log.Error("U盾证书密码错误（安全控件弹窗校验USBKey密码）")
        try:
            Mouse.Action(Hover_ElementSelect("校验USBKey密码_确定按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
            Log.Info("已点击校验USBKey密码弹窗确定按钮，关闭密码错误提示")
        # apa-lint: disable-next-line preserve-exception-traceback -- 关闭错误弹窗失败不改变密码错误的判定结论，由外层登录控制统一处理。
        except Exception as close_error:
            Log.Warn("关闭证书密码错误弹窗失败，可能阻塞后续界面操作：{}".format(str(close_error)))
        return True

    # @step 证书密码提交后补查Windows安全证书选择框和浏览器顶部证书选择框。
    # 手动操作确认存在"证书密码提交后弹窗才出现"的顺序，两种证书选择框
    # （Windows安全桌面弹窗、浏览器顶部证书列表）都可能晚于提交数十秒出现；
    # 这里做最长1分30秒的轮询补查（30次×3秒），任一弹窗出现并确认即结束。
    # 若Windows安全证书框已确认、浏览器顶部证书框也未再出现，说明两类
    # 弹窗均已处理完，立即退出，避免空转占用等待时间。
    for _post_submit_attempt in range(30):
        if _cert_dialog_confirmed:
            browser_certificate_prompt_exists = ebank.wait_for_element(Hover_ElementSelect("分组_选择证书"), 1, 500)
            if not browser_certificate_prompt_exists:
                Log.Info("证书密码提交后两类证书选择框均已处理，跳过补查轮询")
                break
        if _check_and_confirm_windows_cert_dialog(expected_cert_serial_no):
            break
        if _confirm_browser_certificate_prompt(expected_cert_serial_no):
            Log.Info("证书密码提交后已确认浏览器顶部证书选择框")
            break
        Delay(3000)
    return True


def _connect_ukey_through_hub(
    hub: contract.HubConnectionModel,
    login_result: contract.LoginResultModel,
) -> bool:
    """通过当前HUB实现连接U盾，并登记成功后的清理动作。"""

    ip_address = hub.ip_address
    service_port = hub.port
    device_id = hub.device_id

    # @step 释放上一轮可能残留或被占用的U盾连接。
    try:
        result = ebank.disconnect_device(ip_address, service_port, device_id)
        Log.Debug(str(ebank.mask_sensitive(result)))
        vendor_result = contract.VendorResponseModel.model_validate(result)
        Log.Debug(str(ebank.mask_sensitive(vendor_result)))

        if vendor_result.code != 0 and vendor_result.code != 400:
            for disconnect_attempt in range(3):
                Delay(3000)
                vendor_result = contract.VendorResponseModel.model_validate(
                    ebank.disconnect_device(ip_address, service_port, device_id)
                )
                if vendor_result.code == 0:
                    Log.Info("{}断电成功".format(device_id))
                    break
                if disconnect_attempt == 2:
                    Delay(300000)
            result = ebank.power_off_device(ip_address, service_port, device_id)
            Log.Info("U盾似乎已在其他用户连接，调用强制断电接口：")
            Log.Debug(str(ebank.mask_sensitive(result)))
    # apa-lint: disable-next-line preserve-exception-traceback -- 查询连接状态失败时按遗留连接处理并执行强制下电恢复。
    except Exception:
        result = ebank.power_off_device(ip_address, service_port, device_id)
        Log.Info("U盾似乎已在其他用户连接，调用强制断电接口：")
        Log.Debug(str(ebank.mask_sensitive(result)))

    ebank.mark_ukey_released()

    # @step 连接U盾并确认厂商返回成功。
    result = ebank.connect_device(
        ip_address,
        service_port,
        device_id,
        hub.app_code,
        hub.app_key,
    )
    Log.Debug(str(ebank.mask_sensitive(result)))
    try:
        vendor_result = contract.VendorResponseModel.model_validate(result)
        Log.Debug(str(ebank.mask_sensitive(vendor_result)))
        if vendor_result.code != 0:
            raise RuntimeError("U盾连接失败。{}".format(str(result)))
    # apa-lint: disable-next-line preserve-exception-traceback -- HUB异常转换为标准登录失败结果，由登录重试框架统一处理。
    except Exception as error:
        message = "U盾连接失败。{}".format(str(error))
        Log.Error(message)
        login_result.code = 3
        login_result.message = message
        try:
            ebank.disconnect_device(ip_address, service_port, device_id)
        finally:
            ebank.power_off_device(ip_address, service_port, device_id)
        return False

    ebank.remember_ukey_connection(ip_address, service_port, device_id)
    return True


def _connect_password_input_device_through_hub(
    hub: contract.HubConnectionModel,
    login_result: contract.LoginResultModel,
) -> bool:
    """通过当前HUB实现连接密码输入器，并登记成功后的清理动作。"""

    ip_address = hub.ip_address
    service_port = hub.port
    device_id = hub.device_id

    # @step 断开密码输入器并等待设备端口可用。
    result = ebank.disconnect_device(ip_address, service_port, device_id)
    Log.Debug(str(ebank.mask_sensitive(result)))
    password_input_device_is_available = False
    for _status_attempt in range(101):
        result = ebank.query_device(ip_address, service_port, device_id)
        Log.Info("判断密码输入器是否为断开状态：{}".format(str(result)))
        result_data = contract.VendorResponseModel.model_validate(result)
        # 只判断完整ukId对应的唯一设备，其他记录或字段不能作为已断开的证据。
        device_status = contract.VendorResponseModel.model_validate(result_data)
        device_records = device_status.data.get("list") if isinstance(device_status.data, dict) else None
        matched_devices = [
            item for item in device_records
            if isinstance(item, dict) and item.get("ukId") == device_id
        ] if isinstance(device_records, list) else []
        if (device_status.code == 0 and len(matched_devices) == 1
                and matched_devices[0].get("currentState") in ("断开", "已断开")):
            password_input_device_is_available = True
            break
        Log.Info("密码输入器正在被占用，等待中...")
        Delay(3000)

    if not password_input_device_is_available:
        message = "密码输入器被其他机器占用中"
        Log.Warn(message)
        login_result.code = 3
        login_result.message = message
        return False

    # @step 连接密码输入器并确认厂商返回成功。
    result = ebank.connect_device(
        ip_address,
        service_port,
        device_id,
        hub.app_code,
        hub.app_key,
    )
    Log.Debug(str(ebank.mask_sensitive(result)))
    try:
        device_result = contract.VendorResponseModel.model_validate(result)
        if device_result.code != 0:
            raise RuntimeError("密码输入器连接失败。{}".format(str(result)))
    # apa-lint: disable-next-line preserve-exception-traceback -- 厂商返回值解析失败按密码输入器连接失败处理，错误文本已记录。
    except Exception as error:
        message = "密码输入器连接失败。{}".format(str(error))
        Log.Error(message)
        login_result.code = 3
        login_result.message = message
        try:
            ebank.disconnect_device(ip_address, service_port, device_id)
        finally:
            ebank.power_off_device(ip_address, service_port, device_id)
        return False

    ebank.remember_password_input_device_connection(
        ip_address,
        service_port,
        device_id,
    )
    return True


def login_with_ukey(
    ukey_info: contract.UkeyLoginInfoModel,
    password_input_device_info: contract.PasswordInputDeviceLoginInfoModel,
) -> contract.LoginResultModel:
    """网银系统 U 盾登录。

    连接 U 盾和键盒，启动网银助手和浏览器，完成证书密码输入，确认登录状态。

    Args:
        ukey_info: 已校验的U盾连接信息、可选网银用户名和银行助手路径。
        password_input_device_info: 已校验的密码输入器连接信息和密码槽位。

    Returns:
        LoginResultModel: 登录结果。0表示成功，1表示证书密码错误，2表示登录密码错误，
            3表示密码提交前的可重试错误，4表示密码已提交但结果不明确、不得重试。
    """
    assistant_path = ukey_info.login.assistant_path

    # 返回结果定义：0成功；1证书密码错误；2登录密码错误；3提交前错误；4提交后状态不明确。
    login_result = contract.LoginResultModel(code=-1, message="")

    # @step 连接本任务设备前，清理各CloudUSB客户端自己已连接的设备。
    # 同一地址和端口只清场一次，且全部清场发生在连接U盾之前，避免误断刚连接的U盾。
    if ebank.can_disconnect_all_devices():
        cleaned_hub_clients = set()
        for device_hub in (
            ukey_info.hub,
            password_input_device_info.hub if password_input_device_info is not None else None,
        ):
            if device_hub is None:
                continue
            client_address = (device_hub.ip_address, device_hub.port)
            if client_address in cleaned_hub_clients:
                continue
            cleaned_hub_clients.add(client_address)
            Log.Info("[登录前清场] 查询并断开CloudUSB客户端{}:{}自己已连接的全部设备".format(
                device_hub.ip_address, device_hub.port,
            ))
            cleanup_result = ebank.disconnect_all_devices(device_hub.ip_address, device_hub.port)
            if cleanup_result is not None and cleanup_result.code == 0:
                Log.Info("[登录前清场] 完成：{}".format(cleanup_result.msg))
            else:
                Log.Warn("[登录前清场] 未全部完成，按原设备连接流程继续：{}".format(
                    cleanup_result.msg if cleanup_result is not None else "当前HUB未执行清场",
                ))


    # @step 按每台设备的接入方式准备U盾和密码输入器。
    if ukey_info.hub is None:
        Log.Info("U盾直连本机，跳过HUB设备切换")
    else:
        Log.Info("通过当前HUB实现连接U盾")
        if not _connect_ukey_through_hub(ukey_info.hub, login_result):
            return login_result

    if password_input_device_info.hub is None:
        Log.Info("密码输入器无需HUB连接，跳过HUB设备切换")
    else:
        Log.Info("通过当前HUB实现连接密码输入器")
        if not _connect_password_input_device_through_hub(
            password_input_device_info.hub,
            login_result,
        ):
            return login_result

    Log.Info("U盾和密码输入器接入准备完成")

    # @step 启动网银助手并打开中国银行登录页面。
    _open_login_page(assistant_path)

    # @step 打开登录页后立即检查一次Windows安全证书选择框（可能在打开时就弹出）。
    global _cert_dialog_confirmed
    _cert_dialog_confirmed = False
    _check_and_confirm_windows_cert_dialog(ukey_info.ukey_number)

    # @step 进入证书登录并输入、确认U盾证书密码。
    password_was_submitted = _enter_certificate_password(
        password_input_device_info,
        ukey_info.ukey_number,
    )

    # @step 等待并判断用户名框是否已有用户名，有则输入登录密码并点击登录。
    username_filled = ebank.wait_for_element(Hover_ElementSelect("输入控件<input>_用户名"), 5, 1000)
    if not username_filled:
        message = "未进入登录密码输入阶段，也未识别到登录成功页面"
        login_result.code = 3
        login_result.message = message
        Log.Error(message)
        return login_result

    try:
        # 证书密码提交后页面需要时间刷新用户名。手动操作确认存在"证书
        # 密码提交后Windows安全证书选择框才出现"的顺序，弹窗可能晚数十秒，
        # 因此这里做长轮询（最长约2分钟）：每轮同时补查弹窗和读取用户名，
        # 弹窗被点掉后用户名才会刷新。
        username_value = None
        for _username_attempt in range(40):
            _check_and_confirm_windows_cert_dialog(ukey_info.ukey_number)
            username_value = UiElement.GetValue(Hover_ElementSelect("输入控件<input>_用户名"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
            if username_value is not None and str(username_value).strip() != "":
                break
            Delay(3000)
        Log.Info("用户名框当前值：{}".format(str(username_value)))
        if username_value is None or str(username_value).strip() == "":
            # 用户名始终为空：最后回头补查一次Windows安全证书选择框并再等一轮。
            Log.Warn("用户名为空，回头补查Windows安全证书选择框")
            _check_and_confirm_windows_cert_dialog(ukey_info.ukey_number)
            if _cert_dialog_confirmed:
                # 点击确定后重新轮询等待用户名刷新。
                for _username_retry_attempt in range(10):
                    username_value = UiElement.GetValue(Hover_ElementSelect("输入控件<input>_用户名"), {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
                    if username_value is not None and str(username_value).strip() != "":
                        break
                    Delay(3000)
                Log.Info("补查弹窗后用户名框当前值：{}".format(str(username_value)))
        if username_value is None or str(username_value).strip() == "":
            message = "用户名框没有用户名，本次登录停止"
            Log.Error(message)
            login_result.code = 3
            login_result.message = message
            return login_result

        # @step 校验页面回填的用户名与任务指定的期望用户名一致，防止U盾或任务不匹配。
        # 页面用户名由U盾证书验证后自动回填；期望值来自队列任务ukey_username字段。
        # 期望值未提供时（如农行证书登录不需要用户名）跳过校验继续登录。
        expected_username = ukey_info.login.username
        if expected_username is None or str(expected_username).strip() == "":
            Log.Warn("任务未提供期望用户名（ukey_username），跳过用户名校验")
        elif str(username_value).strip() != str(expected_username).strip():
            message = "用户名与任务不一致，页面={}, 期望={}，本次登录停止".format(
                str(username_value).strip(),
                str(expected_username).strip(),
            )
            Log.Error(message)
            login_result.code = 3
            login_result.message = message
            return login_result
        else:
            Log.Info("用户名校验通过：{}".format(str(username_value).strip()))

        # @step 输入登录密码前，最后等待并确认Windows安全证书选择框。
        # 弹窗可能晚于用户名刷新数十秒才出现，未确认前提交登录密码会被
        # 网银助手以"请先关闭所有浏览器窗口"拒绝；这里做最长1分30秒的
        # 专项等待（30次×3秒），弹窗一旦确认即继续。且不再重新点击数字
        # 证书登录——重复发起握手会被网银助手判定会话冲突，反而毁掉已
        # 就绪的会话。若1分30秒内弹窗始终未出现，记录告警后仍继续输密码。
        for _pre_login_dialog_attempt in range(30):
            if _cert_dialog_confirmed:
                break
            if _check_and_confirm_windows_cert_dialog(ukey_info.ukey_number):
                break
            Delay(3000)
        if not _cert_dialog_confirmed:
            Log.Warn("输入登录密码前1分30秒内未出现Windows安全证书选择框，继续尝试输入登录密码")
        Delay(2000)

        # @step 点击登录密码输入框聚焦，再使用密码输入器输入登录密码并点击登录。
        # 安全约束：登录密码一次登录尝试只输入一次。
        Mouse.Action(Hover_ElementSelect("输入控件<input>登录密码输入框"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        Log.Info("已点击登录密码输入框聚焦")
        ebank.input_password(password_input_device_info, "login", 600)
        Delay(1000)
        Mouse.Action(Hover_ElementSelect("按钮<button>_登录"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
        Log.Info("已输入登录密码并点击登录")

        # @step 点击登录后立马判断是否出现登录密码错误弹窗。
        # 该弹窗内容节点（bfe-message-box__content）是通用消息框且页面上会残留
        # 隐藏副本：元素Exists为True、文本也残留，但真实弹窗显示前节点宽高为0。
        # 因此判定弹窗必须同时满足：元素存在 + GetRect宽高大于0（真实可见）。
        login_password_error_dialog_visible = False
        for _error_dialog_attempt in range(3):
            login_password_error_exists = ebank.wait_for_element(Hover_ElementSelect("块级元素<div>_用户名或密码无效，请输入正确的用户名和密码！"), 1, 500)
            if not login_password_error_exists:
                break
            try:
                _dialog_rect = UiElement.GetRect(Hover_ElementSelect("块级元素<div>_用户名或密码无效，请输入正确的用户名和密码！"), "screen", {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200})
                _rect_dict = dict(_dialog_rect) if _dialog_rect else {}
                _rect_width = int(_rect_dict.get("width", 0) or 0)
                _rect_height = int(_rect_dict.get("height", 0) or 0)
            # apa-lint: disable-next-line preserve-exception-traceback -- 读取弹窗区域失败时按不可见处理，避免误判密码错误。
            except Exception:
                _rect_width = 0
                _rect_height = 0
            Log.Info("登录后消息弹窗存在={}，宽={}，高={}".format(str(login_password_error_exists), str(_rect_width), str(_rect_height)))
            if _rect_width > 0 and _rect_height > 0:
                login_password_error_dialog_visible = True
                break
            Delay(1000)
        if login_password_error_dialog_visible:
            dialog_text = ""
            try:
                dialog_text = str(UiElement.GetAttribute(Hover_ElementSelect("块级元素<div>_用户名或密码无效，请输入正确的用户名和密码！"), "innerText", {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200}))
            # apa-lint: disable-next-line preserve-exception-traceback -- 读取弹窗文本失败时按空文本处理，仅影响弹窗类型识别，不阻断登录判断。
            except Exception:
                Log.Warn("[登录] 读取登录后消息弹窗文本失败，按非密码错误弹窗处理")
            Log.Info("登录后消息弹窗文本：{}".format(str(dialog_text)))
            # 无论何种消息弹窗，都先点击确定关闭，避免弹窗阻断后续页面操作。
            try:
                Mouse.Action(Hover_ElementSelect("按钮<button>_确定2-登录密码错误提示框"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
                Log.Info("已点击消息弹窗确定按钮")
            # apa-lint: disable-next-line preserve-exception-traceback -- 弹窗确定按钮点击失败不阻断，继续按弹窗文本判断登录结果。
            except Exception:
                Log.Warn("[登录] 消息弹窗确定按钮点击失败，继续按弹窗文本判断")
            if "用户名或密码无效" in dialog_text:
                message = "网银登录密码错误"
                Log.Error(message)
                login_result.code = 2
                login_result.message = message
                return login_result
            # 其他消息弹窗（如"请先关闭所有浏览器窗口再重新打开"等提示）
            # 不属于密码错误，记录文本后继续走登录成功判断。
            Log.Warn("[登录] 登录后出现非密码错误消息弹窗：{}".format(str(dialog_text)))
    # apa-lint: disable-next-line preserve-exception-traceback -- 登录密码已提交后的检查异常必须转为禁止重试的登录结果，避免密码被重复提交。
    except Exception as error:
        message = "登录密码提交过程出现异常：{}".format(str(error))
        Log.Error(message)
        login_result.code = 4
        login_result.message = message
        login_result.root_location = ebank.extract_root_location(error)
        return login_result

    try:
        # @step 判断是否出现证书密码错误提示。
        Log.Info("判断是否出现证书密码错误")
        # 弹窗为WDUIServer安全控件的系统级模态窗（标题"校验USBKey密码"），
        # 元素已于2026-10-09入库；点击弹窗内唯一确定按钮（Button idx0）关闭。
        certificate_password_error_exists = ebank.wait_for_element(Hover_ElementSelect("校验USBKey密码_密码错误提示窗"), 3, 1000)
        Log.Info("判断是否出现证书密码错误：{}".format(str(certificate_password_error_exists)))
        if certificate_password_error_exists:
            try:
                Mouse.Action(Hover_ElementSelect("校验USBKey密码_确定按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
                Log.Info("已点击校验USBKey密码弹窗确定按钮，关闭密码错误提示")
            # apa-lint: disable-next-line preserve-exception-traceback -- 关闭错误弹窗失败不改变密码错误的判定结论，登录结果已定为code=1。
            except Exception as close_error:
                Log.Warn("关闭证书密码错误弹窗失败，可能阻塞后续界面操作：{}".format(str(close_error)))
            message = "U盾证书密码错误"
            Log.Error(message)
            login_result.code = 1
            login_result.message = message
            return login_result

        # @step 识别是否登录成功：标志是「欢迎进入中国银行网上银行」元素存在。
        Log.Info("判断是否登录成功")
        login_succeeded = ebank.wait_for_element(Hover_ElementSelect("块级元素<div>_欢迎进入中国银行网上银行"), 5, 1000)
        Log.Info("判断是否登录成功：{}".format(str(login_succeeded)))
        if login_succeeded:
            # @step 登录成功后判断是否出现通知公告弹窗；存在则勾选不再提示并关闭。
            announcement_dialog_exists = ebank.wait_for_element(Hover_ElementSelect("网银登录_通知公告弹窗"), 3, 1000)
            Log.Info("登录成功后判断是否出现通知公告弹窗：{}".format(str(announcement_dialog_exists)))
            if announcement_dialog_exists:
                try:
                    Mouse.Action(Hover_ElementSelect("网银登录_通知公告不再提示"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
                    Log.Info("已勾选通知公告不再提示")
                    Delay(500)
                    Mouse.Action(Hover_ElementSelect("网银登录_通知公告关闭按钮"), "left", "click", 10000, {"bContinueOnError": False, "iDelayAfter": 300, "iDelayBefore": 200, "bSetForeground": True, "sCursorPosition": "Center", "iCursorOffsetX": 0, "iCursorOffsetY": 0, "sKeyModifiers": [], "sSimulate": "simulate", "bMoveSmoothly": False})
                    Log.Info("已关闭通知公告弹窗")
                # apa-lint: disable-next-line preserve-exception-traceback -- 通知公告弹窗处理失败不影响登录成功的判定结果，仅记录告警。
                except Exception as announcement_error:
                    Log.Warn("[登录] 通知公告弹窗处理失败，不影响登录成功：{}".format(str(announcement_error)))
            Log.Info("登录成功")
            login_result.code = 0
            login_result.message = "登录成功"
            return login_result
    # apa-lint: disable-next-line preserve-exception-traceback -- 密码已提交后的检查异常必须转为禁止重试的登录结果，避免U盾被锁定。
    except Exception as error:
        if password_was_submitted:
            message = "密码已提交，但登录结果检查失败：{}".format(str(error))
            Log.Error(message)
            login_result.code = 4
            login_result.message = message
            login_result.root_location = ebank.extract_root_location(error)
            return login_result
        raise

    if password_was_submitted:
        # 密码已提交但没有出现密码错误弹窗，也没有出现登录成功标志。
        # 该情况不属于证书密码错误（1）或登录密码错误（2），按普通登录
        # 失败处理，由框架_登录判断按LoginRetryNum继续完整登录重试。
        message = "密码已提交，但未识别到登录成功或已知的密码错误提示"
        login_result.code = 3
    else:
        message = "未进入U盾证书密码提交阶段，也未识别到登录成功页面"
        login_result.code = 3
    Log.Error(message)
    login_result.message = message
    return login_result


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """执行中行企业网银登录，并把登录结果写回参数字典。

    Args:
        argument: 本次登录参数，必须包含：

            - ``ukey``：U盾、可选HUB、可选网银用户名和银行助手信息。
            - ``password_input_device``：密码输入器连接信息和密码槽位。

            执行完成后写入 ``result``，包含登录状态码和说明。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        KeyError: 缺少 ``ukey`` 或 ``password_input_device``。
        Exception: 设备连接、密码输入或页面操作出现未处理异常。
    """
    # @step 校验U盾和密码输入器登录参数。
    login_argument = contract.parse_login_argument(argument)
    if login_argument.password_input_device is None:
        raise RuntimeError(
            "当前中行登录需要密码输入器，请在配置_运行方案.py中调用"
            "ebank.use_password_input_device(...)并提供匹配的任务参数。"
        )

    # @step 执行中行企业网银登录。
    try:
        result = login_with_ukey(
            login_argument.ukey,
            login_argument.password_input_device,
        )
        argument["result"] = result.model_dump(mode="python")
    # apa-lint: disable-next-line preserve-exception-traceback -- 登录异常时先释放密码输入器并附加清理信息后原样重抛，保留原始traceback。
    except Exception as error:
        cleanup_errors = ebank.release_password_input_device(argument)
        for cleanup_error in cleanup_errors:
            error.add_note("密码输入器清理失败：{}".format(str(cleanup_error)))
        raise

    # @step 释放登录阶段使用的密码输入器。
    cleanup_errors = ebank.release_password_input_device(argument)
    if cleanup_errors:
        raise RuntimeError(
            "登录处理已经结束，但密码输入器清理失败：{}".format(str(cleanup_errors))
        )
    # @step 确认登录实现已经返回结果。
    if contract.parse_login_argument(argument).result is None:
        raise RuntimeError("登录实现没有返回result。")
    return argument


# def __UNIT_TEST_FUNCTION__(argument):
#     """为单独运行登录流程块准备真实上下文。
#
#     按主链真实路径执行任务接入和环境初始化，从队列拉取一条真实任务，
#     组装登录参数后调用main执行真实登录。
#     """
#     import 配置_运行方案
#     import 接入_任务数据
#     import 框架_环境初始化
#     import 框架_登录判断
#
#     # @step 执行运行方案注册模块并建立类型化状态。
#     配置_运行方案.main({})
#
#     # @step 按真实链路读取队列任务并初始化环境。
#     接入_任务数据.main({})
#     框架_环境初始化.main({})
#
#     # @step 用真实任务构造登录参数并执行登录。
#     state = GlobalVariables["ebank"]
#     login_argument = 框架_登录判断._build_login_argument(
#         state.task,
#         state.source_task,
#     )
#     return main(login_argument.model_dump(mode="python"))
