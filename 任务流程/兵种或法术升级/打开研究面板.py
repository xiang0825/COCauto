import re

from 任务流程.基础任务框架 import 基础任务


class 打开研究面板任务(基础任务):
    """检查实验室状态并打开研究面板"""

    # ==================== 界面坐标常量 ====================
    实验室状态区域 = (268, 9, 332, 48)
    研究面板点击坐标 = (243, 13)

    def 执行(self) -> bool:
        try:
            if self._检查实验室是否空闲():
                self.上下文.置脚本状态("正在打开研究面板")
                self.上下文.点击(*self.研究面板点击坐标, 是否精确点击=True)
                return True
            return False
        except Exception as e:
            # 转场帧可能只有单个数字或 OCR 为空；无法确认实验室状态
            # 时必须安全跳过，不能把页面上的任何坐标当作研究入口。
            self.上下文.置脚本状态(f"研究面板状态暂时无法确认，已安全跳过：{e}")
            return False

    @staticmethod
    def 解析实验室计数(识别结果) -> tuple[int, int]:
        """从 OCR 结果中提取合法的 ``空闲/总数`` 研究槽位。

        研究面板入口在转场或缩放后的首帧偶尔会只返回 ``1``，旧代码
        直接对第一条文本 split('/') 并解包，产生 ``not enough values``。
        这里遍历全部 OCR 项，只接受 0..2 的合法计数。
        """
        候选 = []
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            文本 = str(项[1] or "").strip().replace(" ", "")
            文本 = (
                文本.replace("O", "0")
                .replace("o", "0")
                .replace("／", "/")
                .replace("I", "/")
                .replace("l", "/")
                .replace("|", "/")
            )
            匹配 = re.search(r"(?<!\d)([0-2])\s*/\s*([0-2])(?!\d)", 文本)
            if not 匹配:
                continue
            空闲位置 = int(匹配.group(1))
            可同时研究总数 = int(匹配.group(2))
            if 可同时研究总数 <= 0 or 空闲位置 > 可同时研究总数:
                continue
            置信度 = float(项[2]) if len(项) >= 3 else 0.0
            候选.append((置信度, 空闲位置, 可同时研究总数))
        if not 候选:
            raise ValueError("未识别到合法实验室计数")
        _, 空闲位置, 可同时研究总数 = max(候选, key=lambda 项: 项[0])
        return 空闲位置, 可同时研究总数

    def _检查实验室是否空闲(self) -> bool:
        """检查实验室是否有空闲位置"""
        识别结果 = self.执行OCR识别(self.实验室状态区域)
        try:
            空闲位置, 可同时研究总数 = self.解析实验室计数(识别结果)
        except ValueError:
            # 首帧 OCR 可能只截到数字左半边；扩大同一顶部区域重试，
            # 不改变点击位置，也不把其它页面文本当成实验室状态。
            回退区域 = (240, 0, 380, 80)
            回退结果 = self.执行OCR识别(回退区域)
            空闲位置, 可同时研究总数 = self.解析实验室计数(回退结果)
            self.上下文.置脚本状态(
                f"实验室窄区域OCR未命中，已用顶部宽区域回退识别：{空闲位置}/{可同时研究总数}"
            )

        # 无空闲位置
        if 空闲位置 == 0:
            self.上下文.置脚本状态(f"实验室有东西在升级：({空闲位置}/{可同时研究总数})")
            return False

        # 哥布林活动特殊情况
        if 可同时研究总数 == 2 and 空闲位置 == 1:
            self.上下文.置脚本状态("当前为哥布林活动，显示1位置但实际不可用")
            return False

        # 正常可用
        if 0 <= 空闲位置 <= 可同时研究总数 <= 2:
            self.上下文.置脚本状态(f"实验室可用：{空闲位置}/{可同时研究总数}")
            return True

        # 异常情况
        self.上下文.置脚本状态(f"实验室状态异常：OCR结果为 {识别结果}")
        return False
