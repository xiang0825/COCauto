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
