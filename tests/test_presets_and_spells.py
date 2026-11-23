"""阵容预设、法术/攻城配置换算、战斗兵栏法术识别与跟随/控制法术施放计划。"""

import os
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from 任务流程.军队配置 import 兵种资料, 阵容预设 as 预设
from 任务流程.军队配置 import 编辑军队 as 编
from 数据库.任务数据库 import 机器人设置
from 应用 import 任务计划 as 计划


class 预设测试(unittest.TestCase):
    def test_每套预设的单位都已登记且有卡片模板(self):
        for 方案 in 预设.预设列表:
            for 名 in 方案.兵种权重:
                self.assertIn(名, 兵种资料.兵种映射, f"{方案.名称}:{名}")
                self.assertIsNotNone(编.读取卡片模板(名), f"{方案.名称}:{名}")
            for 名 in 方案.法术个数:
                self.assertIn(名, 兵种资料.法术映射, f"{方案.名称}:{名}")
                self.assertIsNotNone(编.读取卡片模板(名), f"{方案.名称}:{名}")
            if 方案.攻城:
                self.assertIn(方案.攻城, 兵种资料.攻城列表)
                self.assertIsNotNone(编.读取卡片模板(方案.攻城))
            for 名 in 方案.关键兵种:
                self.assertIn(名, 方案.兵种权重)

    def test_预设法术总占用不超过11(self):
        for 方案 in 预设.预设列表:
            占用 = sum(兵种资料.人口(名) * 数 for 名, 数 in 方案.法术个数.items())
            self.assertLessEqual(占用, 11, 方案.名称)

    def test_实机根蔓雪怪预设的换算结果(self):
        # 2026-11-24 MuMu 实机：352 人口 → 根蔓×8 雪怪×7 女巫×3 天使×2（350/352）
        人口表 = {名: 兵种资料.人口(名) for 名 in ("根蔓骑士", "大雪怪", "女巫", "天使")}
        方案 = 预设.预设映射["根蔓骑士雪怪推进"]
        self.assertEqual(
            兵种资料.按权重分配(方案.兵种权重, 352, 人口表),
            {"根蔓骑士": 8, "大雪怪": 7, "女巫": 3, "天使": 2},
        )
        法术人口 = {名: 兵种资料.人口(名) for 名 in 方案.法术个数}
        self.assertEqual(
            预设.分配法术(方案.法术个数, 11, 法术人口),
            {"狂暴法术": 2, "冰冻法术": 3, "急速法术": 2, "疗伤法术": 1},
        )

    def test_法术容量不足时按顺序截断(self):
        人口表 = {"狂暴法术": 2, "冰冻法术": 1}
        self.assertEqual(预设.分配法术({"狂暴法术": 3, "冰冻法术": 3}, 5, 人口表), {"狂暴法术": 2, "冰冻法术": 1})

    def test_自定义法术轮流放满(self):
        结果 = 编.编辑军队任务._按个数分配({"急速法术": 99, "狂暴法术": 99}, 11, {"急速法术": 1, "狂暴法术": 2})
        self.assertEqual(sum(兵种资料.人口(名) * 数 for 名, 数 in 结果.items()), 11)
        self.assertGreaterEqual(结果["急速法术"], 结果["狂暴法术"])

    def test_期望配置(self):
        设置 = SimpleNamespace(是否自动配置军队=True, 阵容预设="飞龙龙骑士空军")
        配置 = 编.期望配置(设置)
        self.assertEqual(set(配置), {"兵种", "法术", "攻城"})
        self.assertEqual(配置["攻城"], {"攻城飞艇": 1})
        自定义 = SimpleNamespace(
            是否自动配置军队=True, 阵容预设=预设.自定义, 配兵兵种=["野蛮人"], 配兵法术=[], 配兵攻城="攻城钻机",
        )
        self.assertEqual(编.期望配置(自定义), {"兵种": {"野蛮人": 2}, "攻城": {"攻城钻机": 1}})
        self.assertIsNone(编.期望配置(SimpleNamespace(是否自动配置军队=False)))

    def test_三星预设切换玩法(self):
        设置 = SimpleNamespace(是否自动配置军队=True, 阵容预设="巨矛投手推进", 是否自动配兵=False, 自动配兵玩法="资源优先")
        self.assertEqual(预设.生效玩法(设置), (True, "稳健三星"))
        设置.阵容预设 = "隐秘哥布林刷资源"
        self.assertEqual(预设.生效玩法(设置), (True, "资源优先"))
        设置.是否自动配置军队 = False
        self.assertEqual(预设.生效玩法(设置), (False, "资源优先"))


class 设置测试(unittest.TestCase):
    def test_未知值被规范化(self):
        设置 = 机器人设置(阵容预设="不存在", 配兵法术=["狂暴法术", "乱写"], 配兵攻城="坦克")
        self.assertEqual(设置.阵容预设, 预设.自定义)
        self.assertEqual(设置.配兵法术, ["狂暴法术"])
        self.assertEqual(设置.配兵攻城, "")

    def test_兵种选择页包含预设法术和攻城(self):
        字段 = {f.字段 for f in 计划.任务参数表["troop_selection"].字段}
        self.assertEqual(字段, {"是否自动配置军队", "阵容预设", "配兵兵种", "配兵法术", "配兵攻城"})
        设置 = 机器人设置()
        计划.应用参数(设置, "troop_selection", {
            "阵容预设": "根蔓骑士雪怪推进", "配兵法术": ["冰冻法术", "狂暴法术"], "配兵攻城": "攻城战车",
        })
        self.assertEqual(设置.阵容预设, "根蔓骑士雪怪推进")
        self.assertEqual(设置.配兵法术, ["狂暴法术", "冰冻法术"])
        with self.assertRaises(ValueError):
            计划.应用参数(设置, "troop_selection", {"配兵攻城": "坦克"})


class 兵栏识别测试(unittest.TestCase):
    """fixtures/军队编辑/bar_rr.png：MuMu 实机搜索页兵栏（根蔓雪怪预设）。"""

    @classmethod
    def setUpClass(cls):
        路径 = os.path.join(os.path.dirname(__file__), "fixtures", "军队编辑", "bar_rr.png")
        cls.图 = cv2.imdecode(np.fromfile(路径, np.uint8), cv2.IMREAD_COLOR)
        from 任务流程.主世界打鱼.进攻 import 进攻任务
        cls.任务 = 进攻任务.__new__(进攻任务)
        from 模块.检测.模板匹配器 import 模板匹配引擎
        cls.任务.模板识别 = 模板匹配引擎()

    def _槽(self, 序号):
        _, (x1, y1, x2, y2) = self.任务.可见兵栏格子[序号 - 1]
        return self.图[y1:y2, x1:x2]

    def test_新法术与攻城战车模板认对槽位(self):
        法术模板 = self.任务.乱生效类法术列表 + ["法术_镜像法术.bmp"] + self.任务.跟随控制法术列表
        for 序号, 期望 in ((7, "法术_狂暴法术"), (8, "法术_冰冻法术"), (9, "法术_急速法术")):
            名称, 分数 = self.任务._槽位最佳模板(self._槽(序号), 法术模板)
            self.assertEqual(名称, 期望)
            self.assertGreater(分数, 0.9)
        名称, 分数 = self.任务._槽位最佳模板(self._槽(5), self.任务.兵种模板列表)
        self.assertEqual(名称, "兵种_攻城战车")

    def test_兵种卡不会被当成法术(self):
        法术模板 = self.任务.乱生效类法术列表 + ["法术_镜像法术.bmp"] + self.任务.跟随控制法术列表
        for 序号 in (1, 2, 3, 4):
            _, 法术分数 = self.任务._槽位最佳模板(self._槽(序号), 法术模板)
            _, 兵种分数 = self.任务._槽位最佳模板(self._槽(序号), self.任务.兵种模板列表)
            self.assertGreater(兵种分数, 法术分数, f"第{序号}格")


class 全部兵种法术兵栏测试(unittest.TestCase):
    """bar_all1/bar_all2：实机兵栏（巨矛投手/泰坦/巨石投手/猎手/熔炉/德鲁伊 + 7 种法术）。"""

    @staticmethod
    def _图(名):
        路径 = os.path.join(os.path.dirname(__file__), "fixtures", "军队编辑", f"{名}.png")
        return cv2.imdecode(np.fromfile(路径, np.uint8), cv2.IMREAD_COLOR)

    def test_每张卡认成自己(self):
        from 任务流程.主世界打鱼.进攻 import 进攻任务
        from 模块.检测.模板匹配器 import 模板匹配引擎
        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 模板匹配引擎()
        法术模板 = 任务.乱生效类法术列表 + ["法术_镜像法术.bmp"] + 任务.跟随控制法术列表
        图1, 图2 = self._图("bar_all1"), self._图("bar_all2")
        期望 = [
            (图1, 10, "兵种_巨矛投手", 任务.兵种模板列表), (图1, 70, "兵种_雷霆泰坦", 任务.兵种模板列表),
            (图1, 131, "兵种_巨石投手", 任务.兵种模板列表), (图1, 191, "兵种_英雄猎手", 任务.兵种模板列表),
            (图1, 252, "兵种_烈焰熔炉", 任务.兵种模板列表), (图1, 312, "兵种_德鲁伊", 任务.兵种模板列表),
            (图1, 515, "法术_弹跳法术", 法术模板), (图1, 575, "法术_隐形法术", 法术模板),
            (图1, 636, "法术_复苏法术", 法术模板), (图1, 696, "法术_回溯法术", 法术模板),
            (图2, 544, "法术_毒药法术", 法术模板), (图2, 605, "法术_疯狂蔓生法术", 法术模板),
            (图2, 665, "法术_冰障法术", 法术模板),
        ]
        for 图, 左, 名, 模板 in 期望:
            格 = 图[493:594, max(0, 左 - 4):左 + 60]
            self.assertEqual(任务._槽位最佳模板(格, 模板)[0], 名)


class 跟随法术计划测试(unittest.TestCase):
    def setUp(self):
        from 任务流程.主世界打鱼.进攻 import 进攻任务
        self.任务 = 进攻任务.__new__(进攻任务)

    def _项(self, 名, 数):
        return {"类别": "药水", "名称": f"法术_{名}", "数量": 数, "区域": (0, 0, 1, 1)}

    def test_按批沿路径施放且控制法术在核心(self):
        清单 = [self._项("狂暴法术", 2), self._项("冰冻法术", 3), self._项("急速法术", 2),
              self._项("疗伤法术", 1), self._项("闪电法术", 3),
              {"类别": "兵种", "名称": "兵种_女巫", "数量": 3}]
        入口 = [(150, 250), (160, 260)]
        计划 = self.任务.跟随控制法术计划(清单, 入口)
        名称 = [项["名称"] for 项, _, _ in 计划]
        self.assertEqual(名称.count("法术_狂暴法术"), 2)
        self.assertEqual(名称.count("法术_冰冻法术"), 3)
        self.assertNotIn("法术_闪电法术", 名称)
        中心 = self.任务.阵营中心()
        def 到中心(点):
            return ((点[0] - 中心[0]) ** 2 + (点[1] - 中心[1]) ** 2) ** 0.5
        第一批 = [点 for 项, 点, 批 in 计划 if 批 == 0]
        冰冻 = [点 for 项, 点, 批 in 计划 if 项["名称"] == "法术_冰冻法术"]
        self.assertTrue(all(批 >= 1 for 项, _, 批 in 计划 if 项["名称"] == "法术_冰冻法术"))
        self.assertLess(max(到中心(点) for 点 in 冰冻), min(到中心(点) for 点 in 第一批))
        self.assertEqual(len(set(冰冻)), 3)

    def test_复苏和回溯不自动施放(self):
        计划 = self.任务.跟随控制法术计划(
            [self._项("复苏法术", 1), self._项("回溯法术", 1), self._项("隐形法术", 1)], [(150, 250)]
        )
        self.assertEqual([项["名称"] for 项, _, _ in 计划], ["法术_隐形法术"])

    def test_没有下兵位置或没有跟随法术时不施放(self):
        self.assertEqual(self.任务.跟随控制法术计划([self._项("狂暴法术", 2)], []), [])
        self.assertEqual(self.任务.跟随控制法术计划([self._项("闪电法术", 2)], [(100, 100)]), [])


if __name__ == "__main__":
    unittest.main()
