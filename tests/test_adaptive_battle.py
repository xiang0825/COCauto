import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务


class 自适应战斗测试(unittest.TestCase):
    def test_单目标也会生成多个不同落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        落点 = 任务.生成分散下兵点([
            {"中心坐标": 坐标(100, 100), "类别名称": "金矿", "置信度": 0.9}
        ])
        self.assertGreaterEqual(len(set(落点)), 3)

    def test_连续低表现切换探索策略(self):
        class 数据库:
            def 获取最新完整状态(self, _标志):
                return SimpleNamespace(状态数据={
                    "战斗学习": {
                        "近期": [
                            {"结果": "失败", "摧毁率": 32},
                            {"结果": "胜利", "摧毁率": 41},
                        ]
                    }
                })

        上下文 = SimpleNamespace(数据库=数据库(), 机器人标志="测试")
        任务 = 进攻任务.__new__(进攻任务)
        self.assertEqual(任务.读取自适应进攻策略(上下文), "分散探索")

    def test_拆分OCR框仍能读取百分比(self):
        结果 = [
            ([[600, 450], [650, 450], [650, 470], [600, 470]], "摧毁率", 0.99),
            ([[700, 450], [720, 450], [720, 470], [700, 470]], "67", 0.99),
        ]
        self.assertEqual(
            等待战斗结束并回营任务.从OCR结果提取摧毁率(结果, "摧毁率67"),
            67,
        )

    def test_资源阵营评分范围和严格门槛(self):
        易攻目标 = [
            {"类别名称": "金库", "裁剪坐标": [55, 245, 85, 275], "置信度": 0.95},
            {"类别名称": "圣水瓶", "裁剪坐标": [715, 270, 745, 300], "置信度": 0.95},
            {"类别名称": "金矿", "裁剪坐标": [85, 220, 115, 250], "置信度": 0.90},
            {"类别名称": "圣水采集器", "裁剪坐标": [680, 300, 710, 330], "置信度": 0.90},
        ]
        难攻目标 = [
            {"类别名称": "金库", "裁剪坐标": [380, 280, 410, 310], "置信度": 0.95},
            {"类别名称": "圣水瓶", "裁剪坐标": [420, 290, 450, 320], "置信度": 0.95},
        ]
        易攻评分, 依据 = 搜索目标敌人任务.计算资源易窃取评分(易攻目标)
        难攻评分, _ = 搜索目标敌人任务.计算资源易窃取评分(难攻目标)
        self.assertGreater(易攻评分, 5.0)
        self.assertLessEqual(难攻评分, 5.0)
        self.assertGreaterEqual(易攻评分, 0.0)
        self.assertLessEqual(易攻评分, 10.0)
        self.assertIn("高价值资源可达比例", 依据)
        self.assertFalse(搜索目标敌人任务.是否达到资源易窃取门槛(5.0))
        self.assertTrue(搜索目标敌人任务.是否达到资源易窃取门槛(5.01))

    def test_下兵点只允许边界带并能生成邻近候选(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
        )
        候选点 = 任务.生成可下兵候选点(上下文, 坐标(400, 285))
        self.assertEqual(len(候选点), 8)
        self.assertTrue(all(任务.下兵点是否位于可下兵区域(上下文, 点) for 点 in 候选点))
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (400, 285)))

    def test_下兵点不会落入兵栏或放弃按钮(self):
        任务 = 进攻任务.__new__(进攻任务)
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
        )
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (300, 498)))
        self.assertFalse(任务.下兵点是否位于可下兵区域(上下文, (60, 440)))

    def test_兵栏变化才视为下兵成功(self):
        任务 = 进攻任务.__new__(进攻任务)
        前图 = np.zeros((36, 31, 3), dtype=np.uint8)
        后图 = 前图.copy()
        self.assertFalse(任务.判断下兵反馈(前图, 后图, {"类别": "兵种"}))
        后图[10:25, 5:25] = 255
        self.assertTrue(任务.判断下兵反馈(前图, 后图, {"类别": "兵种"}))

    def test_英雄技能无专用模板时按英雄槽位识别高亮(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = Mock()
        任务.模板识别._安全加载模板.return_value = None
        战前图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        战后图像 = 战前图像.copy()
        # 模拟第4格英雄技能区域出现紫色高亮；颜色使用 BGR。
        战后图像[530:570, 245:290] = (200, 0, 255)
        上下文 = SimpleNamespace(
            当前兵栏清单=[{
                "槽位": 4,
                "名称": "英雄_野蛮人之王",
                "类别": "英雄",
                "区域": (234, 510, 304, 594),
            }],
            _战斗开始兵栏画面=战前图像,
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=战后图像),
            ),
            置脚本状态=Mock(),
        )
        状态 = 任务.识别英雄技能状态(上下文)
        self.assertEqual(状态["第4格/英雄_野蛮人之王"], "可用")

    def test_被拒绝的候选点会换点而不是重复点击(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        日志 = []
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        候选点 = 任务.生成可下兵候选点(上下文, 坐标(400, 285))
        with patch.object(任务, "读取兵栏槽位图像", side_effect=[object()] * 5), \
             patch.object(任务, "判断下兵反馈", side_effect=[False, False, False, True]):
            成功, 使用坐标 = 任务.尝试下兵至可用位置(
                上下文,
                {"名称": "测试兵", "区域": (0, 0, 1, 1), "类别": "兵种"},
                坐标(400, 285),
                候选点[:2],
                5,
            )
        self.assertTrue(成功)
        self.assertEqual(使用坐标, 候选点[1])
        self.assertEqual(点击记录, 候选点[:2])
        self.assertTrue(any("换下一个候选点" in 文本 for 文本 in 日志))

    def test_同方向不同目标不共享同一个缓存落点(self):
        任务 = 进攻任务.__new__(进攻任务)
        兵栏项 = {"槽位": 1}
        self.assertNotEqual(
            任务._下兵方向缓存键(坐标(620, 400), 兵栏项),
            任务._下兵方向缓存键(坐标(670, 400), 兵栏项),
        )

    def test_同一坐标被拒绝后本场不重复点击(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=lambda *_参数: None,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        任务.判断下兵反馈 = Mock(return_value=False)
        兵栏项 = {"槽位": 1, "名称": "测试兵", "类别": "兵种", "区域": (0, 0, 1, 1)}
        目标 = 坐标(400, 285)
        候选点 = [(394, 20)]
        任务.尝试下兵至可用位置(上下文, 兵栏项, 目标, 候选点, 5)
        任务.尝试下兵至可用位置(上下文, 兵栏项, 目标, 候选点, 5)
        self.assertEqual(点击记录, [候选点[0]])

    def test_结算页出现后候选点循环立即停止(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        日志 = []
        上下文 = SimpleNamespace(
            _部署区域已初始化=True,
            _部署红色掩码=None,
            本场可下兵区域={
                "边界顶点": [(394, 20), (745, 293), (405, 549), (68, 278)],
                "边界带宽": 58.0,
            },
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.读取兵栏槽位图像 = lambda *_参数: object()
        任务.战斗是否仍在进行 = Mock(return_value=False)
        成功, 坐标结果 = 任务.尝试下兵至可用位置(
            上下文,
            {"名称": "测试兵", "区域": (0, 0, 1, 1), "类别": "兵种"},
            坐标(400, 285),
            [(400, 20), (410, 25)],
            5,
        )
        self.assertFalse(成功)
        self.assertIsNone(坐标结果)
        self.assertEqual(点击记录, [])
        self.assertTrue(any("停止目标" in 文本 for 文本 in 日志))

    def test_兵量足够的普通兵种才启用高速批次(self):
        任务 = 进攻任务.__new__(进攻任务)
        设置 = SimpleNamespace(是否启用高速下兵=True)
        上下文 = SimpleNamespace(设置=设置)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "兵种", "数量": 7}, 7), 1)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "兵种", "数量": 8}, 10), 5)
        self.assertEqual(任务.取高速下兵批次(上下文, {"类别": "英雄", "数量": 20}, 10), 1)

    def test_高速模式分别调用连点和短按压(self):
        class 鼠标:
            def __init__(self):
                self.调用 = []

            def 连续点击(self, *参数, **关键字):
                self.调用.append(("连点", 参数, 关键字))
                return True

            def 长按(self, *参数, **关键字):
                self.调用.append(("短按", 参数, 关键字))
                return True

        鼠标对象 = 鼠标()
        日志 = []
        上下文 = SimpleNamespace(鼠标=鼠标对象, 置脚本状态=日志.append)
        任务 = 进攻任务.__new__(进攻任务)
        # 高速批次最多四次额外点击（合计5个单位），保留40ms呼吸间隔。
        self.assertEqual(任务.执行高速下兵批次(上下文, (100, 200), 5, "快速连点"), 4)
        self.assertEqual(任务.执行高速下兵批次(上下文, (100, 200), 2, "短按压"), 2)
        self.assertEqual([项[0] for 项 in 鼠标对象.调用], ["连点", "短按"])

    def test_英雄后第一个未匹配槽位保留为攻城器械(self):
        任务 = 进攻任务.__new__(进攻任务)
        结果 = 任务._按英雄布局修正槽位类别([
            {"槽位": 4, "类别": "英雄", "名称": "英雄_野蛮人之王", "数量": 1},
            {"槽位": 5, "类别": "攻城器械", "名称": "未匹配攻城器械模板", "数量": 2},
            {"槽位": 6, "类别": "未知", "名称": "法术_生日大爆炸法术", "数量": 2},
            {"槽位": 7, "类别": "未知", "名称": "未匹配模板", "数量": 0},
        ], 4)
        self.assertEqual(结果[1]["类别"], "攻城器械")
        self.assertEqual(结果[2]["类别"], "药水")
        self.assertEqual(结果[3]["类别"], "药水")

    def test_英雄落地后只尝试一次可用技能(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        点击 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            _本场已部署槽位={4},
            _本场已释放英雄技能=set(),
            英雄技能状态={"第4格/英雄_野蛮人之王": "可用"},
            停止事件=SimpleNamespace(is_set=lambda: False),
            点击=点击,
            脚本延时=lambda _毫秒: None,
            置脚本状态=日志.append,
        )
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.识别英雄技能状态 = Mock(
            return_value={"第4格/英雄_野蛮人之王": "已使用/不可用"}
        )
        兵栏项 = {
            "槽位": 4,
            "名称": "英雄_野蛮人之王",
            "区域": (254, 493, 310, 594),
        }
        self.assertTrue(任务.尝试释放英雄技能(上下文, 兵栏项))
        self.assertEqual(点击.call_args.args[:2], (282, 572))
        self.assertIn(4, 上下文._本场已释放英雄技能)
        self.assertTrue(any("技能已点击" in 文本 for 文本 in 日志))

    def test_同一兵栏槽位连续下兵不会重复点击反选(self):
        任务 = 进攻任务.__new__(进攻任务)
        点击记录 = []
        设置 = SimpleNamespace(是否启用高速下兵=False, 下兵间隔毫秒=5)
        上下文 = SimpleNamespace(
            设置=设置,
            当前兵栏清单=[
                {"槽位": 1, "类别": "兵种", "数量": 2,
                 "区域": (20, 20, 50, 50), "名称": "测试兵"}
            ],
            点击=lambda x, y, **_参数: 点击记录.append((x, y)),
            置脚本状态=lambda *_参数, **_关键字: None,
            脚本延时=lambda _毫秒: None,
            op=SimpleNamespace(获取屏幕图像cv=lambda *_区域: np.full((30, 30, 3), (0, 80, 200), dtype=np.uint8)),
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.生成可下兵候选点 = lambda *_参数: [(100, 100)]
        任务.记录可下兵点标记 = lambda *_参数: None
        任务.刷新选中兵种后的下兵边界 = lambda *_参数: None
        任务.战斗是否仍在进行 = lambda *_参数: True
        任务.是否为灰色图片 = lambda *_参数: False
        with patch.object(任务, "尝试下兵至可用位置", side_effect=[(True, (100, 100)), (True, (100, 100))]):
            任务.执行下兵流程(上下文, [{"中心坐标": 坐标(100, 100)}])
        self.assertEqual(点击记录, [(35, 35)])

    def test_补下读取统一兵栏区域的x0并跳过彩色空卡(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        读取区域 = []
        设置 = SimpleNamespace(漏下兵种检测格数=1)
        上下文 = SimpleNamespace(
            机器人标志="测试",
            数据库=SimpleNamespace(获取机器人设置=lambda _标志: 设置),
            当前兵栏清单=[{
                "槽位": 1,
                "类别": "兵种",
                "数量": 117,
                "区域": (56, 493, 112, 594),
                "名称": "兵种_超级哥布林",
            }],
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((36, 56, 3), dtype=np.uint8),
            ),
            置脚本状态=日志.append,
            点击=lambda *_参数, **_关键字: self.fail("x0空卡不应再次点击"),
            脚本延时=lambda _毫秒: None,
        )
        任务.准备可下兵区域 = lambda *_参数, **_关键字: None
        任务.战斗是否仍在进行 = lambda _上下文: True
        任务.是否为灰色图片 = lambda _图像: False

        def 读取当前数量(_上下文, 区域):
            读取区域.append(tuple(区域))
            return 0

        任务.读取槽位显示兵量 = 读取当前数量
        任务.执行漏下兵种下兵流程(
            上下文,
            [{"中心坐标": 坐标(100, 100)}],
        )

        self.assertEqual(读取区域, [(56, 493, 112, 594)])
        self.assertTrue(any("当前数量已确认0" in 文本 for 文本 in 日志))

    def test_读取槽位显示兵量能把OCR的XO识别为零(self):
        任务 = 进攻任务.__new__(进攻任务)
        任务._识别槽位文本 = lambda _图像: "XO|12"
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=lambda *_区域: np.zeros((101, 56, 3), dtype=np.uint8),
            ),
        )
        self.assertEqual(
            任务.读取槽位显示兵量(上下文, (56, 493, 112, 594)),
            0,
        )

    def test_回营模板没有结果页标记时仍视为战斗中(self):
        class 匹配器:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "领取奖励" in 模板路径:
                    return False, (0, 0), None
                return True, (400, 550), None

        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 匹配器()
        任务.ocr引擎 = lambda *_参数, **_关键字: ([], None)
        self.assertFalse(任务._结束画面有结果标记(np.zeros((600, 800, 3), dtype=np.uint8)))

    def test_结果页有失败文字才允许确认结束(self):
        class 匹配器:
            def 执行匹配(self, _图像, 模板路径, **_参数):
                if "领取奖励" in 模板路径:
                    return False, (0, 0), None
                return True, (400, 550), None

        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 匹配器()
        任务.ocr引擎 = lambda *_参数, **_关键字: (
            [([[0, 0], [1, 0], [1, 1], [0, 1]], "战斗失败", 0.99)],
            None,
        )
        self.assertTrue(任务._结束画面有结果标记(np.zeros((600, 800, 3), dtype=np.uint8)))

    def test_页面识别器确认零点八五分结算页(self):
        class 匹配器:
            def 执行匹配(self, _图像, _模板路径, **_参数):
                return False, (0, 0), None

        class 页面识别器:
            def 识别(self, _图像, **_参数):
                return SimpleNamespace(页面="战斗结算", 可信度=0.85)

        任务 = 进攻任务.__new__(进攻任务)
        任务.模板识别 = 匹配器()
        任务.ocr引擎 = lambda *_参数, **_关键字: ([], None)
        任务.上下文 = SimpleNamespace(
            _获取点击页面识别器=lambda: 页面识别器()
        )

        self.assertTrue(
            任务._结束画面有结果标记(np.zeros((600, 800, 3), dtype=np.uint8))
        )

    def test_下兵前会等待战斗过渡完成(self):
        任务 = 进攻任务.__new__(进攻任务)
        日志 = []
        上下文 = SimpleNamespace(
            停止事件=SimpleNamespace(
                is_set=lambda: False,
                wait=lambda timeout: None,
            ),
            识别点击画面=Mock(side_effect=[
                SimpleNamespace(页面="战斗过渡"),
                SimpleNamespace(页面="战斗中"),
            ]),
            置脚本状态=日志.append,
        )

        self.assertEqual(任务.等待战斗画面确认(上下文, 超时秒=2), "战斗中")
        self.assertTrue(any("开始下兵" in 文本 for 文本 in 日志))


if __name__ == "__main__":
    unittest.main()
