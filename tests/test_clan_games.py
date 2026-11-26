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
from unittest.mock import Mock, patch

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
                 个人积分="3350/10000", 面板会出现=True, 开始后显示放弃=True, 已有任务=False,
                 开始后收起详情=False):
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
        self.开始后收起详情 = 开始后收起详情
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
            if self.开始后显示放弃 or self.开始后收起详情:
                self.已接 = self.详情
            if self.开始后收起详情:
                self.详情 = None
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
            if self.开始后收起详情 and self.已接 is not None and self.详情 is None:
                结果.append(ocr("0/12", 329, 223, 357, 241))
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
        self.assertEqual(识别任务类型(文本_法术工厂, 配置), "摧毁指定建筑")
        self.assertEqual(识别任务类型(文本_拆建筑, 配置), "拆毁建筑")
        for 文本 in (文本_夜世界, 文本_指定兵种, 文本_捐兵, ""):
            self.assertIsNone(识别任务类型(文本, 配置), 文本)

    def test_2026_11_25实机任务卡全部按新规则分类(self):
        阵容 = "弓箭手x2+雷龙x11+飞龙+攻城战车+飞龙公爵"
        期望 = {
            # 建筑大师/夜世界（OCR 把 建筑 读成 建莱、对战 读成 载门）
            "狂鑫建筑大师大本誉在建筑大师载门中摧毁1个建筑大师大本营。1503小特": None,
            "在场建大师载门中赢得胜利之星，至少需使用變亡x。8100小时": None,
            "建莱大师载用摘星逢人在建筑大师门中赢得6利之星。2008小时": None,
            "推倒时光钟楼在建筑大师门中摧毁2个时光钟楼。2008小时": None,
            # 指定兵种：阵容里没有亡灵/戈仑冰人/攻城车
            "亡塞浩劫在场多人避中赢得1颗胜利之星，至少需使用亡xl。1503小时": None,
            "冰脂城下在1场多人避中赢得颗胜利之星，至少需使用戈俞冰人x。150": None,
            "在1场多人对战中赢得1颗胜利之星，至少需使用攻城车x1": None,
            # 增援部落成员
            "接助之手向部落成员增援总计45空间的部。150误": None,
            # 可完成
            "推毁x连弩在多人中摧毁12个x连弩600": "摧毁防御建筑",
            "拆毁建菜在多人避中摧毁75座建1503小时": "拆毁建筑",
            "金蒂挑号在单场多人避门中掠200000金。150b小特": "掠夺金币",
            "暴力拆墙在多人游中推毁25境城1503小时": "拆墙",
            "毁减领主在多人避中达到总计300%的摧毁率。600": "摧毁率",
            "在1场多人对战中赢得3颗胜利之星": "多人对战胜利",
            "在多人对战中摧毁10座储金罐": "摧毁资源建筑",
        }
        for 文本, 类型 in 期望.items():
            self.assertEqual(识别任务类型(文本, 配置, 阵容), 类型, 文本)

    def test_指定兵种只在阵容里有该兵种时才接(self):
        文本 = "在1场多人对战中赢得1颗胜利之星，至少需使用雷龙x1"
        self.assertEqual(识别任务类型(文本, 配置, "弓箭手x2+雷龙x11+飞龙"), "多人对战胜利")
        self.assertEqual(识别任务类型("在多人对战中赢得1颗胜利之星，至少需使用飞龙xl", 配置, "雷龙x11+飞龙"), "多人对战胜利")
        # 没有阵容信息、阵容里没有、或者兵种名读不清都不接
        self.assertIsNone(识别任务类型(文本, 配置, ""))
        self.assertIsNone(识别任务类型(文本, 配置, None))
        self.assertIsNone(识别任务类型(文本, 配置, "弓箭手x2+飞龙"))
        self.assertIsNone(识别任务类型("赢得1颗胜利之星，至少需使用", 配置, "雷龙x11"))
        # 攻城车 ≠ 攻城战车
        self.assertIsNone(识别任务类型("赢得胜利之星，至少需使用攻城车x1", 配置, "攻城战车"))

    def test_需要宝石或突袭都城的不接(self):
        for 文本 in ("花费50宝石", "在突袭周末中摧毁3个都城区", "在部落战中赢得3颗星", "训练100个野蛮人"):
            self.assertIsNone(识别任务类型(文本, 配置, "野蛮人x88"), 文本)

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
        # 积分优先：胜利任务 800 分高于掠夺黑油 300 分
        self.assertEqual(选择任务(候选, 核心白名单 + ["多人对战胜利"], 配置).类型, "多人对战胜利")
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

    def test_宝箱领奖页或低置信主页不误判活动结束120分钟冷却(self):
        for 场景, 页面返回 in (
            ("宝箱领奖页", SimpleNamespace(页面="宝箱领奖页", 世界=None, 可信度=0.96)),
            ("低置信主页0.56", SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.56)),
        ):
            with self.subTest(场景=场景):
                游戏 = 模拟游戏(有活动按钮=False)
                数据库 = 假数据库()
                数据库.状态["部落竞赛检查记录"] = {"本期见过入口": "2026-11"}
                任务, 上下文, _, 通知, _ = 构造任务(游戏, 数据库=数据库)
                上下文.识别点击画面 = lambda 强制=False, _r=页面返回: _r
                self.assertTrue(任务.执行())
                self.assertEqual(任务.结果, "非主世界")
                self.assertEqual(游戏.点击记录, [])
                self.assertEqual(通知, [])
                记录 = 上下文.数据库.状态["部落竞赛检查记录"]
                self.assertEqual(记录["结果"], "非主世界")
                self.assertNotEqual(记录["结果"], "入口不存在")
                # 确认即使首帧误过但找不到活动按钮复核仍非高置信主页时，同样拒绝误判入口不存在
                任务2, 上下文2, _, 通知2, _ = 构造任务(游戏, 数据库=假数据库())
                调用 = [0]

                def _先通过后掉出(强制=False, _r=页面返回):
                    调用[0] += 1
                    return (
                        SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.92)
                        if 调用[0] == 1
                        else _r
                    )

                上下文2.识别点击画面 = _先通过后掉出
                self.assertTrue(任务2.执行())
                self.assertEqual(任务2.结果, "非主世界")
                self.assertEqual(通知2, [])

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

    def test_开始后详情收起只剩进度和灰卡也算已接(self):
        游戏 = 模拟游戏(卡片=self.标准卡片(), 开始后显示放弃=False, 开始后收起详情=True)
        任务, _, 日志, _, _ = 构造任务(游戏)
        任务.执行()
        self.assertEqual(任务.结果, "已接任务")
        self.assertEqual(游戏.开始点击, [11])
        self.assertEqual(游戏.状态, "home")

    def test_开始确认不把页码当进度(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        任务, _, _, _, _ = 构造任务(游戏)
        任务._截图 = lambda: np.full((600, 800, 3), (40, 160, 230), np.uint8)
        任务._OCR = lambda _图: [文字项("1/2", (400, 440, 420, 455)), 文字项("1508", (335, 233, 383, 262))]
        self.assertFalse(任务._任务已开始())
        任务._OCR = lambda _图: [文字项("0/12", (329, 223, 357, 241))]
        self.assertTrue(任务._任务已开始())
        任务._OCR = lambda _图: [文字项("放棄", (494, 407, 524, 430))]
        self.assertTrue(任务._任务已开始())

    def test_详情仍显示开始时灰底不算已接(self):
        游戏 = 模拟游戏(卡片=self.标准卡片())
        任务, _, _, _, _ = 构造任务(游戏)
        任务._截图 = lambda: np.full((600, 800, 3), (128, 128, 128), np.uint8)
        任务._OCR = lambda _图: [文字项("開始", (494, 407, 524, 430))]
        self.assertFalse(任务._任务已开始())

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


class 复核与拆墙及优化测试(unittest.TestCase):
    def test_拆墙OCR错字与右边界截断修复且不误判非拆墙任务(self):
        self.assertEqual(配置["面板"]["详情相对开始文字"][2], 85)
        正面用例 = (
            "暴力拆墙在多人游戏中摧毁100块城",
            "暴力拆摘在多人游戏中摧毁100块城",
            "暴力拆瘤在多人对战中摧毁50块城",
            "暴力拆牆在多人對戰中摧毀100塊城牆",
            "在多人对战中摧毁25境城",
        )
        for 文本 in 正面用例:
            self.assertEqual(识别任务类型(文本, 配置), "拆墙", 文本)
        反面用例 = (
            ("在多人对战中摧毁1个部落城堡", "摧毁指定建筑"),
            ("在突袭周末中摧毁3个都城区", None),
            ("在多人对战中摧毁75座建筑", "拆毁建筑"),
        )
        for 文本, 预期 in 反面用例:
            self.assertEqual(识别任务类型(文本, 配置), 预期, 文本)

        # 验证详情框右边界放宽后，右侧 x=开始右+75 的文本仍被纳入（例如 "100块城墙"）
        游戏 = 模拟游戏()
        任务, _, _, _, _ = 构造任务(游戏)
        任务._截图 = lambda: np.full((600, 800, 3), (40, 160, 230), np.uint8)
        任务._OCR = lambda _图: [
            文字项("開始", (494, 407, 524, 430)),
            文字项("暴力拆墙摧毁100块", (365, 290, 560, 312)),
            文字项("城墙", (590, 290, 608, 312)),
            文字项("600", (360, 375, 405, 405)),
        ]
        详情 = 任务._识别详情()
        self.assertIsNotNone(详情)
        self.assertIn("100块城墙", 详情["文本"])

    def test_复核不一致打印原文并返回独立状态且自动顺延次优候选(self):
        # 600 分拆墙卡复核时变成夜世界（模拟卡片错位），同面板还有 300 分掠夺金币和 150 分拆建筑
        游戏 = 模拟游戏()
        任务, _, 日志, _, _ = 构造任务(
            游戏,
            设置=SimpleNamespace(
                是否部落竞赛接任务=True,
                部落竞赛任务白名单=["拆墙", "掠夺金币", "拆毁建筑"],
                部落竞赛检查间隔分钟=30,
                部落竞赛个人积分上限=4000,
            ),
        )
        候选列表 = [
            任务候选(0, (341, 165), "拆墙", 600, 文本="暴力拆墙摧毁100块城墙"),
            任务候选(0, (438, 165), "掠夺金币", 300, 文本=文本_金币),
            任务候选(0, (535, 165), "拆毁建筑", 150, 文本=文本_拆建筑),
        ]
        任务._扫描任务卡 = lambda: 候选列表
        复核详情队列 = [
            {"文本": "在建筑大师战斗中摧毁3个实验室", "积分": 600, "开始点": (507, 418), "禁点": None, "冷却": False},
            {"文本": 文本_金币, "积分": 300, "开始点": (507, 418), "禁点": None, "冷却": False},
        ]
        任务._识别详情 = lambda: 复核详情队列.pop(0) if 复核详情队列 else None
        任务._任务已开始 = lambda 允许弹窗=True: True

        游戏.状态 = "panel"
        任务._截止 = 9999.0
        彩色图 = np.full((600, 800, 3), (40, 160, 230), dtype=np.uint8)
        结果 = 任务._处理面板({"图像": 彩色图, "文字": []})
        self.assertEqual(结果, "已接任务")
        self.assertTrue(any("复核任务类型不一致" in 条 and "实验室" in 条 for 条 in 日志), 日志)
        self.assertFalse(any("护栏阻止" in 条 for 条 in 日志), 日志)

        # 全员复核不一致时应明确返回『复核不一致』，不得覆盖为『护栏阻止』
        任务._识别详情 = lambda: {
            "文本": "向部落成员增援部队", "积分": 300, "开始点": (507, 418), "禁点": None, "冷却": False
        }
        日志.clear()
        结果2 = 任务._处理面板({"图像": 彩色图, "文字": []})
        self.assertEqual(结果2, "复核不一致")
        self.assertTrue(any("增援部队" in 条 for 条 in 日志), 日志)

    def test_灰卡冷却跳过与翻页到底去重(self):
        游戏 = 模拟游戏()
        任务, _, 日志, _, _ = 构造任务(游戏)
        任务._截止 = 9999.0
        # 构造带纹理的高饱和彩色背景图 + 两张低饱和灰卡（第1张与第3张）
        rng = np.random.default_rng(7)
        页图0 = rng.integers(80, 210, (600, 800, 3), dtype=np.uint8)
        # 确保卡片区高饱和
        页图0[:, :, 0] = 30
        页图0[:, :, 1] = 170
        页图0[:, :, 2] = 220
        # 保留第1张和第3张灰卡（低饱和高亮度）
        for cx, cy in ((341, 165), (535, 165)):
            页图0[cy - 45:cy + 5, cx - 30:cx + 30] = (150, 150, 150)

        # 页1 完全不同（有纹理），页2 与页1 一致（模拟滑到底无新卡）
        页图1 = np.full((600, 800, 3), (40, 180, 230), dtype=np.uint8)
        页图1[120:420, 300:660:20] = (20, 220, 240)
        页图2 = 页图1.copy()

        页画面 = {0: 页图0, 1: 页图1, 2: 页图2}
        切换记录 = []
        原切页 = 任务._切换到页

        def _记录切页(当前页, 目标页):
            切换记录.append(目标页)
            任务._当前页 = 目标页
            return 目标页

        任务._切换到页 = _记录切页
        任务._截图 = lambda: 页画面[getattr(任务, "_当前页", 0)]
        # (x1+x2)//2 - 15 = cx, y1 - 50 = 165 => y1 = 215
        任务._OCR = lambda _图: [
            文字项("300", (336, 215, 376, 245)),
            文字项("300", (433, 215, 473, 245)),
            文字项("300", (530, 215, 570, 245)),
        ] if getattr(任务, "_当前页", 0) == 0 else []
        点开位置 = []

        def _假读详情(页, 位置):
            点开位置.append((页, 位置))
            return 任务候选(页=页, 位置=位置, 类型="掠夺金币", 积分=300, 文本=f"金币{页}{位置}")

        任务._读取详情 = _假读详情
        任务._关闭详情 = lambda: None
        任务._配置 = dict(任务.配置)
        任务._配置["面板"] = dict(任务.配置["面板"])
        任务._配置["面板"]["页"] = [
            {"滑动": None, "卡片": [(341, 165), (438, 165), (535, 165)]},
            {"滑动": [700, 420, 700, 130], "卡片": [(341, 360)]},
            {"滑动": [700, 420, 700, 130], "卡片": [(438, 360)]},
        ]

        候选 = 任务._扫描任务卡()
        # 第0页两张灰卡（341,165）与（535,165）应被跳过不点开详情；页2 与页1 指纹一致应提前结束
        self.assertEqual(切换记录, [0, 1, 2])
        self.assertNotIn((0, (341, 165)), 点开位置)
        self.assertNotIn((0, (535, 165)), 点开位置)
        self.assertIn((0, (438, 165)), 点开位置)
        self.assertIn((1, (341, 360)), 点开位置)
        self.assertNotIn((2, (438, 360)), 点开位置)
        self.assertTrue(any(c.冷却 and c.位置 == (341, 165) for c in 候选))
        self.assertTrue(any("提前结束" in 条 for 条 in 日志), 日志)

        # 验证从页2回滑到页0会循环2次
        滑动记录 = []
        任务._滑动 = lambda s: 滑动记录.append(s) or True
        任务._延时 = lambda *_a: None
        原切页(2, 0)
        self.assertEqual(len(滑动记录), 2)

    def test_回营过渡帧日志同状态节流但状态变化立即记录(self):
        from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务

        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务._可接续主世界页面可信 = lambda 结果: 结果.页面 == "主世界主页" and 结果.可信度 >= 0.7
        状态列表 = [
            SimpleNamespace(页面="战斗结算", 世界=None, 可信度=0.92),
            SimpleNamespace(页面="战斗结算", 世界=None, 可信度=0.92),
            SimpleNamespace(页面="战斗结算", 世界=None, 可信度=0.92),
            SimpleNamespace(页面="战斗过渡", 世界=None, 可信度=0.88),
            SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.95),
            SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.95),
        ]
        idx = [0]
        日志 = []
        现在时间 = [100.0]

        class 假识别器:
            def 识别(self, _图, 战斗中=False):
                结果 = 状态列表[min(idx[0], len(状态列表) - 1)]
                idx[0] += 1
                return 结果

        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=lambda *a, **k: np.zeros((600, 800, 3), np.uint8)),
            _获取点击页面识别器=lambda: 假识别器(),
            置脚本状态=lambda 文本: 日志.append(文本),
            脚本延时=lambda _ms: None,
        )

        def 假单调():
            现在时间[0] += 0.5
            return 现在时间[0]

        with patch("任务流程.主世界打鱼.等待战斗结束并回营.检测游戏登录状态任务._检测断线弹窗", return_value=(False, (0, 0))), \
                patch("任务流程.主世界打鱼.等待战斗结束并回营.奖励宝箱.识别宝箱页", return_value=None), \
                patch("任务流程.主世界打鱼.等待战斗结束并回营.time.monotonic", side_effect=假单调):
            self.assertTrue(任务.等待主界面就绪(上下文))

        未确认日志 = [条 for 条 in 日志 if "回营后尚未确认主世界" in 条]
        self.assertEqual(len(未确认日志), 2, 日志)
        self.assertIn("当前=战斗结算", 未确认日志[0])
        self.assertIn("当前=战斗过渡", 未确认日志[1])


if __name__ == "__main__":
    unittest.main()


class 打鱼间隙检查部落竞赛测试(unittest.TestCase):
    def _机器人(self, 结果=True):
        from 线程.自动化机器人 import 自动化机器人
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人._执行部落竞赛计划 = Mock(return_value=结果)
        return 机器人

    def test_未启用event时不检查(self):
        机器人 = self._机器人()
        上下文 = SimpleNamespace(_启用任务键集合=frozenset({"main_resource"}), 置脚本状态=Mock())
        self.assertTrue(机器人._打鱼间隙检查部落竞赛(上下文))
        机器人._执行部落竞赛计划.assert_not_called()

    def test_启用event时每场前都交给模块按冷却判断(self):
        机器人 = self._机器人()
        上下文 = SimpleNamespace(_启用任务键集合=frozenset({"event", "main_resource"}), 置脚本状态=Mock())
        self.assertTrue(机器人._打鱼间隙检查部落竞赛(上下文))
        self.assertTrue(机器人._打鱼间隙检查部落竞赛(上下文))
        self.assertEqual(机器人._执行部落竞赛计划.call_count, 2)

    def test_检查失败时禁止进攻并标记页面恢复失败(self):
        机器人 = self._机器人(结果=False)
        上下文 = SimpleNamespace(
            _启用任务键集合=frozenset({"event"}), 置脚本状态=Mock(), 页面恢复失败=False
        )
        self.assertFalse(机器人._打鱼间隙检查部落竞赛(上下文))
        self.assertTrue(上下文.页面恢复失败)

    def test_没有启用任务集合的旧调用方不检查(self):
        机器人 = self._机器人()
        self.assertTrue(机器人._打鱼间隙检查部落竞赛(SimpleNamespace()))
        机器人._执行部落竞赛计划.assert_not_called()


class 新白名单选择测试(unittest.TestCase):
    def test_同分时选完成快的(self):
        全部 = list(模块.加载配置()["白名单"].keys())
        候选 = [
            任务候选(0, (1, 1), "摧毁率", 600),
            任务候选(0, (2, 2), "摧毁防御建筑", 600),
            任务候选(0, (3, 3), "多人对战胜利", 600),
        ]
        self.assertEqual(选择任务(候选, 全部, 配置).类型, "摧毁防御建筑")
        候选 = [
            任务候选(0, (1, 1), "拆墙", 150),
            任务候选(0, (2, 2), "摧毁资源建筑", 150),
            任务候选(0, (3, 3), "掠夺金币", 150),
            任务候选(0, (4, 4), "拆毁建筑", 150),
        ]
        self.assertEqual(选择任务(候选, 全部, 配置).类型, "掠夺金币")
        self.assertEqual(选择任务(候选[:2] + 候选[3:], 全部, 配置).类型, "摧毁资源建筑")
        self.assertEqual(选择任务([候选[0], 候选[3]], 全部, 配置).类型, "拆墙")

    def test_设置默认全选且旧默认四项自动升级(self):
        from 数据库.任务数据库 import 部落竞赛白名单选项
        self.assertEqual(机器人设置().部落竞赛任务白名单, list(部落竞赛白名单选项))
        旧 = ["掠夺金币", "掠夺圣水", "掠夺黑油", "摧毁资源建筑"]
        self.assertEqual(机器人设置(部落竞赛任务白名单=旧).部落竞赛任务白名单, list(部落竞赛白名单选项))
        # 用户自己选的其它组合保持不变
        self.assertEqual(机器人设置(部落竞赛任务白名单=["掠夺黑油", "拆墙"]).部落竞赛任务白名单, ["掠夺黑油", "拆墙"])

    def test_配置白名单与设置选项一一对应(self):
        from 数据库.任务数据库 import 部落竞赛白名单选项
        self.assertEqual(set(模块.加载配置()["白名单"]), set(部落竞赛白名单选项))
