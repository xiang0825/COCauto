import time
import unittest
import cv2
import numpy as np
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.建筑升级.寻找建筑 import 寻找建筑, 建筑查找模式
from 任务流程.建筑升级.升级普通建筑 import (
    提取建议升级建筑名称,
    提取建议升级建筑,
    升级普通建筑任务,
)
from 任务流程.建筑升级.更新工人状态 import 更新工人状态任务
from 任务流程.建筑升级.升级英雄 import 升级英雄任务


class 建筑升级边界测试(unittest.TestCase):
    def test_建议列表没有可安全目标时收敛为安全跳过(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.查找模式 = 建筑查找模式.建议升级中的第一个可用建筑
        任务.建筑列表 = []
        任务.安全跳过 = False
        任务.排除建筑名称 = set()
        任务.上下文 = SimpleNamespace(
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务.关闭建筑页面 = Mock(return_value=True)
        任务.打开建筑页面 = Mock(return_value=True)
        任务.执行OCR识别 = Mock(return_value=[
            ([[0, 0], [80, 0], [80, 20], [0, 20]], "建議升級", 0.99),
            ([[0, 40], [80, 40], [80, 60], [0, 60]], "復活法術", 0.90),
            ([[0, 80], [80, 80], [80, 100], [0, 100]], "其他升級", 0.99),
        ])
        任务.尝试选中指定建筑 = Mock(return_value=False)

        self.assertFalse(任务.执行())
        self.assertTrue(任务.安全跳过)
        self.assertTrue(any(
            "安全跳过并等待下次检查" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_建议列表混入研究项目时建筑任务不点击研究卡片(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.查找模式 = 建筑查找模式.建议升级中的第一个可用建筑
        任务.建筑列表 = []
        任务.安全跳过 = False
        任务.排除建筑名称 = set()
        任务.上下文 = SimpleNamespace(
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务.关闭建筑页面 = Mock(return_value=True)
        任务.打开建筑页面 = Mock(return_value=True)
        任务.执行OCR识别 = Mock(return_value=[
            ([[0, 0], [80, 0], [80, 20], [0, 20]], "建議升級", 0.99),
            ([[0, 40], [80, 40], [80, 60], [0, 60]], "復活法術", 0.90),
            ([[0, 80], [80, 80], [80, 100], [0, 100]], "頭號殺手", 0.90),
            ([[0, 120], [80, 120], [80, 140], [0, 140]], "其他升級", 0.99),
        ])
        任务.尝试选中指定建筑 = Mock(return_value=False)

        self.assertFalse(任务.执行())
        self.assertTrue(任务.安全跳过)
        任务.尝试选中指定建筑.assert_not_called()
        self.assertTrue(any(
            "只有研究或非建筑项目" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_建议列表中的繁体泰坦兵种不会进入建筑点击路径(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.查找模式 = 建筑查找模式.建议升级中的第一个可用建筑
        任务.建筑列表 = []
        任务.安全跳过 = False
        任务.排除建筑名称 = set()
        任务.上下文 = SimpleNamespace(
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务.关闭建筑页面 = Mock(return_value=True)
        任务.打开建筑页面 = Mock(return_value=True)
        任务.执行OCR识别 = Mock(return_value=[
            ([[0, 0], [80, 0], [80, 20], [0, 20]], "建議升級", 0.99),
            ([[0, 40], [80, 40], [80, 60], [0, 60]], "雷電泰坦", 0.90),
            ([[0, 80], [80, 80], [80, 100], [0, 100]], "其他升級", 0.99),
        ])
        任务.尝试选中指定建筑 = Mock(return_value=False)

        self.assertFalse(任务.执行())
        self.assertTrue(任务.安全跳过)
        任务.尝试选中指定建筑.assert_not_called()
        self.assertTrue(任务._明确非普通建筑("雷電泰坦"))

    def test_建筑扫描收到停止请求后不再OCR或滑动(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.建筑列表 = ["兵营"]
        任务.安全跳过 = False
        任务.上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务.上下文.停止事件.set()
        任务.打开建筑页面 = Mock(return_value=True)
        任务.执行OCR识别 = Mock()
        任务.滑动屏幕 = Mock()

        self.assertFalse(任务.找建筑循环())
        self.assertTrue(任务.安全跳过)
        任务.执行OCR识别.assert_not_called()
        任务.滑动屏幕.assert_not_called()

    def test_建筑扫描超时安全跳过而不是杀死线程(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.建筑列表 = ["兵营"]
        任务.安全跳过 = False
        任务.上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务.打开建筑页面 = Mock(return_value=True)
        任务.执行OCR识别 = Mock(return_value=[])
        任务.滑动屏幕 = Mock()
        任务.关闭建筑页面 = Mock(return_value=True)

        with unittest.mock.patch.object(
            time, "time", side_effect=[0.0, 121.0]
        ):
            self.assertFalse(任务.找建筑循环())

        self.assertTrue(任务.安全跳过)
        任务.关闭建筑页面.assert_called_once_with()
        self.assertTrue(any(
            "本轮安全跳过" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_关闭刷资源时建筑入口仍使用主世界坐标(self):
        点击 = Mock()
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=点击,
            滑动到建筑栏底部=Mock(),
        )

        任务.打开建筑页面(划到底部=False)

        点击.assert_called_once_with(262, 33, 延时=1000)

    def test_关闭刷资源时寻找建筑滑动仍使用主世界坐标(self):
        鼠标 = SimpleNamespace(
            移动到=Mock(),
            左键按下=Mock(),
            移动相对位置=Mock(),
            左键抬起=Mock(),
        )
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            鼠标=鼠标,
            脚本延时=Mock(),
        )

        任务.滑动屏幕(0)

        鼠标.移动到.assert_called_once_with(399, 116)

    def test_建筑升级面板已打开时不会重复点击入口(self):
        点击 = Mock()
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=点击,
            置脚本状态=Mock(),
            op=SimpleNamespace(),
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [60, 10], [60, 30], [10, 30]], "升级中", 0.95),
            ([[10, 40], [60, 40], [60, 60], [10, 60]], "建升级", 0.95),
        ])

        任务.打开建筑页面(划到底部=False)

        点击.assert_not_called()
        任务.上下文.置脚本状态.assert_called_once()

    def test_建筑升级入口点击被拒绝时不继续读取列表(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
            op=SimpleNamespace(),
        )
        任务._建筑升级面板已打开 = Mock(return_value=False)

        self.assertFalse(任务.打开建筑页面(划到底部=False))
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_建筑候选点击被拒绝时不报告已选中(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
        )

        self.assertFalse(任务.选中建筑(100, 100, 140, 140))
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_关闭英雄殿堂后清除主世界升级浮层(self):
        点击 = Mock(return_value=True)
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(点击=点击, 脚本延时=Mock())

        任务._关闭英雄殿堂()

        self.assertEqual(
            点击.call_args_list,
            [
                unittest.mock.call(356, 33, 延时=700),
                unittest.mock.call(700, 300, 延时=500, 是否精确点击=True),
            ],
        )

    def test_英雄目标首次可见时先OCR不做回顶部滑动(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [80, 10], [80, 30], [10, 30]], "弓箭女皇", 0.99),
        ])
        任务._英雄殿堂已打开 = Mock(return_value=True)
        任务._尝试选中指定英雄 = Mock(return_value=True)
        任务._重置英雄殿堂滚动位置 = Mock()

        self.assertTrue(任务._寻找指定英雄(["弓箭女皇"]))
        任务._重置英雄殿堂滚动位置.assert_not_called()
        任务._尝试选中指定英雄.assert_called_once()

    def test_英雄入口未打开时精确重试且禁止地图滑动(self):
        点击 = Mock(return_value=True)
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            点击=点击,
            脚本延时=Mock(),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )
        任务._英雄殿堂已打开 = Mock(side_effect=[False, False])
        任务._重置英雄殿堂滚动位置 = Mock()
        任务._滑动英雄殿堂 = Mock()

        self.assertFalse(任务._寻找指定英雄(["弓箭女皇"]))
        self.assertTrue(任务.上下文.页面恢复失败)
        self.assertEqual(
            点击.call_args_list,
            [
                unittest.mock.call(356, 33, 延时=1000),
                unittest.mock.call(356, 33, 延时=700, 是否精确点击=True),
            ],
        )
        任务._重置英雄殿堂滚动位置.assert_not_called()
        任务._滑动英雄殿堂.assert_not_called()

    def test_关闭建筑页面被拒绝时标记页面恢复失败(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(任务.关闭建筑页面())
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_英雄升级详情关闭被拒绝时不继续清除浮层(self):
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(
            关闭升级详情弹窗=Mock(return_value=False),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(任务.关闭英雄升级页面())
        任务.上下文.关闭升级详情弹窗.assert_called_once_with()
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_建议列表跳过本轮已提交的项目(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.建筑列表 = ["头号杀手", "攻城车"]
        任务.排除建筑名称 = {"头号杀手"}
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        任务.检查升级条件 = Mock(return_value=True)
        任务.选中建筑 = Mock(return_value=True)

        OCR = [
            ([[10, 10], [70, 10], [70, 30], [10, 30]], "头号杀手", 0.99),
            ([[80, 10], [130, 10], [130, 30], [80, 30]], "攻城车", 0.99),
        ]
        self.assertTrue(任务.尝试选中指定建筑(OCR))
        任务.选中建筑.assert_called_once()
        self.assertIn("跳过本轮已提交", " ".join(
            调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_主世界单独出现升级中不会被当成建筑面板(self):
        任务 = 寻找建筑.__new__(寻找建筑)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否刷主世界=False),
            点击=Mock(),
            置脚本状态=Mock(),
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [60, 10], [60, 30], [10, 30]], "升级中", 0.95),
        ])

        self.assertFalse(任务._建筑升级面板已打开())

    def test_OCR只定位底部升级按钮不接受升级中文字(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[10, 10], [60, 10], [60, 30], [10, 30]], "升级中", 0.99),
            ([[520, 492], [546, 492], [546, 511], [520, 511]], "升级", 0.99),
        ])

        self.assertEqual(任务._OCR定位升级按钮(), (533, 502))

    def test_缩放模板只在限定区域且达到新版阈值时返回坐标(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: object()
            ),
            置脚本状态=Mock(),
        )
        任务.模板识别 = SimpleNamespace(
            执行最佳匹配=Mock(return_value=(0.65, (42, 58), "建筑升级界面锤子[1].bmp"))
        )

        self.assertEqual(任务._局部模板定位升级按钮(), (517, 463))

        任务.模板识别.执行最佳匹配.return_value = (0.63, (42, 58), "建筑升级界面锤子[1].bmp")
        self.assertIsNone(任务._局部模板定位升级按钮())

    def test_绿色确认按钮返回底部卡片中心(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace()
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[475, 490], [505, 490], [505, 515], [475, 515]], "升级", 0.99),
        ])

        self.assertEqual(任务._定位升级确认按钮(), (490, 502))

    def test_建筑升级页面关闭时明确授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭建筑升级页面()

        返回.assert_called_once_with(
            "关闭建筑升级页面", 已确认可关闭面板=True
        )

    def test_建筑升级页面优先点击主世界空白区域不发送返回键(self):
        点击 = Mock(return_value=True)
        返回 = Mock(return_value=True)
        状态 = Mock()
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(点击=点击, 安全返回键=返回, 置脚本状态=状态)

        self.assertTrue(任务.关闭建筑升级页面())
        点击.assert_called_once_with(700, 300, 延时=700, 是否精确点击=True)
        返回.assert_not_called()

    def test_详情关闭器未命中时继续清除建筑选中面板(self):
        关闭详情 = Mock(return_value=False)
        点击 = Mock(return_value=True)
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            关闭升级详情弹窗=关闭详情,
            点击=点击,
            置脚本状态=Mock(),
        )

        self.assertTrue(任务._安全关闭当前建筑面板())
        关闭详情.assert_called_once_with()
        点击.assert_called_once_with(700, 300, 延时=700, 是否精确点击=True)

    def test_安全空白点击后主页复核会清除详情器遗留失败标志(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        上下文 = SimpleNamespace(
            关闭升级详情弹窗=Mock(return_value=False),
            点击=Mock(return_value=True),
            识别点击画面=Mock(
                return_value=SimpleNamespace(页面="主世界主页", 世界="主世界")
            ),
            页面恢复失败=True,
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文

        self.assertTrue(任务._安全关闭当前建筑面板())
        self.assertFalse(上下文.页面恢复失败)
        上下文.识别点击画面.assert_called_once_with(强制=True)

    def test_绿色立即完成区域不会被当成资源确认按钮(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace()
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[423, 492], [467, 492], [467, 510], [423, 510]], "立即完成", 0.99),
        ])

        self.assertIsNone(任务._定位升级确认按钮())

    def test_升级进行中面板不会被当成新的升级按钮(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace(), 置脚本状态=Mock())
        任务.执行OCR识别 = Mock(return_value=[
            ([[300, 30], [500, 30], [500, 60], [300, 60]], "正在進行升級", 0.99),
            ([[420, 490], [470, 490], [470, 515], [420, 515]], "立即完成", 0.99),
        ])

        self.assertTrue(任务._当前已在升级中())
        self.assertIsNone(任务._定位升级确认按钮())

    def test_建筑升级入口点击被拒绝时不继续识别确认按钮(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        点击 = Mock(return_value=False)
        任务.上下文 = SimpleNamespace(
            点击=点击,
            置脚本状态=Mock(),
        )
        任务.要升级的建筑 = "测试建筑"
        任务.相似度阈值 = 0.8
        任务.安全跳过 = False
        任务._当前已在升级中 = Mock(return_value=False)
        任务._当前是英雄或研究详情 = Mock(return_value=False)
        任务.是否出现图片 = Mock(return_value=(True, (480, 500)))
        任务._OCR定位升级按钮 = Mock(return_value=(480, 500))
        任务._升级确认按钮可用 = Mock(return_value=True)
        任务._安全关闭当前建筑面板 = Mock(return_value=True)

        self.assertFalse(任务.执行())
        任务._升级确认按钮可用.assert_not_called()
        任务._安全关闭当前建筑面板.assert_called_once_with()

    def test_建筑升级确认点击被拒绝时不报告提交成功(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        点击 = Mock(side_effect=[True, False])
        任务.上下文 = SimpleNamespace(
            点击=点击,
            置脚本状态=Mock(),
        )
        任务.要升级的建筑 = "测试建筑"
        任务.相似度阈值 = 0.8
        任务.安全跳过 = False
        任务._当前已在升级中 = Mock(return_value=False)
        任务._当前是英雄或研究详情 = Mock(return_value=False)
        任务.是否出现图片 = Mock(return_value=(True, (480, 500)))
        任务._OCR定位升级按钮 = Mock(return_value=(480, 500))
        任务._升级确认按钮可用 = Mock(side_effect=[True])
        任务._定位升级确认按钮 = Mock(return_value=(500, 500))
        任务._安全关闭当前建筑面板 = Mock(return_value=True)

        self.assertFalse(任务.执行())
        任务._安全关闭当前建筑面板.assert_called_once_with()

    def test_英雄研究详情不会走普通建筑锤子模板(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace(), 置脚本状态=Mock())
        任务.执行OCR识别 = Mock(return_value=[
            ([[500, 470], [560, 470], [560, 500], [500, 500]], "研究", 0.99),
            ([[300, 470], [360, 470], [360, 500], [300, 500]], "等待", 0.99),
        ])

        self.assertTrue(任务._当前是英雄或研究详情())

    def test_全屏锤子命中但没有底部升级文字时禁止点击(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        点击 = Mock()
        关闭 = Mock()
        任务.要升级的建筑 = "测试建筑"
        任务.相似度阈值 = 0.8
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(), 点击=点击, 处理异常=Mock(),
            关闭升级详情弹窗=关闭,
        )
        任务.是否出现图片 = Mock(return_value=(True, (500, 500)))
        任务._当前已在升级中 = Mock(return_value=False)
        任务._当前是英雄或研究详情 = Mock(return_value=False)
        任务._OCR定位升级按钮 = Mock(return_value=None)
        任务.关闭建筑升级页面 = 关闭

        self.assertFalse(任务.执行())
        点击.assert_not_called()
        self.assertEqual(关闭.call_count, 2)

    def test_确认文字被OCR误识别时使用升级确认标题(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[312, 29], [483, 29], [483, 60], [312, 60]], "将聖水收集器升至17级？", 0.95),
            ([[548, 494], [574, 494], [574, 514], [548, 514]], "雅韧", 0.66),
        ])

        self.assertEqual(任务._定位升级确认按钮(), (560, 522))

    def test_真实升级文字位于资源卡片时允许点击且不覆盖宝石卡片(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[475, 490], [505, 490], [505, 512], [475, 512]], "升级", 0.99),
            ([[548, 490], [580, 490], [580, 512], [548, 512]], "立即完成", 0.99),
        ])

        self.assertEqual(任务._定位升级确认按钮(), (490, 501))

    def test_英雄绿色确认文字只接受右侧确认卡片(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[550, 490], [590, 490], [590, 515], [550, 515]], "確", 0.99),
        ])

        self.assertEqual(任务._定位升级确认按钮(), (570, 502))

    def test_英雄左侧灰色确认按钮不会被点击(self):
        任务 = 升级普通建筑任务.__new__(升级普通建筑任务)
        任务.上下文 = SimpleNamespace(op=SimpleNamespace())
        任务.执行OCR识别 = Mock(return_value=[
            ([[420, 490], [460, 490], [460, 515], [420, 515]], "確", 0.99),
        ])

        self.assertIsNone(任务._定位升级确认按钮())

    def test_建筑坐标右边界跟随OCR框而不是固定值(self):
        任务 = 寻找建筑.__new__(寻找建筑)

        self.assertEqual(
            任务.解析坐标([[10, 20], [50, 20], [50, 40], [10, 40]]),
            (229, 77, 269, 97),
        )

    def test_空OCR坐标被拒绝(self):
        任务 = 寻找建筑.__new__(寻找建筑)

        with self.assertRaises(ValueError):
            任务.解析坐标([])

    def test_建议升级标题被截断且没有其他升级标题时仍提取建筑(self):
        OCR = [
            ([[50, 20], [100, 20], [100, 40], [50, 40]], "升级中", 0.96),
            ([[50, 60], [100, 60], [100, 80], [50, 80]], "建升级", 0.98),
            ([[50, 90], [150, 90], [150, 110], [50, 110]], "圣水收集器x5", 0.96),
            ([[250, 90], [320, 90], [320, 110], [250, 110]], "8000000", 0.99),
            ([[50, 120], [130, 120], [130, 140], [50, 140]], "可使用", 0.99),
            ([[50, 150], [130, 150], [130, 170], [50, 170]], "野蛮人之王", 0.95),
        ]

        self.assertEqual(
            提取建议升级建筑名称(OCR),
            ["圣水收集器x5", "野蛮人之王"],
        )
        self.assertEqual(
            [项目[1] for 项目 in 提取建议升级建筑(OCR)],
            ["圣水收集器x5", "野蛮人之王"],
        )

    def test_繁体建筑名置信度七成仍可作为建议升级候选(self):
        OCR = [
            ([[2, 40], [50, 40], [50, 58], [2, 58]], "建升级", 0.91),
            ([[2, 70], [60, 70], [60, 88], [2, 88]], "頭號殺手", 0.77),
            ([[2, 100], [50, 100], [50, 118], [2, 118]], "其他升级", 0.97),
        ]

        self.assertEqual(
            提取建议升级建筑名称(OCR, 最低置信度=0.70),
            ["頭號殺手"],
        )


class 工人状态容错测试(unittest.TestCase):
    def _创建任务(self, 状态):
        任务 = 更新工人状态任务.__new__(更新工人状态任务)
        任务.机器人标志 = "robot_1"
        任务.数据库 = SimpleNamespace(
            获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据=状态))
        )
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        return 任务

    def test_工人状态缺字段时返回False而不是抛异常(self):
        任务 = self._创建任务({"工人状态": {"空闲工人": 1}})

        self.assertFalse(任务.是否有空闲工人())
        日志 = " ".join(调用.args[0] for 调用 in 任务.上下文.置脚本状态.call_args_list)
        self.assertIn("字段缺失或无效", 日志)

    def test_工人状态字段格式错误时返回False(self):
        任务 = self._创建任务({
            "工人状态": {
                "空闲工人": "?",
                "工人总数": 5,
                "更新时间": time.time(),
            }
        })

        self.assertFalse(任务.是否有空闲工人())

    def test_实机顶部建筑工人计数使用左侧1加斜线2区域(self):
        任务 = 更新工人状态任务.__new__(更新工人状态任务)
        任务.机器人标志 = "robot_1"
        任务.执行OCR识别 = Mock(return_value=[
            ([[12, 12], [38, 12], [38, 34], [12, 34]], "1/2", 0.99),
        ])
        任务.数据库 = SimpleNamespace(更新状态=Mock())
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())

        self.assertTrue(任务.识别当前工人状态写入数据库())
        任务.执行OCR识别.assert_called_once_with((285, 0, 335, 60))
        self.assertEqual(
            任务.数据库.更新状态.call_args.args[2]["工人总数"],
            2,
        )

    def test_顶部窄区域为空时使用宽区域回退且过滤英雄栏(self):
        任务 = 更新工人状态任务.__new__(更新工人状态任务)
        任务.机器人标志 = "robot_1"
        任务.执行OCR识别 = Mock(side_effect=[
            [],
            [
                # 回退区域从 x=250 开始；全局中心约 305，属于工人栏。
                ([[45, 10], [65, 10], [65, 34], [45, 34]], "1/2", 0.88),
                # 右侧英雄栏 1/7 不得覆盖工人计数。
                ([[150, 10], [170, 10], [170, 34], [150, 34]], "1/7", 0.99),
            ],
        ])
        任务.数据库 = SimpleNamespace(更新状态=Mock())
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())

        self.assertTrue(任务.识别当前工人状态写入数据库())
        self.assertEqual(任务.执行OCR识别.call_args_list[1].args[0], (250, 0, 370, 85))
        self.assertEqual(
            任务.数据库.更新状态.call_args.args[2]["空闲工人"],
            1,
        )

    def test_MuMu对顶部1加斜线2误识别前导减号仍解析为1加斜线2(self):
        任务 = 更新工人状态任务.__new__(更新工人状态任务)

        self.assertEqual(
            任务.解析工人计数([
                ([[0, 0], [42, 0], [42, 30], [0, 30]], "-1/2", 0.87),
            ]),
            (1, 2),
        )

    def test_非法负数和英雄栏文本不会成为工人状态(self):
        任务 = 更新工人状态任务.__new__(更新工人状态任务)

        with self.assertRaises(ValueError):
            任务.解析工人计数([
                ([[0, 0], [42, 0], [42, 30], [0, 30]], "-8/2", 0.99),
                ([[0, 0], [42, 0], [42, 30], [0, 30]], "英雄升级中", 0.99),
            ])


class 英雄升级确认页测试(unittest.TestCase):
    def test_英雄殿堂右上角关闭按钮自适应识别(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(屏幕, (720, 40), (780, 100), (0, 0, 220), -1)
        cv2.line(屏幕, (735, 55), (765, 85), (255, 255, 255), 5)
        cv2.line(屏幕, (765, 55), (735, 85), (255, 255, 255), 5)

        结果 = 升级英雄任务._检测英雄殿堂关闭点(屏幕)

        self.assertIsNotNone(结果)
        self.assertAlmostEqual(结果[0], 750, delta=5)
        self.assertAlmostEqual(结果[1], 70, delta=5)

    def test_普通主世界没有英雄殿堂关闭按钮(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        self.assertIsNone(升级英雄任务._检测英雄殿堂关闭点(屏幕))

    def test_繁体标题和绿色资源按钮可以确认升级页(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[465:570, 465:640] = (40, 190, 100)
        OCR = [
            ([[0, 0], [180, 0], [180, 30], [0, 30]], "將野人之王升至84级？", 0.92),
            ([[0, 0], [80, 0], [80, 20], [0, 20]], "195000", 0.99),
        ]

        self.assertTrue(
            升级英雄任务._识别英雄升级确认页(OCR, 屏幕, "野蛮人之王")
        )

    def test_宝石或立即完成文字会阻断英雄升级确认(self):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        屏幕[465:570, 465:640] = (40, 190, 100)
        OCR = [
            ([[0, 0], [180, 0], [180, 30], [0, 30]], "將野人之王升至84级？", 0.92),
            ([[0, 0], [80, 0], [80, 20], [0, 20]], "使用宝石立即完成", 0.99),
        ]

        self.assertFalse(
            升级英雄任务._识别英雄升级确认页(OCR, 屏幕, "野蛮人之王")
        )

    def test_英雄升级确认点击被拒绝时不报告成功(self):
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))),
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
        )
        任务.要升级的英雄 = "野蛮人之王"
        任务.执行OCR识别 = Mock(return_value=[])
        任务._识别英雄升级确认页 = Mock(return_value=True)
        任务.关闭英雄升级页面 = Mock(return_value=True)
        任务.安全跳过 = False

        self.assertFalse(任务.执行())
        任务.关闭英雄升级页面.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
