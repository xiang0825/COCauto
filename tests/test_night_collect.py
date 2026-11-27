import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.夜世界.收集圣水车 import 收集圣水车任务


class 夜世界圣水车测试(unittest.TestCase):
    def test_其它弹窗误读圣水车标题仍不点收集(self):
        任务 = self._任务(np.zeros((600, 800, 3), dtype=np.uint8))
        识别器 = SimpleNamespace(
            定位圣水车弹窗按钮=Mock(return_value=None),
        )
        任务.上下文._获取点击页面识别器 = lambda: 识别器
        任务.上下文.点击 = Mock(return_value=True)
        任务.上下文.点击已确认安全按钮 = Mock(return_value=True)
        任务.上下文.脚本延时 = Mock()
        任务.执行OCR识别 = Mock(return_value=[([], "聖水車", .99)])
        任务._查找OCR文本中心 = Mock(return_value=(588, 507))

        self.assertFalse(任务.尝试收集圣水())

        任务.上下文.点击.assert_not_called()
        任务.上下文.点击已确认安全按钮.assert_not_called()

    def test_空圣水车确认后只点关闭且按已完成返回(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = self._任务(屏幕)
        按钮 = {"收集": None, "关闭": (650, 40, 690, 80), "空车": True}
        识别器 = SimpleNamespace(
            定位圣水车弹窗按钮=Mock(return_value=按钮),
            识别=Mock(side_effect=[
                SimpleNamespace(页面="圣水车弹窗"),
                SimpleNamespace(页面="夜世界主页"),
            ]),
        )
        任务.上下文._获取点击页面识别器 = lambda: 识别器
        任务.上下文.点击 = Mock()
        任务.上下文.点击已确认安全按钮 = Mock(return_value=True)
        任务.上下文.脚本延时 = Mock()
        任务.执行OCR识别 = Mock(side_effect=[
            [([], "聖水車", .99)],
            [([], "暫無新的防禦獎勵", .99)],
        ])

        self.assertTrue(任务.尝试收集圣水())

        任务.上下文.点击.assert_not_called()
        任务.上下文.点击已确认安全按钮.assert_called_once_with(670, 60, 延时=180)
        self.assertTrue(any(
            "圣水车为空" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))
        self.assertFalse(getattr(任务, "_收集已点击", False))

    def test_完整收集调用链遇到输入拒绝不重试其它候选或关闭(self):
        for 拒绝阶段 in ("收集", "安全关闭", "候选关闭"):
            with self.subTest(拒绝阶段=拒绝阶段):
                任务 = self._任务(np.zeros((600, 800, 3), dtype=np.uint8))
                任务._夜世界仍在前台 = Mock(return_value=True)
                任务._查找海岸船锚点 = Mock(return_value=(True, (200, 200), .95))
                任务._生成圣水车候选点 = Mock(return_value=[
                    (200, 200, "候选1"), (300, 300, "候选2")])
                任务.是否在危险区域内 = Mock(return_value=False)
                任务.执行OCR识别 = Mock(return_value=[([], "聖水車", .99)])
                任务._查找OCR文本中心 = Mock(return_value=(588, 507))
                任务._检测详情面板关闭点 = Mock(return_value=(680, 50))
                任务.上下文.脚本延时 = Mock()
                任务.上下文.点击 = Mock(side_effect=[True, 拒绝阶段 != "收集"])
                任务.上下文.点击已确认安全按钮 = Mock(return_value=False)
                if 拒绝阶段 == "安全关闭":
                    识别器 = SimpleNamespace(
                        识别=Mock(return_value=SimpleNamespace(页面="圣水车弹窗")),
                        定位圣水车弹窗按钮=Mock(
                            return_value={
                                "收集": (539, 481, 638, 532),
                                "关闭": (650, 40, 690, 80),
                                "空车": False,
                            }
                        ),
                    )
                    任务.上下文._获取点击页面识别器 = lambda: 识别器
                if 拒绝阶段 == "候选关闭":
                    # 候选未通过标题 OCR；页级识别为圣水车弹窗时只经公共
                    # 护栏点击同帧关闭 X，被拒绝后不再点其它候选。
                    任务.执行OCR识别.return_value = [([], "加農炮", .99)]
                    任务.上下文.点击 = Mock(side_effect=[True, False])
                    识别器 = SimpleNamespace(
                        识别=Mock(return_value=SimpleNamespace(页面="圣水车弹窗")),
                        定位圣水车弹窗按钮=Mock(return_value={
                            "收集": None, "关闭": (650, 40, 690, 80), "空车": True,
                        }),
                    )
                    任务.上下文._获取点击页面识别器 = lambda: 识别器
                self.assertFalse(任务.执行())
                self.assertTrue(任务._输入已拒绝)
                self.assertEqual(任务.上下文.点击.call_count, 2)
                self.assertEqual(任务.上下文.点击已确认安全按钮.call_count,
                                 1 if 拒绝阶段 == "安全关闭" else 0)
                self.assertFalse(getattr(任务, "_本轮未发现可收集圣水车", False))

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
        任务._世界识别器.识别.return_value = SimpleNamespace(当前世界="夜世界")
        任务._查找海岸船锚点 = Mock(return_value=(True, (200, 200), 0.9))
        任务._生成圣水车候选点 = Mock(return_value=[(200, 200, "测试候选1"), (300, 300, "测试候选2")])
        任务.尝试收集圣水 = Mock(return_value=False)
        识别器 = SimpleNamespace(
            识别=Mock(return_value=SimpleNamespace(页面="主世界主页"))
        )
        任务.上下文._获取点击页面识别器 = lambda: 识别器
        任务.上下文.点击 = Mock()

        self.assertFalse(任务.执行())
        任务.上下文.点击.assert_called_once_with(200, 200)
        self.assertTrue(any("回到主世界" in c.args[0] for c in 任务.上下文.置脚本状态.call_args_list))

    def test_未定位圣水车最多四次边缘拖动后有界退出(self):
        """未命中时只允许最多 4 次边缘拖动，之后有界退出，不卡住任务线程。"""
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = self._任务(屏幕)
        任务._夜世界仍在前台 = Mock(return_value=True)
        任务._查找圣水车模板 = Mock(return_value=(False, (0, 0), 0.0))
        任务._查找海岸船锚点 = Mock(return_value=(False, (0, 0), 0.0))
        任务._生成动态紫色候选点 = Mock(return_value=[])
        任务._边缘拖动 = Mock(return_value=True)
        任务.上下文.脚本延时 = Mock()
        任务.上下文.滑动屏幕 = Mock()
        任务.上下文.点击 = Mock()

        self.assertFalse(任务.执行())
        self.assertEqual(任务._查找海岸船锚点.call_count, 5)
        self.assertEqual(任务._边缘拖动.call_count, 4)
        for 调用 in 任务._边缘拖动.call_args_list:
            self.assertIn(调用.args[0], 收集圣水车任务.圣水车搜索拖动路径)
        任务.上下文.滑动屏幕.assert_not_called()
        任务.上下文.点击.assert_not_called()
        self.assertTrue(任务._本轮未发现可收集圣水车)
        self.assertTrue(any("有限扫描" in c.args[0] for c in 任务.上下文.置脚本状态.call_args_list))

    def test_圣水车全部候选未命中时可安全跳过并留待下一周期重试(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = self._任务(屏幕)
        任务._夜世界仍在前台 = Mock(return_value=True)
        任务._查找海岸船锚点 = Mock(return_value=(True, (300, 200), 0.95))
        任务._生成圣水车候选点 = Mock(return_value=[
            (180, 240, "候选1"), (196, 258, "候选2"), (168, 234, "候选3"),
        ])
        任务.尝试收集圣水 = Mock(return_value=False)
        任务._候选后恢复夜世界主页 = Mock(return_value=True)
        任务.上下文.点击 = Mock(return_value=True)
        任务.上下文.脚本延时 = Mock()
        任务.上下文.游戏内拉远视距 = Mock()

        self.assertFalse(任务.执行())

        self.assertTrue(任务._本轮未发现可收集圣水车)
        self.assertEqual(任务.上下文.点击.call_count, 3)
        self.assertTrue(any(
            "留待下次重试" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
