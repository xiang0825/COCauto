import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务


class _匹配器:
    def 执行匹配(self, _图像, 模板路径, **_参数):
        if "家乡进攻图标" in 模板路径:
            return True, (0, 0), None
        return True, (120, 130), None


class _屏幕:
    def 获取屏幕图像cv(self, *_区域):
        return object()


class _数据库:
    def 获取机器人设置(self, _机器人标志):
        return type("设置", (), {"是否试战统计胜率": False})()


class _上下文:
    op = _屏幕()
    数据库 = _数据库()
    机器人标志 = "测试机器人"

    def __init__(self):
        self.点击记录 = []
        self.状态 = []

    def 点击(self, x, y, *参数, **关键字参数):
        self.点击记录.append((x, y))

    def 脚本延时(self, _毫秒):
        pass

    def 置脚本状态(self, 文本, *参数, **关键字参数):
        self.状态.append(文本)


class 回营状态机测试(unittest.TestCase):
    def test_OCR胜负结果不能把未知当胜利(self):
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("胜利！"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("战斗失败"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("戰鬥勝利！"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("戰鬥失敗"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("氧败"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("胜"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("结束战斗"), "未知")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本提取摧毁率("摧毁率 67%"), 67)
        self.assertEqual(等待战斗结束并回营任务.从OCR文本提取摧毁率("摧毀率 67％"), 67)
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(0, 32),
            32,
        )
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(67, 32),
            67,
        )
        self.assertEqual(
            等待战斗结束并回营任务.合并本场摧毁率(None, 32),
            32,
        )
        self.assertIsNone(等待战斗结束并回营任务.识别星数(None, "结束战斗"))
        self.assertEqual(等待战斗结束并回营任务.校正星数("失败", 3, 49), 0)
        self.assertEqual(等待战斗结束并回营任务.校正星数("胜利", None, 35), 1)
        self.assertIsNone(等待战斗结束并回营任务.校正星数("胜利", 3, 99))
        self.assertEqual(等待战斗结束并回营任务.校正星数("胜利", 3, 100), 3)
        self.assertIn("未识别战斗结果", 等待战斗结束并回营任务.生成战斗诊断("未知", None, None, {}))

    def test_低摧毁率诊断使用本场下兵证据(self):
        上下文 = SimpleNamespace(
            本场进攻目标数量=18,
            本场边缘目标数量=14,
            本场进攻方向数量=4,
        )
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "失败", 0, 28, {}, 上下文
        )
        self.assertIn("多方向边缘资源覆盖", 诊断)
        self.assertIn("可达评分", 诊断)

    def test_低摧毁率诊断能指出目标或入口不足(self):
        上下文 = SimpleNamespace(
            本场进攻目标数量=2,
            本场边缘目标数量=1,
            本场进攻方向数量=1,
        )
        诊断 = 等待战斗结束并回营任务.生成战斗诊断(
            "失败", 0, 28, {}, 上下文
        )
        self.assertIn("资源目标或进攻入口不足", 诊断)

    def test_战斗学习保存目标证据并改变下一场建议(self):
        class 数据库:
            def __init__(自身):
                自身.保存状态 = None

            def 获取最新完整状态(自身, _机器人标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 28},
                            {"结果": "失败", "摧毁率": 33},
                        ]
                    }
                })

            def 更新状态(自身, _机器人标志, _名称, 数据):
                自身.保存状态 = 数据

        数据库实例 = 数据库()
        上下文 = SimpleNamespace(
            数据库=数据库实例,
            机器人标志="测试机器人",
            本场进攻策略="资源全覆盖+分散探索",
            本场进攻方向=["左上", "右下", "左下", "右上"],
            本场进攻目标数量=18,
            本场边缘目标数量=14,
            本场进攻方向数量=4,
            英雄技能状态={},
            置脚本状态=lambda _文本: None,
        )
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.更新战斗学习(
            上下文,
            "失败",
            0,
            28,
            {"金币": 0, "圣水": 100, "黑油": 200},
        )
        记录 = 数据库实例.保存状态["近期"][-1]
        self.assertEqual(记录["目标数量"], 18)
        self.assertEqual(记录["边缘目标数量"], 14)
        self.assertEqual(记录["进攻方向数量"], 4)
        self.assertEqual(数据库实例.保存状态["下一场建议"], "提高目标可达评分")

    def test_实机结算星形布局识别两星(self):
        图片 = Path(__file__).resolve().parents[1] / ".tmp" / "runtime_after_battle_wait.png"
        if not 图片.exists():
            self.skipTest("没有维护观察截图")
        数据 = np.fromfile(图片, dtype=np.uint8)
        图像 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
        self.assertIsNotNone(图像)
        self.assertEqual(等待战斗结束并回营任务.识别星数(图像, "胜利"), 2)

    def test_结算横幅灰度OCR补足繁体战败(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        调用维度 = []

        def 假OCR(图像, **_参数):
            调用维度.append(getattr(图像, "ndim", None))
            if getattr(图像, "ndim", None) == 2:
                return [([], "載敗")], None
            return [], None

        任务.ocr引擎 = 假OCR
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        文本 = 任务.识别结果页横幅文本(图像)
        self.assertIn("敗", 文本)
        self.assertIn(3, 调用维度)
        self.assertIn(2, 调用维度)

    def test_点击回营后必须确认主界面(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        上下文 = _上下文()

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        self.assertEqual(上下文.点击记录, [(120, 130)])
        self.assertIn("已确认回到主界面，可进入下一场", 上下文.状态)

    def test_实机零点八五分结算按钮会进入回营流程(self):
        class 评分匹配器:
            def 执行匹配(self, _图像, 模板路径, 相似度阈值=0.8, **_参数):
                if "家乡进攻图标" in 模板路径:
                    return True, (0, 0), None
                if "回营" in 模板路径:
                    return 相似度阈值 <= 0.85, (409, 520), None
                return False, (0, 0), None

        class 页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.85)

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 评分匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: True
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: 页面识别器()

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        self.assertEqual(上下文.点击记录, [(409, 520)])
        self.assertIn("检测到回营按钮，点击返回主界面", 上下文.状态)

    def test_战斗统计不完整时不点击回营也不开启下一场(self):
        class 评分匹配器:
            def 执行匹配(self, _图像, 模板路径, 相似度阈值=0.8, **_参数):
                if "回营" in 模板路径:
                    return 相似度阈值 <= 0.85, (409, 520), None
                return False, (0, 0), None

        class 页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.85)

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = 评分匹配器()
        任务.记录战斗结果 = lambda *_参数, **_关键字: False
        上下文 = _上下文()
        上下文._获取点击页面识别器 = lambda: 页面识别器()

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertFalse(结果)
        self.assertEqual(上下文.点击记录, [])
        self.assertIn("未完整确认", " ".join(上下文.状态))


if __name__ == "__main__":
    unittest.main()
