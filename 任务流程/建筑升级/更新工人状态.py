import re
import time

from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务


class 更新工人状态任务(夜世界基础任务):

    @staticmethod
    def 解析工人计数(识别结果, 区域左侧: int = 0) -> tuple[int, int]:
        """从顶部工人计数 OCR 中提取合法的 ``空闲/总数``。

        在 MuMu 1280×720 画面中，RapidOCR 偶尔会把左侧数字的描边
        误识别为前导 ``-``（真实画面 ``1/2`` 会变成 ``-1/2``）。
        工人数量不可能为负数，因此只允许 0--7 的两个数字，并把这个
        单独的前导噪声视为 OCR 误差。其它文本一律拒绝，避免把英雄栏
        或升级提示误写入工人状态。
        """
        候选 = []
        for 项 in 识别结果 or []:
            if not isinstance(项, (list, tuple)) or len(项) < 2:
                continue
            文本 = str(项[1] or "").strip().replace(" ", "")
            if not 文本:
                continue
            # O/o 是 OCR 对 0 的常见误识别；竖线/I/l 是斜线的常见误识别。
            文本 = (
                文本.replace("O", "0")
                .replace("o", "0")
                .replace("I", "/")
                .replace("l", "/")
                .replace("|", "/")
            )
            匹配 = re.search(r"(?<!\d)(?:[-—–_]\s*)?([0-7])\s*/\s*([0-7])(?!\d)", 文本)
            if not 匹配:
                continue
            空闲工人 = int(匹配.group(1))
            工人总数 = int(匹配.group(2))
            if 工人总数 <= 0 or 空闲工人 > 工人总数:
                continue
            置信度 = float(项[2]) if len(项) >= 3 else 0.0
            # 宽区域回退识别时，英雄栏也可能出现在同一张 OCR 图中。
            # 只接受顶部建筑工人计数的横向位置，避免把旁边的英雄计数
            # （例如 1/7）误当成建筑工人状态。
            if 区域左侧 and len(项) >= 1 and isinstance(项[0], (list, tuple)) and 项[0]:
                try:
                    中心x = sum(float(点[0]) for 点 in 项[0]) / len(项[0]) + 区域左侧
                    if not 270 <= 中心x <= 345:
                        continue
                except (TypeError, ValueError, IndexError):
                    pass
            候选.append((置信度, 空闲工人, 工人总数, 文本))

        if not 候选:
            raise ValueError("未识别到合法工人计数")
        _, 空闲工人, 工人总数, _ = max(候选, key=lambda 项: 项[0])
        return 空闲工人, 工人总数

    def 执行(self) -> bool:
        """任务入口"""
        return self.识别当前工人状态写入数据库()

    def 识别当前工人状态写入数据库(self) -> bool:
        """识别屏幕的工人状态并写入数据库"""
        try:
            # MuMu 当前 1280×720 主世界顶部的建筑工人计数是物理
            # x≈480..520，映射到 800×600 参考画布约 x=300..325。
            # 旧区域 (349,3,441,47) 实际覆盖英雄栏 1/6 和升级文字，
            # 会把英雄数量误写成工人数量，升级过程中还会解析到“正在進行升”。
            主要区域 = (285, 0, 335, 60)
            识别结果 = self.执行OCR识别(主要区域)

            try:
                空闲工人, 工人总数 = self.解析工人计数(识别结果, 主要区域[0])
            except ValueError:
                # MuMu 在缩放/转场后的首帧可能让窄裁剪完全没有 OCR
                # 结果。只扩大同一顶部区域重试，不发送任何点击；并且
                # 通过全局横坐标过滤，不能把右侧英雄栏的 1/7 当工人。
                回退区域 = (250, 0, 370, 85)
                回退结果 = self.执行OCR识别(回退区域)
                空闲工人, 工人总数 = self.解析工人计数(回退结果, 回退区域[0])
                self.上下文.置脚本状态(
                    f"建筑工人窄区域OCR未命中，已用顶部宽区域回退识别：{空闲工人}/{工人总数}"
                )

            状态字典 = {
                "空闲工人": 空闲工人,
                "工人总数": 工人总数,
                "更新时间": time.time(),
            }

            # 更新数据库
            self.数据库.更新状态(self.机器人标志, "工人状态", 状态字典)

            # 将时间戳转换为可读格式
            可读时间 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(状态字典["更新时间"]))

            self.上下文.置脚本状态(f"工人状态已更新: 空闲工人={空闲工人}, 工人总数={工人总数}, 更新时间={可读时间}")
            return True

        except Exception as e:
            self.上下文.置脚本状态(f"识别工人状态失败: {str(e)}，工人状态未更新")
            return False

    def 是否有空闲工人(self) -> bool:
        """检查数据库中的工人状态是否可信，并判断是否有空闲工人"""
        try:
            状态 = (
                self.数据库
                .获取最新完整状态(self.机器人标志)
                .状态数据["工人状态"]
            )
        except Exception as e:
            self.上下文.置脚本状态(f"读取工人状态失败: {e}")
            return False

        if not isinstance(状态, dict):
            self.上下文.置脚本状态(f"工人状态格式异常：{状态!r}")
            return False

        try:
            空闲工人 = int(状态["空闲工人"])
            工人总数 = int(状态["工人总数"])
            更新时间 = float(状态["更新时间"])
        except (KeyError, TypeError, ValueError) as e:
            self.上下文.置脚本状态(f"工人状态字段缺失或无效：{e}，不执行建筑升级")
            return False

        # 1. 数据是否过期
        if time.time() - 更新时间 > 120:
            self.上下文.置脚本状态("工人状态数据更新已超过2分钟，状态不可信")
            return False

        # 2. 常见无空闲工人情况
        if 空闲工人 == 0:
            self.上下文.置脚本状态(F"无空闲工人：({空闲工人}/{工人总数})")
            return False

        # 3. 异常情况：7工人但显示1空闲（哥布林）
        if 工人总数 == 7 and 空闲工人 == 1:
            self.上下文.置脚本状态("当前为哥布林活动，显示1工人但实际不可用")
            return False

        # 刷墙保留工人
        if self.上下文.设置.开启刷墙 and 空闲工人 == 1:
            self.上下文.置脚本状态("开启了刷墙，而且只剩下1个工人了，留作刷墙用")
            return False

        # 4. 正常可用
        if 0 <= 空闲工人 <= 工人总数 <= 7:
            self.上下文.置脚本状态(f"工人可用：{空闲工人}/{工人总数}")
            return True

        # 5. 兜底异常
        self.上下文.置脚本状态(f"工人状态异常：{状态}")
        return False
