import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.建筑升级.升级英雄 import 升级英雄任务
from 任务流程.兵种或法术升级.完成兵种或法术升级 import 完成兵种或法术升级任务
from 任务流程.战宠升级.完成宠物升级 import 完成宠物升级任务
from 任务流程.战宠升级.寻找战宠小屋 import 寻找战宠小屋任务
from 任务流程.战宠升级.打开要升级的宠物 import 打开要升级的宠物任务


class 升级面板关闭安全测试(unittest.TestCase):
    def test_英雄面板关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭英雄升级页面()

        返回.assert_called_once_with(
            "关闭英雄升级页面", 已确认可关闭面板=True
        )

    def test_英雄面板优先点主世界空白区域不发送返回键(self):
        点击 = Mock(return_value=True)
        返回 = Mock(return_value=True)
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(点击=点击, 安全返回键=返回)

        self.assertTrue(任务.关闭英雄升级页面())
        点击.assert_called_once_with(680, 300, 延时=700, 是否精确点击=True)
        返回.assert_not_called()

    def test_研究面板关闭两次都授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 完成兵种或法术升级任务.__new__(完成兵种或法术升级任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务._关闭升级面板()

        self.assertEqual(返回.call_count, 2)
        for 调用, 说明 in zip(
            返回.call_args_list, ("关闭升级详情", "关闭研究面板")
        ):
            self.assertEqual(
                调用,
                unittest.mock.call(说明, 已确认可关闭面板=True),
            )

    def test_战宠升级面板关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 完成宠物升级任务.__new__(完成宠物升级任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        self.assertTrue(任务._安全关闭面板("关闭战宠升级页面", "关闭战宠小屋"))
        self.assertEqual(返回.call_count, 2)
        self.assertTrue(all(
            调用.kwargs.get("已确认可关闭面板") is True
            for 调用 in 返回.call_args_list
        ))

    def test_战宠小屋关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 打开要升级的宠物任务.__new__(打开要升级的宠物任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭战宠小屋页面()

        返回.assert_called_once_with(
            "关闭战宠小屋页面", 已确认可关闭面板=True
        )

    def test_战宠小屋按钮使用面板区域和自适应阈值(self):
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        上下文 = SimpleNamespace(
            脚本延时=Mock(),
            点击=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.是否出现图片 = Mock(return_value=(True, (489, 450)))

        self.assertTrue(任务._点击打开按钮())
        任务.是否出现图片.assert_called_once_with(
            "打开战宠小屋按钮.bmp|打开战宠小屋按钮1.bmp",
            区域=(400, 360, 580, 560),
            相似度阈值=0.55,
        )
        上下文.点击.assert_called_once_with(
            489, 450, 延时=350, 是否精确点击=True
        )

    def test_战宠小屋使用放大地图切片并还原参考坐标(self):
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        调用次数 = 0

        def 检测(图像):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 == 1:
                return [{
                    "裁剪坐标": [300, 300, 360, 360],
                    "类别名称": "战宠小屋",
                    "置信度": 0.80,
                }]
            return []

        任务.战宠小屋检测器 = SimpleNamespace(检测=检测)
        任务.上下文 = SimpleNamespace(
            是否内存异常=lambda 异常: False,
            触发内存保护=Mock(),
            置脚本状态=Mock(),
        )

        结果 = 任务._检测放大地图区域(
            np.zeros((600, 800, 3), dtype=np.uint8)
        )

        self.assertEqual(调用次数, 4)
        self.assertEqual(结果[0]["裁剪坐标"], [320, 280, 360, 320])
        self.assertEqual(结果[0]["置信度"], 0.80)


if __name__ == "__main__":
    unittest.main()
