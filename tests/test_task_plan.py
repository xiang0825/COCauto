import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 数据库.任务数据库 import 机器人设置
from 界面.日志面板 import 日志面板
from 界面.任务计划面板 import 生成任务计划
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 线程.自动化机器人 import 自动化机器人
from 工具包.工具函数 import 是否夜世界资源打满
from 任务流程.夜世界.更新夜世界账号资源状态 import 更新夜世界资源状态任务
from 任务流程.夜世界.夜世界打鱼.下兵 import 下兵
from 任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗 import 等待回营或第二次战斗
from 任务流程.兵种或法术升级 import 兵种或法术升级任务
from 任务流程.战宠升级 import 战宠升级任务
from 任务流程.建筑升级 import 建筑升级任务


class 任务计划测试(unittest.TestCase):
    def test_世界任务开始时发现断线会先走游戏内重连(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            识别点击画面=Mock(
                return_value=SimpleNamespace(页面="断线弹窗")
            ),
            置脚本状态=Mock(),
        )
        检测登录 = Mock()
        检测登录.执行.return_value = True

        self.assertTrue(机器人._断线时恢复游戏连接(上下文, 检测登录))
        检测登录.执行.assert_called_once_with(首次登录=False)
        self.assertFalse(上下文.页面恢复失败)
        self.assertTrue(any("重新登入" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))

    def test_启动时已有战斗先回营再执行任务计划(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        上下文 = SimpleNamespace(
            _启动时已有战斗=True,
            页面恢复失败=False,
            置脚本状态=Mock(),
        )
        检测登录 = Mock()
        检测登录.执行.return_value = True
        with patch("线程.自动化机器人.主世界打鱼任务") as 战斗任务:
            战斗任务.return_value.执行.return_value = True
            self.assertTrue(机器人._接管启动时战斗(上下文, 检测登录))

        战斗任务.return_value.执行.assert_called_once_with()
        检测登录.执行.assert_called_once_with(首次登录=False)
        self.assertFalse(上下文._启动时已有战斗)
        self.assertFalse(上下文._入口已进入战斗)
        self.assertTrue(any("允许继续执行任务计划" in 调用.args[0]
                            for 调用 in 上下文.置脚本状态.call_args_list))

    def test_计划状态来自机器人配置(self):
        设置 = 机器人设置(
            是否刷主世界=True,
            是否刷夜世界=False,
            开启刷墙=True,
            欲升级的战宠="莱希",
            欲升级的兵种或法术="雷电法术",
        )

        计划 = {项["名称"]: 项 for 项 in 生成任务计划(设置)}

        self.assertEqual(计划["主世界刷资源"]["状态"], "已启用")
        self.assertEqual(计划["夜世界刷资源"]["状态"], "未启用")
        self.assertEqual(计划["刷墙"]["状态"], "已启用")
        self.assertIn("莱希", 计划["战宠升级"]["说明"])
        self.assertIn("雷电法术", 计划["兵种或法术研究"]["说明"])

    def test_空配置不生成任务(self):
        self.assertEqual(生成任务计划(None), [])

    def test_资源打满动作和任务顺序有默认值并可规范化(self):
        设置 = 机器人设置(资源打满后动作="未知值", 任务计划顺序=["night_resource", "night_resource", "unknown"])

        self.assertEqual(设置.资源打满后动作, "退出")
        self.assertEqual(设置.任务计划顺序[0], "night_resource")
        self.assertEqual(设置.任务计划顺序.count("night_resource"), 1)
        self.assertIn("main_resource", 设置.任务计划顺序)

    def test_战利品优先级和自动配兵配置有安全默认值(self):
        设置 = 机器人设置(
            战利品优先级="未知",
            自动配兵玩法="未知",
            高速下兵方式="未知",
        )

        self.assertEqual(设置.战利品优先级, "均衡")
        self.assertEqual(设置.自动配兵玩法, "资源优先")
        self.assertTrue(设置.是否启用高速下兵)
        self.assertEqual(设置.高速下兵方式, "快速连点")

    def test_战利品评分会随优先级改变(self):
        金币优先 = 搜索目标敌人任务.计算战利品评分(800000, 100000, 1000, "金币")
        黑水优先 = 搜索目标敌人任务.计算战利品评分(100000, 100000, 8000, "黑水")

        self.assertGreater(金币优先, 700000)
        self.assertGreater(黑水优先, 700000)

    def test_日志面板会去掉实时消息时间前缀(self):
        self.assertEqual(
            日志面板._去掉实时前缀("[14:33:41] 下兵成功"),
            "下兵成功",
        )
        self.assertEqual(日志面板._去掉实时前缀("普通历史日志"), "普通历史日志")

    def test_刷墙资源不足会自动刷资源后重试一次(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        上下文 = SimpleNamespace(
            刷墙需要资源=False,
            置脚本状态=Mock(),
        )
        调用次数 = {"wall": 0}

        def 模拟升级(任务键, 当前上下文, _检测登录):
            调用次数[任务键] += 1
            当前上下文.刷墙需要资源 = 调用次数[任务键] == 1

        机器人._执行升级计划 = Mock(side_effect=模拟升级)
        机器人._执行主世界刷资源计划 = Mock(return_value=True)

        with patch("线程.自动化机器人.到主世界任务") as 回主世界:
            机器人._执行刷墙计划(上下文, object())

        self.assertEqual(调用次数["wall"], 2)
        机器人._执行主世界刷资源计划.assert_called_once()
        # 进入主世界已经由被测的主世界刷资源流程统一负责，避免重复点击。
        回主世界.assert_not_called()
        self.assertFalse(机器人.停止事件.is_set())

    def test_天鹰任务无法回到主世界时不继续点击(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            置脚本状态=Mock(),
        )
        检测登录 = Mock()

        with patch("线程.自动化机器人.到主世界任务") as 回主世界, \
                patch("任务流程.天鹰火炮成就.刷天鹰火炮任务") as 刷天鹰:
            回主世界.return_value.执行.return_value = False

            结果 = 机器人._执行天鹰计划(上下文, 检测登录)

        self.assertFalse(结果)
        self.assertTrue(上下文.页面恢复失败)
        刷天鹰.assert_not_called()
        检测登录.assert_not_called()

    def test_夜世界圣水车未完成时禁止继续下一场战斗(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        机器人.机器人标志 = "测试机器人"
        状态 = SimpleNamespace(
            状态数据={"夜世界资源": {"金币": 123456, "圣水": 234567, "识别成功": True}}
        )
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            机器人标志="测试机器人",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            识别点击画面=Mock(return_value=SimpleNamespace(页面="夜世界主页")),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        with patch("线程.自动化机器人.到夜世界任务") as 回夜世界, \
                patch("线程.自动化机器人.收集资源任务"), \
                patch("线程.自动化机器人.更新夜世界资源状态任务") as 更新资源, \
                patch("线程.自动化机器人.收集圣水车任务") as 收集圣水车, \
                patch("线程.自动化机器人.夜世界打鱼任务") as 打鱼, \
                patch("线程.自动化机器人.是否夜世界资源打满", return_value=False):
            回夜世界.return_value.执行.return_value = True
            更新资源.return_value.执行.return_value = True
            收集圣水车.return_value.执行.return_value = False

            结果 = 机器人._执行夜世界刷资源计划(上下文, Mock())

        self.assertFalse(结果)
        self.assertTrue(上下文.页面恢复失败)
        打鱼.return_value.执行.assert_not_called()
        self.assertTrue(
            any("禁止继续执行夜世界收集和下一场战斗" in 调用.args[0]
                for 调用 in 上下文.置脚本状态.call_args_list)
        )

    def test_刷墙普通无操作不会被当成页面故障(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        上下文 = SimpleNamespace(
            刷墙需要资源=False,
            页面恢复失败=False,
        )
        机器人._执行升级计划 = Mock(return_value=True)

        结果 = 机器人._执行刷墙计划(上下文, Mock())

        self.assertTrue(结果)
        self.assertFalse(上下文.页面恢复失败)

    def test_夜世界没有确认下兵时停止后续英雄点击(self):
        任务 = 下兵.__new__(下兵)
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.执行下兵操作 = Mock(return_value=False)

        self.assertFalse(任务.执行())
        self.assertTrue(上下文.页面恢复失败)
        任务.执行下兵操作.assert_called_once()

    def test_夜世界第二场下兵失败不会继续等待回营点击(self):
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务.上下文 = 上下文
        任务.是否出现换兵种箭头 = Mock(return_value=True)
        任务.尝试点击回营按钮 = Mock(return_value=False)

        with patch("任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗.下兵") as 下兵任务:
            下兵任务.return_value.执行.return_value = False
            self.assertFalse(任务.执行())

        self.assertTrue(上下文.页面恢复失败)
        任务.尝试点击回营按钮.assert_not_called()

    def test_夜世界结算页限制区域识别回营按钮(self):
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        调用 = {}

        class 匹配器:
            def 执行匹配(self, 图像, 模板路径, 相似度阈值=0.9):
                调用["图像"] = 图像
                调用["模板路径"] = 模板路径
                调用["阈值"] = 相似度阈值
                return True, (100, 40), None

        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=lambda *区域: object()),
            点击=Mock(),
        )
        任务.上下文 = 上下文
        任务.模板识别 = 匹配器()

        self.assertTrue(任务.尝试点击回营按钮())
        self.assertEqual(调用["模板路径"], "夜世界_回营.bmp|夜世界_回营[1].bmp")
        self.assertEqual(调用["阈值"], 0.58)
        上下文.点击.assert_called_once_with(400, 490)

    def test_非主页时最多单次ESC并确认主世界主页(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.模板匹配引擎") as 引擎工厂:
            引擎工厂.return_value.执行匹配.side_effect = [
                (False, (0, 0), None),
                (False, (0, 0), None),
                (True, (0, 0), None),
                (True, (0, 0), None),
            ]
            self.assertTrue(机器人._确保主世界主页面(上下文))

        self.assertEqual(键盘.按字符按压.call_count, 1)
        self.assertFalse(上下文.页面恢复失败)

    def test_已经是主世界主页时不发送ESC(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.模板匹配引擎") as 引擎工厂:
            引擎工厂.return_value.执行匹配.return_value = (True, (0, 0), None)
            self.assertTrue(机器人._确保主世界主页面(上下文))

        键盘.按字符按压.assert_not_called()
        self.assertFalse(上下文.页面恢复失败)

    def test_主世界主页确认失败时禁止继续(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("线程.自动化机器人.模板匹配引擎") as 引擎工厂:
            引擎工厂.return_value.执行匹配.return_value = (False, (0, 0), None)
            self.assertFalse(机器人._确保主世界主页面(上下文, 2, 3))

        self.assertEqual(键盘.按字符按压.call_count, 3)
        self.assertTrue(上下文.页面恢复失败)

    def test_战斗回营失败时禁止开启下一轮(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        机器人.机器人标志 = "测试机器人"
        机器人._进入并确认主世界 = Mock(return_value=True)
        机器人._取已确认家乡资源 = Mock(
            return_value={"金币": 1, "圣水": 1, "黑油": 0}
        )
        状态 = SimpleNamespace(状态数据={"家乡资源": {"金币": 1, "圣水": 1, "黑油": 0}})
        上下文 = SimpleNamespace(
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            机器人标志="测试机器人",
            识别点击画面=Mock(return_value=SimpleNamespace(页面="主世界主页")),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        检测登录 = Mock()

        with patch("线程.自动化机器人.收集资源任务"), \
             patch("线程.自动化机器人.更新家乡资源状态任务") as 更新资源, \
             patch("线程.自动化机器人.主世界打鱼任务") as 打鱼, \
             patch("线程.自动化机器人.是否家乡资源打满", return_value=False):
            更新资源.return_value.执行.return_value = True
            打鱼.return_value.执行.return_value = False

            结果 = 机器人._执行主世界刷资源计划(上下文, 检测登录)

        self.assertFalse(结果)
        self.assertTrue(上下文.页面恢复失败)
        打鱼.return_value.执行.assert_called_once()
        检测登录.assert_not_called()
        self.assertTrue(
            any("禁止开始下一轮" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        )

    def test_夜世界资源缺失或识别失败不会被当成零资源(self):
        self.assertIsNone(
            自动化机器人._取已确认夜世界资源(
                SimpleNamespace(状态数据={})
            )
        )

    def test_战后资源同时大幅下降时判为OCR错位(self):
        self.assertFalse(
            自动化机器人._资源快照变化可信(
                {"金币": 4_077_019, "圣水": 29_080_484, "黑油": 294_101},
                {"金币": 480_441, "圣水": 596_149, "黑油": 300_149},
            )
        )

    def test_战后单项资源大幅下降也判为OCR错位(self):
        self.assertFalse(
            自动化机器人._资源快照变化可信(
                {"金币": 1_273_187, "圣水": 220_943_231, "黑油": 359_340},
                {"金币": 12_943_637, "圣水": 2_132_062, "黑油": 364_450},
            )
        )
        self.assertFalse(
            自动化机器人._资源快照变化可信(
                {"金币": 13_380_831, "圣水": 211_262, "黑油": 364_450},
                {"金币": 13_808_831, "圣水": 21_282_648, "黑油": 703},
            )
        )

    def test_资源小幅变化仍然可信(self):
        self.assertTrue(
            自动化机器人._资源快照变化可信(
                {"金币": 4_077_019, "圣水": 2_080_484, "黑油": 294_101},
                {"金币": 3_500_000, "圣水": 1_900_000, "黑油": 300_149},
            )
        )
        self.assertIsNone(
            自动化机器人._取已确认夜世界资源(
                SimpleNamespace(状态数据={
                    "夜世界资源": {
                        "金币": 0,
                        "圣水": 0,
                        "识别成功": False,
                    }
                })
            )
        )

    def test_夜世界资源打满必须同时确认金币和圣水(self):
        self.assertFalse(是否夜世界资源打满({"金币": 1000000, "圣水": 123456}))
        self.assertTrue(是否夜世界资源打满({"金币": 1000000, "圣水": 2000000}))

    def test_夜世界资源识别失败不会覆盖数据库(self):
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            数据库=Mock(),
            机器人标志="测试机器人",
        )
        任务 = 更新夜世界资源状态任务.__new__(更新夜世界资源状态任务)
        任务.上下文 = 上下文
        任务.识别当前资源 = Mock(return_value={
            "金币": 0,
            "圣水": 0,
            "总资源": 0,
            "识别成功": False,
        })

        self.assertFalse(任务.执行())
        上下文.数据库.更新状态.assert_not_called()

    def test_研究实验室不可用时作为正常跳过不阻断任务计划(self):
        上下文 = SimpleNamespace(
            设置=机器人设置(欲升级的兵种或法术="雷电法术"),
            页面恢复失败=False,
            置脚本状态=Mock(),
            数据库=Mock(),
            机器人标志="测试机器人",
        )
        任务 = 兵种或法术升级任务.__new__(兵种或法术升级任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = 上下文.机器人标志
        任务._检查冷却时间 = Mock(return_value=True)
        with patch("任务流程.兵种或法术升级.打开研究面板任务") as 打开研究面板:
            打开研究面板.return_value.执行.return_value = False
            self.assertTrue(任务.执行())

        self.assertFalse(上下文.页面恢复失败)
        self.assertTrue(
            any("实验室不可用或已有升级中" in 调用.args[0]
                for 调用 in 上下文.置脚本状态.call_args_list)
        )

    def test_战宠小屋不可用时作为正常跳过不阻断任务计划(self):
        上下文 = SimpleNamespace(
            设置=机器人设置(欲升级的战宠="莱希"),
            页面恢复失败=False,
            置脚本状态=Mock(),
            数据库=Mock(
                获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据={}))
            ),
            机器人标志="测试机器人",
        )
        任务 = 战宠升级任务.__new__(战宠升级任务)
        任务.上下文 = 上下文
        任务.数据库 = 上下文.数据库
        任务.机器人标志 = 上下文.机器人标志
        with patch("任务流程.战宠升级.寻找战宠小屋任务") as 寻找小屋:
            寻找小屋.return_value.执行.return_value = False
            self.assertTrue(任务.执行())

        self.assertFalse(上下文.页面恢复失败)

    def test_建筑和英雄未配置时作为正常跳过不阻断任务计划(self):
        上下文 = SimpleNamespace(
            设置=机器人设置(
                欲升级的英雄或建筑=[],
                是否升级建议升级的建筑=False,
            ),
            置脚本状态=Mock(),
        )
        任务 = 建筑升级任务.__new__(建筑升级任务)
        任务.上下文 = 上下文

        self.assertTrue(任务.执行())
        self.assertTrue(
            any("跳过升级建筑任务" in 调用.args[0]
                for 调用 in 上下文.置脚本状态.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
