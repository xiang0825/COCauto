import pathlib
import unittest

import cv2
import numpy as np

from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.世界跳转.世界识别器 import 世界识别器


class _评分识图替身:
    def __init__(self, 分数):
        self.分数 = 分数

    def 执行最佳匹配(self, _图像, 模板路径):
        if "主世界圣水" in 模板路径:
            分数 = self.分数["主资源"]
        elif "夜世界圣水" in 模板路径:
            分数 = self.分数["夜资源"]
        elif "家乡进攻" in 模板路径:
            分数 = self.分数["主入口"]
        else:
            分数 = 0.0
        return 分数, (10, 10), 模板路径.split("|")[0]


class _夜世界备用模板替身(_评分识图替身):
    def 执行最佳匹配(self, _图像, 模板路径):
        if 模板路径 == "夜世界圣水图标.bmp":
            return 0.897, (10, 10), 模板路径
        if "夜世界圣水图标1.bmp" in 模板路径:
            return 0.955, (10, 10), "夜世界圣水图标1.bmp"
        return super().执行最佳匹配(_图像, 模板路径)


class 世界识别测试(unittest.TestCase):
    def test_主世界需要资源栏和入口特征共同确认(self):
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.99, "夜资源": 0.88, "主入口": 0.99})
        )
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8))
        self.assertEqual(结果.当前世界, "主世界")
        self.assertIn("主世界资源栏", 结果.摘要())
        self.assertIn("主世界入口", 结果.摘要())

    def test_新版左下黄色战斗卡片作为主世界入口特征(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 模拟新版 HUD 固定位置的黄色“战斗”卡片；地图黄色内容不在
        # 这个受限区域内，资源栏仍作为独立主页信号交叉验证。
        cv2.rectangle(画面, (18, 505), (112, 575), (0, 205, 255), -1)
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.99, "夜资源": 0.10, "主入口": 0.0})
        )

        结果 = 识别器.识别(画面)

        self.assertEqual(结果.当前世界, "主世界")
        self.assertGreater(结果.主世界入口分数, 0.90)
        self.assertIn("新版战斗入口", 结果.摘要())

    def test_新版竖向战斗卡片按实机宽高比识别(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 实机按钮映射到参考画布后约 80×105，不是旧版横向按钮。
        cv2.rectangle(画面, (14, 480), (96, 590), (0, 205, 255), -1)
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.99, "夜资源": 0.10, "主入口": 0.0})
        )

        结果 = 识别器.识别(画面)

        self.assertEqual(结果.当前世界, "主世界")
        self.assertGreater(结果.主世界入口分数, 0.90)
        self.assertIn("新版战斗入口", 结果.摘要())

    def test_新版战斗卡片能在资源模板改版时提供中等主页置信度(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (18, 505), (112, 575), (0, 205, 255), -1)
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.10, "夜资源": 0.10, "主入口": 0.0})
        )

        结果 = 识别器.识别(画面)

        self.assertEqual(结果.当前世界, "主世界")
        self.assertGreaterEqual(结果.主世界分数, 0.50)

    def test_新版战斗卡片与轻微降分的主世界资源栏共同达到安全复核门槛(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 对应实机新版主页证据：资源栏模板 0.94、竖向战斗入口约 0.99。
        # 两帧连续复核仍由调用方执行；这里只验证两项独立锚点可进入该门槛。
        cv2.rectangle(画面, (14, 480), (96, 590), (0, 205, 255), -1)
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.94, "夜资源": 0.10, "主入口": 0.0})
        )

        结果 = 识别器.识别(画面)

        self.assertEqual(结果.当前世界, "主世界")
        self.assertGreaterEqual(结果.主世界分数, 0.70)
        self.assertIn("主世界资源栏0.94", 结果.依据)
        self.assertIn("新版战斗入口", 结果.摘要())

    def test_新版主世界头像通知红点不能覆盖强主页锚点(self):
        """主页资源栏和战斗入口都强命中时，头像红色通知点不是夜世界徽章。"""
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (14, 480), (96, 590), (0, 205, 255), -1)
        # 新版头像上的红色提醒落在旧徽章扫描区，覆盖率足以触发颜色兜底。
        cv2.circle(画面, (35, 28), 19, (0, 0, 255), -1)
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.94, "夜资源": 0.10, "主入口": 0.0})
        )

        结果 = 识别器.识别(画面)

        self.assertEqual(识别器._徽章颜色证据(画面)[1], 1.0)
        self.assertEqual(结果.当前世界, "主世界", 结果.摘要())
        self.assertNotIn("夜世界红色等级徽章", 结果.依据)

    def test_主世界入口黄色小噪点不作为入口证据(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(画面, (40, 530), (55, 540), (0, 205, 255), -1)
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.10, "夜资源": 0.10, "主入口": 0.0})
        )

        结果 = 识别器.识别(画面)

        self.assertEqual(结果.主世界入口分数, 0.0)
        self.assertIsNone(结果.当前世界)

    def test_夜世界资源栏明显领先时识别为夜世界(self):
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.88, "夜资源": 0.99, "主入口": 0.20})
        )
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8))
        self.assertEqual(结果.当前世界, "夜世界")

    def test_夜世界首模板中等命中时仍扫描新版备用模板(self):
        识别器 = 世界识别器(_夜世界备用模板替身({
            "主资源": 0.88, "夜资源": 0.00, "主入口": 0.20,
        }))
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8))
        self.assertEqual(结果.当前世界, "夜世界")
        self.assertGreaterEqual(结果.夜世界资源图标分数, 0.955)

    def test_两套特征接近时返回未知不继续误点击(self):
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.97, "夜资源": 0.97, "主入口": 0.20})
        )
        结果 = 识别器.识别(np.zeros((600, 800, 3), dtype=np.uint8))
        self.assertIsNone(结果.当前世界)
        self.assertFalse(结果.可靠)

    def test_军队配置棕红色面板不冒充夜世界徽章(self):
        """配置页的整块棕红面板不能授权夜世界入口操作。"""
        识别器 = 世界识别器(
            _评分识图替身({"主资源": 0.70, "夜资源": 0.84, "主入口": 0.65})
        )
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 模拟实机军队配置页左上 HUD 被棕红色面板覆盖的情况，
        # 覆盖率约 40%，不是局部夜世界等级徽章。
        图像[:105, :90] = (30, 30, 180)
        结果 = 识别器.识别(图像)
        self.assertIsNone(结果.当前世界)
        self.assertNotIn("夜世界红色等级徽章", 结果.依据)

    def test_实机主世界截图命中主世界且不命中夜世界(self):
        根目录 = pathlib.Path(__file__).resolve().parents[1]
        图片路径 = 根目录 / ".tmp" / "runtime_observation_after10s.png"
        if not 图片路径.exists():
            self.skipTest("没有维护观察截图")
        数据 = np.fromfile(
            图片路径, dtype=np.uint8
        )
        屏幕图像 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
        if 屏幕图像 is None:
            self.skipTest("没有维护观察截图")

        引擎 = 模板匹配引擎(图片库路径=根目录 / "img")
        结果 = 世界识别器(引擎).识别(屏幕图像)
        self.assertEqual(结果.当前世界, "主世界")
        self.assertGreater(结果.主世界资源图标分数, 0.92)
        self.assertGreater(结果.主世界入口分数, 0.86)


if __name__ == "__main__":
    unittest.main()
