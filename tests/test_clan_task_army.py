import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 数据库.任务数据库 import 机器人设置
from 任务流程.活动.部落竞赛 import 加载配置, 部落竞赛任务, 文字项, 识别任务类型
from 任务流程.活动.竞赛配兵策略 import 构建任务配兵
from 任务流程.主世界打鱼.进攻 import 进攻任务
from 任务流程.主世界打鱼.进攻坐标逻辑计算 import 坐标


class 竞赛配兵方案测试(unittest.TestCase):
    def setUp(self):
        self.原配兵 = {
            "兵种": {"雷龙": 6, "飞龙": 4},
            "法术": {"狂暴法术": 3},
            "攻城": {"攻城飞艇": 1},
        }

    def test_拆墙任务只追加炸弹人并保留原配兵(self):
        配置, 原因 = 构建任务配兵(
            "拆墙", "暴力拆墙在多人游戏中摧毁25块城墙", self.原配兵, {"炸弹人"}
        )

        self.assertEqual(原因, "")
        self.assertEqual(配置["兵种"]["雷龙"], 6)
        self.assertEqual(配置["兵种"]["飞龙"], 4)
        self.assertGreater(配置["兵种"]["炸弹人"], 0)
        self.assertEqual(配置["法术"], self.原配兵["法术"])
        self.assertEqual(配置["攻城"], self.原配兵["攻城"])

    def test_亡灵指定兵种映射到游戏配置名苍蝇(self):
        配置, 原因 = 构建任务配兵(
            "指定兵种",
            "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1",
            self.原配兵,
            {"苍蝇"},
        )

        self.assertEqual(原因, "")
        self.assertGreater(配置["兵种"]["苍蝇"], 0)
        self.assertEqual(配置["兵种"]["雷龙"], 6)

    def test_攻城车任务临时替换攻城飞艇且仍保留其它兵种法术(self):
        配置, 原因 = 构建任务配兵(
            "指定兵种",
            "在1场多人对战中赢得1颗胜利之星，至少需使用攻城车x1",
            self.原配兵,
            {"攻城战车"},
        )

        self.assertEqual(原因, "")
        self.assertEqual(配置["攻城"], {"攻城战车": 1})
        self.assertEqual(配置["兵种"], self.原配兵["兵种"])
        self.assertEqual(配置["法术"], self.原配兵["法术"])

    def test_未解锁或未知的指定单位拒绝方案并说明原因(self):
        配置, 原因 = 构建任务配兵(
            "指定兵种",
            "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1",
            self.原配兵,
            {"气球兵"},
        )
        self.assertIsNone(配置)
        self.assertIn("未解锁", 原因)

        配置, 原因 = 构建任务配兵(
            "指定兵种",
            "在1场多人对战中赢得1颗胜利之星，至少需使用神秘兵x1",
            self.原配兵,
            {"神秘兵"},
        )
        self.assertIsNone(配置)
        self.assertIn("不支持", 原因)

        配置, 原因 = 构建任务配兵(
            "指定兵种",
            "在1场多人对战中赢得1颗胜利之星，至少需使用攻城滚木车x1",
            self.原配兵,
            {"攻城滚木车"},
        )
        self.assertIsNone(配置)
        self.assertIn("不支持", 原因)

    def test_未开自动配兵也可生成方案_实际个数由编辑页快照决定(self):
        # rc161：不再要求“按设置自动配兵”作为恢复基准；换兵前读实际阵容快照。
        配置, 原因 = 构建任务配兵("拆墙", "摧毁25块城墙", None, {"炸弹人"})
        self.assertEqual(原因, "")
        self.assertIn("炸弹人", 配置["兵种"])

    def test_资源摧毁类返回基准配兵不切换(self):
        配置, 原因 = 构建任务配兵("掠夺金币", "在多人游戏中掠夺金币", self.原配兵, set())
        self.assertIsNone(配置)
        self.assertIn("保持原配兵", 原因)

    def test_竞赛任务切换覆盖并在任务变更时清除恢复(self):
        上下文 = SimpleNamespace(
            设置=机器人设置(是否自动配置军队=True),
            _部落竞赛基准配兵配置=self.原配兵,
            _部落竞赛可用单位={"兵种": {"苍蝇"}},
            置脚本状态=Mock(),
        )
        任务 = object.__new__(部落竞赛任务)
        任务.上下文 = 上下文
        任务._配置 = 加载配置()
        任务._截止 = 0
        任务._时钟 = lambda: 0

        self.assertTrue(
            任务._同步竞赛配兵(
                "指定兵种", "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1"
            )
        )
        self.assertIn("苍蝇", 上下文._部落竞赛配兵配置覆盖["兵种"])
        self.assertEqual(上下文._竞赛配兵关键单位["兵种"], ["苍蝇"])

        任务._清除竞赛配兵("竞赛任务已完成")
        self.assertIsNone(上下文._部落竞赛配兵配置覆盖)
        self.assertEqual(上下文._竞赛配兵关键单位, {})
        self.assertTrue(any("恢复原配兵" in call.args[0] for call in 上下文.置脚本状态.call_args_list))

    def test_同一任务切换失败后保持基准并不反复重配(self):
        文本 = "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1"
        上下文 = SimpleNamespace(
            设置=机器人设置(是否自动配置军队=True),
            _部落竞赛基准配兵配置=self.原配兵,
            _部落竞赛可用单位={"兵种": {"苍蝇"}},
            _竞赛配兵失败任务键=f"指定兵种:{文本[:48]}",
            置脚本状态=Mock(),
        )
        任务 = object.__new__(部落竞赛任务)
        任务.上下文 = 上下文
        任务._配置 = 加载配置()
        任务._截止 = 0
        任务._时钟 = lambda: 0

        self.assertFalse(任务._同步竞赛配兵("指定兵种", 文本))
        self.assertIsNone(getattr(上下文, "_部落竞赛配兵配置覆盖", None))
        self.assertEqual(上下文._竞赛配兵关键单位, {})
        self.assertTrue(any("保持原配兵继续打鱼" in call.args[0] for call in 上下文.置脚本状态.call_args_list))

    def test_拆墙识别要求预检到炸弹人(self):
        拆墙 = "暴力拆墙在多人游戏中摧毁25块城墙"
        self.assertEqual(识别任务类型(拆墙, 加载配置(), 可用单位={"炸弹人"}), "拆墙")
        self.assertIsNone(识别任务类型(拆墙, 加载配置(), 可用单位={"雷龙"}))

    def test_要求单位必须有成功下兵槽位反馈(self):
        上下文 = SimpleNamespace(
            _竞赛配兵关键单位={"兵种": ["苍蝇"]},
            _本场已部署槽位=set(), 置脚本状态=Mock(),
        )
        任务 = object.__new__(进攻任务)
        兵栏 = [{"槽位": 3, "类别": "兵种", "名称": "兵种_苍蝇.bmp"}]

        任务._记录竞赛要求单位部署结果(上下文, 兵栏)
        上下文.置脚本状态.assert_called_once()
        self.assertIn("未获游戏反馈确认", 上下文.置脚本状态.call_args.args[0])

        上下文._本场已部署槽位.add(3)
        上下文.置脚本状态.reset_mock()
        任务._记录竞赛要求单位部署结果(上下文, 兵栏)
        上下文.置脚本状态.assert_not_called()

    def test_没有资源目标时竞赛关键单位仍走安全落点并记录(self):
        任务 = object.__new__(进攻任务)
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否自动配兵=False, 是否自动配置军队=False, 下兵间隔毫秒=25),
            _部落竞赛配兵任务类型="指定兵种",
            _竞赛配兵关键单位={"兵种": ["炸弹人"]},
            当前兵栏清单=[
                {"槽位": 1, "类别": "兵种", "数量": 1, "区域": (0, 0, 10, 10), "名称": "兵种_炸弹人.bmp"},
                {"槽位": 2, "类别": "兵种", "数量": 20, "区域": (10, 0, 20, 10), "名称": "兵种_弓箭手.bmp"},
            ],
            _本场已部署槽位={1},
            op=SimpleNamespace(获取屏幕图像cv=lambda *a, **k: None),
            点击=Mock(return_value=True),
            置脚本状态=Mock(),
        )
        任务.准备可下兵区域 = Mock()
        任务.阵营中心 = Mock(return_value=(400, 300))
        任务.生成可下兵候选点 = Mock(return_value=[(400, 490)])
        任务.记录可下兵点标记 = Mock()
        任务.是否为灰色图片 = Mock(return_value=False)
        任务.战斗是否仍在进行 = Mock(return_value=True)
        任务.刷新选中兵种后的下兵边界 = Mock()
        任务.复核兵栏槽位选择 = Mock(return_value=True)
        任务.尝试下兵至可用位置 = Mock(return_value=(True, (400, 490)))
        任务._记录实际下兵反馈 = Mock()
        任务._记录竞赛要求单位部署结果 = Mock()

        任务.执行下兵流程(上下文, [])

        任务.尝试下兵至可用位置.assert_called_once()
        self.assertEqual(任务.尝试下兵至可用位置.call_args.args[2], 坐标(400, 300))
        self.assertEqual(任务.尝试下兵至可用位置.call_args.args[1]["槽位"], 1)
        self.assertTrue(any("没有有效资源目标" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))
        任务._记录竞赛要求单位部署结果.assert_called_once()
        self.assertEqual(
            [项["槽位"] for 项 in 任务._记录竞赛要求单位部署结果.call_args.args[1]], [1]
        )

    def test_进行中卡片与缓存不一致或无法确认时清除临时配兵(self):
        原文本 = "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1"
        for 当前卡文本 in (
            "在1场多人对战中赢得1颗胜利之星，至少需使用气球兵x1",
            None,
        ):
            with self.subTest(当前卡文本=当前卡文本):
                记录 = {"当前任务类型": "指定兵种", "当前任务文本": 原文本, "当前任务卡文本": 原文本}
                上下文 = SimpleNamespace(
                    设置=机器人设置(是否自动配置军队=True),
                    数据库=SimpleNamespace(
                        获取最新完整状态=lambda _: SimpleNamespace(状态数据={"部落竞赛检查记录": dict(记录)})
                    ),
                    机器人标志="r",
                    _部落竞赛配兵配置覆盖={"兵种": {"苍蝇": 1}},
                    _竞赛配兵关键单位={"兵种": ["苍蝇"]},
                    _竞赛配兵任务键="指定兵种:旧任务",
                    _部落竞赛配兵任务类型="指定兵种",
                    置脚本状态=Mock(),
                )
                任务 = object.__new__(部落竞赛任务)
                任务.上下文 = 上下文
                任务._配置 = 加载配置()
                任务.数据库 = 上下文.数据库
                任务.机器人标志 = "r"
                任务._截止 = 0
                任务._时钟 = lambda: 0
                任务._本次进攻前 = False
                任务._存在进行中任务 = Mock(return_value=True)
                任务._读取进度 = Mock(return_value=(0, 1))
                任务._同步竞赛配兵 = Mock(return_value=True)
                任务._进度 = None
                任务卡文字项 = [文字项("0/1", (329, 223, 357, 241))]
                if 当前卡文本:
                    任务卡文字项.append(文字项(当前卡文本, (280, 145, 410, 181)))

                self.assertEqual(任务._处理面板({"文字": 任务卡文字项, "图像": None}), "已有任务")

                self.assertIsNone(上下文._部落竞赛配兵配置覆盖)
                self.assertEqual(上下文._竞赛配兵关键单位, {})
                任务._同步竞赛配兵.assert_not_called()

    def test_进行中任务卡与缓存完全一致时按已确认任务同步(self):
        文本 = "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1"
        记录 = {"当前任务类型": "指定兵种", "当前任务文本": "详情全文：" + 文本, "当前任务卡文本": 文本}
        上下文 = SimpleNamespace(
            设置=机器人设置(是否自动配置军队=True),
            数据库=SimpleNamespace(
                获取最新完整状态=lambda _: SimpleNamespace(状态数据={"部落竞赛检查记录": dict(记录)})
            ),
            机器人标志="r",
            _部落竞赛配兵配置覆盖={"兵种": {"苍蝇": 1}},
            _竞赛配兵关键单位={"兵种": ["苍蝇"]},
            _竞赛配兵任务键="指定兵种:当前任务",
            _部落竞赛配兵任务类型="指定兵种",
            置脚本状态=Mock(),
        )
        任务 = object.__new__(部落竞赛任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = "r"
        任务._配置 = 加载配置()
        任务._截止 = 0
        任务._时钟 = lambda: 0
        任务._本次进攻前 = False
        任务._存在进行中任务 = Mock(return_value=True)
        任务._读取进度 = Mock(return_value=(0, 1))
        任务._同步竞赛配兵 = Mock(return_value=True)
        任务卡文字项 = [
            文字项("0/1", (329, 223, 357, 241)),
            文字项(文本, (280, 145, 410, 181)),
            文字项("另一个任务文本", (475, 145, 610, 181)),
        ]

        self.assertEqual(任务._处理面板({"文字": 任务卡文字项, "图像": None}), "已有任务")

        # 卡文本只作比对基准；同步仍用接任务时的详情全文，保持任务键一致。
        任务._同步竞赛配兵.assert_called_once_with("指定兵种", "详情全文：" + 文本)
        self.assertIsNotNone(上下文._部落竞赛配兵配置覆盖)

    def _进行中任务(self, 记录: dict):
        状态 = {"记录": dict(记录)}
        上下文 = SimpleNamespace(
            设置=机器人设置(是否自动配置军队=True),
            数据库=SimpleNamespace(
                获取最新完整状态=lambda _: SimpleNamespace(
                    状态数据={"部落竞赛检查记录": dict(状态["记录"])}
                )
            ),
            机器人标志="r",
            _部落竞赛配兵配置覆盖={"兵种": {"苍蝇": 1}},
            _竞赛配兵关键单位={"兵种": ["苍蝇"]},
            _竞赛配兵任务键="指定兵种:旧任务",
            _部落竞赛配兵任务类型="指定兵种",
            置脚本状态=Mock(),
        )
        任务 = object.__new__(部落竞赛任务)
        任务.上下文 = 上下文
        任务._配置 = 加载配置()
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = "r"
        任务._截止 = 0
        任务._时钟 = lambda: 0
        任务._本次进攻前 = False
        任务._存在进行中任务 = Mock(return_value=True)
        任务._读取进度 = Mock(return_value=(0, 5))
        任务._同步竞赛配兵 = Mock(return_value=True)
        任务._进度 = None
        任务._本轮个人积分 = None
        任务._本轮选择 = ""
        任务._本轮任务文本 = ""
        任务._当前任务类型 = ""
        任务._当前任务文本 = ""
        任务._当前任务卡文本 = ""
        任务._计划进攻复查 = Mock(return_value=0)
        任务._现在 = lambda: __import__("datetime").datetime(2026, 11, 27)
        任务._写状态 = Mock(side_effect=lambda 新: 状态.__setitem__("记录", dict(新)))
        return 任务, 上下文, 状态

    def test_进行中任务卡第一轮不一致后第二轮不回流旧类型(self):
        旧详情 = "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1"
        旧卡 = "至少需使用亡灵x1"
        新卡 = "摧毁5座迫击炮"
        任务, 上下文, 状态 = self._进行中任务(
            {"当前任务": "指定兵种（100分）", "当前任务类型": "指定兵种",
             "当前任务文本": 旧详情, "当前任务卡文本": 旧卡}
        )
        卡 = [文字项("0/5", (329, 223, 357, 241)), 文字项(新卡, (280, 145, 410, 181))]

        for 轮 in (1, 2):
            with self.subTest(轮=轮):
                任务._当前任务类型 = 任务._当前任务文本 = 任务._当前任务卡文本 = ""
                上下文._部落竞赛配兵配置覆盖 = {"兵种": {"苍蝇": 1}}
                上下文._竞赛配兵关键单位 = {"兵种": ["苍蝇"]}
                self.assertEqual(任务._处理面板({"文字": 卡, "图像": None}), "已有任务")
                任务._记录结果(dict(状态["记录"]), "已有任务", 30)
                self.assertIsNone(上下文._部落竞赛配兵配置覆盖)
                任务._同步竞赛配兵.assert_not_called()
                self.assertEqual(状态["记录"]["当前任务类型"], "未知")
                self.assertEqual(状态["记录"]["当前任务卡文本"], 新卡)
                self.assertNotIn("亡灵", 状态["记录"]["当前任务文本"])

    def test_接任务后按卡片口径记录比对基准(self):
        任务, 上下文, 状态 = self._进行中任务({})
        卡文 = "至少需使用亡灵x1"
        任务._截图 = Mock(return_value=None)
        任务._OCR = Mock(return_value=[
            文字项("0/1", (329, 223, 357, 241)), 文字项(卡文, (280, 145, 410, 181)),
        ])
        任务._关闭详情 = Mock()
        self.assertEqual(任务._读取已接任务卡文本(), 卡文)
        任务._关闭详情.assert_not_called()

        任务._本轮选择 = "指定兵种（100分）"
        任务._本轮任务文本 = "详情全文：" + 卡文
        任务._当前任务卡文本 = 卡文
        任务._记录结果({}, "已接任务", 30)
        self.assertEqual(状态["记录"]["当前任务卡文本"], 卡文)

        # 下一轮同一张卡：按卡文本比对一致，沿用接任务时的类型与详情全文。
        任务._当前任务类型 = 任务._当前任务文本 = 任务._当前任务卡文本 = ""
        self.assertEqual(
            任务._处理面板({"文字": 任务._OCR.return_value, "图像": None}), "已有任务"
        )
        任务._同步竞赛配兵.assert_called_once_with("指定兵种", "详情全文：" + 卡文)

    def test_进行中卡片无文案时读取安全详情并与缓存一致后同步(self):
        文本 = "在1场多人对战中赢得1颗胜利之星，至少需使用亡灵x1"
        任务, 上下文, _ = self._进行中任务(
            {"当前任务类型": "指定兵种", "当前任务文本": "详情全文：" + 文本, "当前任务卡文本": 文本}
        )
        任务._读取进度 = Mock(return_value=(11, 25))
        任务._等待 = Mock(return_value=文本)
        任务._识别当前任务详情 = Mock()
        任务._点击 = Mock(return_value=True)
        任务._关闭详情 = Mock()
        项列表 = [文字项("11/25", (329, 223, 357, 241))]

        self.assertEqual(任务._处理面板({"文字": 项列表, "图像": None}), "已有任务")

        任务._点击.assert_called_once_with((341, 165), "进行中任务卡详情")
        self.assertEqual(任务._等待.call_args.args[1], "进行中任务详情")
        任务._关闭详情.assert_called_once_with()
        任务._同步竞赛配兵.assert_called_once_with("指定兵种", "详情全文：" + 文本)


if __name__ == "__main__":
    unittest.main()
