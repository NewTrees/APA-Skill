"""网银流程的数据契约与运行时校验。

本文件负责说明“数据应该长什么样”，并把稳定的配置、任务和运行状态
转换为 Pydantic 模型。流程块通过 ``对象.字段`` 读取数据；字段写错、类型
不正确或运行中写入非法值时，会尽早报出容易定位的错误。

新增稳定的银行字段或外部配置字段时，优先在这里补充契约。新增业务如果能用
统一业务上下文和结果表达，则不修改本文件。不要在各流程块中重复编写零散的
``isinstance``。
"""

from __future__ import annotations

from apa_runtime import *
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


NonEmptyText = Annotated[str, Field(min_length=1)]
PortNumber = Annotated[int, Field(ge=1, le=65535)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]


class ContractModel(BaseModel):
    """所有网银数据契约的共同配置。

    框架内部模型禁止未知字段，能够及时发现字段名拼错。外部数据模型通过
    ``ExternalContractModel`` 单独允许上游新增字段。
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class ExternalContractModel(ContractModel):
    """允许上游增加模板暂时不使用字段的外部数据契约。"""

    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


# ==================== 外部运行配置 ====================


class BaseConfigModel(ExternalContractModel):
    """Asset配置中的 ``Base`` 段。"""

    apps_name: list[NonEmptyText] = Field(
        alias="AppsName",
        min_length=1,
        description="流程启动、重试或结束时需要关闭的相关进程名称列表。",
    )
    certificate_password_retry_num: NonNegativeInt = Field(
        default=0,
        alias="CertificatePasswordRetryNum",
        description=(
            "U盾证书密码错误后允许自动重试的次数，不包含首次提交；"
            "大于2时强制定为2，小于等于2时按设置走；"
            "省略或设为0表示只提交一次，密码错误后不再重试。"
        ),
    )
    login_password_retry_num: NonNegativeInt = Field(
        alias="LoginPasswordRetryNum",
        description="网银登录密码错误后允许自动重试的次数，不包含首次提交。",
    )
    login_retry_num: NonNegativeInt = Field(
        alias="LoginRetryNum",
        description="一次任务中允许重新执行完整登录动作的次数，不包含首次执行。",
    )
    max_retry_num: NonNegativeInt = Field(
        alias="MaxRetryNum",
        description="整个网银任务发生业务异常后允许重试整轮流程的次数，不包含首次执行。",
    )
    log_level: str | int | None = Field(
        default=None,
        alias="LogLevel",
        description="APA正式运行阶段的日志级别；未配置时使用运行方案中的默认级别。",
    )
    exception_screenshots_folder_path: NonEmptyText | None = Field(
        default=None,
        alias="ExScreenshotsFolderPath",
        description=(
            "异常截图的自定义目录；配置时截图直接保存到该目录，"
            "未配置时使用 Output/银行名称/日期/异常截图 默认层级。"
        ),
    )
    xts_config_path: NonEmptyText | None = Field(
        default=None,
        alias="XTSConfigPath",
        description="保存HUB应用编码和应用密钥的XTS Excel配置文件路径；设备直连且未启用HUB时可以省略。",
    )
    output_folder: NonEmptyText = Field(
        alias="OutputFolder",
        description="任务保存银行原始文件、转换文件和汇总文件的基础目录。",
    )
    transaction_convert_enabled: bool | None = Field(
        default=None,
        alias="TransactionConvertEnabled",
        description="是否启用流水数据转换；未启用流水数据转换时可以省略。",
    )
    template_file: NonEmptyText | None = Field(
        default=None,
        alias="TemplateFile",
        description="流水转换模板覆盖路径；省略时由交付模块使用项目内置模板。",
    )
    field_map_path: NonEmptyText | None = Field(
        default=None,
        alias="FieldMapPath",
        description="字段映射覆盖路径；省略时由交付模块使用项目内置映射。",
    )
    all_data_table_template_file: NonEmptyText | None = Field(
        default=None,
        alias="AllDataTableTemplateFile",
        description="执行结果汇总模板路径；省略时使用项目内置执行汇总模板。",
    )


class AssetSetConfigModel(ExternalContractModel):
    """Asset配置中的 ``Set`` 段，包含邮件、数据库及XTS鉴权信息。"""

    smtp_account: NonEmptyText | None = Field(
        default=None,
        alias="SMTPAccount",
        description="异常通知邮件使用的发件邮箱账号；未启用邮件收尾时可以省略。",
    )
    smtp_password: str | None = Field(
        default=None,
        alias="SMTPPassword",
        description="异常通知邮件使用的发件邮箱密码或授权码；未启用邮件收尾时可以省略。",
    )
    smtp_server: NonEmptyText | None = Field(
        default=None,
        alias="SMTPServer",
        description="异常通知邮件使用的SMTP服务器地址；未启用邮件收尾时可以省略。",
    )
    smtp_port: PortNumber | None = Field(
        default=None,
        alias="SMTPPort",
        description="异常通知邮件使用的SMTP服务器端口；未启用邮件收尾时可以省略。",
    )
    mysql_ip: NonEmptyText | None = Field(
        default=None,
        alias="MySQLIp",
        description="保存网银账户配置和任务状态的MySQL服务器地址；未启用数据库收尾时可以省略。",
    )
    mysql_port: PortNumber | None = Field(
        default=None,
        alias="MySQLPort",
        description="MySQL服务器端口；未启用数据库收尾时可以省略。",
    )
    mysql_database: NonEmptyText | None = Field(
        default=None,
        alias="MySQLDatabase",
        description="网银账户配置所在的MySQL数据库名称；未启用数据库收尾时可以省略。",
    )
    mysql_table: NonEmptyText | None = Field(
        default=None,
        alias="MySQLTable",
        description="网银账户配置和运行状态所在的数据表名称；未启用数据库收尾时可以省略。",
    )
    mysql_user: NonEmptyText | None = Field(
        default=None,
        alias="MySQLUser",
        description="连接网银配置数据库使用的用户名；未启用数据库收尾时可以省略。",
    )
    mysql_password: str | None = Field(
        default=None,
        alias="MySQLPassword",
        description="连接网银配置数据库使用的密码；未启用数据库收尾时可以省略。",
    )
    xts_app_key: str | None = Field(
        default=None,
        alias="XTSAppKey",
        description="HUB接口鉴权使用的应用密钥；读取Asset时可以为空，合并XTS Excel后必须有值。",
    )
    xts_code: str | None = Field(
        default=None,
        alias="XTSCode",
        description="HUB接口识别当前应用使用的应用编码；读取Asset时可以为空，合并XTS Excel后必须有值。",
    )


class UserConfigModel(ExternalContractModel):
    """Asset配置中的 ``User`` 段。"""

    mail_receiver: NonEmptyText | None = Field(
        default=None,
        alias="MailReceiver",
        description="异常通知邮件的主要收件人地址；未启用邮件收尾时可以省略。",
    )
    mail_title: str | None = Field(
        default=None,
        alias="MailTitle",
        description="异常通知邮件的自定义标题；为空时由收尾模块生成标题。",
    )
    mail_content: str | None = Field(
        default=None,
        alias="MailContent",
        description="异常通知邮件的自定义正文；为空时由收尾模块生成正文。",
    )
    mail_cc: str | list[str] | None = Field(
        default=None,
        alias="MailCC",
        description="异常通知邮件的抄送地址，可以是一个地址、地址列表或空值。",
    )


class AssetConfigModel(ExternalContractModel):
    """Asset ``EbankConfig`` 的完整结构。"""

    base: BaseConfigModel = Field(alias="Base", description="业务、登录、重试、日志、输出目录和模板覆盖等基础配置。")
    settings: AssetSetConfigModel = Field(alias="Set", description="邮件、数据库和XTS鉴权相关的系统配置。")
    user: UserConfigModel = Field(alias="User", description="通知收件人和邮件内容等用户配置。")


class RetryLimitsModel(ContractModel):
    """流程各阶段允许重试的次数；所有次数都不包含首次执行。"""

    workflow: NonNegativeInt = Field(description="整个网银任务发生业务异常后允许重试的次数，不包含首次执行。")
    login: NonNegativeInt = Field(description="完整登录失败后允许重试的次数，不包含首次执行。")
    certificate_password: NonNegativeInt = Field(
        default=0,
        description="U盾证书密码错误后允许自动重试的次数，不包含首次提交。大于2时强制定为2，小于等于2时按设置走；省略或设为0表示只提交一次，密码错误后不再重试。",
    )
    login_password: NonNegativeInt = Field(description="网银登录密码错误后允许重试的次数，不包含首次提交。")


class DatabaseConfigModel(ContractModel):
    """网银任务状态数据库的连接信息。"""

    host: NonEmptyText = Field(description="保存网银账户配置和任务状态的MySQL服务器地址。")
    port: PortNumber = Field(description="MySQL服务器端口，范围为1到65535。")
    database: NonEmptyText = Field(description="网银账户配置所在的MySQL数据库名称。")
    table: NonEmptyText = Field(description="网银账户配置和运行状态所在的数据表名称。")
    username: NonEmptyText = Field(description="连接网银配置数据库使用的用户名。")
    password: str = Field(description="连接网银配置数据库使用的密码。")


class HubConfigModel(ContractModel):
    """HUB接口鉴权和配置文件信息。"""

    config_file: NonEmptyText = Field(description="保存HUB应用编码和密钥的XTS Excel配置文件路径。")
    app_code: NonEmptyText = Field(description="调用HUB接口时使用的应用编码。")
    app_key: NonEmptyText = Field(description="调用HUB接口时使用的应用鉴权密钥。")


class OutputFoldersModel(ContractModel):
    """流程输出文件使用的基础目录。"""

    business: NonEmptyText = Field(description="任务保存银行原始文件、转换文件和汇总文件的基础目录。")
    screenshots: NonEmptyText | None = Field(
        default=None,
        description="异常截图的自定义目录；未配置时使用默认层级 Output/银行名称/日期/异常截图。",
    )


class ConvertTemplateFilesModel(ContractModel):
    """流水数据转换使用的模板和字段映射。"""

    enabled: bool = Field(default=True, description="当前运行方案是否启用流水数据转换。")
    transaction: NonEmptyText | None = Field(default=None, description="流水转换模板覆盖路径；为空时由交付模块使用项目内置模板。")
    field_map: NonEmptyText | None = Field(default=None, description="字段映射覆盖路径；为空时由交付模块使用项目内置映射。")


class SummaryTemplateFilesModel(ContractModel):
    """平台可选提供的执行结果汇总模板。"""

    summary: NonEmptyText | None = Field(default=None, description="执行结果汇总模板路径；为空时使用项目默认模板。")


class MailConfigModel(ContractModel):
    """流程异常通知邮件的连接和收件信息。"""

    server: NonEmptyText = Field(description="异常通知邮件使用的SMTP服务器地址。")
    port: PortNumber = Field(description="SMTP服务器端口，范围为1到65535。")
    account: NonEmptyText = Field(description="异常通知邮件使用的发件邮箱账号。")
    password: str = Field(description="异常通知邮件使用的发件邮箱密码或授权码。")
    receiver: NonEmptyText = Field(description="异常通知邮件的主要收件人地址。")
    title: str | None = Field(default=None, description="异常通知邮件的自定义标题；为空时由收尾模块生成。")
    content: str | None = Field(default=None, description="异常通知邮件的自定义正文；为空时由收尾模块生成。")
    cc: str | list[str] | None = Field(default=None, description="异常通知邮件的抄送地址，可以是一个地址、地址列表或空值。")


class RuntimeConfigModel(ContractModel):
    """供流程内部使用、按照业务含义整理后的运行配置。"""

    related_apps: list[NonEmptyText] = Field(min_length=1, description="重试或结束流程时需要关闭的相关进程名称列表。")
    retry: RetryLimitsModel = Field(description="整轮流程、登录和密码允许的重试次数。")
    database: DatabaseConfigModel | None = Field(default=None, description="网银任务状态数据库连接信息；未启用数据库收尾时为空。")
    hub: HubConfigModel | None = Field(default=None, description="HUB配置文件和接口鉴权信息；运行方案未启用HUB时为空。")
    output: OutputFoldersModel = Field(description="业务产物和异常截图的基础输出目录。")
    convert_templates: ConvertTemplateFilesModel = Field(default_factory=ConvertTemplateFilesModel, description="流水转换开关及模板覆盖配置；未提供路径时由交付模块回退到项目资源。")
    summary_templates: SummaryTemplateFilesModel = Field(description="执行结果汇总模板配置；路径为空时使用项目内置执行汇总模板。")

    mail: MailConfigModel | None = Field(default=None, description="异常通知邮件配置；未启用邮件收尾时为空。")
    log_level: str | int | None = Field(description="Asset配置中的日志级别；未配置时使用运行方案默认级别。")


class XtsSetConfigModel(ExternalContractModel):
    """XTS Excel配置中的 ``Set`` 段。"""

    xts_app_key: NonEmptyText = Field(alias="XTSAppKey", description="XTS Excel中记录的HUB接口应用密钥。")
    xts_code: NonEmptyText = Field(alias="XTSCode", description="XTS Excel中记录的HUB接口应用编码。")


class XtsConfigModel(ExternalContractModel):
    """从XTS Excel读取出的配置。"""

    settings: XtsSetConfigModel = Field(alias="Set", description="XTS Excel的Set工作表中读取出的HUB鉴权配置。")


# ==================== 队列原始任务 ====================


class SourceAccountModel(ExternalContractModel):
    """队列任务中的一个银行子账号。"""

    bank_account: NonEmptyText = Field(description="需要执行网银业务的银行子账号。")
    account_name: NonEmptyText = Field(description="银行子账号对应的账户名称。")
    open_bank_name: NonEmptyText = Field(description="银行子账号的开户银行或开户网点名称。")
    open_unit: str | None = Field(
        default=None,
        description="银行子账号所属的开户单位；外部系统未提供时可以省略。",
    )
    keeper: str | None = Field(
        default=None,
        description="负责保管或维护该账户的人员名称；未配置时可以省略。",
    )
    start_date: NonEmptyText = Field(description="当前账号本轮查询的开始日期。")
    end_date: NonEmptyText = Field(description="当前账号本轮查询的结束日期。")


class SourceTaskModel(ExternalContractModel):
    """DataQueue返回的网银任务。

    字段别名保持外部系统现有命名。模型导回字典后仍使用 ``EnableConvertTemplate``、
    ``BusinessType`` 等原字段，不要求现有流程块同步改名。
    """

    task_id: str | int = Field(alias="id", description="外部队列任务的唯一编号，用于日志、汇总和结果回传。")
    process_name: NonEmptyText = Field(description="Commander或上游系统分配的流程名称。")
    worker_name: NonEmptyText = Field(description="执行当前任务的Worker或机器人名称。")
    enable_convert_template: bool = Field(
        default=False,
        alias="EnableConvertTemplate",
        description="任务级开关，是否启用流水模板转换功能；默认关闭。",
    )
    business_types: list[PositiveInt] = Field(
        alias="BusinessType",
        min_length=1,
        description=(
            "本次任务需要执行的业务编号列表；当前模板内置编号1到4分别表示流水、余额、回单和对账单。"
            "新增业务可以使用其他正整数，具体编号和实现以配置_运行方案.py中的use_business注册为准。"
        ),
    )
    ukey_number: NonEmptyText = Field(alias="ukey_no", description="当前任务使用的银行U盾业务编号。")
    ukey_ip_address: NonEmptyText | None = Field(
        default=None,
        alias="ukey_ip",
        description="U盾所在HUB服务的IP地址或主机名；U盾直连本机时可以省略。",
    )
    ukey_service_port: PortNumber | None = Field(
        default=None,
        alias="ukey_port",
        description="U盾所在HUB服务的访问端口；U盾直连本机时可以省略。",
    )
    ukey_device_id: NonEmptyText | None = Field(
        default=None,
        alias="ukey_hub_port",
        description="U盾在HUB中的设备端口或设备标识；U盾直连本机时可以省略。",
    )
    password_input_device_number: str | int | None = Field(
        default=None,
        alias="keybox_no",
        description=(
            "密码输入器实现识别的设备编号；外部队列字段名保持为keybox_no。"
            "未启用密码输入器时可以省略。"
        ),
    )
    password_input_device_ip_address: NonEmptyText | None = Field(
        default=None,
        alias="keybox_ip",
        description="密码输入器所在服务的IP地址或主机名；不通过厂商HUB连接时可以省略。",
    )
    password_input_device_service_port: PortNumber | None = Field(
        default=None,
        alias="keybox_port",
        description="密码输入器所在服务的访问端口；不通过厂商HUB连接时可以省略。",
    )
    password_input_device_id: NonEmptyText | None = Field(
        default=None,
        alias="keybox_hub_port",
        description="密码输入器在厂商HUB中的设备标识；不通过厂商HUB连接时可以省略。",
    )
    login_password_index: NonNegativeInt | None = Field(
        default=None,
        alias="login_pwd_keybox_group",
        description=(
            "密码输入器中保存网银登录密码的受控槽位编号；当前农行K宝证书登录"
            "只使用证书密码，不使用该字段，可以省略。只有登录实现需要输入"
            "网银登录密码时才提供。"
        ),
    )
    certificate_password_index: NonNegativeInt | None = Field(
        default=None,
        alias="cert_pwd_keybox_group",
        description="密码输入器中保存U盾证书密码的受控槽位编号；未启用密码输入器时可以省略。",
    )
    ukey_username: NonEmptyText | None = Field(
        default=None,
        description=(
            "登录银行企业网银时使用的用户名；当前农行K宝证书登录不使用该字段，"
            "可以省略。只有所选登录实现明确需要用户名时才提供。"
        ),
    )
    accounts: list[SourceAccountModel] = Field(
        min_length=1,
        description="本次任务需要依次处理的银行子账号列表。",
    )

    @model_validator(mode="after")
    def validate_account_dates(self) -> SourceTaskModel:
        """校验每个账号都提供了查询日期。"""

        for index, account in enumerate(self.accounts):
            for field_name in ("start_date", "end_date"):
                value = getattr(account, field_name)
                if value is None or str(value).strip() == "":
                    raise ValueError(
                        "accounts[{}].{}不能为空。".format(index, field_name)
                    )
        return self


# ==================== 框架标准任务 ====================


class HubConnectionModel(ContractModel):
    """一台设备通过HUB接入当前执行机所需的连接信息。"""

    ip_address: NonEmptyText = Field(description="HUB厂商服务的IP地址或主机名。")
    port: PortNumber = Field(description="HUB厂商服务端口，范围为1到65535。")
    device_id: NonEmptyText = Field(description="设备在HUB上的端口或设备标识，可以是U盾或密码输入器编号。")
    app_code: NonEmptyText = Field(description="调用HUB接口时使用的应用编码。")
    app_key: NonEmptyText = Field(description="调用HUB接口时使用的应用鉴权密钥。")


class UkeyDeviceModel(ContractModel):
    """标准任务中的U盾及其可选HUB连接信息。"""

    ukey_number: NonEmptyText = Field(description="上游业务系统分配的U盾编号，用于日志和任务结果关联。")
    hub: HubConnectionModel | None = Field(default=None, description="U盾通过HUB接入时使用的连接信息；直连本机时为空。")
    connection_status: NonEmptyText = Field(description="U盾当前连接状态，例如未连接、已连接或已断开。")


class PasswordInputDeviceModel(ContractModel):
    """标准任务中的密码输入器及其可选HUB连接信息。"""

    device_number: str | int = Field(description="密码输入器编号，由具体实现或厂商服务识别。")
    hub: HubConnectionModel | None = Field(default=None, description="密码输入器通过HUB接入时使用的连接信息；无需HUB时为空。")
    login_password_index: NonNegativeInt | None = Field(
        default=None,
        description=(
            "密码输入器中保存网银登录密码的受控槽位编号；当前农行K宝证书登录"
            "不使用该槽位，可以为空。需要输入网银登录密码的实现应在执行时校验。"
        ),
    )
    certificate_password_index: NonNegativeInt = Field(description="密码输入器中保存U盾证书密码的受控槽位编号。")
    connection_status: NonEmptyText = Field(description="密码输入器当前连接或可用状态。")


class DevicesModel(ContractModel):
    """标准任务使用的设备。"""

    ukey: UkeyDeviceModel = Field(description="当前任务使用的银行U盾及其HUB连接信息。")
    password_input_device: PasswordInputDeviceModel | None = Field(
        default=None,
        description="当前任务使用的密码输入器及其连接和密码槽位信息；未启用密码输入器时为空。",
    )


class LoginStateModel(ContractModel):
    """登录阶段状态。"""

    status: NonEmptyText = Field(description="登录阶段状态，例如未登录、登录中、成功或失败。")
    is_logged_in: bool = Field(description="当前浏览器会话是否已经成功登录企业网银。")
    error_message: str = Field(description="最近一次登录失败的原因；没有错误时为空字符串。")
    login_time: str = Field(description="成功登录的时间文本；尚未登录时为空字符串。")
    ever_logged_in: bool = Field(default=False, description="本次任务任意一轮是否曾经登录成功；用于区分“从未登录成功”和“曾成功后重试轮登录失败”。")
    rounds_logged_in: NonNegativeInt = Field(default=0, description="本次任务累计登录成功的轮次数。")
    retry_count: NonNegativeInt = Field(description="当前任务已经执行过的登录重试次数。")
    browser_handle: Any = Field(default=None, description="登录后可复用的浏览器对象或窗口句柄；不需要时为空。")
    login_retry_limit: NonNegativeInt = Field(description="完整登录失败后允许重试的次数，不包含首次执行。")
    certificate_password_retry_limit: NonNegativeInt = Field(description="U盾证书密码错误后允许重试的次数，不包含首次提交。")
    login_password_retry_limit: NonNegativeInt = Field(description="网银登录密码错误后允许重试的次数，不包含首次提交。")


class TaskOutputModel(ContractModel):
    """当前任务实际生成和使用的输出路径。"""

    business_folder: NonEmptyText = Field(description="当前任务保存业务文件的实际目录。")
    summary_file: str = Field(description="当前任务汇总Excel的完整路径；尚未生成时为空字符串。")
    screenshots_folder: NonEmptyText = Field(description="当前任务保存异常截图的实际目录。")


class QueryDatesModel(ContractModel):
    """单个账号本轮查询的日期范围。"""

    start_date: NonEmptyText = Field(description="当前账号本轮查询使用的开始日期文本。")
    end_date: NonEmptyText = Field(description="当前账号本轮查询使用的结束日期文本。")


class BusinessOutputModel(ContractModel):
    """一项网银业务产生的文件或文件夹。"""

    output_type: Literal["file", "folder"] = Field(description="产物类型：file表示单个文件，folder表示包含一组文件的目录。")
    category: NonEmptyText = Field(description="产物的业务类别，例如流水、回单或对账单，供交付和汇总模块选择。")
    path: NonEmptyText = Field(description="产物的完整路径。文件产物填写文件路径，目录产物填写目录路径。")
    name: NonEmptyText = Field(description="便于流程开发人员识别的产物名称，通常是文件名或目录名。")


class BusinessValueModel(ContractModel):
    """一项网银业务返回的可展示数值或文本。"""

    name: NonEmptyText = Field(description="结果名称，例如可用余额、冻结金额或查询状态。")
    value: str = Field(description="银行页面或接口返回的结果值，保留业务需要的文本格式。")
    unit: str = Field(default="", description="结果单位，例如元；结果没有单位时为空字符串。")


class BusinessResultModel(ContractModel):
    """所有可插拔网银业务返回给框架的统一结果。"""

    code: int = Field(description="业务结果码：0表示成功，2表示没有数据，其他值表示失败。")
    message: str = Field(default="", description="业务执行说明或失败原因。")
    outputs: list[BusinessOutputModel] = Field(default_factory=list, description="业务生成的文件或目录；业务没有产物时为空列表。")
    values: list[BusinessValueModel] = Field(default_factory=list, description="业务返回的余额等可展示值；业务没有数值结果时为空列表。")

    def first_output(self, category: str | None = None) -> BusinessOutputModel | None:
        """取得第一个产物；指定类别时只返回该类别的第一个产物。"""

        for output in self.outputs:
            if category is None or output.category == category:
                return output
        return None

    def get_value(self, name: str) -> str:
        """按名称读取结果值；未返回该值时得到空字符串。"""

        for item in self.values:
            if item.name == name:
                return item.value
        return ""


class BusinessExecutionModel(ContractModel):
    """一个账号的一项已启用业务及其执行状态。"""

    business_type: PositiveInt = Field(description="上游任务和运行方案共同约定的业务编号。")
    business_name: NonEmptyText = Field(description="根据业务模块文件名生成的中文业务名称，供日志和汇总展示。")
    status: Literal["pending", "processing", "success", "no_data", "failed", "skipped"] = Field(default="pending", description="该业务当前的执行状态。")
    error_code: int = Field(default=-1, description="业务返回码；0表示成功，2表示没有数据，其他值表示失败或尚未执行。")
    error_message: str = Field(default="", description="业务失败原因；没有错误时为空字符串。")
    start_time: str | None = Field(default=None, description="该业务开始执行的时间；尚未执行时为空。")
    end_time: str | None = Field(default=None, description="该业务结束执行的时间；尚未结束时为空。")
    duration_seconds: int | float = Field(default=0, description="该业务本轮执行耗时，单位为秒。")
    attempt_count: NonNegativeInt = Field(default=0, description="该业务针对当前账号已经执行的总次数，包含首次执行。")
    skip_reason: str = Field(default="", description="业务被跳过的原因；未跳过时为空字符串。")
    result: BusinessResultModel | None = Field(default=None, description="业务模块本轮返回的类型化结果；尚未执行或异常中断时为空。")


class TransactionConvertStateModel(ContractModel):
    """单个账号的流水数据转换状态。"""

    status: NonEmptyText = Field(description="当前账号的流水数据转换状态。")
    error_message: str = Field(description="流水数据转换失败原因；没有错误时为空字符串。")
    converted_file_path: str = Field(description="流水数据转换后生成的文件完整路径；尚未转换时为空字符串。")
    record_count: NonNegativeInt = Field(description="本次转换后的数据记录数；尚未转换时为0。")
    skip_reason: str = Field(description="流水数据转换被跳过的原因；未跳过时为空字符串。")


class AccountDeliveryModel(ContractModel):
    """一个账号的交付处理状态。"""

    transaction_convert: TransactionConvertStateModel = Field(description="当前账号流水数据转换的状态。")


class AccountInfoModel(ContractModel):
    """帮助流程开发人员识别银行账号的基本信息。"""

    account_id: str | int = Field(description="上游提供的账号记录编号；没有独立编号时可使用列表序号。")
    bank_account: NonEmptyText = Field(description="需要执行网银业务的银行账号。")
    account_name: NonEmptyText = Field(description="银行账号对应的账户名称。")
    open_bank_name: NonEmptyText = Field(description="银行账号的开户银行或开户网点名称。")
    open_unit: str | None = Field(description="银行账号所属开户单位；上游未提供时可以为空。")
    keeper: str | None = Field(description="负责保管或维护该账号的人员名称；未配置时可以为空。")


class ExecutionLogEntryModel(ContractModel):
    """标准账号的一条结构化执行记录。"""

    timestamp: str = Field(description="事件发生时间；尚未取得时间时允许为空字符串。")
    stage: NonEmptyText = Field(description="事件所属阶段，例如login、balance或convert_transaction。")
    status: NonEmptyText = Field(description="事件执行状态，例如processing、success或failed。")
    detail: str = Field(default="", description="供流程开发人员阅读的事件说明。")
    action: str | None = Field(default=None, description="阶段内更细的动作名称；不需要区分时可以为空。")
    error_message: str = Field(default="", description="事件失败原因；没有错误时为空字符串。")
    duration_seconds: int | float = Field(default=0, description="该事件记录的执行耗时，单位为秒。")
    output_file_path: str = Field(default="", description="该事件生成或上传的文件路径；没有文件时为空字符串。")
    record_count: NonNegativeInt = Field(default=0, description="该事件处理的数据记录数；不涉及记录数量时为0。")


class StandardAccountModel(ContractModel):
    """框架标准任务中的一个账号。"""

    index: NonNegativeInt = Field(description="账号在本次任务列表中的序号，从0开始。")
    info: AccountInfoModel = Field(description="账号编号、账户名称、开户行和保管人等基本信息。")
    query_dates: QueryDatesModel = Field(description="当前账号本轮实际采用的查询日期范围。")
    status: NonEmptyText = Field(description="当前账号汇总后的总体执行状态，例如待处理、成功、部分成功或失败。")
    error_message: str = Field(description="当前账号汇总后的失败原因；没有错误时为空字符串。")
    businesses: list[BusinessExecutionModel] = Field(description="当前账号按任务要求启用的业务及其执行状态。")
    delivery: AccountDeliveryModel = Field(description="账号产物的转换和外部系统交付状态。")
    execution_log: list[ExecutionLogEntryModel] = Field(description="当前账号执行过程中的结构化事件列表。")

    @model_validator(mode="after")
    def validate_unique_business_types(self) -> StandardAccountModel:
        """同一个账号不能重复登记同一业务编号。"""

        business_types = [business.business_type for business in self.businesses]
        if len(business_types) != len(set(business_types)):
            raise ValueError("同一个账号不能重复登记相同的业务编号")
        return self

    def get_business(self, business_type: int) -> BusinessExecutionModel | None:
        """按业务编号取得执行状态；账号未启用该业务时返回空。"""

        for business in self.businesses:
            if business.business_type == business_type:
                return business
        return None

    def require_business(self, business_type: int) -> BusinessExecutionModel:
        """按业务编号取得执行状态；账号未启用时给出明确错误。"""

        business = self.get_business(business_type)
        if business is None:
            raise ValueError("账号{}未启用业务{}。".format(self.info.bank_account, business_type))
        return business


class StandardTaskModel(ContractModel):
    """框架提供给登录、业务、交付和收尾模块的标准任务。"""

    task_id: str | int = Field(description="沿用外部队列任务编号，关联本次执行的日志和结果。")
    bank_name: NonEmptyText = Field(description="当前任务所属的银行名称。")
    process_name: NonEmptyText = Field(description="上游分配的流程名称。")
    worker_name: NonEmptyText = Field(description="执行当前任务的Worker或机器人名称。")
    enable_convert_template: bool = Field(description="任务级开关，是否启用流水模板转换功能。")
    business_types: list[int] = Field(min_length=1, description="当前任务实际启用的业务编号列表。")
    start_time: NonEmptyText = Field(description="本次流程开始执行的时间文本。")
    status: NonEmptyText = Field(description="当前任务的总体运行状态，例如处理中、成功或失败。")
    devices: DevicesModel = Field(description="本次任务使用的U盾和密码输入器信息。")
    login: LoginStateModel = Field(description="本次任务的登录状态和登录重试限制。")
    output: TaskOutputModel = Field(description="当前任务实际使用的业务、汇总和截图输出路径。")
    accounts: list[StandardAccountModel] = Field(min_length=1, description="本次任务需要依次处理的标准银行账号列表。")


# ==================== 跨流程块状态与可插拔模块 ====================


class RunStateModel(ContractModel):
    """框架重试和异常状态。"""

    retry_count: NonNegativeInt = Field(default=0, description="当前任务已经进入的整轮重试次数，首次执行为0。")
    max_retry_count: NonNegativeInt = Field(default=1, description="当前任务允许重试整轮流程的次数，不包含首次执行。")
    has_error: bool = Field(default=False, description="登录或业务主链是否出现尚未处理的错误。")
    has_delivery_error: bool = Field(default=False, description="产物上传或结果回传阶段是否出现错误。")
    error_message: str = Field(default="", description="最近一次需要框架处理的错误信息；无错误时为空字符串。")


class LoggingStateModel(ContractModel):
    """流程日志级别策略。"""

    default_level: str = Field(default="2", pattern="^[0-4]$", description="外部配置没有有效日志级别时使用的APA日志级别，允许0到4。")
    use_external_level: bool = Field(default=True, description="是否优先使用Asset配置中的日志级别。")
    current_level: str = Field(default="3", pattern="^[0-4]$", description="当前已经应用到APA运行时的日志级别，允许0到4。")


class DeviceActionDataModel(ContractModel):
    """USB设备生命周期动作使用的连接信息。"""

    ip_address: NonEmptyText = Field(description="设备所在HUB服务的IP地址或主机名。")
    port: str | int = Field(description="设备所在HUB服务端口。")
    device_id: NonEmptyText = Field(description="USB设备在HUB上的端口或设备标识。")


class AppsActionDataModel(ContractModel):
    """相关进程清理动作使用的数据。"""

    app_names: list[NonEmptyText] = Field(description="最终清理或重试前需要关闭的进程名称列表。")


LifecycleActionName = Literal["U-Key设备", "密码输入器", "相关进程", "网银会话"]


class LifecycleActionModel(ContractModel):
    """一个已经进入、尚未退出的生命周期动作。"""

    owner: NonEmptyText = Field(description="登记该动作的模块或能力名称。")
    name: LifecycleActionName = Field(description="退出时用于选择清理方式的动作名称。")
    data: DeviceActionDataModel | AppsActionDataModel | LogoutArgumentModel = Field(description="执行对应退出动作需要的类型化参数。")


class FrameworkStateModel(ContractModel):
    """公共框架维护的生命周期和收尾状态。"""

    active_actions: list[LifecycleActionModel] = Field(default_factory=list, description="已经进入且尚未退出的生命周期动作，最终按逆序释放。")
    current_business: str | None = Field(default=None, description="当前正在执行的业务模块名；没有业务运行时为空。")
    finished: bool = Field(default=False, description="正常或异常最终收尾是否已经执行，避免重复收尾。")
    cleanup_errors: list[str] = Field(default_factory=list, description="最近一次资源清理过程中发生的补充错误文本。")


class BusinessModuleStateModel(ContractModel):
    """一个可插拔业务模块的运行状态。"""

    status: Literal["idle", "running", "completed", "failed"] = Field(default="idle", description="业务模块当前所处的运行阶段。")


class EbankStateModel(ContractModel):
    """存放在 ``GlobalVariables['ebank']`` 中的统一运行对象。

    配置、任务、日志策略、生命周期动作和业务运行状态全部使用Pydantic模型。
    只有APA固定的 ``main(argument)`` 边界和外部JSON边界短暂使用普通字典。
    """

    bank_name: str = Field(default="", description="当前模板运行的银行名称，由运行方案流程块设置。")
    assistant_path: str = Field(default="", description="当前银行网银助手程序的完整路径，由运行方案流程块设置；登录实现按需读取。")
    config: RuntimeConfigModel | None = Field(default=None, description="合并Asset和XTS后供所有流程块读取的运行配置；接入前为空。")
    source_task: SourceTaskModel | None = Field(default=None, description="从任务队列取得并校验后的原始任务；接入前为空。")
    task: StandardTaskModel | None = Field(default=None, description="环境初始化生成并在登录、业务、交付和收尾阶段持续更新的标准任务；初始化前为空。")
    run: RunStateModel = Field(default_factory=RunStateModel, description="框架统一维护的整轮重试和异常状态。")
    logging: LoggingStateModel = Field(default_factory=LoggingStateModel, description="流程启动和正式运行阶段使用的日志级别策略。")
    framework: FrameworkStateModel = Field(default_factory=FrameworkStateModel, description="公共框架维护的生命周期动作、当前业务和收尾状态。")
    business: dict[str, BusinessModuleStateModel] = Field(default_factory=dict, description="按模块名称保存的可插拔业务运行状态。")


class LoginInfoModel(ContractModel):
    """网银登录界面需要的用户信息。"""

    username: NonEmptyText | None = Field(
        default=None,
        description=(
            "登录企业网银时填写的用户名；当前农行K宝证书登录不使用该字段，"
            "可以为空。需要账号登录的实现应在执行时明确校验。"
        ),
    )
    assistant_path: NonEmptyText = Field(description="银行网银助手程序的完整路径。")


class PasswordInputDeviceInfoModel(ContractModel):
    """密码输入器编号、密码槽位和输入参数。"""

    device_number: str | int = Field(description="具体实现或厂商服务识别的密码输入器编号。")
    login_password_index: NonNegativeInt | None = Field(
        default=None,
        description=(
            "密码输入器中保存网银登录密码的受控槽位编号；当前农行K宝证书登录"
            "不使用该槽位，可以为空。调用login密码输入时必须提供。"
        ),
    )
    certificate_password_index: NonNegativeInt = Field(description="密码输入器中保存U盾证书密码的受控槽位编号。")
    press_delay_ms: NonNegativeInt = Field(default=0, description="密码输入器发送按键前的等待时间，单位为毫秒；未配置时为0。")
    key_interval_ms: NonNegativeInt = Field(default=0, description="密码输入器连续输入字符或密码时相邻按键间隔，单位为毫秒；未配置时为0。")


class UkeyLoginInfoModel(ContractModel):
    """登录实现收到的U盾、可选用户名和银行助手信息。"""

    hub: HubConnectionModel | None = Field(default=None, description="登录时用于连接银行U盾的HUB信息；U盾直连本机时为空。")
    login: LoginInfoModel = Field(description="可选网银登录用户名和银行助手程序路径。")
    ukey_number: NonEmptyText = Field(description="用于证书选择窗口匹配证书序列号的U盾业务编号。")


class PasswordInputDeviceLoginInfoModel(ContractModel):
    """登录实现收到的密码输入器连接和密码槽位信息。"""

    hub: HubConnectionModel | None = Field(default=None, description="输入密码时用于连接密码输入器所在HUB的信息；当前实现不需要HUB时为空。")
    device: PasswordInputDeviceInfoModel = Field(description="密码输入器编号及登录密码、证书密码槽位。")


class LoginResultModel(ContractModel):
    """任何登录实现都必须返回的结果。"""

    code: int = Field(
        description=(
            "登录结果码；0表示成功，1表示U盾证书密码错误，2表示网银登录密码错误，"
            "3表示密码提交前的可重试错误，4表示U盾证书密码已提交但结果不明确、不得自动重试。"
        )
    )
    message: str = Field(description="登录结果说明或失败原因。")
    root_location: str = Field(
        default="",
        description=(
            "登录失败的根因位置，格式为“（位置：文件名 第N行）”；"
            "由登录实现从原始异常traceback提取并写入，供登录框架拼接进最终报错，"
            "纯业务判断类失败（无异常对象）时为空。"
        ),
    )


class LoginArgumentModel(ContractModel):
    """登录实现的统一 ``main(argument)`` 参数。"""

    ukey: UkeyLoginInfoModel = Field(description="银行U盾连接信息、可选网银用户名和助手程序路径。")
    password_input_device: PasswordInputDeviceLoginInfoModel | None = Field(
        default=None,
        description="密码输入器连接信息以及密码槽位；所选登录实现不使用密码输入器时为空。",
    )
    result: LoginResultModel | None = Field(default=None, description="登录模块执行后写入的结果；调用前可以为空。")


class LogoutArgumentModel(ContractModel):
    """安全退出实现的统一 ``main(argument)`` 参数。"""

    result: bool | None = Field(default=None, description="页面安全退出结果；调用前为空，执行后为成功或失败。")


class OperationResultModel(ContractModel):
    """查询、下载等业务内部动作的统一中间结果。

    它只用于业务模块内部传递状态，不会直接上传到外部系统。最终返回给框架时，
    仍应转换为对应业务的正式结果模型。
    """

    code: int = Field(description="内部动作结果码；0表示成功，1表示失败，2表示没有可处理的数据，-1表示尚未得到明确结果。")
    message: str = Field(default="", description="内部动作执行说明或失败原因。")
    file_path: str = Field(default="", description="下载动作生成的文件完整路径；查询动作或失败时为空字符串。")
    record_count: NonNegativeInt = Field(default=0, description="查询动作从页面结果列表统计的数据条数；查询失败或列表为空时为0。")


class VendorResponseModel(ExternalContractModel):
    """HUB或密码输入器厂商接口返回的通用JSON结构。"""

    code: int = Field(description="厂商接口结果码；具体成功值由对应厂商实现解释。")
    msg: str = Field(default="", description="厂商接口返回的说明或失败原因。")
    data: Any = Field(default=None, description="厂商接口返回的附加数据；接口不返回数据时可以为空。")


class VendorTokenSeedModel(ExternalContractModel):
    """厂商令牌接口返回的随机种子。"""

    data: Any = Field(description="与应用密钥组合生成一次性访问令牌的厂商随机种子。")
    code: int | None = Field(default=None, description="厂商可选的结果码；该令牌接口没有返回结果码时为空。")
    msg: str = Field(default="", description="厂商可选的执行说明或失败原因。")


class TransactionConvertResultModel(ContractModel):
    """流水数据转换函数的统一返回结构。"""

    code: int = Field(description="流水数据转换结果码；0表示成功，其他值表示失败。")
    message: str = Field(default="", description="流水数据转换执行说明或失败原因。")
    file_path: str = Field(default="", description="文件转换成功后生成的文件完整路径；其他操作或失败时为空字符串。")
    record_count: NonNegativeInt = Field(default=0, description="转换结果包含的数据条数；不涉及数据条数时为0。")


class BusinessArgumentModel(ContractModel):
    """框架传给任意可插拔网银业务的统一上下文。"""

    business_type: PositiveInt = Field(description="当前正在执行的业务编号。")
    business_name: NonEmptyText = Field(description="当前业务模块的中文名称，供业务日志和错误信息使用。")
    account: AccountInfoModel = Field(description="当前需要处理的银行账号基本信息。")
    query_dates: QueryDatesModel = Field(description="当前账号本轮查询采用的日期范围。")
    ukey_number: NonEmptyText = Field(description="当前任务使用的U盾编号，用于业务查询和产物命名。")
    output_folder: NonEmptyText = Field(description="当前任务业务产物的根目录；业务模块自行决定下级目录和文件名。")


def _format_validation_error(data_name: str, error: ValidationError) -> str:
    """生成不包含密码原值、且流程开发人员容易定位的错误信息。"""

    details: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "根节点"
        details.append("{}：{}".format(location, item.get("msg", "字段无效")))
    return "{}不符合数据契约：\n- {}".format(data_name, "\n- ".join(details))


def _validate_model(
    model_type: type[ContractModel],
    value: Mapping[str, Any] | ContractModel,
    data_name: str,
) -> ContractModel:
    """把外部字典或已有模型转换为指定的数据契约模型。"""

    try:
        return model_type.model_validate(value)
    except ValidationError as error:
        raise ValueError(_format_validation_error(data_name, error)) from error


def create_ebank_state() -> EbankStateModel:
    """创建一份新的跨流程块运行状态。"""

    return EbankStateModel()


def parse_asset_config(value: Mapping[str, Any] | AssetConfigModel) -> AssetConfigModel:
    """读取并校验尚未合并XTS信息的Asset配置。"""

    return AssetConfigModel.model_validate(_validate_model(AssetConfigModel, value, "EbankConfig"))


def parse_xts_config(value: Mapping[str, Any] | XtsConfigModel) -> XtsConfigModel:
    """读取并校验从XTS Excel取得的HUB鉴权配置。"""

    return XtsConfigModel.model_validate(_validate_model(XtsConfigModel, value, "XTS配置"))


RequiredConfigValue = TypeVar("RequiredConfigValue")


def _required_config_value(
    value: RequiredConfigValue | None,
    field_name: str,
) -> RequiredConfigValue:
    """取得已确认存在的配置值，并为运行时和静态检查保留同一层保护。"""

    if value is None:
        raise ValueError("配置字段{}不能为空。".format(field_name))
    return value


def build_runtime_config(
    asset: AssetConfigModel,
    xts: XtsConfigModel | None = None,
) -> RuntimeConfigModel:
    """把外部Asset和可选XTS配置整理为流程内部容易理解的语义结构。"""

    base = asset.base
    settings = asset.settings
    user = asset.user
    database = None
    if all(
        value is not None
        for value in (
            settings.mysql_ip,
            settings.mysql_port,
            settings.mysql_database,
            settings.mysql_table,
            settings.mysql_user,
            settings.mysql_password,
        )
    ):
        database = DatabaseConfigModel(
            host=_required_config_value(settings.mysql_ip, "Set.MysqlIp"),
            port=_required_config_value(settings.mysql_port, "Set.MysqlPort"),
            database=_required_config_value(settings.mysql_database, "Set.MysqlDatabase"),
            table=_required_config_value(settings.mysql_table, "Set.MysqlTable"),
            username=_required_config_value(settings.mysql_user, "Set.MysqlUser"),
            password=_required_config_value(settings.mysql_password, "Set.MysqlPassword"),
        )

    convert_templates = ConvertTemplateFilesModel(
        enabled=base.transaction_convert_enabled is not False,
        transaction=base.template_file,
        field_map=base.field_map_path,
    )

    summary_templates = SummaryTemplateFilesModel(
        summary=base.all_data_table_template_file,
    )

    mail = None
    if all(
        value is not None
        for value in (
            settings.smtp_server,
            settings.smtp_port,
            settings.smtp_account,
            settings.smtp_password,
            user.mail_receiver,
        )
    ):
        mail = MailConfigModel(
            server=_required_config_value(settings.smtp_server, "Set.SMTPServer"),
            port=_required_config_value(settings.smtp_port, "Set.SMTPPort"),
            account=_required_config_value(settings.smtp_account, "Set.SMTPAccount"),
            password=_required_config_value(settings.smtp_password, "Set.SMTPPassword"),
            receiver=_required_config_value(user.mail_receiver, "User.MailReceiver"),
            title=user.mail_title,
            content=user.mail_content,
            cc=user.mail_cc,
        )

    hub = None
    if xts is not None:
        hub = HubConfigModel(
            config_file=_required_config_value(
                base.xts_config_path,
                "Base.XTSConfigPath",
            ),
            app_code=xts.settings.xts_code,
            app_key=xts.settings.xts_app_key,
        )

    return RuntimeConfigModel(
        related_apps=base.apps_name,
        retry=RetryLimitsModel(
            workflow=base.max_retry_num,
            login=base.login_retry_num,
            certificate_password=base.certificate_password_retry_num if base.certificate_password_retry_num <= 2 else 2,
            login_password=base.login_password_retry_num,
        ),
        database=database,
        hub=hub,
        output=OutputFoldersModel(
            business=base.output_folder,
            screenshots=base.exception_screenshots_folder_path,
        ),
        convert_templates=convert_templates,
        summary_templates=summary_templates,
        mail=mail,
        log_level=base.log_level,
    )


ConfigSectionModel = TypeVar("ConfigSectionModel", bound=ContractModel)


def require_config_section(
    section: ConfigSectionModel | None,
    section_name: str,
) -> ConfigSectionModel:
    """取得可插拔模块需要的配置段；未配置时给出明确错误。

    Args:
        section: ``RuntimeConfigModel`` 中可能为空的配置段。
        section_name: 面向流程开发人员展示的配置名称，例如“异常邮件”。

    Returns:
        ConfigSectionModel: 已存在且已经通过Pydantic校验的配置对象。

    Raises:
        RuntimeError: 当前项目启用了对应模块，但外部配置没有提供完整字段。
    """

    if section is None:
        raise RuntimeError(
            "当前运行方案启用了{}，但外部配置没有提供完整的{}配置。".format(
                section_name,
                section_name,
            )
        )
    return section


def parse_runtime_config(value: Mapping[str, Any] | RuntimeConfigModel) -> RuntimeConfigModel:
    """读取并校验已经补齐XTS信息的完整运行配置。"""

    return RuntimeConfigModel.model_validate(_validate_model(RuntimeConfigModel, value, "网银运行配置"))


def parse_source_task(value: Mapping[str, Any] | SourceTaskModel) -> SourceTaskModel:
    """读取并校验任务队列返回的原始任务。"""

    return SourceTaskModel.model_validate(_validate_model(SourceTaskModel, value, "队列任务"))


def parse_standard_task(value: Mapping[str, Any] | StandardTaskModel) -> StandardTaskModel:
    """读取并校验供登录、业务、交付和收尾使用的标准任务。"""

    return StandardTaskModel.model_validate(_validate_model(StandardTaskModel, value, "标准任务"))


def parse_run_state(value: Mapping[str, Any] | RunStateModel) -> RunStateModel:
    """读取并校验框架的整轮重试和异常状态。"""

    return RunStateModel.model_validate(_validate_model(RunStateModel, value, "运行状态"))


def parse_login_argument(value: Mapping[str, Any] | LoginArgumentModel) -> LoginArgumentModel:
    """读取并校验登录模块的完整参数。"""

    return LoginArgumentModel.model_validate(_validate_model(LoginArgumentModel, value, "登录模块参数"))


def parse_logout_argument(value: Mapping[str, Any] | LogoutArgumentModel) -> LogoutArgumentModel:
    """读取并校验安全退出模块的完整参数。"""

    return LogoutArgumentModel.model_validate(_validate_model(LogoutArgumentModel, value, "安全退出模块参数"))


def parse_password_input_device_info(
    value: Mapping[str, Any] | PasswordInputDeviceLoginInfoModel,
) -> PasswordInputDeviceLoginInfoModel:
    """读取并校验密码输入器共同使用的连接信息和密码槽位。"""

    return PasswordInputDeviceLoginInfoModel.model_validate(
        _validate_model(PasswordInputDeviceLoginInfoModel, value, "密码输入器参数")
    )


def parse_business_argument(
    business_type: int,
    argument: Mapping[str, Any] | BusinessArgumentModel,
) -> BusinessArgumentModel:
    """把任意已注册业务的输入转换为统一上下文，并核对业务编号。"""

    context = BusinessArgumentModel.model_validate(
        _validate_model(BusinessArgumentModel, argument, "业务{}参数".format(business_type))
    )
    if context.business_type != business_type:
        raise ValueError(
            "调用的业务编号{}与参数中的业务编号{}不一致。".format(
                business_type,
                context.business_type,
            )
        )
    return context


def parse_business_module_result(
    business_type: int,
    argument: Mapping[str, Any],
) -> BusinessResultModel:
    """从任意业务模块的入口字典中取得统一结果。"""

    if "business_result" not in argument:
        raise ValueError(
            "业务{}结果不符合数据契约：缺少 business_result。".format(business_type)
        )
    return BusinessResultModel.model_validate(
        _validate_model(
            BusinessResultModel,
            argument["business_result"],
            "业务{}结果".format(business_type),
        )
    )


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """保留数据契约在流程图中的维护入口。

    数据契约由其他模块调用具名校验函数，本入口不执行校验，也不应连接主流程。

    Args:
        argument: 当前流程参数字典，本入口不会读取或修改其中内容。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    return argument
