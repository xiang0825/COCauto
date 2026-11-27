"""部落竞赛临时换兵：按编辑页实际阵容快照换兵/精确恢复，不依赖“按设置自动配兵”。

fixtures/coc_army_config_live_ui.png 是 MuMu 实机 800×600 编辑军队主页面：
兵种 雷龙×8、气球兵×22、弓箭手×2（352/352），法术 闪电×11（11/11），攻城 攻城气球×1（1/3）。
"""

import os
import tempfile
import threading
import unittest
import unittest.mock
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.军队配置 import 编辑军队 as 编
from 任务流程.活动.竞赛配兵策略 import 按快照构建临时阵容, 解析要求数量

实机图 = os.path.join(os.path.dirname(__file__), "fixtures", "coc_army_config_live_ui.png")

# 主人实际阵容（隐秘哥布林预设与之完全不同）
主人兵种 = {"雷龙": 11, "飞龙": 1, "弓箭手": 2}


def 读实机图():
    return cv2.imdecode(np.fromfile(实机图, np.uint8), cv2.IMREAD_COLOR)


def 假OCR(文本表):
    """按 OCR 区域返回文字：容量区与卡片左上角数量区。"""
    def 识别(_图, 区域):
        return 文本表.get(tuple(区域), "")
    return 识别


def 实机OCR表():
    return {
        编.分区表["兵种"].人口OCR区域: "352/352",
        编.分区表["法术"].人口OCR区域: "11/11",
        编.分区表["攻城"].人口OCR区域: "1/3",
        编.阵容数量区域("兵种", 0): "x8",
        编.阵容数量区域("兵种", 1): "X22",
        编.阵容数量区域("兵种", 2): "x2",
        编.阵容数量区域("法术", 0): "x11",
        编.阵容数量区域("攻城", 0): "X1",
    }


def 新任务(上下文):
    任务 = object.__new__(编.编辑军队任务)
    任务.上下文 = 上下文
    return 任务


def 竞赛上下文(**额外):
    库 = Mock()
    库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
    值 = dict(
        设置=SimpleNamespace(是否自动配置军队=False, 阵容预设="隐秘哥布林刷资源",
                           配兵兵种=[], 配兵法术=[], 配兵攻城=""),
        数据库=库, 机器人标志="r", 置脚本状态=Mock(), 脚本延时=Mock(),
        _部落竞赛配兵配置覆盖={"兵种": {"炸弹人": 0.5}},
        _竞赛配兵关键单位={"兵种": ["炸弹人"]},
        _竞赛配兵任务键="拆墙:摧毁25块城墙",
        _竞赛配兵任务文本="暴力拆墙在多人游戏中摧毁25块城墙",
        _部落竞赛配兵任务类型="拆墙",
    )
    值.update(额外)
    return SimpleNamespace(**值)


def 挂页面桩(任务):
    任务._确认主世界主页 = Mock(return_value=True)
    任务._打开编辑页 = Mock(return_value=True)
    任务._退出到主世界 = Mock()
    任务._结束编辑状态 = Mock()
    return 任务


class 快照读取测试(unittest.TestCase):
    def _任务(self, 表):
        上下文 = SimpleNamespace(置脚本状态=Mock(), 脚本延时=Mock())
        任务 = 新任务(上下文)
        图 = 读实机图()
        任务._截图 = Mock(return_value=图)
        任务._OCR文本 = 假OCR(表)
        return 任务

    def test_实机编辑页读出兵种法术攻城个数并与容量合计一致(self):
        任务 = self._任务(实机OCR表())
        兵种, 原因 = 任务._读取分区阵容("兵种")
        self.assertEqual(原因, "")
        self.assertEqual(兵种, {"单位": {"雷龙": 8, "气球兵": 22, "弓箭手": 2}, "容量": [352, 352]})
        法术, _ = 任务._读取分区阵容("法术")
        self.assertEqual(法术["单位"], {"闪电法术": 11})
        攻城, _ = 任务._读取分区阵容("攻城")
        self.assertEqual(攻城["单位"], {"攻城气球": 1})

    def test_任一数量读不到即快照不完整(self):
        任务 = self._任务({**实机OCR表(), 编.阵容数量区域("兵种", 1): ""})
        快照, 原因 = 任务._读取分区阵容("兵种")
        self.assertIsNone(快照)
        self.assertIn("数量读不到", 原因)

    def test_合计与容量不一致即快照不完整(self):
        # 例如还有卡片在可视范围外：容量 360 而识别合计 352。
        任务 = self._任务({**实机OCR表(), 编.分区表["兵种"].人口OCR区域: "360/360"})
        快照, 原因 = 任务._读取分区阵容("兵种")
        self.assertIsNone(快照)
        self.assertIn("不一致", 原因)

    def test_读不到容量即快照不完整(self):
        任务 = self._任务({**实机OCR表(), 编.分区表["兵种"].人口OCR区域: ""})
        快照, 原因 = 任务._读取分区阵容("兵种")
        self.assertIsNone(快照)
        self.assertIn("容量", 原因)

    def test_空白卡片区无法识别时不猜(self):
        任务 = self._任务(实机OCR表())
        噪声 = np.random.default_rng(1).integers(0, 255, (600, 800, 3), dtype=np.uint8)
        任务._截图 = Mock(return_value=噪声)
        快照, _ = 任务._读取分区阵容("兵种")
        self.assertIsNone(快照)

    def test_数量文字解析(self):
        self.assertEqual(编.解析卡片数量("X22"), 22)
        self.assertEqual(编.解析卡片数量("×1O"), 10)
        self.assertIsNone(编.解析卡片数量(""))
        self.assertIsNone(编.解析卡片数量("x0"))


class 临时阵容构建测试(unittest.TestCase):
    def _快照(self, 兵种=None, 攻城=None):
        return {
            "兵种": {"单位": dict(兵种 or 主人兵种), "容量": [352, 352]},
            "攻城": {"单位": dict(攻城 or {"攻城战车": 1}), "容量": [1, 3]},
        }

    def test_拆墙从主力腾空间给炸弹人_其余个数不变(self):
        临时, 原因 = 按快照构建临时阵容(
            "拆墙", "摧毁25块城墙", {"兵种": ["炸弹人"]}, self._快照())
        self.assertEqual(原因, "")
        兵 = 临时["兵种"]
        self.assertEqual(兵["飞龙"], 1)
        self.assertLess(兵["雷龙"], 11)
        self.assertGreaterEqual(兵["炸弹人"], 25)
        self.assertLessEqual(编.阵容占用(兵), 352)
        self.assertNotIn("攻城", 临时)

    def test_已带攻城战车的攻城车任务不需要换兵(self):
        临时, 原因 = 按快照构建临时阵容(
            "指定兵种", "至少需使用攻城车x1", {"攻城": ["攻城战车"]}, self._快照())
        self.assertIsNone(临时)
        self.assertTrue(原因.startswith("已满足"))

    def test_攻城车任务替换攻城器械为一个(self):
        临时, _ = 按快照构建临时阵容(
            "指定兵种", "至少需使用攻城车x1", {"攻城": ["攻城战车"]},
            self._快照(攻城={"攻城飞艇": 1}))
        self.assertEqual(临时, {"攻城": {"攻城战车": 1}})

    def test_指定兵种按要求数量(self):
        self.assertEqual(解析要求数量("至少需使用亡灵x3"), 3)
        临时, _ = 按快照构建临时阵容(
            "指定兵种", "至少需使用亡灵x3", {"兵种": ["苍蝇"]}, self._快照())
        self.assertGreaterEqual(临时["兵种"]["苍蝇"], 3)
        self.assertLessEqual(编.阵容占用(临时["兵种"]), 352)


class 竞赛换兵流程测试(unittest.TestCase):
    def test_快照不完整就不换兵并写原因(self):
        上下文 = 竞赛上下文()
        任务 = 挂页面桩(新任务(上下文))
        任务._读取分区阵容 = Mock(return_value=(None, "兵种第2张卡片数量读不到"))
        任务._配置分区 = Mock()
        任务._清空分区 = Mock()

        self.assertTrue(任务.执行())

        任务._配置分区.assert_not_called()
        任务._清空分区.assert_not_called()
        self.assertIsNone(上下文._部落竞赛配兵配置覆盖)
        self.assertEqual(上下文._竞赛配兵关键单位, {})
        self.assertEqual(上下文._竞赛配兵失败任务键, "拆墙:摧毁25块城墙")
        日志 = " ".join(c.args[0] for c in 上下文.置脚本状态.call_args_list)
        self.assertIn("快照不完整", 日志)
        self.assertIn("数量读不到", 日志)
        上下文.数据库.更新状态.assert_not_called()
        self.assertFalse(getattr(上下文, "页面恢复失败", False))

    def test_换兵前先落盘快照_成功后标记已应用且不重复进编辑页(self):
        上下文 = 竞赛上下文()
        任务 = 挂页面桩(新任务(上下文))
        快照值 = {"单位": dict(主人兵种), "容量": [352, 352]}
        保存时快照 = []
        上下文.数据库.更新状态.side_effect = lambda _r, 类型, 数据: 保存时快照.append((类型, dict(数据)))
        任务._读取分区阵容 = Mock(return_value=(快照值, ""))
        任务._配置分区 = Mock(return_value=({"炸弹人": 45}, (352, 352)))

        self.assertTrue(任务.执行())

        self.assertEqual(保存时快照[0][0], 编.快照状态类型)
        self.assertFalse(保存时快照[0][1]["已应用"])
        self.assertEqual(保存时快照[0][1]["分区"]["兵种"]["单位"], 主人兵种)
        self.assertTrue(保存时快照[-1][1]["已应用"])
        区, 临时, 关键, 确认 = 任务._配置分区.call_args.args
        self.assertEqual((区, 关键, 确认), ("兵种", ("炸弹人",), ("炸弹人",)))
        self.assertTrue(任务._配置分区.call_args.kwargs["精确"])
        self.assertEqual(临时["飞龙"], 1)

        任务._打开编辑页.reset_mock()
        self.assertTrue(任务.执行())
        任务._打开编辑页.assert_not_called()

    def test_任务完成后按快照精确恢复数量_未开自动配兵也恢复(self):
        上下文 = 竞赛上下文(_部落竞赛配兵配置覆盖=None, _竞赛配兵关键单位={})
        上下文._竞赛原阵容快照 = {
            "任务键": "拆墙:x", "已应用": True,
            "分区": {"兵种": {"单位": dict(主人兵种), "容量": [352, 352]}},
        }
        self.assertTrue(编.有待恢复竞赛快照(上下文))
        任务 = 挂页面桩(新任务(上下文))
        任务._读取分区阵容 = Mock(return_value=(
            {"单位": {"雷龙": 8, "飞龙": 1, "弓箭手": 2, "炸弹人": 45}, "容量": [352, 352]}, ""))
        任务._配置分区 = Mock(return_value=(dict(主人兵种), (352, 352)))

        self.assertTrue(任务.执行())

        任务._配置分区.assert_called_once_with("兵种", 主人兵种, (), (), 精确=True)
        self.assertFalse(编.有待恢复竞赛快照(上下文))
        上下文.数据库.更新状态.assert_called_with("r", 编.快照状态类型, {})

    def test_恢复时与快照一致的分区不点击(self):
        上下文 = 竞赛上下文(_部落竞赛配兵配置覆盖=None)
        上下文._竞赛原阵容快照 = {
            "任务键": "x", "分区": {"兵种": {"单位": dict(主人兵种), "容量": [352, 352]}},
        }
        任务 = 挂页面桩(新任务(上下文))
        任务._读取分区阵容 = Mock(return_value=({"单位": dict(主人兵种), "容量": [352, 352]}, ""))
        任务._配置分区 = Mock()
        任务._清空分区 = Mock()
        self.assertTrue(任务.执行())
        任务._配置分区.assert_not_called()
        任务._清空分区.assert_not_called()

    def test_恢复失败安全停在主页且保留快照(self):
        上下文 = 竞赛上下文(_部落竞赛配兵配置覆盖=None)
        快照 = {"任务键": "x", "分区": {"兵种": {"单位": dict(主人兵种), "容量": [352, 352]}}}
        上下文._竞赛原阵容快照 = 快照
        任务 = 挂页面桩(新任务(上下文))
        任务._读取分区阵容 = Mock(return_value=(None, "识别失败"))
        任务._配置分区 = Mock(return_value=None)

        self.assertFalse(任务.执行())

        self.assertTrue(上下文.页面恢复失败)
        任务._退出到主世界.assert_called()
        self.assertTrue(编.有待恢复竞赛快照(上下文))
        日志 = " ".join(c.args[0] for c in 上下文.置脚本状态.call_args_list)
        self.assertIn("恢复失败", 日志)
        self.assertIn("停止进攻", 日志)

    def test_临时换兵失败按快照恢复_恢复再失败则安全停止(self):
        上下文 = 竞赛上下文()
        任务 = 挂页面桩(新任务(上下文))
        快照值 = {"单位": dict(主人兵种), "容量": [352, 352]}
        任务._读取分区阵容 = Mock(side_effect=[(快照值, ""), (None, "x")])
        任务._配置分区 = Mock(return_value=None)

        self.assertFalse(任务.执行())

        self.assertEqual(任务._配置分区.call_count, 2)
        self.assertEqual(任务._配置分区.call_args_list[1].args[1], 主人兵种)
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(编.有待恢复竞赛快照(上下文))

    def test_临时换兵失败按快照恢复成功则保持原阵容继续(self):
        上下文 = 竞赛上下文()
        任务 = 挂页面桩(新任务(上下文))
        快照值 = {"单位": dict(主人兵种), "容量": [352, 352]}
        任务._读取分区阵容 = Mock(side_effect=[(快照值, ""), (None, "x")])
        任务._配置分区 = Mock(side_effect=[None, (dict(主人兵种), (352, 352))])

        self.assertTrue(任务.执行())

        self.assertFalse(getattr(上下文, "页面恢复失败", False))
        self.assertFalse(编.有待恢复竞赛快照(上下文))
        self.assertEqual(上下文._竞赛配兵失败任务键, "拆墙:摧毁25块城墙")
        self.assertIsNone(上下文._部落竞赛配兵配置覆盖)

    def test_换兵后未确认回到主页则停止(self):
        上下文 = 竞赛上下文()
        任务 = 挂页面桩(新任务(上下文))
        任务._确认主世界主页 = Mock(side_effect=[True, False])
        任务._读取分区阵容 = Mock(return_value=({"单位": dict(主人兵种), "容量": [352, 352]}, ""))
        任务._配置分区 = Mock(return_value=({}, (352, 352)))
        self.assertFalse(任务.执行())
        self.assertTrue(上下文.页面恢复失败)


class 精确复核测试(unittest.TestCase):
    def _任务(self, 读数):
        上下文 = SimpleNamespace(置脚本状态=Mock(), 脚本延时=Mock(), 停止事件=threading.Event())
        任务 = 新任务(上下文)
        任务._读取人口 = Mock(return_value=(0, 352))
        任务._打开列表 = Mock(return_value=True)
        任务._扫描可用 = Mock(side_effect=lambda 区, 名称: list(名称))
        任务._收起列表 = Mock()
        任务._清空分区 = Mock(return_value=True)
        任务._添加兵种 = Mock()
        任务._逐个添加 = Mock()
        任务._读取分区阵容 = Mock(side_effect=读数)
        return 任务

    def test_精确恢复不补偿多点_只补缺口(self):
        任务 = self._任务([
            ({"单位": {"雷龙": 10, "飞龙": 1, "弓箭手": 2}, "容量": [322, 352]}, ""),
            ({"单位": dict(主人兵种), "容量": [352, 352]}, ""),
        ])
        结果 = 任务._配置分区("兵种", dict(主人兵种), (), (), 精确=True)
        self.assertEqual(结果, (主人兵种, (352, 352)))
        首次, 补缺 = 任务._添加兵种.call_args_list
        self.assertEqual(首次.args[0], 主人兵种)
        self.assertFalse(首次.kwargs["补偿"])
        self.assertEqual(补缺.args[0], {"雷龙": 1})
        self.assertFalse(补缺.kwargs["补偿"])

    def test_数量多了即失败(self):
        任务 = self._任务([({"单位": {"雷龙": 11, "飞龙": 1, "弓箭手": 3}, "容量": [353, 360]}, "")])
        self.assertIsNone(任务._配置分区("兵种", dict(主人兵种), (), (), 精确=True))

    def test_精确配置缺单位时不清空(self):
        任务 = self._任务([])
        任务._扫描可用 = Mock(return_value=["雷龙", "弓箭手"])
        self.assertIsNone(任务._配置分区("兵种", dict(主人兵种), (), (), 精确=True))
        任务._清空分区.assert_not_called()

    def test_不补偿时每批最多三下且停止后零点击(self):
        停止事件 = threading.Event()
        上下文 = SimpleNamespace(
            停止事件=停止事件, 置脚本状态=Mock(), 脚本延时=Mock(),
            鼠标=SimpleNamespace(连续点击=Mock(side_effect=lambda *a, **k: (停止事件.set() or True))),
        )
        任务 = 新任务(上下文)
        任务._逐页 = Mock(return_value=iter([(0, np.zeros((600, 800, 3), np.uint8))]))
        任务._截图 = Mock(return_value=np.zeros((600, 800, 3), np.uint8))
        with unittest.mock.patch.object(编, "查找兵种卡片", return_value=((100, 400), 0.99)):
            任务._添加兵种({"雷龙": 11}, {}, 补偿=False)
        上下文.鼠标.连续点击.assert_called_once()
        self.assertEqual(上下文.鼠标.连续点击.call_args.args[2], 3)


class 未开自动配兵不碰军队测试(unittest.TestCase):
    def test_无快照无竞赛覆盖时不进编辑页(self):
        from 数据库.任务数据库 import 任务数据库

        库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "snap.db"))
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(是否自动配置军队=False, 阵容预设="隐秘哥布林刷资源",
                               配兵兵种=[], 配兵法术=[], 配兵攻城=""),
            数据库=库, 机器人标志="r", 置脚本状态=Mock(),
        )
        self.assertFalse(编.有待恢复竞赛快照(上下文))
        任务 = 挂页面桩(新任务(上下文))
        任务._配置流程 = Mock()
        self.assertTrue(任务.执行())
        任务._打开编辑页.assert_not_called()
        任务._配置流程.assert_not_called()

    def test_快照落盘后重启仍会恢复(self):
        from 数据库.任务数据库 import 任务数据库

        库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "snap.db"))
        旧 = SimpleNamespace(数据库=库, 机器人标志="r")
        编.保存竞赛快照(旧, {"任务键": "x", "分区": {"兵种": {"单位": dict(主人兵种), "容量": [352, 352]}}})
        新 = SimpleNamespace(数据库=库, 机器人标志="r")
        self.assertTrue(编.有待恢复竞赛快照(新))
        编.保存竞赛快照(新, {})
        self.assertFalse(编.有待恢复竞赛快照(SimpleNamespace(数据库=库, 机器人标志="r")))


if __name__ == "__main__":
    unittest.main()
