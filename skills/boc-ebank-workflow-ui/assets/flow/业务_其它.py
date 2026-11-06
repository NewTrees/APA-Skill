from apa_runtime import *
from typing import Any

import 公共_数据契约 as contract


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """作为新增网银业务的最小示例，当前默认不启用。

    流程开发人员可以复制本文件并改为具体业务名称，在这里完成页面操作，
    然后统一写回 ``business_result``。业务没有文件或数值产物也可以成功，
    无需为了接入框架修改公共数据契约。

    Args:
        argument: 统一业务上下文字典，包含业务编号和名称、当前账号、查询日期、
            U盾编号以及输出根目录。执行完成后必须写入
            ``business_result``。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    # @step 校验新增业务的统一输入参数。
    context = contract.BusinessArgumentModel.model_validate(argument)

    # @step 返回尚未实现的标准业务结果。
    result = contract.BusinessResultModel(
        code=1,
        message="{}尚未实现".format(context.business_name),
    )
    argument["business_result"] = result.model_dump(mode="python")
    return argument
