"""网银流程正常结束入口。"""

from typing import Any

from apa_runtime import *
import 公共_网银能力 as ebank


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """执行已配置的正常收尾模块，并保证释放全部活动资源。

    Args:
        argument: 流程块共享字典。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。

    Raises:
        RuntimeError: 正常收尾模块或最终资源清理失败。
    """

    # @step 执行正常收尾并释放全部活动资源。
    return ebank.finish_success(argument)
