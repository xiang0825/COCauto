import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.世界跳转.进入世界基类 import 进入世界任务基类
from 任务流程.世界跳转.到主世界任务 import 到主世界任务
from 任务流程.世界跳转.到夜世界任务 import 到夜世界任务
from 任务流程.世界跳转.世界识别器 import 世界识别器


class 世界跳转测试(unittest.TestCase):
    def test_新版夜世界红色等级徽章可在资源模板失配时确认夜世界(self):
        识别器 = 世界识别器(Mock())
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 仅模拟固定左上 HUD，不依赖具体版本的资源数字和图标素材。
        画面[10:88, 10:62] = (0, 0, 220)
        结果 = 识别器.识别(画面)
        self.assertEqual(结果.当前世界, "夜世界")
        self.assertIn("夜世界红色等级徽章", 结果.依据)

    def test_主世界蓝色等级徽章不会被误判为夜世界(self):
        识别器 = 世界识别器(Mock())
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        画面[10:88, 10:62] = (220, 80, 0)
        结果 = 识别器.识别(画面)
        self.assertEqual(结果.当前世界, "主世界")
        self.assertIn("主世界蓝色等级徽章", 结果.依据)

    def test_世界未知时不发送任何输入(self):
        模块 = importlib.import_module("任务流程.世界跳转.进入世界基类")
        时钟 = SimpleNamespace(当前时间=0.0)
        键盘 = Mock()

        def 脚本延时(毫秒数):
            时钟.当前时间 += 毫秒数 / 1000

        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            键盘=键盘,
            脚本延时=脚本延时,
            置脚本状态=Mock(),
        )
        任务 = object.__new__(进入世界任务基类)
        任务.上下文 = 上下文
        任务.状态文本 = "主世界"
        任务.船模板路径 = "船.bmp"
        任务.滑动配置 = SimpleNamespace(起点=(1, 1), 终点=(2, 2))
        任务.模板识别 = Mock()
        任务.模板识别.执行匹配.return_value = (False, (0, 0), None)
        任务.滑动屏幕 = Mock()
        任务.是否在目标世界 = Mock(return_value=False)
        任务.识别当前世界 = Mock(return_value=SimpleNamespace(当前世界="未知"))

        原时间函数 = 模块.time.time
        模块.time.time = lambda: 时钟.当前时间
        try:
            self.assertFalse(任务.执行())
        finally:
            模块.time.time = 原时间函数

        键盘.按字符按压.assert_not_called()
        任务.滑动屏幕.assert_not_called()
        self.assertTrue(
            any("禁止点击、滑动、ESC或返回键" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        )

    def test_页级主页识别可以补充转场资源过渡帧(self):
        任务 = object.__new__(进入世界任务基类)
        任务.状态文本 = "夜世界"
        上下文 = SimpleNamespace(
            识别点击画面=Mock(
                return_value=SimpleNamespace(
                    页面="夜世界主页", 世界="夜世界", 可信度=0.78
                )
            ),
            置脚本状态=Mock(),
        )

        self.assertTrue(任务._页面级确认目标世界(上下文))
        上下文.识别点击画面.assert_called_once_with(强制=True)

    def test_入口点击后多帧确认目标世界才允许继续(self):
        任务 = object.__new__(进入世界任务基类)
        任务.状态文本 = "夜世界"
        任务.识别当前世界 = Mock(
            side_effect=[
                SimpleNamespace(当前世界="主世界"),
                SimpleNamespace(当前世界="夜世界"),
            ]
        )
        上下文 = SimpleNamespace(
            识别点击画面=Mock(
                return_value=SimpleNamespace(
                    页面="主世界主页", 世界="主世界", 可信度=0.78
                )
            ),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.assertTrue(任务._等待目标世界确认(上下文, 尝试次数=3))
        上下文.脚本延时.assert_called_once_with(500)

    def test_世界入口只在左下安全区域匹配并还原坐标(self):
        任务 = object.__new__(进入世界任务基类)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.85, (12, 18), "船.bmp")

        命中, 坐标, 分数 = 任务.查找世界入口(np.zeros((600, 800, 3), dtype=np.uint8))

        self.assertTrue(命中)
        self.assertEqual(坐标, (87, 394))
        self.assertAlmostEqual(分数, 0.85)
        区域 = 任务.模板识别.执行最佳匹配.call_args.args[0]
        self.assertEqual(区域.shape[:2], (240, 300))

    def test_首次画面中的橙色地图建筑不会当成飞艇入口(self):
        任务 = object.__new__(进入世界任务基类)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.0, (0, 0), None)
        任务.模板识别.执行匹配.return_value = (False, (0, 0), None)
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 模拟首次主世界画面里 y≈368 的橙色建筑；它不在拖动后
        # 海岸飞艇的安全 y 带内，必须返回未命中而不能发送点击。
        画面[350:386, 190:235] = (0, 0, 220)

        命中, _, _ = 任务.查找世界入口(画面)

        self.assertFalse(命中)

    def test_左侧橙色建筑候选不会被当成飞艇(self):
        任务 = object.__new__(进入世界任务基类)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.67, (70, 34), "船.bmp")
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 复现 MuMu 实机误命中的普通建筑：逻辑中心约 (166,384)。
        画面[362:406, 150:184] = (0, 0, 220)

        命中, _, 分数 = 任务.查找世界入口(画面)

        self.assertFalse(命中)
        self.assertLess(分数, 0.78)

    def test_镜头移动后备用地图区高分模板可以确认入口(self):
        任务 = object.__new__(到夜世界任务)
        任务.船模板路径 = "船.bmp"
        任务.世界入口备用搜索区域 = (80, 80, 760, 590)
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.side_effect = [
            (0.61, (20, 30), "纹理.bmp"),
            (0.86, (155, 351), "船.bmp"),
        ]
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)

        命中, 坐标, 分数 = 任务.查找世界入口(画面)

        self.assertTrue(命中)
        self.assertEqual(坐标, (210, 457))
        self.assertAlmostEqual(分数, 0.86)
        self.assertEqual(任务.模板识别.执行最佳匹配.call_count, 2)

    def test_主世界入口搜索会轮换安全拖动方向(self):
        任务 = object.__new__(到夜世界任务)
        任务.滑动配置 = SimpleNamespace(起点=(9, 9), 终点=(8, 8))

        第一路径 = 任务._获取本轮搜索滑动配置(0)
        第二路径 = 任务._获取本轮搜索滑动配置(1)
        第五路径 = 任务._获取本轮搜索滑动配置(4)

        self.assertNotEqual(第一路径, 第二路径)
        self.assertEqual(第五路径, 第一路径)

    def test_低分海岸橙色候选只作为搜索线索不会点击(self):
        任务 = object.__new__(进入世界任务基类)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.0, (0, 0), None)
        任务.模板识别.执行匹配.return_value = (False, (0, 0), None)
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        画面[420:475, 190:235] = (0, 0, 220)

        命中, 坐标, 分数 = 任务.查找世界入口(画面)

        self.assertFalse(命中)
        self.assertEqual(坐标, (0, 0))
        self.assertAlmostEqual(分数, 0.0)

    def test_低分实机船体颜色候选不会绕过模板阈值(self):
        任务 = object.__new__(进入世界任务基类)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.0, (0, 0), None)
        任务.模板识别.执行匹配.return_value = (False, (0, 0), None)
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        # MuMu 当前实机截图中船体颜色连通块约为 x=263..314、
        # y=357..427，重心约 (286,392)。
        画面[357:427, 263:314] = (0, 0, 220)

        命中, 坐标, 分数 = 任务.查找世界入口(画面)

        self.assertFalse(命中)
        self.assertEqual(坐标, (0, 0))
        self.assertAlmostEqual(分数, 0.0)

    def test_夜世界返回主世界使用右上入口区域(self):
        任务 = object.__new__(到主世界任务)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.925, (96, 46), "船.bmp")

        命中, 坐标, 分数 = 任务.查找世界入口(
            np.zeros((600, 800, 3), dtype=np.uint8)
        )

        self.assertTrue(命中)
        self.assertEqual(坐标, (521, 72))
        self.assertAlmostEqual(分数, 0.925)
        区域 = 任务.模板识别.执行最佳匹配.call_args.args[0]
        self.assertEqual(区域.shape[:2], (250, 350))

    def test_原始设备截图会先归一化再搜索右上入口(self):
        """1280×720 原图不能按 800×600 坐标直接裁剪。"""
        任务 = object.__new__(到主世界任务)
        任务.船模板路径 = "船.bmp"
        任务.模板识别 = Mock()
        任务.模板识别.执行最佳匹配.return_value = (0.925, (96, 46), "船.bmp")

        命中, 坐标, 分数 = 任务.查找世界入口(
            np.zeros((720, 1280, 3), dtype=np.uint8)
        )

        self.assertTrue(命中)
        self.assertEqual(坐标, (521, 72))
        self.assertAlmostEqual(分数, 0.925)
        区域 = 任务.模板识别.执行最佳匹配.call_args.args[0]
        self.assertEqual(区域.shape[:2], (250, 350))

    def test_同一入口连续未转场后停止重复点击(self):
        模块 = importlib.import_module("任务流程.世界跳转.进入世界基类")
        时钟 = SimpleNamespace(当前时间=0.0)

        def 脚本延时(毫秒数):
            时钟.当前时间 += 毫秒数 / 1000

        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))),
            脚本延时=脚本延时,
            置脚本状态=Mock(),
            点击=Mock(),
        )
        任务 = object.__new__(进入世界任务基类)
        任务.上下文 = 上下文
        任务.状态文本 = "夜世界"
        任务.船模板路径 = "船.bmp"
        任务.滑动配置 = SimpleNamespace(起点=(1, 1), 终点=(2, 2))
        任务.是否在目标世界 = Mock(return_value=False)
        任务.识别当前世界 = Mock(return_value=SimpleNamespace(当前世界="主世界"))
        任务.查找世界入口 = Mock(return_value=(True, (188, 562), 0.75))
        任务.滑动屏幕 = Mock()

        原时间函数 = 模块.time.time
        模块.time.time = lambda: 时钟.当前时间
        try:
            self.assertFalse(任务.执行())
        finally:
            模块.time.time = 原时间函数

        上下文.点击.assert_called_once_with(188, 562)
        任务.滑动屏幕.assert_not_called()
        self.assertTrue(any("连续点击后仍未转场" in c.args[0] for c in 上下文.置脚本状态.call_args_list))

    def test_世界入口点击被输入层拒绝时停止转场(self):
        模块 = importlib.import_module("任务流程.世界跳转.进入世界基类")
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            点击=Mock(return_value=False),
            页面恢复失败=False,
        )
        任务 = object.__new__(进入世界任务基类)
        任务.上下文 = 上下文
        任务.状态文本 = "夜世界"
        任务.船模板路径 = "船.bmp"
        任务.滑动配置 = SimpleNamespace(起点=(1, 1), 终点=(2, 2))
        任务.是否在目标世界 = Mock(return_value=False)
        任务.识别当前世界 = Mock(return_value=SimpleNamespace(当前世界="主世界"))
        任务.查找世界入口 = Mock(return_value=(True, (188, 562), 0.85))
        任务.滑动屏幕 = Mock()
        任务._等待目标世界确认 = Mock()

        原时间函数 = 模块.time.time
        模块.time.time = lambda: 0.0
        try:
            self.assertFalse(任务.执行())
        finally:
            模块.time.time = 原时间函数

        self.assertTrue(上下文.页面恢复失败)
        任务._等待目标世界确认.assert_not_called()
        任务.滑动屏幕.assert_not_called()


if __name__ == "__main__":
    unittest.main()
