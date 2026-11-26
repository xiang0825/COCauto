"""分辨率无关：画面几何、模板多尺度回退与 1280×720 实拍回放。

实拍样本位于 tests/回放样本/16比9（MuMu 1280×720 原始尺寸，mumu_ipc 只读截图）。
回放时与线上一致：先把原图缩放到 800×600 逻辑画布再交给识别函数。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 模块 import 画面几何
from 模块.检测.模板匹配器 import 模板匹配引擎
from 模块.检测.页面识别器 import 页面识别器
from 任务流程.夜世界.收集圣水车 import 收集圣水车任务
from 任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗 import 等待回营或第二次战斗
from 任务流程.世界跳转.到主世界任务 import 到主世界任务

测试目录 = Path(__file__).resolve().parent
宽屏样本目录 = 测试目录 / "回放样本" / "16比9"
旧样本目录 = 测试目录 / "回放样本"
图片库 = 测试目录.parent / "img"


def 读取(文件: Path) -> np.ndarray:
    图像 = cv2.imdecode(np.fromfile(str(文件), dtype=np.uint8), cv2.IMREAD_COLOR)
    if 图像 is None:
        raise AssertionError(f"无法解码：{文件}")
    return 图像


def 宽屏样本(前缀: str) -> np.ndarray:
    文件 = sorted(宽屏样本目录.glob(f"{前缀}_*.jpg"))
    if not 文件:
        raise AssertionError(f"缺少样本：{前缀}")
    return 读取(文件[0])


def 逻辑画布(图像: np.ndarray) -> np.ndarray:
    return cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)


class 画面几何测试(unittest.TestCase):
    def tearDown(self):
        画面几何.清除设备尺寸()

    def test_十六比九任意尺寸与旧参考尺寸都是恒等(self):
        for 尺寸 in ((1280, 720), (1920, 1080), (1600, 900), (2560, 1440), (800, 600)):
            with self.subTest(尺寸=尺寸):
                self.assertTrue(画面几何.坐标恒等(尺寸))
                self.assertEqual(画面几何.锚点坐标(62, 546, "左下", 尺寸), (62, 546))
                self.assertEqual(画面几何.锚点坐标(746, 538, "右下", 尺寸), (746, 538))
                self.assertIsNone(画面几何.分辨率提示(*尺寸))
        # 未知尺寸同样恒等，旧测试/旧设备不受影响。
        self.assertEqual(画面几何.锚点坐标(746, 538, "右下"), (746, 538))

    def test_四比三按高度贴边换算HUD(self):
        尺寸 = (1600, 1200)
        # 左侧贴边：校准设备 x=62/800*2133=165 → 新设备 165/1600*800≈83
        左x, 左y = 画面几何.锚点坐标(62, 546, "左下", 尺寸)
        self.assertEqual(左y, 546)
        self.assertAlmostEqual(左x, 83, delta=1)
        # 右侧贴边：保持到右边缘的距离（以高度为单位）。
        右x, _ = 画面几何.锚点坐标(746, 538, "右下", 尺寸)
        self.assertAlmostEqual(800 - 右x, (800 - 746) * (2133.33 / 1600), delta=1)
        # 居中元素保持居中。
        self.assertEqual(画面几何.锚点坐标(400, 300, "中", 尺寸), (400, 300))
        self.assertIsNotNone(画面几何.分辨率提示(*尺寸))

    def test_模板尺度候选(self):
        self.assertEqual(画面几何.模板尺度候选((800, 600)), [])
        self.assertEqual(画面几何.模板尺度候选(None), [])
        候选 = 画面几何.模板尺度候选((1280, 720))
        self.assertIn((0.9, 1.2), 候选)
        # 任意 16:9 尺寸得到同一组逻辑尺度。
        self.assertEqual(候选, 画面几何.模板尺度候选((1920, 1080)))

    def test_线程内记录设备尺寸(self):
        画面几何.记录设备尺寸(1280, 720)
        self.assertEqual(画面几何.当前设备尺寸(), (1280, 720))
        画面几何.记录设备尺寸(0, 0)
        self.assertEqual(画面几何.当前设备尺寸(), (1280, 720))

    def test_主页HUD区域覆盖原误点坐标但不覆盖圣水车(self):
        # rc155 实机：夜世界回主世界误点 175,575（左下 HUD 日历条）。
        self.assertTrue(画面几何.点在主页HUD内(175, 575))
        self.assertTrue(画面几何.点在主页HUD内(746, 538))
        self.assertFalse(画面几何.点在主页HUD内(553, 135))
        self.assertFalse(画面几何.点在主页HUD内(400, 300))
        # 顶边飞艇帆条带保持可点击。
        self.assertFalse(画面几何.点在主页HUD内(674, 2, 边距=0))


class 主流程HUD锚定测试(unittest.TestCase):
    def tearDown(self):
        画面几何.清除设备尺寸()

    def test_十六比九与旧参考尺寸下锚定为恒等(self):
        from 任务流程.世界跳转 import 新版界面坐标 as 坐标

        for 尺寸 in ((1280, 720), (1920, 1080), (800, 600)):
            画面几何.记录设备尺寸(*尺寸)
            self.assertEqual(坐标.锚定(坐标.主世界战斗菜单), 坐标.主世界战斗菜单)
            self.assertEqual(坐标.锚定(坐标.主世界建造菜单), 坐标.主世界建造菜单)
            self.assertEqual(坐标.锚定(坐标.新版建造面板OCR区域), 坐标.新版建造面板OCR区域)
            self.assertEqual(坐标.锚定(坐标.新版工人计数OCR区域), 坐标.新版工人计数OCR区域)

    def test_四比三下右侧HUD贴右边缘(self):
        from 任务流程.世界跳转 import 新版界面坐标 as 坐标

        画面几何.记录设备尺寸(1024, 768)
        x, y = 坐标.锚定(坐标.主世界建造菜单)
        self.assertEqual(y, 坐标.主世界建造菜单[1])
        self.assertLess(800 - x, 800 - 坐标.主世界建造菜单[0] + 30)
        self.assertGreater(800 - x, 800 - 坐标.主世界建造菜单[0])
        左, 上, 右, 下 = 坐标.锚定(坐标.新版建造面板OCR区域)
        self.assertEqual(右, 800)
        self.assertLess(左, 坐标.新版建造面板OCR区域[0])
        # 未登记坐标原样返回。
        self.assertEqual(坐标.锚定((1, 2)), (1, 2))


class 模板多尺度测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.引擎 = 模板匹配引擎(图片库路径=图片库)

    def test_旧参考尺寸结果与执行最佳匹配一致(self):
        图 = 逻辑画布(宽屏样本("night_battle2_start"))
        路径 = "更换兵种箭头[1].bmp|更换兵种箭头[3].bmp"
        原 = self.引擎.执行最佳匹配(图, 路径)
        多 = self.引擎.执行多尺度最佳匹配(图, 路径, 尺度列表=[])
        self.assertAlmostEqual(原[0], 多[0], places=5)
        self.assertEqual(原[1], 多[1])
        self.assertEqual(多[3], (1.0, 1.0))

    def test_宽屏几何尺度让换兵箭头越过原阈值(self):
        图 = 逻辑画布(宽屏样本("night_battle2_start"))[495:600, 163:800]
        路径 = "|".join(f"更换兵种箭头[{i}].bmp" for i in range(1, 6))
        原分数 = self.引擎.执行最佳匹配(图, 路径)[0]
        多分数, _, _, 尺度 = self.引擎.执行多尺度最佳匹配(
            图, 路径, 尺度列表=画面几何.模板尺度候选((1280, 720))
        )
        self.assertLess(原分数, 0.90)
        self.assertGreaterEqual(多分数, 0.90)
        self.assertNotEqual(尺度, (1.0, 1.0))


class 夜世界第二场实拍回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.引擎 = 模板匹配引擎(图片库路径=图片库)

    def tearDown(self):
        画面几何.清除设备尺寸()

    def _任务(self, 原图):
        画面几何.记录设备尺寸(原图.shape[1], 原图.shape[0])
        逻辑 = 逻辑画布(原图)

        def 截图(x1=0, y1=0, x2=800, y2=600, **_):
            return 逻辑[y1:y2, x1:x2].copy()

        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=截图),
            点击=Mock(return_value=True),
            置脚本状态=Mock(),
        )
        任务.模板识别 = self.引擎
        return 任务

    def test_第二场开始帧识别到换兵箭头并点击兵卡(self):
        任务 = self._任务(宽屏样本("night_battle2_start"))
        self.assertTrue(任务.是否出现换兵种箭头())
        x, y = 任务.上下文.点击.call_args.args[:2]
        # 第 7/8 张兵卡（逻辑 x≈505..600），点击落在兵栏内。
        self.assertTrue(480 <= x <= 610 and 520 <= y <= 560, (x, y))

    def test_第一场帧不会误判第二场(self):
        for 前缀 in ("night_battle1_mid", "night_battle1_end"):
            with self.subTest(前缀=前缀):
                任务 = self._任务(宽屏样本(前缀))
                self.assertFalse(任务.是否出现换兵种箭头())
                任务.上下文.点击.assert_not_called()

    def test_旧参考尺寸不启用额外尺度(self):
        任务 = self._任务(宽屏样本("night_battle2_start"))
        画面几何.记录设备尺寸(800, 600)
        self.assertFalse(任务.是否出现换兵种箭头())

    def test_倒计时标题文字判定(self):
        判定 = 等待回营或第二次战斗.是第二场开始倒计时文字
        self.assertTrue(判定("離門開始剩下："))
        self.assertTrue(判定("离战斗开始剩下"))
        self.assertFalse(判定("離門結束剩下："))
        self.assertFalse(判定("离战斗结束剩下"))
        self.assertFalse(判定(""))

    def test_倒计时OCR节流且只读(self):
        任务 = self._任务(宽屏样本("night_battle2_start"))
        任务.执行OCR识别 = Mock(return_value=[([], "離門開始剩下：", 0.84)])
        self.assertTrue(任务._第二场开始倒计时已出现())
        self.assertFalse(任务._第二场开始倒计时已出现())  # 2 秒内节流
        self.assertEqual(任务.执行OCR识别.call_count, 1)
        任务.上下文.点击.assert_not_called()

    def test_只等待回营模式不看第二场证据(self):
        任务 = self._任务(宽屏样本("night_battle2_start"))
        任务.只等待回营 = True
        任务._读取页面状态 = Mock(return_value=(SimpleNamespace(页面="战斗中"), True))
        任务.是否出现换兵种箭头 = Mock(return_value=True)
        任务._第二场开始倒计时已出现 = Mock(return_value=True)
        次数 = {"n": 0}

        def 回营():
            次数["n"] += 1
            return 次数["n"] >= 3

        任务.尝试点击回营按钮 = 回营
        任务.上下文.脚本延时 = Mock()
        import 任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗 as 模块
        原 = 模块.停止并等待英雄技能线程
        模块.停止并等待英雄技能线程 = lambda *a, **k: True
        try:
            self.assertTrue(任务.执行())
        finally:
            模块.停止并等待英雄技能线程 = 原
        任务.是否出现换兵种箭头.assert_not_called()
        任务._第二场开始倒计时已出现.assert_not_called()


class 搜索对手页回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.识别器 = 页面识别器(模板匹配引擎(图片库路径=图片库))

    def test_匹配页在原图和逻辑画布上都识别(self):
        原图 = 宽屏样本("night_matchmaking")
        for 图 in (原图, 逻辑画布(原图)):
            结果 = self.识别器.识别(图)
            self.assertEqual(结果.页面, "搜索对手中")
            self.assertGreaterEqual(结果.可信度, 0.90)

    def test_其它实拍页面不误判为匹配页(self):
        文件列表 = [
            文件 for 文件 in sorted(宽屏样本目录.glob("*.jpg"))
            if not 文件.name.startswith("night_matchmaking")
        ]
        文件列表 += sorted(旧样本目录.glob("*.jpg"))
        文件列表 += sorted((测试目录 / "fixtures").glob("*.png"))
        self.assertGreaterEqual(len(文件列表), 12)
        for 文件 in 文件列表:
            with self.subTest(文件=文件.name):
                图 = 逻辑画布(读取(文件))
                self.assertEqual(self.识别器._搜索对手页分数(图), 0.0)

    def test_输入护栏在匹配页阻断任何点击(self):
        from 任务流程.基础任务框架 import 任务上下文

        上下文 = 任务上下文.__new__(任务上下文)
        上下文._内存保护已触发 = False
        上下文._正在开启奖励宝箱 = False
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文._最近点击页面结果 = SimpleNamespace(页面="搜索对手中")
        self.assertTrue(上下文.输入前安全检查())


class 圣水车与飞艇实拍回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.引擎 = 模板匹配引擎(图片库路径=图片库)

    def tearDown(self):
        画面几何.清除设备尺寸()

    def _圣水车任务(self, 原图):
        画面几何.记录设备尺寸(原图.shape[1], 原图.shape[0])
        逻辑 = 逻辑画布(原图)
        任务 = object.__new__(收集圣水车任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=逻辑)),
            置脚本状态=Mock(),
        )
        任务.模板识别 = self.引擎
        return 任务

    def test_实拍画面定位圣水车车体(self):
        任务 = self._圣水车任务(宽屏样本("night_home_boat_cart"))
        命中, (x, y), 分数 = 任务._查找圣水车模板()
        self.assertTrue(命中)
        self.assertGreaterEqual(分数, 0.78)
        self.assertTrue(540 <= x <= 566 and 120 <= y <= 150, (x, y))

    def test_无圣水车画面不命中(self):
        for 前缀 in (
            "night_home_wall_menu", "night_attack_panel", "night_battle1_mid",
            "night_battle2_start", "night_settle", "night_star_reward",
        ):
            with self.subTest(前缀=前缀):
                任务 = self._圣水车任务(宽屏样本(前缀))
                self.assertFalse(任务._查找圣水车模板()[0])

    def test_圣水车命中点击车体并要求标题OCR(self):
        任务 = self._圣水车任务(宽屏样本("night_home_boat_cart"))
        任务._夜世界仍在前台 = Mock(return_value=True)
        任务.上下文.点击 = Mock(return_value=True)
        任务.上下文.脚本延时 = Mock()
        任务.尝试收集圣水 = Mock(return_value=True)
        self.assertTrue(任务.执行())
        x, y = 任务.上下文.点击.call_args.args[:2]
        self.assertTrue(540 <= x <= 566 and 120 <= y <= 150)
        任务.尝试收集圣水.assert_called_once()

    def test_圣水车标题未确认时只关闭面板并跳过(self):
        任务 = self._圣水车任务(宽屏样本("night_home_boat_cart"))
        任务._夜世界仍在前台 = Mock(return_value=True)
        任务.上下文.点击 = Mock(return_value=True)
        任务.上下文.脚本延时 = Mock()
        任务.尝试收集圣水 = Mock(return_value=False)
        任务._关闭候选详情面板 = Mock(return_value=True)
        self.assertFalse(任务.执行())
        self.assertEqual(任务.上下文.点击.call_count, 1)
        self.assertTrue(任务._本轮未发现可收集圣水车)

    def test_边缘拖动后复核夜世界失败则停止(self):
        任务 = self._圣水车任务(宽屏样本("night_home_wall_menu"))
        鼠标 = SimpleNamespace(移动到=Mock(), 左键按下=Mock(), 左键抬起=Mock())
        任务.上下文.鼠标 = 鼠标
        任务.上下文.脚本延时 = Mock()
        任务._夜世界仍在前台 = Mock(return_value=False)
        self.assertFalse(任务._边缘拖动(收集圣水车任务.圣水车搜索拖动路径[0]))
        鼠标.左键按下.assert_called_once()
        鼠标.左键抬起.assert_called_once()
        for 调用 in 鼠标.移动到.call_args_list:
            x, y = 调用.args
            self.assertFalse(画面几何.点在主页HUD内(x, y, 边距=0), (x, y))

    def test_拖动路径全部避开HUD(self):
        for 路径 in 收集圣水车任务.圣水车搜索拖动路径:
            for 点 in (路径.起点, 路径.终点):
                self.assertFalse(画面几何.点在主页HUD内(*点, 边距=0), 点)

    def test_飞艇被资源栏遮挡时由圣水车反推也拒绝点击(self):
        原图 = 宽屏样本("night_home_boat_cart")
        画面几何.记录设备尺寸(1280, 720)
        任务 = object.__new__(到主世界任务)
        任务.状态文本 = "主世界"
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        任务.模板识别 = self.引擎
        命中, 坐标, _ = 任务._圣水车反推入口(逻辑画布(原图))
        self.assertFalse(命中)
        self.assertEqual(坐标, (0, 0))
        self.assertTrue(any(
            "HUD" in 调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_旧船模板在实拍夜世界主页不产生点击(self):
        for 前缀 in ("night_home_boat_cart", "night_home_wall_menu"):
            with self.subTest(前缀=前缀):
                任务 = object.__new__(到主世界任务)
                任务.上下文 = SimpleNamespace(置脚本状态=Mock())
                任务.模板识别 = self.引擎
                命中, _, _ = 任务.查找世界入口(逻辑画布(宽屏样本(前缀)))
                self.assertFalse(命中)

    def test_固定模板命中HUD时拒绝点击(self):
        任务 = object.__new__(到主世界任务)
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        任务.模板识别 = Mock()
        # rc155 现场：模板中心 (167,555) → 点击 (175,575)，落在左下 HUD。
        任务.模板识别.执行最佳匹配.return_value = (0.83, (87, 555), "船.bmp")
        任务.模板识别._安全加载模板 = Mock(return_value=None)
        任务.模板识别.执行多尺度最佳匹配 = Mock(return_value=(0.0, (0, 0), None, (1.0, 1.0)))
        命中, 坐标, _ = 任务.查找世界入口(逻辑画布(宽屏样本("night_home_wall_menu")))
        self.assertFalse(命中)
        self.assertEqual(坐标, (0, 0))


if __name__ == "__main__":
    unittest.main()
