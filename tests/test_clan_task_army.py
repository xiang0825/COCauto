import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 数据库.任务数据库 import 机器人设置
from 任务流程.活动.部落竞赛 import 加载配置, 部落竞赛任务, 识别任务类型
from 任务流程.活动.竞赛配兵策略 import 构建任务配兵
from 任务流程.主世界打鱼.进攻 import 进攻任务


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

    def test_没有可恢复的基准配兵不接动态配兵任务(self):
        配置, 原因 = 构建任务配兵("拆墙", "摧毁25块城墙", None, {"炸弹人"})
        self.assertIsNone(配置)
        self.assertIn("原配兵", 原因)

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


if __name__ == "__main__":
    unittest.main()
