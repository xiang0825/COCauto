"""大脑事项 #21：夜世界跑到一半自动停的专项回归单测。

覆盖：
1. 问题 1(a)：点击护栏对单帧「战斗过渡」做跨帧复核，且夜世界下兵遇短暂
   过渡抖动可有限等待复核后重试，不再因单帧抖动中止整次下兵。
2. 问题 1(b)：夜世界结算 OCR 把「摧毁率」读成「推毁率」时仍确认 0 星战败，
   安全待命第 1/2 次即可正常点击回营；且正常「战斗中」等待不计入 180 秒
   未知页面待命告警（900 秒硬上限不受影响）。
3. 问题 2：拖动期间脚本延时不插入重型全屏截图/OCR 弹窗检查；圣水车边缘
   拖动、圣水车扫描、夜世界资源 OCR 复读、夜世界战斗等待等长循环在每次
   迭代续期心跳，正常推进不超时，但真正卡死停止续期时监控中心仍能发现。
"""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼.下兵 import 下兵
from 任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗 import 等待回营或第二次战斗
from 任务流程.夜世界.夜世界打鱼.等待进入战斗 import 等待进入战斗
from 任务流程.夜世界.收集圣水车 import 收集圣水车任务, 滑动配置
from 任务流程.夜世界.更新夜世界账号资源状态 import 更新夜世界资源状态任务
from 线程.自动化机器人 import 自动化机器人


def _页面(名称, 世界=None, 可信度=0.0, 依据=()):
    return SimpleNamespace(页面=名称, 世界=世界, 可信度=可信度, 依据=依据)


class 战斗过渡单帧抖动修复测试(unittest.TestCase):
    def test_点击护栏单帧战斗过渡跨帧复核为战斗中时放行下兵(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.识别点击画面 = Mock(side_effect=[
            _页面("战斗过渡"),
            _页面("战斗中", 可信度=0.96, 依据=("战斗倒计时0.96",)),
        ])

        self.assertFalse(上下文.检查宝石商店危险页面())
        self.assertEqual(上下文.识别点击画面.call_count, 2)
        self.assertTrue(any(
            "战斗过渡单帧抖动" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_点击护栏持续战斗过渡仍阻止输入(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.识别点击画面 = Mock(return_value=_页面("战斗过渡"))

        self.assertTrue(上下文.检查宝石商店危险页面())
        self.assertEqual(上下文.识别点击画面.call_count, 3)
        self.assertTrue(any(
            "尚未确认战斗画面" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_奖励选择候选挂起态的战斗过渡不绕过阻断(self):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = True
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.识别点击画面 = Mock(return_value=_页面(
            "战斗过渡",
            可信度=0.96,
            依据=("奖励选择候选需间隔至少0.5秒的新帧复核",),
        ))

        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.识别点击画面.assert_called_once()

    def test_夜世界下兵遇短暂战斗过渡拒绝时等待复核后重试成功(self):
        上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            _战斗中=True,
            _最近点击页面结果=_页面("战斗中", 可信度=0.96),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            保活心跳=Mock(),
        )
        点击结果 = [True, False] + [True] * 200
        点击序号 = [0]

        def 模拟点击(x, y, 延时=None, 是否精确点击=False):
            当前 = 点击序号[0]
            点击序号[0] += 1
            结果 = 点击结果[当前]
            if 结果 is False:
                上下文._最近点击页面结果 = _页面("战斗过渡")
            else:
                上下文._最近点击页面结果 = _页面("战斗中", 可信度=0.96)
            return 结果

        上下文.点击 = Mock(side_effect=模拟点击)
        上下文.识别点击画面 = Mock(side_effect=[
            # _当前已是结算页 / _当前是更换部队弹窗 复核
            _页面("战斗过渡"),
            _页面("战斗过渡"),
            # _等待真实战斗画面 复核恢复为战斗中
            _页面("战斗中", 可信度=0.96),
        ])

        任务 = 下兵.__new__(下兵)
        任务.上下文 = 上下文
        任务.第二场 = False
        任务._战斗结算已确认 = False

        self.assertTrue(任务.执行下兵操作())
        self.assertFalse(任务._战斗结算已确认)
        # 5 个槽位 * (1 次选槽 + 12 次下兵) + 1 次重试被拒的 (45, 250) = 66 次点击
        self.assertEqual(上下文.点击.call_count, 66)
        self.assertTrue(any(
            "短暂战斗过渡抖动" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_夜世界下兵遇真实结算拒绝时不重试并交回营流程(self):
        上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            _战斗中=True,
            _最近点击页面结果=_页面("战斗结算", 可信度=0.94),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            保活心跳=Mock(),
            点击=Mock(side_effect=[True, False]),
            识别点击画面=Mock(return_value=_页面("战斗结算", 可信度=0.94)),
        )
        任务 = 下兵.__new__(下兵)
        任务.上下文 = 上下文
        任务.第二场 = False
        任务._战斗结算已确认 = False

        self.assertFalse(任务.执行下兵操作())
        self.assertTrue(任务._战斗结算已确认)
        self.assertEqual(上下文.点击.call_count, 2)


class 夜世界结算推毁率与安全待命修复测试(unittest.TestCase):
    def test_识别星数兼容OCR误读推毁率和毁率零星战败(self):
        黑图 = np.zeros((600, 800, 3), dtype=np.uint8)
        self.assertEqual(等待战斗结束并回营任务.识别星数(黑图, "推毁率：0%"), 0)
        self.assertEqual(等待战斗结束并回营任务.识别星数(黑图, "推毁率：42%"), 0)
        self.assertEqual(等待战斗结束并回营任务.识别星数(黑图, "推毀率：0％"), 0)
        self.assertEqual(等待战斗结束并回营任务.识别星数(黑图, "毁率：18%"), 0)

    def test_零摧毁率推毁率结算页首轮即可完整记录失败零星(self):
        黑图 = np.zeros((600, 800, 3), dtype=np.uint8)
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.ocr引擎 = lambda _img, **_kw: ([
            ([[350, 210], [450, 210], [450, 235], [350, 235]], "推毁率：", 0.85),
            ([[370, 240], [430, 240], [430, 285], [370, 285]], "0%", 0.99),
            ([[370, 500], [430, 500], [430, 535], [370, 535]], "回营", 0.99),
        ], None)
        任务._画面仍在战斗 = Mock(return_value=False)
        任务.保存战斗结果截图 = Mock()
        任务.更新战斗学习 = Mock(return_value={})
        任务.生成战斗诊断 = Mock(return_value="0% 战败")
        数据库 = Mock()
        数据库.获取最新完整状态.return_value = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            数据库=数据库,
            机器人标志="robot_test",
            置脚本状态=Mock(),
            脚本延时=Mock(),
            本场实时摧毁率=0,
            本场最高实时摧毁率=0,
            本场目标战利品={},
            英雄技能状态={},
            op=SimpleNamespace(获取屏幕图像cv=lambda *a, **k: 黑图),
        )

        self.assertTrue(
            任务.记录战斗结果(上下文, 黑图, 结算页已复核=True, 战斗世界="夜世界")
        )
        统计 = 数据库.更新状态.call_args.args[2]
        self.assertEqual(统计["最近结果"], "失败")
        self.assertEqual(统计["最近星数"], 0)
        self.assertEqual(统计["最近摧毁率"], 0)

    def test_夜世界结算统计连续两次不完整时仍安全点击回营不永久滞留(self):
        识别器 = Mock()
        识别器.识别.return_value = _页面("战斗结算", 可信度=0.94)
        识别器.定位结算回营按钮.return_value = (400, 508)
        安全点击 = Mock(return_value=True)
        上下文 = SimpleNamespace(
            _战斗中=True,
            数据库=Mock(),
            机器人标志="robot_test",
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            _获取点击页面识别器=Mock(return_value=识别器),
            点击已确认安全按钮=安全点击,
            置脚本状态=Mock(),
            清除战斗结算保护状态=Mock(),
        )
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        任务.上下文 = 上下文
        任务._记录结算统计 = Mock(return_value=False)

        # 第 1 次统计不完整先返回 False 给下帧补拍机会
        self.assertFalse(任务.尝试点击回营按钮())
        安全点击.assert_not_called()
        # 第 2 次连续确认结算页仍不完整则直接安全回营，避免死卡 5 分钟
        self.assertTrue(任务.尝试点击回营按钮())
        安全点击.assert_called_once_with(400, 508, 延时=300)
        上下文.清除战斗结算保护状态.assert_called_once_with()

    def test_安全待命正常战斗等待不误触发180秒未知页面告警_真实未知仍告警(self):
        def 构造机器人():
            机器人 = 自动化机器人.__new__(自动化机器人)
            机器人.停止事件 = threading.Event()
            机器人.继续事件 = threading.Event()
            机器人.继续事件.set()
            机器人.停止原因 = ""
            机器人.记录日志 = Mock()
            机器人._处理待命超时告警 = Mock()
            时间 = [0.0]

            def 等待(timeout=None):
                时间[0] += float(timeout or 0.0)
                return 机器人.停止事件.is_set()

            机器人.停止事件.wait = Mock(side_effect=等待)
            return 机器人, 时间

        # 场景 1：战斗中持续 170 秒（34 帧 * 5 秒）后结算并回营回主页 -> 不误报未知页面待命告警
        机器人1, 时间1 = 构造机器人()
        页面序列1 = (
            [_页面("战斗中", 可信度=0.96)] * 34
            + [_页面("战斗结算", 可信度=0.94)] * 2
            + [_页面("夜世界主页", "夜世界", 0.74)] * 3
        )
        上下文1 = SimpleNamespace(
            _待命恢复世界="夜世界",
            _战斗中=True,
            识别点击画面=Mock(side_effect=页面序列1),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        机器人1._安全待命结算回营 = Mock(return_value=True)
        with patch("线程.自动化机器人._安全待命单调时间", side_effect=lambda: 时间1[0]):
            self.assertTrue(机器人1._等待人工恢复主世界(上下文1, Mock()))
        机器人1._处理待命超时告警.assert_not_called()

        # 场景 2：真正停在未知页 185 秒 -> 必须照常触发未知页面待命告警
        机器人2, 时间2 = 构造机器人()
        调用2 = [0]

        def 读取未知(**_kw):
            调用2[0] += 1
            if 调用2[0] >= 40:
                机器人2.停止事件.set()
            return _页面("未知")

        上下文2 = SimpleNamespace(
            _待命恢复世界="夜世界",
            识别点击画面=Mock(side_effect=读取未知),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        with patch("线程.自动化机器人._安全待命单调时间", side_effect=lambda: 时间2[0]):
            机器人2._等待人工恢复主世界(上下文2, Mock())
        机器人2._处理待命超时告警.assert_called_once()


class 长循环心跳续期与真卡死检测测试(unittest.TestCase):
    def _创建真实机器人与上下文(self, 初始时间=1000.0):
        虚拟时间 = [float(初始时间)]
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_night"
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人._最近心跳续期 = None
        最后日志 = SimpleNamespace(
            日志内容="未确认圣水车，沿地图边缘拖动搜索（1/4）",
            记录时间=float(初始时间),
            下次超时=float(初始时间 + 60.0),
        )
        机器人.数据库 = SimpleNamespace(读取最后日志=Mock(return_value=最后日志))
        机器人.记录日志 = Mock()

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.机器人标志 = 机器人.机器人标志
        上下文.停止事件 = 机器人.停止事件
        上下文.继续事件 = 机器人.继续事件
        上下文.置脚本状态 = Mock()
        上下文.续期心跳 = 机器人.续期心跳
        上下文._任务计划长时间等待 = False
        上下文._战斗中 = False
        上下文._最近点击页面结果 = None
        上下文._部落竞赛占用画面 = lambda: True
        上下文.自动确认升级完成弹窗 = Mock()
        上下文.清理中央游戏提示 = Mock()
        上下文.op = None
        return 机器人, 上下文, 虚拟时间

    def test_拖动期间短脚本延时不触发升级或中央提示弹窗OCR检查(self):
        _, 上下文, 虚拟时间 = self._创建真实机器人与上下文(1000.0)
        上下文._部落竞赛占用画面 = lambda: False
        上下文.鼠标 = SimpleNamespace(_按下起点=(670, 150))
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8)))

        def 推进(timeout=None):
            虚拟时间[0] += float(timeout or 0.0)
            return False

        上下文.停止事件.wait = Mock(side_effect=推进)
        with patch("任务流程.基础任务框架.time.monotonic", side_effect=lambda: 虚拟时间[0]):
            for _ in range(24):
                虚拟时间[0] += 1.0
                上下文.脚本延时(16)

        上下文.自动确认升级完成弹窗.assert_not_called()
        上下文.清理中央游戏提示.assert_not_called()
        上下文.op.获取屏幕图像cv.assert_not_called()

    def test_圣水车边缘拖动长循环每次迭代续期心跳超过90秒不超时(self):
        机器人, 上下文, 虚拟时间 = self._创建真实机器人与上下文(1000.0)
        超时采样 = []

        def 慢步延时(_毫秒):
            # 模拟每步耗时 4 秒（24 步共 96 秒，远超 60+5 秒阈值）
            虚拟时间[0] += 4.0
            超时采样.append(机器人.检查超时())

        上下文.脚本延时 = Mock(side_effect=慢步延时)
        上下文.鼠标 = SimpleNamespace(
            移动到=Mock(),
            左键按下=Mock(),
            左键抬起=Mock(),
        )

        任务 = 收集圣水车任务.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        任务._夜世界仍在前台 = Mock(return_value=True)

        with patch("线程.自动化机器人.time.time", side_effect=lambda: 虚拟时间[0]):
            self.assertTrue(任务._边缘拖动(滑动配置((670, 150), (670, 400))))
            self.assertGreaterEqual(虚拟时间[0] - 1000.0, 96.0)
            self.assertTrue(all(not 超时 for 超时, _ in 超时采样), 超时采样[:5])
            self.assertEqual(机器人.检查超时(), (False, ""))

    def test_圣水车边缘拖动真卡死停止续期后监控仍触发心跳超时(self):
        机器人, 上下文, 虚拟时间 = self._创建真实机器人与上下文(1000.0)
        上下文.鼠标 = SimpleNamespace(
            移动到=Mock(),
            左键按下=Mock(),
            左键抬起=Mock(),
        )
        步计数 = [0]

        def 卡死延时(_毫秒):
            步计数[0] += 1
            if 步计数[0] <= 5:
                虚拟时间[0] += 3.0
                self.assertEqual(机器人.检查超时(), (False, ""))
            elif 步计数[0] == 6:
                # 第 6 步开始线程在底层 ADB/OCR 中真正卡死 70 秒，不再推进循环
                虚拟时间[0] += 70.0
                超时, 原因 = 机器人.检查超时()
                self.assertTrue(超时)
                self.assertIn("圣水车边缘拖动", 原因)
                self.assertIn("含5秒宽限", 原因)
                机器人.停止事件.set()
                raise RuntimeError("模拟监控因心跳超时停止线程")

        上下文.脚本延时 = Mock(side_effect=卡死延时)
        任务 = 收集圣水车任务.__new__(收集圣水车任务)
        任务.上下文 = 上下文
        任务._夜世界仍在前台 = Mock(return_value=True)

        with patch("线程.自动化机器人.time.time", side_effect=lambda: 虚拟时间[0]):
            self.assertFalse(任务._边缘拖动(滑动配置((670, 150), (670, 400))))

    def test_夜世界资源OCR复读与战斗等待循环正常迭代均续期心跳(self):
        机器人, 上下文, 虚拟时间 = self._创建真实机器人与上下文(2000.0)
        黑图 = np.zeros((600, 800, 3), dtype=np.uint8)
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=黑图))
        上下文.脚本延时 = Mock(side_effect=lambda _ms: 虚拟时间.__setitem__(0, 虚拟时间[0] + 15.0))

        # 1) 夜世界资源独立复读：跨 30+ 秒仍续心跳
        资源任务 = 更新夜世界资源状态任务.__new__(更新夜世界资源状态任务)
        资源任务.ocr引擎 = Mock(return_value=([], None))

        def 慢OCR(*_a, **_kw):
            虚拟时间[0] += 25.0
            self.assertEqual(机器人.检查超时(), (False, ""))
            return 123456

        with patch("线程.自动化机器人.time.time", side_effect=lambda: 虚拟时间[0]), \
             patch("任务流程.夜世界.更新夜世界账号资源状态.单行资源识别", side_effect=慢OCR):
            self.assertEqual(资源任务._独立复读(上下文, "圣水"), (123456, 123456))

        # 2) 等待进入夜世界战斗（匹配页超过 75 秒）：每轮续心跳不超时
        等待任务 = 等待进入战斗.__new__(等待进入战斗)
        等待任务.上下文 = 上下文
        次数 = [0]

        def 模拟匹配():
            次数[0] += 1
            if 次数[0] <= 5:
                return _页面("搜索对手中", 可信度=0.92), True
            return _页面("战斗中", 可信度=0.96), True

        等待任务._读取页面状态 = Mock(side_effect=模拟匹配)
        上下文.点击 = Mock(return_value=True)
        with patch("线程.自动化机器人.time.time", side_effect=lambda: 虚拟时间[0]), \
             patch("任务流程.夜世界.夜世界打鱼.等待进入战斗.time.time", side_effect=lambda: 虚拟时间[0]):
            self.assertTrue(等待任务.执行())
            self.assertEqual(机器人.检查超时(), (False, ""))

        # 3) 等待回营或第二次战斗（超过 90 秒）：每轮续心跳不超时
        回营任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        回营任务.上下文 = 上下文
        回营任务.只等待回营 = True
        回营次数 = [0]

        def 模拟回营():
            回营次数[0] += 1
            return 回营次数[0] >= 6

        回营任务._读取页面状态 = Mock(return_value=(_页面("战斗中", 可信度=0.96), True))
        回营任务.尝试点击回营按钮 = Mock(side_effect=模拟回营)
        with patch("线程.自动化机器人.time.time", side_effect=lambda: 虚拟时间[0]), \
             patch("任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗.time.time", side_effect=lambda: 虚拟时间[0]):
            self.assertTrue(回营任务.执行())
            self.assertEqual(机器人.检查超时(), (False, ""))

        # 4) 随后真正卡死 70 秒不再续期 -> 必须超时
        虚拟时间[0] += 70.0
        with patch("线程.自动化机器人.time.time", side_effect=lambda: 虚拟时间[0]):
            超时, 原因 = 机器人.检查超时()
        self.assertTrue(超时)
        self.assertIn("含5秒宽限", 原因)


if __name__ == "__main__":
    unittest.main()


class 过期结算缓存锁修复测试(unittest.TestCase):
    """实机 17:50：拖动中单帧误识别“战斗星级奖励”后缓存残留，锁住进攻入口。"""

    def _上下文(self, 新帧序列):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文._军队编辑中 = False
        上下文._战斗结束已确认 = False
        上下文._宝石保护已触发 = False
        上下文._最近结算视觉时间 = 0.0
        上下文._最近点击页面结果 = _页面(
            "战斗星级奖励", 可信度=0.96, 依据=("蓝紫星级奖励面板+中央确定按钮0.96",)
        )
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文._获取点击识别截图 = Mock(return_value=np.zeros((600, 800, 3), np.uint8))
        帧 = iter(新帧序列)

        def 识别(强制=False):
            结果 = next(帧)
            上下文._最近点击页面结果 = 结果
            return 结果

        上下文.识别点击画面 = Mock(side_effect=识别)
        return 上下文

    def test_过期星级奖励缓存新帧为夜世界主页时解除结算锁放行进攻入口(self):
        主页 = _页面("夜世界主页", "夜世界", 0.74, ("夜世界资源栏0.98", "新版战斗入口0.98"))
        上下文 = self._上下文([主页, 主页])

        self.assertFalse(上下文.检查宝石商店危险页面())
        日志 = [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list]
        self.assertTrue(any("结算页缓存已过期" in 行 for 行 in 日志))
        self.assertFalse(any("本场结算状态已锁定" in 行 for 行 in 日志))

    def test_新帧仍为星级奖励时保持结算锁(self):
        奖励 = _页面("战斗星级奖励", 可信度=0.96)
        上下文 = self._上下文([奖励, 奖励])

        self.assertTrue(上下文.检查宝石商店危险页面())
        日志 = [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list]
        self.assertTrue(any("本场结算状态已锁定" in 行 for 行 in 日志))

    def test_新帧为低置信主页时保持结算锁(self):
        上下文 = self._上下文([_页面("夜世界主页", "夜世界", 0.40)])

        self.assertTrue(上下文.检查宝石商店危险页面())

    def test_战斗状态机已确认结束时不复核直接锁定(self):
        上下文 = self._上下文([])
        上下文._战斗结束已确认 = True

        self.assertTrue(上下文.检查宝石商店危险页面())
        上下文.识别点击画面.assert_not_called()
