"""部落竞赛 rc147：按进攻场次尽快接新任务、可领奖只提醒不点击。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from 任务流程.活动.部落竞赛 import 文字项, 状态键
from tests.test_clan_games import 构造任务, 模拟游戏, 假数据库, 文本_夜世界, 文本_拆建筑, 文本_金币, 文本_黑油


def 标准卡片():
    卡片 = [dict(文本=文本_夜世界, 积分="150")] * 12
    卡片[7] = dict(文本=文本_拆建筑, 积分="150")
    卡片[8] = dict(文本=文本_金币, 积分="150")
    卡片[11] = dict(文本=文本_黑油, 积分=" 300")
    return 卡片


class 场次调度测试(unittest.TestCase):
    def _任务(self, 数据库=None):
        游戏 = 模拟游戏(卡片=标准卡片())
        任务, 上下文, 日志, 通知, _ = 构造任务(游戏, 数据库=数据库 or 假数据库())
        return 任务, 上下文

    def test_冷却内未到场次只计数不开面板(self):
        数据库 = 假数据库()
        数据库.状态[状态键] = {"下次检查时间": 9e12, "下次检查进攻计数": 5, "进攻计数": 2}
        任务, 上下文 = self._任务(数据库)
        任务._流程 = lambda: self.fail("不应开面板")
        self.assertTrue(任务.执行(进攻前=True))
        self.assertEqual(数据库.状态[状态键]["进攻计数"], 3)

    def test_到达预定场次即使在时间冷却内也开面板(self):
        数据库 = 假数据库()
        # 已打完 3 场（本次进攻前计数加到 4，含即将开打的这一场）→ 到达预定的第 3 场
        数据库.状态[状态键] = {"下次检查时间": 9e12, "下次检查进攻计数": 3, "进攻计数": 3}
        任务, _ = self._任务(数据库)
        调用 = []
        任务._流程 = lambda: 调用.append(1) or "已有任务"
        任务._回到主页 = lambda: True
        任务.执行(进攻前=True)
        self.assertEqual(调用, [1])

    def test_计划任务调用不增加进攻计数(self):
        数据库 = 假数据库()
        数据库.状态[状态键] = {"下次检查时间": 9e12, "进攻计数": 2}
        任务, _ = self._任务(数据库)
        任务.执行()
        self.assertEqual(数据库.状态[状态键]["进攻计数"], 2)

    def test_接任务后下一场就复查(self):
        任务, _ = self._任务()
        记录 = {"进攻计数": 7}
        self.assertEqual(任务._计划进攻复查(记录, "已接任务"), 8)
        self.assertEqual(记录["进度基线"], {"进度": 0, "进攻计数": 7})

    def test_按进度速率预测完成场次(self):
        任务, _ = self._任务()
        # 接任务时计数 7，打了 3 场到 9/12：每场 3 个，还差 3 个 → 1 场后复查
        记录 = {"进攻计数": 10, "进度基线": {"进度": 0, "进攻计数": 7}}
        任务._进度 = (9, 12)
        self.assertEqual(任务._计划进攻复查(记录, "已有任务"), 11)
        # 每场 1 个、还差 6 个 → 6 场后
        记录 = {"进攻计数": 13, "进度基线": {"进度": 0, "进攻计数": 7}}
        任务._进度 = (6, 12)
        self.assertEqual(任务._计划进攻复查(记录, "已有任务"), 19)
        # 很慢时最多隔 10 场
        记录 = {"进攻计数": 20, "进度基线": {"进度": 0, "进攻计数": 10}}
        任务._进度 = (1, 75)
        self.assertEqual(任务._计划进攻复查(记录, "已有任务"), 30)

    def test_换了任务或无基线时重置基线并下一场再看(self):
        任务, _ = self._任务()
        记录 = {"进攻计数": 10, "进度基线": {"进度": 9, "进攻计数": 5}}
        任务._进度 = (2, 25)
        self.assertEqual(任务._计划进攻复查(记录, "已有任务"), 11)
        self.assertEqual(记录["进度基线"], {"进度": 2, "进攻计数": 10})

    def test_没有可接任务时每两场复查且时间上限十分钟(self):
        数据库 = 假数据库()
        任务, _ = self._任务(数据库)
        记录 = {"进攻计数": 4}
        with patch("任务流程.活动.部落竞赛.time.time", return_value=1000.0):
            任务._记录结果(记录, "无可接任务", 30)
        self.assertEqual(记录["下次检查进攻计数"], 6)
        self.assertEqual(记录["下次检查时间"], 1000.0 + 600)

    def test_读取进度只认卡片区分数(self):
        任务, _ = self._任务()
        项 = [
            文字项("4100/10000", (120, 532, 210, 552)),   # 个人积分，卡片区外
            文字项("1/2", (760, 280, 780, 296)),          # 主页建筑工人，卡片区外
            文字项("9/12", (329, 223, 357, 241)),
        ]
        self.assertEqual(任务._读取进度(项), (9, 12))
        self.assertIsNone(任务._读取进度(项[:2]))

    def test_进度已满时不当作进行中直接挑新任务(self):
        游戏 = 模拟游戏(卡片=标准卡片(), 已有任务=True)
        任务, 上下文, 日志, _, _ = 构造任务(游戏)
        原OCR = 游戏.ocr结果

        def 带进度():
            结果 = 原OCR()
            if 游戏.状态 == "panel" and 游戏.详情 is None:
                结果.append(([[329, 223], [357, 223], [357, 241], [329, 241]], "12/12", 0.9))
            return 结果

        游戏.ocr结果 = 带进度
        任务._存在进行中任务 = lambda *_a: True  # 灰卡等旧信号仍在
        任务.执行()
        self.assertTrue(any("已完成，立即挑选新任务" in 行 for 行 in 日志))
        self.assertNotEqual(任务.结果, "已有任务")


class 可领奖提醒测试(unittest.TestCase):
    def test_可领奖只提醒一次且不点击面板(self):
        游戏 = 模拟游戏(卡片=标准卡片())
        原OCR = 游戏.ocr结果
        游戏.ocr结果 = lambda: 原OCR() + ([([[300, 300], [400, 300], [400, 320], [300, 320]], "領取獎勵", 0.9)]
                                       if 游戏.状态 == "panel" else [])
        任务, 上下文, 日志, 通知, _ = 构造任务(游戏)
        任务.执行()
        self.assertEqual(任务.结果, "可领奖")
        面板点击 = [记录 for 记录 in 游戏.点击记录 if 记录[0] == "panel" and 记录[1:] != (709, 40)]
        self.assertEqual(面板点击, [])
        self.assertEqual(len(通知), 1)
        self.assertIn("可以领奖了", 通知[0])

    def test_满分也写日志提醒(self):
        游戏 = 模拟游戏(卡片=标准卡片(), 个人积分="10000/10000")
        任务, 上下文, _, 通知, _ = 构造任务(游戏)
        任务.执行()
        self.assertEqual(任务.结果, "已满分")
        self.assertEqual(len(通知), 1)
        self.assertIn("个人积分已满", 通知[0])

    def test_代码中没有领奖点击(self):
        from pathlib import Path

        源码 = Path("任务流程/活动/部落竞赛.py").read_text(encoding="utf-8")
        self.assertNotIn('_点击(领奖', 源码)
        self.assertNotIn('"领取奖励"', 源码)


if __name__ == "__main__":
    unittest.main()
