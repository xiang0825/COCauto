"""阵容学习：阵容签名、玩法适配度、按阵容累计战果与收益对比。"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 数据库.任务数据库 import 任务数据库
from 任务流程.主世界打鱼 import 阵容学习


def _槽(槽位, 类别, 名称, 数量=1):
    return {"槽位": 槽位, "类别": 类别, "名称": 名称, "数量": 数量}


# 来自实机日志的当前阵容：雷龙x8、气球兵x22、弓箭手x2、攻城气球、飞龙公爵、闪电法术
空军阵容 = [
    _槽(1, "兵种", "兵种_雷龙.bmp", 8), _槽(2, "兵种", "兵种_气球兵.bmp", 22),
    _槽(3, "兵种", "兵种_弓箭手.bmp", 2), _槽(4, "攻城器械", "兵种_攻城气球.bmp", 1),
    _槽(5, "英雄", "英雄_飞龙公爵.bmp", 1), _槽(6, "药水", "法术_闪电法术.bmp", 11),
    _槽(7, "药水", "未匹配模板(待探测)", 1),
]
哥布林阵容 = [
    _槽(1, "兵种", "兵种_超级哥布林.bmp", 60), _槽(2, "兵种", "兵种_超级野蛮人.bmp", 10),
    _槽(5, "英雄", "英雄_野蛮人之王.bmp", 1), _槽(6, "药水", "法术_急速法术.bmp", 5),
]


class 阵容识别测试(unittest.TestCase):
    def test_签名包含兵种攻城英雄不含法术和未识别槽(self):
        self.assertEqual(
            阵容学习.阵容签名(空军阵容), "雷龙x8+气球兵x22+弓箭手x2+攻城气球+飞龙公爵",
        )
        self.assertEqual(阵容学习.阵容签名([]), "")

    def test_空军阵容与资源优先不匹配并给出建议(self):
        适配度, 冲突 = 阵容学习.评估适配度(空军阵容, "资源优先")
        self.assertLess(适配度, 30)
        self.assertEqual(set(冲突), {"气球兵", "攻城气球"})
        提示 = 阵容学习.阵容提示(空军阵容, "资源优先")
        self.assertIn("只攻击防御建筑", 提示)
        self.assertIn("隐秘哥布林", 提示)

    def test_哥布林阵容适配资源优先不提建议(self):
        适配度, 冲突 = 阵容学习.评估适配度(哥布林阵容, "资源优先")
        self.assertGreaterEqual(适配度, 90)
        self.assertEqual(冲突, [])
        self.assertNotIn("建议", 阵容学习.阵容提示(哥布林阵容, "资源优先"))

    def test_稳健三星不评估资源适配度(self):
        self.assertEqual(阵容学习.评估适配度(空军阵容, "稳健三星"), (None, []))


class 阵容统计测试(unittest.TestCase):
    def setUp(self):
        self.库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.空军 = 阵容学习.阵容签名(空军阵容)
        self.哥布林 = 阵容学习.阵容签名(哥布林阵容)

    def _打(self, 签名, 场数, 结果, 星, 摧毁, 金, 水, 油):
        for _ in range(场数):
            阵容学习.记录战斗结果(self.库, "r", 签名, 结果, 星, 摧毁)
            阵容学习.记录资源收益(self.库, "r", 签名, {"金币": 金, "圣水": 水, "黑油": 油})

    def test_样本不足时不比较(self):
        self._打(self.空军, 3, "失败", 0, 30, 100_000, 100_000, 1_000)
        学习 = 阵容学习.读取(self.库, "r")
        self.assertEqual(阵容学习.阵容对比(学习), [])
        self.assertIn("已记录 3 场", 阵容学习.对比日志(学习, self.空军))

    def test_黑油误读成大额负收益不计入(self):
        # 实机 rc132：黑油 70,303 读成 157 → 净变化 −70,146，按 50 倍折算拖垮整套阵容
        self.assertFalse(阵容学习.记录资源收益(
            self.库, "r", self.空军, {"金币": 818_101, "圣水": 1_124_013, "黑油": -70_146}))
        self.assertTrue(阵容学习.记录资源收益(
            self.库, "r", self.空军, {"金币": 300_000, "圣水": 200_000, "黑油": -500}))
        统计 = 阵容学习.读取(self.库, "r")["阵容"][self.空军]
        self.assertEqual(统计["收益场次"], 1)
        self.assertEqual(统计["黑油和"], -500)

    def test_按场均收益排序并建议更好的阵容(self):
        self._打(self.空军, 10, "失败", 0, 30, 200_000, 300_000, 2_000)
        self._打(self.哥布林, 10, "胜利", 1, 55, 600_000, 700_000, 5_000)
        学习 = 阵容学习.读取(self.库, "r")
        对比 = 阵容学习.阵容对比(学习)
        self.assertEqual([项["阵容"] for 项 in 对比], [self.哥布林, self.空军])
        self.assertEqual(对比[0]["场均金币"], 600_000)
        self.assertEqual(对比[0]["胜率"], 100.0)
        self.assertIn("建议换回", 阵容学习.对比日志(学习, self.空军))
        self.assertNotIn("建议换回", 阵容学习.对比日志(学习, self.哥布林))

    def test_战利品优先级改变排序(self):
        self._打(self.空军, 10, "失败", 0, 30, 900_000, 0, 0)
        self._打(self.哥布林, 10, "失败", 0, 30, 0, 0, 10_000)
        学习 = 阵容学习.读取(self.库, "r")
        self.assertEqual(阵容学习.阵容对比(学习, "金币")[0]["阵容"], self.空军)
        self.assertEqual(阵容学习.阵容对比(学习, "黑水")[0]["阵容"], self.哥布林)

    def test_只保留最新快照且阵容数量有上限(self):
        for 序号 in range(阵容学习.最多保留阵容 + 3):
            阵容学习.记录战斗结果(self.库, "r", f"阵容{序号}", "失败", 0, 10)
        学习 = 阵容学习.读取(self.库, "r")
        self.assertEqual(len(学习["阵容"]), 阵容学习.最多保留阵容)
        with self.库._获取连接() as 连接:
            行数 = 连接.execute(
                "SELECT COUNT(*) FROM 运行时状态 WHERE 状态类型 = ?", (阵容学习.状态类型,)
            ).fetchone()[0]
        self.assertEqual(行数, 1)


class 接入测试(unittest.TestCase):
    def test_进攻时记录签名且同阵容只提示一次(self):
        from 任务流程.主世界打鱼.进攻 import 进攻任务
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            置脚本状态=Mock(), 设置=SimpleNamespace(自动配兵玩法="资源优先"),
        )
        任务._记录本场阵容(上下文, 空军阵容)
        任务._记录本场阵容(上下文, 空军阵容)
        self.assertEqual(上下文.本场阵容签名, 阵容学习.阵容签名(空军阵容))
        self.assertEqual(上下文.置脚本状态.call_count, 1)
        任务._记录本场阵容(上下文, 哥布林阵容)
        self.assertEqual(上下文.置脚本状态.call_count, 2)

    def test_机器人记录收益每五场输出对比(self):
        from 线程.自动化机器人 import 自动化机器人
        from 数据库.任务数据库 import 机器人设置
        库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "t.db"))
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "r"
        机器人.数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=机器人设置()))
        上下文 = SimpleNamespace(本场阵容签名="哥布林x60", 数据库=库, 置脚本状态=Mock())
        for _ in range(5):
            机器人._记录阵容收益(上下文, {"金币": 1, "圣水": 2, "黑油": 3})
        self.assertEqual(上下文.置脚本状态.call_count, 1)
        self.assertIn("阵容学习", 上下文.置脚本状态.call_args[0][0])
        self.assertEqual(阵容学习.读取(库, "r")["阵容"]["哥布林x60"]["收益场次"], 5)

    def test_没有签名时不记录(self):
        from 线程.自动化机器人 import 自动化机器人
        机器人 = 自动化机器人.__new__(自动化机器人)
        上下文 = SimpleNamespace(数据库=Mock(), 置脚本状态=Mock())
        机器人._记录阵容收益(上下文, {"金币": 1})
        上下文.数据库.更新状态.assert_not_called()


if __name__ == "__main__":
    unittest.main()
