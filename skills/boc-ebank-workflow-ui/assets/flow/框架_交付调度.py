"""按照运行方案配置执行交付模块。"""

from apa_runtime import *
from typing import Any

import 公共_网银能力 as ebank


def main(argument: dict[str, Any]) -> dict[str, Any]:
    """按照配置顺序执行全部交付模块。

    Args:
        argument: 流程块共享字典。

    Returns:
        dict[str, Any]: 传入的同一个 ``argument`` 对象。
    """

    # @step 按运行方案顺序执行已启用的交付模块。
    return ebank.run_delivery(argument)
