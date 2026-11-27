import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 模块.ADB设备操作类 import ADB错误
from 任务流程.基础任务框架 import 任务上下文
from 线程.自动化机器人 import 自动化机器人


class 人工安全恢复等待测试(unittest.TestCase):
    def _创建机器人(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        机器人.停止事件.wait = Mock(return_value=False)
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        return 机器人

    def _启用虚拟待命时钟(self, 机器人):
        时间 = [0.0]

        def 等待(timeout=None):
            时间[0] += float(timeout or 0.0)
            return False

        机器人.停止事件.wait.side_effect = 等待
        计时器 = patch(
            "线程.自动化机器人._安全待命单调时间",
            side_effect=lambda: 时间[0],
        )
        计时器.start()
        self.addCleanup(计时器.stop)
        return 时间

    @staticmethod
    def _创建内存恢复上下文(预算结果):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.op = SimpleNamespace(
            检查主机内存预算=Mock(side_effect=预算结果),
        )
        上下文._内存保护已触发 = True
        上下文._主机内存保护可恢复 = True
        上下文._主机内存恢复连续正常次数 = 0
        上下文.页面恢复失败 = True
        上下文.停止事件 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.释放识别模型 = Mock()
        return 上下文

    @staticmethod
    def _页面(名称, 世界=None, 可信度=0.0):
        return SimpleNamespace(页面=名称, 世界=世界, 可信度=可信度)

    def test_要求连续三帧跨至少五秒主世界确认且不处理中间未知页(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[
                self._页面("未知"),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("未知"),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 6)
        self.assertTrue(all(
            调用.kwargs == {"强制": True}
            for 调用 in 上下文.识别点击画面.call_args_list
        ))
        self.assertTrue(any(
            "连续3帧" in 调用.args[0] and "主世界主页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_人工恢复要求连续稳定的夜世界主页(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        主页 = self._页面("主世界主页", "主世界", 0.78)
        夜页 = self._页面("夜世界主页", "夜世界", 0.78)
        页面序列 = [主页, 夜页, 夜页, 夜页]
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 > len(页面序列):
                机器人.停止事件.set()
            return 页面序列[min(调用次数 - 1, len(页面序列) - 1)]

        上下文 = SimpleNamespace(
            _待命恢复世界="夜世界",
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))
        self.assertEqual(上下文.识别点击画面.call_count, 4)
        self.assertFalse(上下文._主世界战斗模式选择页)
        self.assertTrue(any(
            "连续3帧" in 调用.args[0] and "夜世界主页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_连续确认新版主世界战斗模式页后交回任务流程(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        模式页 = self._页面("主世界战斗模式选择", "主世界", 0.96)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 > 3:
                机器人.停止事件.set()
            return 模式页

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 3)
        self.assertTrue(上下文._主世界战斗模式选择页)
        self.assertTrue(any(
            "连续3帧" in 调用.args[0] and "主世界战斗模式选择页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_稳定战斗页面不自动恢复也不消耗额度(self):
        """战斗中接续任务计划会在战场里开下一轮；只读等战斗结束。"""
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        战斗页 = self._页面("战斗中", 可信度=0.96)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 >= 6:
                机器人.停止事件.set()
            return 战斗页

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 6)
        self.assertFalse(hasattr(上下文, "_安全待命自动恢复次数"))
        self.assertFalse(any(
            "自动恢复：" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))
        self.assertEqual(sum(
            "战斗仍在进行" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ), 1)

    def test_宝石商店购买和升级页面继续只读待命(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        待命页 = [
            self._页面("宝石购买页", 可信度=0.99),
            self._页面("商店弹窗", 可信度=0.99),
            self._页面("升级详情弹窗", 可信度=0.99),
        ]
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            return 待命页[min(调用次数 - 1, len(待命页) - 1)]

        def 等待并停止(timeout=None):
            机器人.虚拟时钟[0] += float(timeout or 0.0)
            if 调用次数 >= 3:
                机器人.停止事件.set()
            return 机器人.停止事件.is_set()

        # 接管虚拟等待以便在三次只读页面检查后结束测试循环。
        机器人.虚拟时钟 = self._启用虚拟待命时钟(机器人)
        机器人.停止事件.wait.side_effect = 等待并停止
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            点击已确认安全按钮=Mock(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 3)
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertFalse(hasattr(上下文, "_安全待命自动恢复次数"))

    def test_每次机器人运行最多自动恢复一次(self):
        机器人 = self._创建机器人()
        虚拟时钟 = self._启用虚拟待命时钟(机器人)
        安全主页 = self._页面("主世界主页", "主世界", 0.95)
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[安全主页] * 6),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        等待次数 = 0

        def 等待并在第二次待命时停止(timeout=None):
            nonlocal 等待次数
            等待次数 += 1
            虚拟时钟[0] += float(timeout or 0.0)
            if 等待次数 >= 5:
                机器人.停止事件.set()
            return 机器人.停止事件.is_set()

        机器人.停止事件.wait.side_effect = 等待并在第二次待命时停止
        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))
        self.assertEqual(上下文._安全待命自动恢复次数, 1)
        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 6)
        self.assertEqual(上下文._安全待命自动恢复次数, 1)
        self.assertTrue(any(
            "自动恢复上限" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_安全待命只读观察战后奖励并连续确认主页(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        页面序列 = iter([
            self._页面("未知"),
            self._页面("战斗星级奖励", 可信度=0.99),
            self._页面("主世界主页", "主世界", 0.78),
            self._页面("主世界主页", "主世界", 0.78),
            self._页面("主世界主页", "主世界", 0.78),
        ])
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=lambda **_参数: next(页面序列)),
            处理战斗星级奖励弹窗=Mock(return_value=True),
            _战斗结束已确认=True,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        上下文.处理战斗星级奖励弹窗.assert_not_called()
        self.assertGreater(上下文._战后星级奖励检查截止时间, 0)
        self.assertEqual(上下文.识别点击画面.call_count, 5)
        self.assertTrue(any(
            "勝利之星獎勵弹窗" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_安全待命连续两帧星级奖励只调用确認处理且最多两次(self):
        """rc162 19:56：勝利之星獎勵弹窗只读等待导致卡死 180 秒。"""
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        奖励 = self._页面("战斗星级奖励", 可信度=0.96)
        页面序列 = iter([奖励] * 6 + [self._页面("夜世界主页", "夜世界", 0.95)] * 3)
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=lambda **_参数: next(页面序列)),
            处理战斗星级奖励弹窗=Mock(return_value=True),
            安全待命确认战斗星级奖励=Mock(return_value=False),
            _待命恢复世界="夜世界",
            _战斗结束已确认=True,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        上下文.处理战斗星级奖励弹窗.assert_not_called()
        self.assertEqual(上下文.安全待命确认战斗星级奖励.call_count, 2)
        self.assertTrue(any(
            "只点確定（第1/2次）" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_低置信度战斗模式页不解除安全待命(self):
        机器人 = self._创建机器人()
        模式页 = self._页面("主世界战斗模式选择", "主世界", 0.89)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 > 2:
                机器人.停止事件.set()
            return 模式页

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取页面),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertFalse(getattr(上下文, "_主世界战斗模式选择页", False))

    def test_安全待命遇到断线按现有重连流程恢复(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[
                self._页面("断线弹窗"),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        检测登录 = Mock()
        检测登录.执行.return_value = True

        self.assertTrue(机器人._等待人工恢复主世界(上下文, 检测登录))

        检测登录.执行.assert_called_once_with(首次登录=False)
        self.assertTrue(any(
            "执行游戏内断线重连" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_满仓待机期间断线只读观察到主页后继续待机(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        主页面 = self._页面("主世界主页", "主世界", 0.78)
        断线页 = self._页面("断线弹窗")
        页面序列 = iter([主页面, 断线页, 断线页, 主页面, 主页面, 主页面])
        页面调用次数 = 0
        延时次数 = 0
        上下文 = None

        def 待机延时(_毫秒):
            nonlocal 延时次数
            self.assertTrue(getattr(上下文, "_任务计划长时间等待", False))
            延时次数 += 1
            if 延时次数 >= 3:
                机器人.停止事件.set()

        def 读取页面(**_参数):
            nonlocal 页面调用次数
            页面调用次数 += 1
            页面 = next(页面序列)
            if 页面调用次数 >= 6:
                机器人.停止事件.set()
            return 页面

        上下文 = SimpleNamespace(
            停止事件=机器人.停止事件,
            页面恢复失败=False,
            机器人标志="robot_1",
            识别点击画面=Mock(side_effect=读取页面),
            数据库=SimpleNamespace(
                获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据={
                    "家乡资源": {
                        "金币": 31_000_000,
                        "圣水": 31_000_000,
                        "黑油": 480_000,
                    }
                })),
                获取近期家乡资源峰值=Mock(return_value={
                    "金币": 31_000_000,
                    "圣水": 31_000_000,
                    "黑油": 480_000,
                }),
            ),
            置脚本状态=Mock(),
            脚本延时=Mock(side_effect=待机延时),
        )
        检测登录 = Mock()
        检测登录.执行.return_value = True

        with patch("线程.自动化机器人.更新家乡资源状态任务") as 更新资源, \
                patch("线程.自动化机器人.是否目标资源打满", return_value=True):
            更新资源.return_value.执行.return_value = True
            self.assertFalse(机器人._满仓待机并监测断线(上下文, 检测登录))

        检测登录.执行.assert_not_called()
        self.assertEqual(上下文.识别点击画面.call_count, 6)
        self.assertTrue(any(
            "满仓待机只读检测到断线" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))
        self.assertFalse(上下文._任务计划长时间等待)

    def test_满仓待机四分钟后只在确认主页时轻拖保活(self):
        机器人 = self._创建机器人()
        机器人.机器人标志 = "robot_1"
        主页面 = self._页面("主世界主页", "主世界", 0.78)
        延时次数 = 0

        def 待机延时(_毫秒):
            nonlocal 延时次数
            延时次数 += 1
            if 延时次数 >= 2:
                机器人.停止事件.set()

        滑动 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            停止事件=机器人.停止事件,
            页面恢复失败=False,
            机器人标志="robot_1",
            识别点击画面=Mock(return_value=主页面),
            设备=SimpleNamespace(滑动=滑动),
            _满仓待机上次保活时间=100.0,
            数据库=SimpleNamespace(
                获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据={
                    "家乡资源": {
                        "金币": 31_000_000,
                        "圣水": 31_000_000,
                        "黑油": 480_000,
                    }
                })),
                获取近期家乡资源峰值=Mock(return_value={
                    "金币": 31_000_000,
                    "圣水": 31_000_000,
                    "黑油": 480_000,
                }),
            ),
            置脚本状态=Mock(),
            脚本延时=Mock(side_effect=待机延时),
        )

        with patch("线程.自动化机器人.time.monotonic", return_value=341.0), \
                patch("线程.自动化机器人.更新家乡资源状态任务") as 更新资源, \
                patch("线程.自动化机器人.是否目标资源打满", return_value=True):
            更新资源.return_value.执行.return_value = True
            机器人._满仓待机并监测断线(上下文, Mock())

        滑动.assert_called_once_with((300, 260), (340, 260), 时长毫秒=350)

    def test_满仓待机未知页面和四分钟间隔内都不保活(self):
        机器人 = self._创建机器人()
        滑动 = Mock()
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            _战斗中=False,
            继续事件=threading.Event(),
            _满仓待机上次保活时间=100.0,
            设备=SimpleNamespace(滑动=滑动),
            置脚本状态=Mock(),
        )
        上下文.继续事件.set()

        with patch("线程.自动化机器人.time.monotonic", return_value=339.0):
            self.assertFalse(机器人._满仓待机安全轻拖(
                上下文, self._页面("未知", "未知", 0.99)
            ))
            self.assertFalse(机器人._满仓待机安全轻拖(
                上下文, self._页面("主世界主页", "主世界", 0.78)
            ))

        滑动.assert_not_called()

    def test_满仓待机中资源降到容量以下时请求恢复刷资源(self):
        机器人 = self._创建机器人()
        机器人.机器人标志 = "robot_1"
        主页面 = self._页面("主世界主页", "主世界", 0.96)
        延时次数 = 0

        def 待机延时(_毫秒):
            nonlocal 延时次数
            延时次数 += 1
            if 延时次数 >= 2:
                机器人.停止事件.set()

        状态 = SimpleNamespace(状态数据={
            "家乡资源": {"金币": 3_046_305, "圣水": 822_720, "黑油": 139_035}
        })
        上下文 = SimpleNamespace(
            停止事件=机器人.停止事件,
            页面恢复失败=False,
            机器人标志="robot_1",
            识别点击画面=Mock(return_value=主页面),
            数据库=SimpleNamespace(
                获取最新完整状态=Mock(return_value=状态),
                获取近期家乡资源峰值=Mock(return_value={
                    "金币": 31_000_000, "圣水": 31_000_000, "黑油": 480_000
                }),
            ),
            置脚本状态=Mock(),
            脚本延时=Mock(side_effect=待机延时),
        )

        with patch("线程.自动化机器人.更新家乡资源状态任务") as 更新资源, \
                patch("线程.自动化机器人.是否目标资源打满", return_value=False) as 判断满仓:
            更新资源.return_value.执行.return_value = True
            结果 = 机器人._满仓待机并监测断线(上下文, Mock())

        更新资源.return_value.执行.assert_called_once_with()
        判断满仓.assert_called_once()
        self.assertTrue(结果)
        self.assertTrue(any(
            "资源已从满仓状态下降" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_BuilderBase满仓待机复核夜世界资源并在下降时恢复(self):
        机器人 = self._创建机器人()
        机器人.机器人标志 = "robot_1"
        延时次数 = 0

        def 待机延时(_毫秒):
            nonlocal 延时次数
            延时次数 += 1
            if 延时次数 >= 3:
                机器人.停止事件.set()

        上下文 = SimpleNamespace(
            停止事件=机器人.停止事件,
            _待命恢复世界="夜世界",
            _夜世界大本营等级=7,
            页面恢复失败=False,
            机器人标志="robot_1",
            识别点击画面=Mock(return_value=self._页面("夜世界主页", "夜世界", 0.78)),
            数据库=SimpleNamespace(
                获取最新完整状态=Mock(return_value=SimpleNamespace(状态数据={
                    "夜世界资源": {
                        "金币": 2_000_000,
                        "圣水": 2_000_000,
                        "识别成功": True,
                    }
                })),
            ),
            置脚本状态=Mock(),
            脚本延时=Mock(side_effect=待机延时),
        )

        with patch("线程.自动化机器人.更新夜世界资源状态任务") as 更新夜资源, \
                patch("线程.自动化机器人.更新家乡资源状态任务") as 更新家乡资源:
            更新夜资源.return_value.执行.return_value = True
            结果 = 机器人._满仓待机并监测断线(上下文, Mock())

        self.assertTrue(结果)
        更新夜资源.return_value.执行.assert_called_once_with()
        更新家乡资源.return_value.执行.assert_not_called()

    def test_重复断线帧限频只重连一次再等待主页复核(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        断线页 = self._页面("断线弹窗")
        主页 = self._页面("主世界主页", "主世界", 0.78)
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[断线页, 断线页, 断线页, 主页, 主页, 主页]),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        检测登录 = Mock()

        self.assertTrue(机器人._等待人工恢复主世界(上下文, 检测登录))

        self.assertEqual(上下文.识别点击画面.call_count, 6)
        # 三帧断线相隔 5 秒，重连按 60 秒限频，只会执行一次。
        检测登录.执行.assert_called_once_with(首次登录=False)
        self.assertFalse(机器人.停止事件.is_set())
        self.assertTrue(上下文._主世界战斗模式选择页 is False)

    def test_停止事件会结束安全待命(self):
        机器人 = self._创建机器人()

        def 读取后停止(**_参数):
            机器人.停止原因 = "用户停止"
            机器人.停止事件.set()
            return self._页面("未知")

        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=读取后停止),
            置脚本状态=Mock(),
            脚本延时=Mock(side_effect=lambda _毫秒: 机器人.停止事件.set()),
        )

        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))
        self.assertEqual(上下文.识别点击画面.call_count, 1)

    def test_可恢复页面保护事件不会阻止人工恢复等待(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        机器人.停止事件.set()
        上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=[
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
                self._页面("主世界主页", "主世界", 0.78),
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )

        self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))

        self.assertEqual(上下文.识别点击画面.call_count, 3)
        self.assertFalse(机器人.停止事件.is_set())

    def test_保护事件期间收到明确停止请求仍会终止恢复等待(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()

        机器人.停止("用户停止", 等待=False)

        self.assertEqual(机器人.停止原因, "用户停止")
        self.assertTrue(机器人.停止事件.is_set())

        上下文 = SimpleNamespace(
            识别点击画面=Mock(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))
        上下文.识别点击画面.assert_not_called()

    def test_低内存待命期间不截图并等待用户停止(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()
        内存上下文 = self._创建内存恢复上下文([
            (False, "主机内存保护已触发：可用提交额度828MB"),
        ])
        内存上下文.识别点击画面 = Mock()
        内存上下文.置脚本状态 = Mock()
        内存上下文.op.检查主机内存预算.return_value = (
            False, "主机内存保护已触发：可用提交额度828MB"
        )

        def 用户停止(timeout=None):
            机器人.停止原因 = "用户停止"
            机器人.停止事件.set()
            return True

        机器人.停止事件.wait = Mock(side_effect=用户停止)

        self.assertFalse(机器人._等待人工恢复主世界(内存上下文, Mock()))

        内存上下文.识别点击画面.assert_not_called()
        内存上下文.op.检查主机内存预算.assert_called_once_with(强制刷新=True)
        self.assertEqual(机器人.停止原因, "用户停止")
        self.assertTrue(机器人.停止事件.is_set())
        self.assertEqual(
            机器人.停止事件.wait.call_args.kwargs.get("timeout"), 10.0
        )

    def test_连续三次内存预算健康后仍需三帧五秒安全页面确认(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        机器人.停止事件.set()
        内存上下文 = self._创建内存恢复上下文([
            (True, "健康样本1"),
            (True, "健康样本2"),
            (True, "健康样本3"),
        ])
        内存上下文.识别点击画面 = Mock(side_effect=[
            self._页面("主世界主页", "主世界", 0.78),
            self._页面("主世界主页", "主世界", 0.78),
            self._页面("主世界主页", "主世界", 0.78),
        ])

        self.assertTrue(机器人._等待人工恢复主世界(内存上下文, Mock()))

        self.assertEqual(内存上下文.op.检查主机内存预算.call_count, 3)
        self.assertEqual(内存上下文.识别点击画面.call_count, 3)
        self.assertEqual(
            [调用.kwargs.get("timeout") for 调用 in 机器人.停止事件.wait.call_args_list[:2]],
            [10.0, 10.0],
        )
        self.assertFalse(内存上下文._内存保护已触发)
        self.assertFalse(内存上下文._主机内存保护可恢复)

    def test_待命截图时触发宿主机内存保护后转入预算恢复等待(self):
        机器人 = self._创建机器人()
        self._启用虚拟待命时钟(机器人)
        内存上下文 = self._创建内存恢复上下文([
            (False, "提交额度828MB"),
            (True, "健康样本1"),
            (True, "健康样本2"),
            (True, "健康样本3"),
        ])
        内存上下文._内存保护已触发 = False
        内存上下文._主机内存保护可恢复 = False
        内存上下文.停止事件 = 机器人.停止事件
        内存上下文.op.检查主机内存预算.reset_mock()
        主页 = self._页面("主世界主页", "主世界", 0.78)
        调用次数 = 0

        def 读取页面(**_参数):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 == 1:
                内存上下文.触发内存保护(
                    "点击护栏",
                    ADB错误("主机内存保护已触发：可用提交额度828MB"),
                )
                return None
            return 主页

        内存上下文.识别点击画面 = Mock(side_effect=读取页面)
        内存上下文.置脚本状态 = Mock()

        self.assertTrue(机器人._等待人工恢复主世界(内存上下文, Mock()))

        self.assertEqual(内存上下文.op.检查主机内存预算.call_count, 4)
        self.assertEqual(内存上下文.识别点击画面.call_count, 4)
        self.assertEqual(
            [调用.kwargs.get("timeout") for 调用 in 机器人.停止事件.wait.call_args_list],
            [10.0, 10.0, 10.0, 5.0, 5.0],
        )
        self.assertFalse(机器人.停止事件.is_set())
        self.assertFalse(内存上下文._内存保护已触发)
        self.assertFalse(内存上下文._主机内存保护可恢复)

    def test_任一低内存样本会清零连续健康计数(self):
        内存上下文 = self._创建内存恢复上下文([
            (True, "健康"),
            (True, "健康"),
            (False, "提交额度不足"),
            (True, "健康"),
            (True, "健康"),
            (True, "健康"),
        ])
        检查恢复 = getattr(内存上下文, "检查主机内存预算恢复", None)
        self.assertTrue(callable(检查恢复), "任务上下文必须提供内存恢复检查")
        if not callable(检查恢复):
            return

        恢复状态 = [
            检查恢复()[0]
            for _ in range(6)
        ]

        self.assertEqual(恢复状态, [False, False, False, False, False, True])
        self.assertEqual(内存上下文.op.检查主机内存预算.call_count, 6)

    def test_只有明确的主机预算保护会标记为可自动恢复(self):
        主机预算上下文 = self._创建内存恢复上下文([])
        主机预算上下文._内存保护已触发 = False
        主机预算上下文.触发内存保护(
            "截图", ADB错误("主机内存保护已触发：可用提交额度828MB")
        )

        一般内存上下文 = self._创建内存恢复上下文([])
        一般内存上下文._内存保护已触发 = False
        一般内存上下文.触发内存保护("OCR", MemoryError("bad allocation"))
        是否可恢复 = getattr(
            主机预算上下文, "是否可自动恢复主机内存保护", None
        )
        self.assertTrue(callable(是否可恢复), "任务上下文必须标明内存保护类型")
        if not callable(是否可恢复):
            return
        是否可恢复一般 = getattr(
            一般内存上下文, "是否可自动恢复主机内存保护", None
        )
        self.assertTrue(callable(是否可恢复一般))
        if not callable(是否可恢复一般):
            return

        self.assertTrue(是否可恢复())
        self.assertFalse(是否可恢复一般())

    def test_一般MemoryError保持停止且不进入截图恢复(self):
        机器人 = self._创建机器人()
        机器人.停止事件.set()
        内存上下文 = self._创建内存恢复上下文([])
        内存上下文._主机内存保护可恢复 = False
        内存上下文.识别点击画面 = Mock(side_effect=lambda **_参数: (
            机器人.停止事件.set() or self._页面("未知")
        ))
        内存上下文.置脚本状态 = Mock()

        self.assertFalse(机器人._等待人工恢复主世界(内存上下文, Mock()))

        内存上下文.识别点击画面.assert_not_called()
        self.assertTrue(机器人.停止事件.is_set())


if __name__ == "__main__":
    unittest.main()
