from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank

import HUB_新同事
import 密码输入器_KeyBox
import 会话_登录
import 会话_网银安全退出
import 业务_流水查询和下载
import 业务_余额查询
import 业务_回单查询和下载
import 业务_对账单查询和下载
import 交付_流水数据转换
import 收尾_执行结果汇总
import 收尾_密码错误处置
import 收尾_异常邮件通知


# 当前模板对应的银行名称。新建其他银行模板时修改这里即可。
BANK_NAME = "中国银行"

# 当前银行网银助手程序的完整路径。银行没有助手程序时改为空字符串，
# 由登录实现在需要时校验；路径按目标机器实际安装位置调整。
ASSISTANT_PATH = r"C:\Program Files (x86)\BOCBank\EBankingAssistant\BOCAssistant.exe"

# 外部Asset没有提供有效日志级别时使用。0=错误、1=警告、2=信息、
# 3=调试、4=调试及TracePrint跟踪。
DEFAULT_LOG_LEVEL = "2"

# True表示优先使用Asset配置中的Base.LogLevel；False表示始终使用上面的默认值。
USE_EXTERNAL_LOG_LEVEL = True

def main(argument: dict[str, Any]) -> dict[str, Any]:
    """配置当前项目使用的网银实现模块和日志策略。

    这是流程开发人员和Agent调整运行方案的主要入口。选择设备厂商、替换
    登录页面、增删业务、改变交付方式或增加收尾动作时，只修改本文件中的
    显式 ``use_*`` 调用；不要为此修改 ``框架_*`` 文件。

    Args:
        argument: 流程块之间传递的共享字典。本步骤不要求包含特定键。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    # @step 设置开发期日志级别。
    # 必须是本流程入口的第一条可执行语句。外部配置尚未读取时先启用
    # Debug，确保模块选择或任务接入失败仍能留下排障信息。
    Log.SetLevel("3")

    # @step 清除上次调试留下的模块选择。
    # 重复执行本流程块时，已经删除的 use_* 配置不会继续残留。
    ebank.unuse_all()

    # @step 设置银行名称、助手路径和运行期日志策略。
    # 公共入口会在首次调用时自动建立类型化运行状态，不需要额外的初始化块。
    ebank.set_bank_name(BANK_NAME)
    ebank.set_assistant_path(ASSISTANT_PATH)

    ebank.configure_logging(
        default_level=DEFAULT_LOG_LEVEL,
        use_external_level=USE_EXTERNAL_LOG_LEVEL,
    )

    # @step 选择可选HUB、密码输入器和网银会话实现。
    # 设备通过HUB接入时选择一个HUB实现；全部直连本机时删除下面的
    # use_hub调用及对应import，框架会跳过HUB配置、连接和清理。
    ebank.use_hub(HUB_新同事)
    ebank.use_password_input_device(密码输入器_KeyBox)
    ebank.use_login(会话_登录)
    ebank.use_logout(会话_网银安全退出)

    # @step 注册当前项目启用的网银业务。
    # 业务能力按任务中的BusinessType动态调用，可按项目需要增删。
    ebank.use_business(1, 业务_流水查询和下载)
    ebank.use_business(2, 业务_余额查询)
    ebank.use_business(3, 业务_回单查询和下载)
    ebank.use_business(4, 业务_对账单查询和下载)

    # @step 选择交付方式。
    # 默认注册流水转换，由任务EnableConvertTemplate决定是否执行；多个交付按顺序执行。
    ebank.use_delivery([
        交付_流水数据转换,  # 将流水文件转换为指定模板格式。
    ])

    # @step 选择正常和异常结束后的处理动作。
    # 默认启用执行汇总、密码错误处置和异常邮件；按项目需求移除不需要的注册及导入。
    ebank.use_finish_handlers(
        success=[
            收尾_执行结果汇总,  # 正常结束时生成执行结果汇总文件。
        ],
        failure=[
            收尾_执行结果汇总,  # 失败时也生成结果汇总文件。
            收尾_密码错误处置,  # 密码错误时停用相关U盾，避免连续输错锁定。
            收尾_异常邮件通知,  # 失败时发送异常通知邮件。
        ],
    )

    Log.Info("[运行配置] 网银实现模块已注册")
    Log.Debug("[运行配置] 银行={}".format(BANK_NAME))
    return argument
