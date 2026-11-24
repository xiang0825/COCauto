"""自动配兵（编辑军队页）：实机截图上的兵种查找、人口解析、流程分支与点击护栏放行。

fixtures/军队编辑 下是 MuMu 实机 800×600 截图：
m1 战斗菜单；g2 编辑页（军营已清空、兵种列表未打开）；
m3/s1/s2 军营满员时的灰色卡列表；g3/w1 军营清空后的彩色卡列表。
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.军队配置 import 编辑军队 as 编

目录 = os.path.join(os.path.dirname(__file__), "fixtures", "军队编辑")


def 读图(名):
    return cv2.imdecode(np.fromfile(os.path.join(目录, f"{名}.png"), np.uint8), cv2.IMREAD_COLOR)


def 找到的兵种(图):
    return {名: 编.查找兵种卡片(图, 名)[0] for 名 in 编.兵种人口 if 编.查找兵种卡片(图, 名)}


class 兵种查找测试(unittest.TestCase):
    def test_灰色卡页面(self):
        self.assertEqual(
            set(找到的兵种(读图("m3"))), {"野蛮人", "巨人", "炸弹人", "弓箭手", "哥布林", "气球兵"}
        )
        s2 = 找到的兵种(读图("s2"))
        self.assertIn("超级哥布林", s2)
        self.assertIn("戈仑冰人", s2)

    def test_彩色卡页面包括法师和天使(self):
        w1 = 找到的兵种(读图("w1"))
        for 名 in ("野蛮人", "哥布林", "法师", "天使", "雷龙", "大雪怪"):
            self.assertIn(名, w1)

    def test_返回卡片中心坐标(self):
        中心 = 找到的兵种(读图("g3"))
        # 实机 g3：野蛮人卡在第一行，哥布林在第二行右侧一列；点击点为头像中心
        self.assertEqual(中心["野蛮人"], (537, 405))
        self.assertEqual(中心["哥布林"], (617, 512))

    def test_没有列表的画面不误报(self):
        self.assertEqual(找到的兵种(读图("m1")), {})
        self.assertEqual(找到的兵种(读图("g2")), {})
        self.assertFalse(编.列表已打开(读图("g2")))
        self.assertTrue(编.列表已打开(读图("g3")))

    def test_有模板的兵种都有人口数值(self):
        for 名 in 编.兵种人口:
            self.assertIsNotNone(编.读取卡片模板(名), 名)
        self.assertIsNone(编.读取卡片模板("超级野蛮人"))


class 人口解析测试(unittest.TestCase):
    def test_解析(self):
        self.assertEqual(编.解析人口("352/352"), (352, 352))
        self.assertEqual(编.解析人口("0 / 352"), (0, 352))
        self.assertEqual(编.解析人口("351／352!"), (351, 352))
        self.assertIsNone(编.解析人口("400/352"))
        self.assertIsNone(编.解析人口("编辑军队"))

    def test_补满计划按权重填空位(self):
        补充 = 编.编辑军队任务._补满计划(12, {"超级哥布林": 88, "野蛮人": 88}, 编.兵种人口)
        self.assertEqual(补充, {"超级哥布林": 4})
        补充 = 编.编辑军队任务._补满计划(5, {"超级哥布林": 88, "野蛮人": 88}, 编.兵种人口)
        self.assertEqual(补充, {"超级哥布林": 1, "野蛮人": 2})
        self.assertEqual(编.编辑军队任务._补满计划(0, {"野蛮人": 1}, 编.兵种人口), {})


class 流程分支测试(unittest.TestCase):
    def _任务(self, **设置项):
        上下文 = SimpleNamespace(
            设置=SimpleNamespace(**{
                "是否自动配置军队": True, "配兵兵种": ["超级哥布林"], "配兵法术": [], "配兵攻城": "",
                "阵容预设": "自定义勾选", **设置项,
            }),
            数据库=Mock(), 机器人标志="r", 置脚本状态=Mock(), 获取模板识别器=Mock(),
        )
        任务 = 编.编辑军队任务(上下文)
        任务._退出到主世界 = Mock()
        return 任务, 上下文

    def test_未开启或未勾选不配置(self):
        任务, _ = self._任务(是否自动配置军队=False)
        self.assertFalse(任务.需要配置())
        任务, _ = self._任务(配兵兵种=[])
        self.assertFalse(任务.需要配置())

    def test_没有模板的兵种不进编辑页(self):
        任务, 上下文 = self._任务(配兵兵种=["超级野蛮人"])
        任务._配置流程 = Mock()
        self.assertTrue(任务.执行())
        任务._配置流程.assert_not_called()
        self.assertIn("暂无卡片模板", 上下文.置脚本状态.call_args_list[0][0][0])

    def test_成功后记录并不再重复(self):
        任务, 上下文 = self._任务()
        任务._配置流程 = Mock(return_value={"配置": {"超级哥布林": 117}, "人口": [352, 352]})
        self.assertTrue(任务.执行())
        self.assertEqual(上下文._本次运行已配兵签名, "兵种:超级哥布林6")
        上下文.数据库.更新状态.assert_called_once()
        self.assertFalse(任务.需要配置())

    def test_重启后同一套配置不再清空重配_改了设置才重配(self):
        import tempfile
        from 数据库.任务数据库 import 任务数据库
        库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "t.db"))

        def 新运行(预设="隐秘哥布林刷资源"):
            上下文 = SimpleNamespace(
                设置=SimpleNamespace(是否自动配置军队=True, 阵容预设=预设, 配兵兵种=[], 配兵法术=[], 配兵攻城=""),
                数据库=库, 机器人标志="r", 置脚本状态=Mock(), 获取模板识别器=Mock(),
            )
            任务 = 编.编辑军队任务(上下文)
            任务._退出到主世界 = Mock()
            任务._配置流程 = Mock(return_value={"配置": {"超级哥布林": 88}, "人口": [352, 352]})
            return 任务, 上下文

        第一次, _ = 新运行()
        self.assertTrue(第一次.执行())
        第一次._配置流程.assert_called_once()
        重启后, 上下文 = 新运行()
        self.assertTrue(重启后.执行())
        重启后._配置流程.assert_not_called()
        self.assertIn("跳过重配", 上下文.置脚本状态.call_args[0][0])
        改预设, _ = 新运行("根蔓骑士雪怪推进")
        self.assertTrue(改预设.执行())
        改预设._配置流程.assert_called_once()

    def test_未填满不算成功且最多尝试两次(self):
        任务, 上下文 = self._任务()
        任务._配置流程 = Mock(return_value={"配置": {"超级哥布林": 117}, "人口": [85, 352]})
        self.assertTrue(任务.执行())
        self.assertFalse(hasattr(上下文, "_本次运行已配兵签名"))
        self.assertIn("未填满军营", 上下文.置脚本状态.call_args[0][0])
        self.assertTrue(任务.需要配置())
        任务.执行()
        self.assertFalse(任务.需要配置())
        self.assertEqual(任务._配置流程.call_count, 2)

    def test_异常时退出编辑页并清除编辑标志(self):
        任务, 上下文 = self._任务()
        def 失败():
            上下文._军队编辑中 = True
            上下文._最近结算视觉时间 = 123.0
            raise RuntimeError("截图失败")
        任务._配置流程 = Mock(side_effect=lambda _: 失败())
        上下文._最近结算视觉时间 = 0.0
        self.assertTrue(任务.执行())
        任务._退出到主世界.assert_called_once()
        self.assertFalse(上下文._军队编辑中)
        self.assertEqual(上下文._最近结算视觉时间, 0.0)

    def test_确认按钮只在移除部队弹窗且无宝石时返回(self):
        任务, 上下文 = self._任务()
        任务._截图 = Mock(return_value=np.zeros((600, 800, 3), np.uint8))
        确定框 = [[440, 370], [530, 370], [530, 400], [440, 400]]
        def OCR返回(*文字):
            return Mock(return_value=([(确定框 if 文 == "確定" else [[0, 0], [9, 0], [9, 9], [0, 9]], 文, 0.9) for 文 in 文字], None))
        上下文.获取OCR引擎 = Mock(return_value=OCR返回("移除部隊？", "確定要移除這些部隊嗎？", "取消", "確定"))
        self.assertEqual(任务._查找确认按钮(), (485, 385))
        上下文.获取OCR引擎 = Mock(return_value=OCR返回("升級", "確定"))
        self.assertIsNone(任务._查找确认按钮())
        上下文.获取OCR引擎 = Mock(return_value=OCR返回("移除部隊？", "寶石", "確定"))
        self.assertIsNone(任务._查找确认按钮())


class 点击护栏放行测试(unittest.TestCase):
    def _上下文(self, 页面):
        from 任务流程.基础任务框架 import 任务上下文
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._最近点击页面结果 = SimpleNamespace(页面=页面, 世界="未知", 可信度=0.9)
        上下文.检查宝石商店危险页面 = Mock(return_value=False)
        上下文.置脚本状态 = Mock()
        上下文.清理官方评分弹窗 = Mock(return_value=False)
        return 上下文

    def test_移除部队确认只在标志打开时放行(self):
        上下文 = self._上下文("多按钮弹窗")
        self.assertTrue(上下文.输入前安全检查())
        上下文._移除部队确认中 = True
        self.assertFalse(上下文.输入前安全检查())


if __name__ == "__main__":
    unittest.main()
