"""兵种选择：资料表、人口分配、多选设置项与按职责下兵顺序。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.军队配置 import 兵种资料
from 数据库.任务数据库 import 机器人设置
from 应用 import 任务计划 as 计划


class 兵种资料测试(unittest.TestCase):
    def test_可选兵种都有战斗兵栏模板(self):
        # 超级野蛮人/超级巨人/超级飞龙沿用旧模板名（霸天巨人等）；其余均来自 MuMu 实机兵栏截图。
        import os
        缺少 = {名 for 名 in 兵种资料.可选兵种名称 if not os.path.isfile(os.path.join("img", f"兵种_{名}.bmp"))}
        self.assertEqual(缺少, set())

    def test_职责识别兼容模板文件名(self):
        self.assertEqual(兵种资料.职责("兵种_炸弹人.bmp"), "开墙")
        self.assertEqual(兵种资料.职责("超级哥布林"), "资源")
        self.assertIsNone(兵种资料.职责("兵种_未知.bmp"))
        self.assertLess(兵种资料.下兵职责排序值("兵种_巨人.bmp"), 兵种资料.下兵职责排序值("兵种_法师.bmp"))
        self.assertEqual(兵种资料.下兵职责排序值("未登记"), len(兵种资料.职责顺序))

    def test_按权重分配并尽量填满军营(self):
        结果 = 兵种资料.分配兵量(["超级哥布林", "超级野蛮人"], 352, {"超级哥布林": 3, "超级野蛮人": 5})
        占用 = 结果["超级哥布林"] * 3 + 结果["超级野蛮人"] * 5
        self.assertLessEqual(占用, 352)
        self.assertGreaterEqual(占用, 350)
        self.assertGreater(结果["超级哥布林"] * 3, 结果["超级野蛮人"] * 5 * 2)  # 权重 6:2

    def test_读不到人口的兵种跳过且未知兵种忽略(self):
        结果 = 兵种资料.分配兵量(["哥布林", "气球兵", "不存在"], 100, {"哥布林": 1})
        self.assertEqual(结果, {"哥布林": 100})
        self.assertEqual(兵种资料.分配兵量([], 100, {}), {})


class 设置测试(unittest.TestCase):
    def test_旧配置默认关闭且未知兵种被过滤(self):
        设置 = 机器人设置(配兵兵种=["哥布林", "不存在", "哥布林", "巨人"])
        self.assertFalse(设置.是否自动配置军队)
        self.assertEqual(设置.配兵兵种, ["哥布林", "巨人"])
        self.assertEqual(机器人设置().配兵兵种, [])

    def test_多选参数按选项顺序保存并拒绝未知(self):
        设置 = 机器人设置()
        计划.应用参数(设置, "troop_selection", {"是否自动配置军队": True, "配兵兵种": ["巨人", "超级哥布林"]})
        self.assertTrue(设置.是否自动配置军队)
        self.assertEqual(设置.配兵兵种, ["超级哥布林", "巨人"])
        with self.assertRaises(ValueError):
            计划.应用参数(设置, "troop_selection", {"配兵兵种": ["龙宝"]})


class 下兵顺序测试(unittest.TestCase):
    def _排序(self, 开启: bool):
        from 任务流程.主世界打鱼.进攻 import 进攻任务
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        清单 = [
            {"槽位": 1, "类别": "兵种", "名称": "兵种_弓箭手.bmp", "数量": 2, "区域": (0, 0, 1, 1)},
            {"槽位": 2, "类别": "兵种", "名称": "兵种_超级哥布林.bmp", "数量": 60, "区域": (0, 0, 1, 1)},
            {"槽位": 3, "类别": "兵种", "名称": "兵种_炸弹人.bmp", "数量": 6, "区域": (0, 0, 1, 1)},
            {"槽位": 4, "类别": "英雄", "名称": "英雄_野蛮人之王.bmp", "数量": 1, "区域": (0, 0, 1, 1)},
            {"槽位": 5, "类别": "兵种", "名称": "兵种_天使.bmp", "数量": 2, "区域": (0, 0, 1, 1)},
        ]
        上下文 = SimpleNamespace(
            当前兵栏清单=清单, 置脚本状态=日志.append,
            设置=SimpleNamespace(是否自动配置军队=开启, 是否自动配兵=False, 下兵间隔毫秒=25),
            op=SimpleNamespace(获取屏幕图像cv=Mock(side_effect=RuntimeError("停止"))),
        )
        任务.准备可下兵区域 = Mock()
        任务.生成可下兵候选点 = Mock(return_value=[])
        任务.记录可下兵点标记 = Mock()
        任务.战斗是否仍在进行 = Mock(return_value=True)
        with self.assertRaises(RuntimeError):
            任务.执行下兵流程(上下文, [{"中心坐标": (1, 1)}])
        return 日志

    def test_开启后按职责排序普通兵(self):
        日志 = self._排序(True)
        顺序 = next(行 for 行 in 日志 if 行.startswith("实际下兵顺序"))
        self.assertIn("槽位4,3,2,1,5", 顺序)
        职责 = next(行 for 行 in 日志 if 行.startswith("按兵种职责下兵"))
        self.assertIn("炸弹人(开墙) → 超级哥布林(资源) → 弓箭手(远程) → 天使(支援)", 职责)

    def test_关闭时保持原有顺序(self):
        日志 = self._排序(False)
        顺序 = next(行 for 行 in 日志 if 行.startswith("实际下兵顺序"))
        self.assertIn("槽位4,1,2,3,5", 顺序)
        self.assertFalse(any(行.startswith("按兵种职责下兵") for 行 in 日志))


if __name__ == "__main__":
    unittest.main()
