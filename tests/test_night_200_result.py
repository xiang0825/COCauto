"""rc162 11-27 19:56 夜世界两阶段 200% 结算与“勝利之星獎勵！”待命卡死回放。

1. 两阶段打出 200%、三颗银星的结算页没有胜负文字，旧解析只认 0~100%
   和金色星，得到“未知/待识别/40%”，结算统计永远不完整，300 秒超时。
2. 回营后出现单按钮“勝利之星獎勵！”弹窗，安全待命一律只读，弹窗不会
   自己消失，180 秒后再次卡死。

样本均为现场截图只读复制。
"""
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 模块.检测.OCR识别器 import 安全OCR引擎
from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务

测试目录 = Path(__file__).resolve().parent
样本目录 = 测试目录 / "回放样本"
两阶段结算图 = 样本目录 / "night_200_result_20261127_195602.png"
星级奖励图 = 样本目录 / "night_star_reward_20261127_195902.png"
单阶段结算图 = 样本目录 / "standby_night_settle_20261127_152329.png"
夜世界主页图 = sorted((样本目录 / "16比9").glob("night_home_boat_cart_*.jpg"))[0]


def 读取(文件: Path) -> np.ndarray:
    图像 = cv2.imdecode(np.fromfile(str(文件), dtype=np.uint8), cv2.IMREAD_COLOR)
    if 图像 is None:
        raise AssertionError(f"无法读取样本：{文件}")
    if 图像.shape[:2] != (600, 800):
        图像 = cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)
    return 图像


class 夜世界两阶段结算回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.OCR = 安全OCR引擎()
        cls.识别器 = 页面识别器(模板匹配引擎(图片库路径=测试目录.parent / "img"))

    def _任务(self, 上限=200):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.ocr引擎 = self.OCR
        任务._本次结算摧毁率上限 = 上限
        return 任务

    def test_200结算页识别为结算并定位底部回营(self):
        图 = 读取(两阶段结算图)
        结果 = self.识别器.识别(图, 战斗中=True)
        self.assertEqual(结果.页面, "战斗结算", 结果.摘要())
        x, y = self.识别器.定位结算回营按钮(图)
        self.assertTrue(340 <= x <= 460 and 480 <= y <= 535, (x, y))

    def test_200结算页读出200摧毁率与三颗银星(self):
        图 = 读取(两阶段结算图)
        任务 = self._任务()
        _, 文本, 战斗结果, 摧毁率 = 任务.识别结算帧(图)
        self.assertEqual(摧毁率, 200, 文本)
        self.assertEqual(等待战斗结束并回营任务.识别星数(图, 文本), 3, 文本)
        # 主世界上限 100：不接受 200%，避免资源数字粘连误读。
        _, _, _, 主世界摧毁率 = self._任务(100).识别结算帧(图)
        self.assertNotEqual(主世界摧毁率, 200)

    def test_单阶段夜世界结算仍为100与三星(self):
        图 = 读取(单阶段结算图)
        任务 = self._任务()
        _, 文本, _, 摧毁率 = 任务.识别结算帧(图)
        self.assertEqual(摧毁率, 100, 文本)
        self.assertEqual(等待战斗结束并回营任务.识别星数(图, 文本), 3)

    def test_夜世界200结算统计完整记录且不压回100(self):
        图 = 读取(两阶段结算图)
        任务 = self._任务()
        任务._画面仍在战斗 = Mock(return_value=False)
        任务.保存战斗结果截图 = Mock()
        任务.更新战斗学习 = Mock(return_value={})
        任务.生成战斗诊断 = Mock(return_value="两阶段200%")
        数据库 = Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="测试机器人",
            置脚本状态=Mock(),
            本场实时摧毁率=40,
            本场最高实时摧毁率=40,
            本场目标战利品={},
            英雄技能状态={},
        )
        self.assertTrue(任务.记录战斗结果(
            上下文, 图, 结算页已复核=True, 战斗世界="夜世界",
        ))
        self.assertEqual(数据库.更新状态.call_args.args[1], "夜世界战斗胜率")
        统计 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(统计["最近结果"], "胜利")
        self.assertEqual(统计["最近星数"], 3)
        self.assertEqual(统计["最近摧毁率"], 200)

    def test_主世界三星校正仍把漏读摧毁率补为100(self):
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率("胜利", 3, 87, 结算页已复核=True), 100
        )
        self.assertEqual(
            等待战斗结束并回营任务.校正三星摧毁率("胜利", 3, 200, 结算页已复核=True), 200
        )
        self.assertEqual(等待战斗结束并回营任务.合并本场摧毁率(200, 40), 200)


class 安全待命勝利之星獎勵回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.OCR = 安全OCR引擎()
        cls.识别器 = 页面识别器(模板匹配引擎(图片库路径=测试目录.parent / "img"))

    def _上下文(self, 帧序列, OCR=None):
        上下文 = 任务上下文.__new__(任务上下文)
        帧 = iter(帧序列)
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(side_effect=lambda *a, **k: next(帧)))
        上下文._点击页面识别器 = self.识别器
        上下文._获取点击页面识别器 = lambda: self.识别器
        上下文.获取OCR引擎 = lambda: OCR or self.OCR
        上下文._存在中央宝石危险模板 = Mock(return_value=(False, ""))
        上下文.清除战斗结算保护状态 = Mock()
        上下文.停止事件 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        return 上下文

    def test_现场帧识别为战斗星级奖励并定位确定(self):
        图 = 读取(星级奖励图)
        结果 = self.识别器.识别(图, 战斗中=False)
        self.assertEqual(结果.页面, "战斗星级奖励", 结果.摘要())
        x, y = self.识别器.定位战斗星级奖励确定按钮(图)
        self.assertTrue(340 <= x <= 460 and 440 <= y <= 495, (x, y))

    def test_只点確定并确认弹窗消失(self):
        上下文 = self._上下文([读取(星级奖励图), 读取(夜世界主页图)])
        self.assertTrue(上下文.安全待命确认战斗星级奖励())
        上下文.点击已确认安全按钮.assert_called_once()
        x, y = 上下文.点击已确认安全按钮.call_args.args[:2]
        self.assertTrue(340 <= x <= 460 and 440 <= y <= 495, (x, y))
        上下文.清除战斗结算保护状态.assert_called_once()

    def test_点击后弹窗仍在则返回失败(self):
        上下文 = self._上下文([读取(星级奖励图), 读取(星级奖励图)])
        self.assertFalse(上下文.安全待命确认战斗星级奖励())
        上下文.点击已确认安全按钮.assert_called_once()

    def test_出现宝石或购买字样时不点击(self):
        def 危险OCR(图):
            结果, 其它 = self.OCR(图)
            return list(结果 or []) + [[[[0, 0], [1, 0], [1, 1], [0, 1]], "使用寶石購買", 0.99]], 其它

        上下文 = self._上下文([读取(星级奖励图)], OCR=危险OCR)
        self.assertFalse(上下文.安全待命确认战斗星级奖励())
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertTrue(上下文.页面恢复失败)

    def test_非星级奖励页不发送输入(self):
        上下文 = self._上下文([读取(夜世界主页图)])
        self.assertFalse(上下文.安全待命确认战斗星级奖励())
        上下文.点击已确认安全按钮.assert_not_called()


if __name__ == "__main__":
    unittest.main()
