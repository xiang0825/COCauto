"""部落竞赛接任务：白名单选择、护栏禁点、活动结束跳过、超时。

用一个模拟游戏画面驱动真实流程代码：OCR 和模板匹配按模拟状态返回，
坐标和文字取自 2026-11-24 实机截图（繁体界面）的 OCR 输出。
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from 任务流程.活动 import 部落竞赛 as 模块
from 任务流程.活动.部落竞赛 import (
    任务候选,
    加载配置,
    官方API判断满分,
    含禁点文字,
    文字项,
    解析个人积分,
    解析积分,
    识别任务类型,
    识别卡片位置,
    选择任务,
    部落竞赛任务,
)
from 数据库.任务数据库 import 机器人设置, 规范化任务计划顺序

配置 = 加载配置()
核心白名单 = ["掠夺金币", "掠夺圣水", "掠夺黑油", "摧毁资源建筑"]

# 实机 OCR 原文（含识别错字）
文本_金币 = "在單場多人避門中掠200000金。"
文本_黑油 = "在單場多人門中掠5000黑重油。"
文本_夜世界 = "在建築大師载門中摧毁1個建築大師大本营。"
文本_指定兵种 = "在場多人避中赢得1颗勝利之星，至少需使用"
文本_捐兵 = "向部落成員增援總計45空間的部。"
文本_法术工厂 = "在多人戴中推毁4個間黑法術工廠"
文本_拆建筑 = "在多人遊戲中摧毀75座建築"


def ocr(文字, x1, y1, x2, y2):
    return ([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], 文字, 0.95)


卡片位置 = [
    [(341, 165), (438, 165), (535, 165), (632, 165), (341, 330), (438, 330), (535, 330), (632, 330)],
    [(341, 360), (438, 360), (535, 360), (632, 360)],
]


class 模拟游戏:
    """极简状态机：home → events → panel(page, detail)。"""

    def __init__(self, 卡片=None, 有活动按钮=True, 有部落竞赛=True, 需滑动=1,
                 个人积分="3350/10000", 面板会出现=True, 开始后显示放弃=True, 已有任务=False):
        self.状态 = "home"
        self.页 = 0
        self.详情 = None
        self.列表滑动 = 0
        self.有活动按钮 = 有活动按钮
        self.有部落竞赛 = 有部落竞赛
        self.需滑动 = 需滑动
        self.个人积分 = 个人积分
        self.面板会出现 = 面板会出现
        self.开始后显示放弃 = 开始后显示放弃
        默认 = [dict(文本=文本_夜世界, 积分="150")] * 12
        self.卡片 = list(卡片 or 默认)
        self.点击记录 = []
        self.开始点击 = []
        self.已接 = 0 if 已有任务 else None

    # --- 输入
    def 点击(self, x, y):
        self.点击记录.append((self.状态, x, y))
        def 近(点, 半径=30):
            return abs(x - 点[0]) <= 半径 and abs(y - 点[1]) <= 半径
        if self.状态 == "home" and 近((196, 556)):
            self.状态 = "events"
        elif self.状态 == "events" and 近((660, 45)):
            self.状态 = "home"
        elif self.状态 == "events" and self.有部落竞赛 and 近((592, 492)):
            self.状态 = "panel" if self.面板会出现 else "loading"
            self.页 = 0
        elif self.状态 == "panel" and 近((709, 40)):
            self.状态, self.详情 = "home", None
        elif self.状态 == "panel" and self.详情 is not None and 近((507, 418)):
            self.开始点击.append(self.详情)
            if self.开始后显示放弃:
                self.已接 = self.详情
        elif self.状态 == "panel" and 近((160, 500)):
            self.详情 = None
        elif self.状态 == "panel":
            for 序, 位置 in enumerate(卡片位置[self.页]):
                if 近(位置, 10):
                    self.详情 = 序 + (8 if self.页 == 1 else 0)
                    break
        return True

    def 滑动(self, 起点, 终点):
        if self.状态 == "events":
            self.列表滑动 += 1
        elif self.状态 == "panel":
            self.页 = 1 if 起点[1] > 终点[1] else 0

    # --- 识别
    def ocr结果(self):
        if self.状态 == "events":
            结果 = [ocr("活動", 380, 35, 420, 55)]
            if self.有部落竞赛 and self.列表滑动 >= self.需滑动:
                结果 += [ocr("部落競賽", 140, 368, 200, 384), ocr("開啟", 575, 484, 610, 500)]
            return 结果
        if self.状态 == "panel":
            结果 = [ocr("部落競赛", 95, 26, 216, 93), ocr(self.个人积分, 120, 532, 210, 552)]
            if self.详情 is not None:
                卡 = self.卡片[self.详情]
                if self.已接 == self.详情:
                    结果.append(ocr("放棄", 494, 407, 524, 430))
                elif not 卡.get("冷却"):
                    结果.append(ocr("開始", 494, 407, 524, 430))
                结果 += [ocr(卡["文本"], 358, 293, 549, 310), ocr(卡["积分"], 349, 377, 406, 410)]
                if 卡.get("附加"):
                    结果.append(ocr(卡["附加"], 360, 330, 450, 350))
            return 结果
        return []

    def 模板(self, 名称, 区域):
        点 = None
        if 名称 == "活动按钮" and self.状态 == "home" and self.有活动按钮:
            点 = (196, 556)
        elif 名称 == "活动列表关闭" and self.状态 == "events":
            点 = (660, 45)
        elif 名称 == "开启按钮" and self.状态 == "events" and self.有部落竞赛 and self.列表滑动 >= self.需滑动:
            点 = (592, 492)
        elif 名称 in ("面板标题",) and self.状态 == "panel":
            点 = (156, 60)
        elif 名称 == "关闭按钮" and self.状态 == "panel":
            点 = (709, 40)
        elif (名称 == "开始按钮" and self.状态 == "panel" and self.详情 is not None
              and self.已接 != self.详情 and not self.卡片[self.详情].get("冷却")):
            点 = (507, 418)
        elif 名称 == "宝石图标" and self.状态 == "panel" and self.详情 is not None and self.卡片[self.详情].get("宝石"):
            点 = (420, 340)
        if 点 is None:
            return None
        if 区域 is not None:
            x1, y1, x2, y2 = 区域
            if not (x1 <= 点[0] <= x2 and y1 <= 点[1] <= y2):
                return None
        return 点


class 假数据库:
    def __init__(self):
        self.状态 = {}

    def 获取最新完整状态(self, 标志):
        return SimpleNamespace(状态数据=dict(self.状态))

    def 更新状态(self, 标志, 类型, 数据):
        self.状态[类型] = 数据


def 构造任务(游戏, 设置=None, 数据库=None, 配置覆盖=None, 官方摘要=None):
    时间 = {"t": 0.0}
    日志 = []
    通知 = []
    设置 = 设置 or SimpleNamespace(
        是否部落竞赛接任务=True,
        部落竞赛任务白名单=list(核心白名单),
        部落竞赛检查间隔分钟=30,
        部落竞赛个人积分上限=4000,
    )

    def 延时(毫秒):
        时间["t"] += 毫秒 / 1000.0

    def 点击(x, y, 延时=None, 是否精确点击=False):
        时间["t"] += 0.5
        return 游戏.点击(x, y)

    上下文 = SimpleNamespace(
        机器人标志="robot_test",
        数据库=数据库 or 假数据库(),
        设置=设置,
        # 正常卡片是彩色；接了任务后其余卡片变灰。
        op=SimpleNamespace(获取屏幕图像cv=lambda *a, **k: np.full(
            (600, 800, 3), (128, 128, 128) if 游戏.已接 is not None else (40, 160, 230), np.uint8)),
        获取OCR引擎=lambda: (lambda 图: (游戏.ocr结果(), None)),
        获取模板识别器=lambda: None,
        识别点击画面=lambda 强制=False: SimpleNamespace(
            页面="主世界主页" if 游戏.状态 == "home" else "未知", 世界="主世界"),
        点击=点击,
        滑动屏幕=lambda a, b: 游戏.滑动(a, b),
        脚本延时=延时,
        置脚本状态=lambda 文本, *a: 日志.append(文本),
        发送企业微信通知=lambda 文本, 包含截图=True: 通知.append(文本),
        停止事件=None,
        页面恢复失败=False,
    )
    任务配置 = dict(配置)
    if 配置覆盖:
        任务配置.update(配置覆盖)
    任务 = 部落竞赛任务(上下文, 配置=任务配置, 官方摘要=官方摘要, 时钟=lambda: 时间["t"],
                    现在=lambda: datetime(2026, 11, 24, 21, 0))
    任务._匹配模板 = lambda 图像, 名称, 区域=None: 游戏.模板(名称, 区域)
    return 任务, 上下文, 日志, 通知, 时间


class 白名单识别测试(unittest.TestCase):
    def test_按积分数字定位任务卡(self):
        # 接任务后第二页实机 OCR：只剩 5 张完整卡，第 4 行只有 1 张。
        项 = [
            文字项("1508", (335, 233, 383, 262)), 文字项("1508", (432, 234, 477, 260)),
            文字项("8008", (522, 233, 574, 261)), 文字项("6008", (619, 233, 670, 261)),
            文字项("2008", (330, 396, 382, 424)),
            文字项("0/1", (329, 223, 357, 241)),   # 进行中卡片的进度，不是积分
            文字项("3350/10000", (120, 532, 210, 552)),  # 个人积分，在卡片区外
            文字项("200", (330, 92, 380, 104)),   # 被顶栏截掉一半的卡，不点
        ]
        self.assertEqual(
            识别卡片位置(项, 配置),
            [(344, 183), (439, 184), (533, 183), (629, 183), (341, 346)],
        )
        self.assertEqual(识别卡片位置([], 配置), [])

    def test_收集器不会被全局排除词误拦(self):
        self.assertEqual(识别任务类型("在多人遊戲中摧毀10座聖水收集器", 配置), "摧毁资源建筑")
        self.assertEqual(识别任务类型("在多人對戰中摧毀8座圣水收集器", 配置), "摧毁资源建筑")
        # 夜世界/捐兵等仍按精确词排除
        self.assertIsNone(识别任务类型("在建築大師戰鬥中摧毀5座聖水收集器", 配置))

    def test_空白点不落在任何实机详情弹窗内(self):
        # 2026-11-24 实机截图量出的详情弹窗外框（800x600），覆盖三行四列各位置。
        弹窗外框 = [
            (140, 95, 390, 355),   # 第1行第2列（弹窗在左）
            (400, 95, 650, 355),   # 第1行第1列
            (470, 205, 600, 470),  # 第2行第2列（弹窗在左下）
            (330, 215, 585, 470),  # 第2行第4列
            (140, 200, 390, 470),  # 第2行第2列 / 第3行第2列（弹窗在左）
            (515, 230, 770, 470),  # 第3行第3列
        ]
        x, y = 配置["面板"]["空白点"]
        for 框 in 弹窗外框:
            self.assertFalse(框[0] <= x <= 框[2] and 框[1] <= y <= 框[3], 框)

    def test_实机OCR文本分类(self):
        self.assertEqual(识别任务类型(文本_金币, 配置), "掠夺金币")
        self.assertEqual(识别任务类型(文本_黑油, 配置), "掠夺黑油")
        self.assertEqual(识别任务类型("在單場多人遊戲戰鬥中掠奪300000聖水。", 配置), "掠夺圣水")
        self.assertEqual(识别任务类型("在多人對戰中摧毀10座金礦", 配置), "摧毁资源建筑")
        self.assertEqual(识别任务类型("在多人對戰中摧毀5座加農炮", 配置), "摧毁防御建筑")
        self.assertEqual(识别任务类型("在多人對戰中贏得3場勝利", 配置), "多人对战胜利")
        for 文本 in (文本_夜世界, 文本_指定兵种, 文本_捐兵, 文本_法术工厂, 文本_拆建筑, ""):
            self.assertIsNone(识别任务类型(文本, 配置), 文本)

    def test_积分解析(self):
        self.assertEqual(解析积分([文字项("1508", (0, 0, 1, 1))]), 150)
        self.assertEqual(解析积分([文字项(" 300", (0, 0, 1, 1)), 文字项("5000黑", (0, 0, 1, 1))]), 300)
        self.assertIsNone(解析积分([文字项("8小時", (0, 0, 1, 1))]))
        self.assertEqual(解析个人积分("你的分3350/10000"), (3350, 10000))
        self.assertIsNone(解析个人积分("3天18小時"))

    def test_选择按层级积分和白名单(self):
        候选 = [
            任务候选(0, (1, 1), "掠夺金币", 150),
            任务候选(0, (2, 2), "掠夺黑油", 300),
            任务候选(0, (3, 3), "多人对战胜利", 800),
            任务候选(0, (4, 4), "掠夺圣水", 600, 冷却=True),
            任务候选(0, (5, 5), "摧毁资源建筑", 1000, 禁点原因="跳过"),
            任务候选(0, (6, 6), None, 900),
        ]
        self.assertEqual(选择任务(候选, 核心白名单, 配置).类型, "掠夺黑油")
        # 可选项开启后，仍然优先核心打鱼类任务
        self.assertEqual(选择任务(候选, 核心白名单 + ["多人对战胜利"], 配置).类型, "掠夺黑油")
        self.assertEqual(选择任务(候选[2:3], ["多人对战胜利"], 配置).类型, "多人对战胜利")
        self.assertIsNone(选择任务(候选[2:3], 核心白名单, 配置))
        self.assertIsNone(选择任务(候选[3:5], 核心白名单, 配置))

    def test_禁点文字(self):
        for 文本 in ("立即完成", "跳過冷卻", "重置任務", "使用寶石", "購買"):
            self.assertIsNotNone(含禁点文字(文本, 配置), 文本)
        self.assertIsNone(含禁点文字(文本_黑油, 配置))


class 流程测试(unittest.TestCase):
    def 标准卡片(self):
        卡片 = [dict(文本=文本_夜世界, 积分="150")] * 12
        卡片[7] = dict(文本=文本_拆建筑, 积分="150")
        卡片[8] = dict(文本=文本_金币, 积分="150")
        卡片[11] = dict(文本=文本_黑油, 积分=" 300")
        return 卡片

    def test_按白名单接积分最高的打鱼任务(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        任务, 上下文, 日志, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已接任务")
        self.assertEqual(游戏.开始点击, [11])
        self.assertEqual(游戏.状态, "home")
        self.assertGreater(上下文.数据库.状态["部落竞赛检查记录"]["下次检查时间"], 0)

    def test_冷却期内不操作(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        数据库 = 假数据库()
        任务, _, _, _, _ = 构造任务(游戏, 数据库=数据库)
        任务.执行()
        点击数 = len(游戏.点击记录)
        任务2, _, _, _, _ = 构造任务(游戏, 数据库=数据库)
        self.assertTrue(任务2.执行())
        self.assertEqual(len(游戏.点击记录), 点击数)

    def test_未开启时不操作(self):
        游戏 = 模拟游戏()
        设置 = SimpleNamespace(是否部落竞赛接任务=False)
        任务, _, _, _, _ = 构造任务(游戏, 设置=设置)
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.点击记录, [])

    def test_详情出现禁点文字或宝石不点开始(self):
        卡片 = self.标准卡片()
        卡片[11] = dict(文本=文本_黑油, 积分="300", 附加="跳過")
        卡片[8] = dict(文本=文本_金币, 积分="150", 宝石=True)
        游戏 = 模拟游戏(卡片=卡片)
        任务, _, _, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "无可接任务")
        self.assertEqual(游戏.开始点击, [])
        self.assertEqual(游戏.状态, "home")

    def test_冷却卡不点(self):
        卡片 = self.标准卡片()
        卡片[11] = dict(文本=文本_黑油, 积分="300", 冷却=True)
        游戏 = 模拟游戏(卡片=卡片)
        任务, _, _, _, _ = 构造任务(游戏)
        任务.执行()
        self.assertEqual(游戏.开始点击, [8])

    def test_白名单外不接(self):
        游戏 = 模拟游戏()  # 全部是夜世界任务
        任务, _, _, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "无可接任务")
        self.assertEqual(游戏.开始点击, [])

    def test_活动结束直接跳过(self):
        游戏 = 模拟游戏(有部落竞赛=False)
        任务, 上下文, _, _, 时间 = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "入口不存在")
        self.assertEqual(游戏.状态, "home")  # 关闭了活动列表
        self.assertFalse(上下文.页面恢复失败)
        self.assertLess(时间["t"], 60)
        记录 = 上下文.数据库.状态["部落竞赛检查记录"]
        self.assertEqual(记录["结果"], "入口不存在")

    def test_活动结束时提醒领奖一次(self):
        游戏 = 模拟游戏(有部落竞赛=False)
        数据库 = 假数据库()
        数据库.状态["部落竞赛检查记录"] = {"本期见过入口": "2026-11"}
        任务, _, _, 通知, _ = 构造任务(游戏, 数据库=数据库)
        任务.执行()
        self.assertEqual(len(通知), 1)
        self.assertIn("领奖", 通知[0])

    def test_没有活动按钮不点击(self):
        游戏 = 模拟游戏(有活动按钮=False)
        任务, _, _, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "入口不存在")
        self.assertEqual(游戏.点击记录, [])

    def test_不在主世界不点击(self):
        游戏 = 模拟游戏()
        游戏.状态 = "battle"
        任务, _, _, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "非主世界")
        self.assertEqual(游戏.点击记录, [])

    def test_个人积分已满不接任务并提醒(self):
        游戏 = 模拟游戏(卡片=self.标准卡片(), 个人积分="10000/10000")
        任务, _, _, 通知, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已满分")
        self.assertEqual(游戏.开始点击, [])
        self.assertEqual(游戏.状态, "home")
        self.assertEqual(len(通知), 1)

    def test_面板不出现时步骤超时(self):
        游戏 = 模拟游戏(面板会出现=False)
        任务, 上下文, _, _, 时间 = 构造任务(游戏)
        结果 = 任务.执行()
        self.assertEqual(任务.结果, "面板未确认")
        # 未知画面没有可确认的关闭按钮：不盲点，标记页面恢复失败交给主流程。
        self.assertFalse(结果)
        self.assertTrue(上下文.页面恢复失败)
        self.assertLess(时间["t"], 配置["超时"]["总流程秒"] + 60)

    def test_总流程超时会中止并关闭面板(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        任务, _, _, _, _ = 构造任务(游戏, 配置覆盖={"超时": {"步骤秒": 8, "总流程秒": 6, "轮询毫秒": 500}})
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "超时")
        self.assertEqual(游戏.开始点击, [])
        self.assertEqual(游戏.状态, "home")

    def test_已有进行中任务直接返回(self):
        游戏 = 模拟游戏(卡片=self.标准卡片(), 已有任务=True)
        任务, _, _, _, _ = 构造任务(游戏)
        self.assertTrue(任务.执行())
        self.assertEqual(任务.结果, "已有任务")
        self.assertFalse([记录 for 记录 in 游戏.点击记录 if 记录[0] == "panel" and 记录[1:] != (709, 40)])
        self.assertEqual(游戏.状态, "home")

    def test_开始后没有放弃按钮记为超时(self):
        游戏 = 模拟游戏(卡片=self.标准卡片(), 开始后显示放弃=False)
        任务, _, _, _, _ = 构造任务(游戏)
        任务.执行()
        self.assertEqual(任务.结果, "超时")
        self.assertEqual(游戏.开始点击, [11])  # 只点了一次，没有重复点
        self.assertEqual(游戏.状态, "home")

    def test_未校准或缺模板时不点击(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        任务, _, _, _, _ = 构造任务(游戏, 配置覆盖={"已校准": False})
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.点击记录, [])
        游戏2 = 模拟游戏(卡片=self.标准卡片())
        任务2, _, _, _, _ = 构造任务(游戏2, 配置覆盖={"必需模板": ["不存在的模板"]})
        self.assertTrue(任务2.执行())
        self.assertEqual(游戏2.点击记录, [])

    def test_官方API显示满分时不打开面板(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        数据库 = 假数据库()
        数据库.状态["部落竞赛检查记录"] = {"官方API": {"期号": "2026-11", "基线": 100000}}
        任务, _, _, _, _ = 构造任务(游戏, 数据库=数据库, 官方摘要=SimpleNamespace(部落竞赛累计积分=104000))
        self.assertTrue(任务.执行())
        self.assertEqual(游戏.点击记录, [])


class 辅助函数测试(unittest.TestCase):
    def test_官方API基线与满分(self):
        现在 = datetime(2026, 11, 24)
        满分, 记录 = 官方API判断满分(5000, None, 4000, 现在)
        self.assertIsNone(满分)
        self.assertEqual(记录, {"期号": "2026-11", "基线": 5000})
        self.assertFalse(官方API判断满分(8000, 记录, 4000, 现在)[0])
        self.assertTrue(官方API判断满分(9000, 记录, 4000, 现在)[0])
        # 换月重新取基线
        self.assertIsNone(官方API判断满分(9000, 记录, 4000, datetime(2026, 12, 22))[0])
        self.assertIsNone(官方API判断满分(None, 记录, 4000, 现在)[0])

    def test_旧配置把部落竞赛插到主世界刷资源之前(self):
        self.assertEqual(
            规范化任务计划顺序(["wall", "main_resource", "night_resource"])[:3],
            ["wall", "event", "main_resource"],
        )
        self.assertEqual(规范化任务计划顺序(["night_resource"])[0], "night_resource")
        self.assertEqual(机器人设置().任务计划顺序[:2], ["event", "main_resource"])
        self.assertFalse(机器人设置().是否部落竞赛接任务)
        self.assertEqual(机器人设置().部落竞赛个人积分上限, 0)
        self.assertEqual(机器人设置(部落竞赛任务白名单=["掠夺黑油", "瞎写"]).部落竞赛任务白名单, ["掠夺黑油"])

    def test_资源优先读EXE同级目录(self):
        with tempfile.TemporaryDirectory() as 临时:
            根 = Path(临时)
            for 子 in ("外部", "外部/_internal"):
                路径 = 根 / 子 / "资源" / "活动"
                路径.mkdir(parents=True)
                (路径 / "部落竞赛.json").write_text('{"来源": "%s"}' % 子, encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(根 / "外部" / "部落冲突.exe")), \
                    patch.object(sys, "_MEIPASS", str(根 / "外部" / "_internal"), create=True):
                self.assertEqual(加载配置()["来源"], "外部")
                (根 / "外部" / "资源" / "活动" / "部落竞赛.json").unlink()
                self.assertEqual(加载配置()["来源"], "外部/_internal")

    def test_真实模板能在画面中定位(self):
        import cv2
        游戏 = 模拟游戏()
        任务, _, _, _, _ = 构造任务(游戏)
        del 任务._匹配模板  # 恢复真实实现
        模板 = 任务._读模板("开始按钮")[0]
        画面 = np.full((600, 800, 3), 40, np.uint8)
        th, tw = 模板.shape[:2]
        画面[380:380 + th, 450:450 + tw] = 模板
        点 = 任务._匹配模板(画面, "开始按钮")
        self.assertIsNotNone(点)
        self.assertLessEqual(abs(点[0] - (450 + tw // 2)), 2)
        self.assertIsNone(任务._匹配模板(np.zeros((600, 800, 3), np.uint8), "开始按钮"))
        self.assertEqual(任务.缺少的模板(), [])


if __name__ == "__main__":
    unittest.main()
