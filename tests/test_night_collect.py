import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.夜世界.收集圣水车 import 收集圣水车任务


class 夜世界圣水车测试(unittest.TestCase):
    def _任务(self, 屏幕):
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            置脚本状态=Mock(),
        )
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        return 任务

    def test_动态紫色气泡不进入点击候选(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 构造和实机一致的紫色收集气泡，位于地图区域内。
        cv2.circle(屏幕, (484, 224), 18, (180, 60, 220), -1)
        任务 = self._任务(屏幕)

        候选 = 任务._生成圣水车候选点(692, 7)

        self.assertEqual(候选[0][2], "船模板兼容偏移1")
        self.assertNotIn((484, 224, "动态紫色资源气泡"), 候选)

    def test_旧船模板未命中时仍能独立扫描动态气泡(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.circle(屏幕, (415, 193), 12, (180, 60, 220), -1)
        任务 = self._任务(屏幕)

        候选 = 任务._生成动态紫色候选点()

        self.assertIn((415, 193, "动态紫色资源气泡"), 候选)

    def test_所有候选点都在参考画布内且固定偏移不会越界(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = self._任务(屏幕)

        候选 = 任务._生成圣水车候选点(10, 0)

        self.assertTrue(候选)
        self.assertTrue(all(12 <= x <= 788 and 12 <= y <= 588 for x, y, _ in 候选))

    def test_海岸船锚点限制地图区域并还原坐标(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            置脚本状态=Mock(),
        )
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.91, (516, 61), "船.bmp")

        命中, 坐标, 分数 = 任务._查找海岸船锚点()

        self.assertTrue(命中)
        self.assertEqual(坐标, (596, 109))
        self.assertAlmostEqual(分数, 0.91)

    def test_海岸船锚点拒绝顶部资源栏假匹配(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            置脚本状态=Mock(),
        )
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.95, (690, 10), "船.bmp")

        命中, _, _ = 任务._查找海岸船锚点()

        self.assertFalse(命中)

    def test_海岸船锚点拒绝右上资源栏低分假匹配(self):
        """右上资源栏纹理的低分命中不能触发三次错误点击。"""
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=屏幕)),
            置脚本状态=Mock(),
        )
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        # 与实机日志中的资源栏假匹配一致：全局约(631,91)，分数0.68。
        任务.模板识别.执行最佳匹配.return_value = (0.68, (551, 43), "船.bmp")

        命中, _, _ = 任务._查找海岸船锚点()

        self.assertFalse(命中)

    def test_船模板覆盖全部变体(self):
        for 编号 in range(1, 13):
            self.assertIn(f"夜世界的船{编号}.bmp", 收集圣水车任务.船模板路径)

    def test_只识别右上角明确红色关闭按钮(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        # OpenCV 使用 BGR；用红色方块模拟游戏内详情面板的关闭按钮。
        cv2.rectangle(屏幕, (660, 30), (716, 86), (0, 0, 220), -1)

        关闭点 = 收集圣水车任务._检测详情面板关闭点(屏幕)

        self.assertIsNotNone(关闭点)
        self.assertTrue(650 <= 关闭点[0] <= 730)
        self.assertTrue(28 <= 关闭点[1] <= 90)

    def test_贴近画面顶边的红色像素不允许作为关闭按钮(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(屏幕, (660, 0), (716, 20), (0, 0, 220), -1)

        self.assertIsNone(收集圣水车任务._检测详情面板关闭点(屏幕))

    def test_主页没有红色关闭按钮时不发送关闭输入(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)

        self.assertIsNone(收集圣水车任务._检测详情面板关闭点(屏幕))

    def test_简繁体圣水车标题都可确认(self):
        self.assertTrue(收集圣水车任务._是否圣水车标题([([], "聖水車", 0.99)]))
        self.assertTrue(收集圣水车任务._是否圣水车标题([([], "圣水车", 0.99)]))
        self.assertFalse(收集圣水车任务._是否圣水车标题([([], "雙管加農炮", 0.99)]))

    def test_候选点击后回到主世界立即停止剩余点击(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = self._任务(屏幕)
        任务.模板识别 = Mock()
        任务._世界识别器 = Mock()
        任务._世界识别器.识别.side_effect = [
            SimpleNamespace(当前世界="夜世界"),
            SimpleNamespace(当前世界="主世界"),
        ]
        任务._查找海岸船锚点 = Mock(return_value=(True, (200, 200), 0.9))
        任务._生成圣水车候选点 = Mock(return_value=[(200, 200, "测试候选1"), (300, 300, "测试候选2")])
        任务.尝试收集圣水 = Mock(return_value=False)
        任务._关闭候选详情面板 = Mock(return_value=False)
        任务.上下文.点击 = Mock()

        self.assertFalse(任务.执行())
        任务.上下文.点击.assert_called_once_with(200, 200)
        self.assertTrue(any("回到主世界" in c.args[0] for c in 任务.上下文.置脚本状态.call_args_list))


if __name__ == "__main__":
    unittest.main()
