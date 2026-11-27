"""rc160 11-27 15:20 夜世界第二场“更換部隊”弹层卡死与安全待命恢复回放。

现场：等待回营或第二次战斗 命中第二场换兵箭头后点击，弹出宽幅
“更換部隊”弹层遮住“結束戰鬥”，页面识别只能给出“战斗过渡”，下兵
等满 20 秒失败进入安全待命；之后结算页、闲置断线弹窗都不是安全主页，
待命一直不恢复。样本均为现场截图只读复制。
"""
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼 import 等待回营或第二场战斗 as 回营模块
from 任务流程.夜世界.夜世界打鱼.下兵 import 下兵
from 任务流程.夜世界.夜世界打鱼.等待回营或第二场战斗 import 等待回营或第二次战斗
from 工具包.工具函数 import 单行资源识别
from 线程.自动化机器人 import 自动化机器人

测试目录 = Path(__file__).resolve().parent
样本目录 = 测试目录 / "回放样本"
宽屏目录 = 样本目录 / "16比9"
图片库 = 测试目录.parent / "img"


def 读取(文件: Path) -> np.ndarray:
    图像 = cv2.imdecode(np.fromfile(str(文件), dtype=np.uint8), cv2.IMREAD_COLOR)
    if 图像 is None:
        raise AssertionError(f"无法读取样本：{文件}")
    return cv2.resize(图像, (800, 600), interpolation=cv2.INTER_AREA)


def 宽屏(前缀: str) -> np.ndarray:
    return 读取(sorted(宽屏目录.glob(f"{前缀}_*.jpg"))[0])


换兵弹层图 = 样本目录 / "night_stage2_swap_popup_20261127_152029.png"
待命结算图 = 样本目录 / "standby_night_settle_20261127_152329.png"


def _页面(名称, 世界=None, 可信度=0.0):
    return SimpleNamespace(页面=名称, 世界=世界, 可信度=可信度)


class 换兵弹层识别回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.识别器 = 页面识别器(模板匹配引擎(图片库路径=图片库))

    def test_现场帧识别为更换部队弹窗且关闭点在来源兵卡卡面(self):
        图 = 读取(换兵弹层图)
        for 战斗中 in (True, False):
            with self.subTest(战斗中=战斗中):
                结果 = self.识别器.识别(图, 战斗中=战斗中)
                self.assertEqual(结果.页面, "更换部队弹窗")
        x, y = 页面识别器.定位更换部队弹窗关闭点(图)
        # 小三角指向第 7 格兵卡（逻辑 x≈505..558）；y 在卡面中部，
        # 远离卡底 y≈560~585 的绿色换兵箭头，也在弹层（y≤460）之外。
        self.assertTrue(505 <= x <= 558, x)
        self.assertEqual(y, 515)

    def test_其它夜世界与结算帧不会误判为换兵弹层(self):
        样本 = [读取(待命结算图)] + [
            读取(文件) for 文件 in sorted(宽屏目录.glob("*.jpg"))
        ]
        for 序号, 图 in enumerate(样本):
            with self.subTest(序号=序号):
                self.assertIsNone(页面识别器.定位更换部队弹窗关闭点(图))

    def test_待命现场结算帧可定位回营按钮(self):
        图 = 读取(待命结算图)
        结果 = self.识别器.识别(图, 战斗中=True)
        self.assertEqual(结果.页面, "战斗结算")
        x, y = self.识别器.定位结算回营按钮(图)
        self.assertTrue(340 <= x <= 460 and 480 <= y <= 535, (x, y))

    def test_第二场开始帧正常识别为战斗中(self):
        结果 = self.识别器.识别(宽屏("night_battle2_start"), 战斗中=True)
        self.assertEqual(结果.页面, "战斗中")


class 上下文收起换兵弹层测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.识别器 = 页面识别器(模板匹配引擎(图片库路径=图片库))

    def _上下文(self, 帧序列):
        上下文 = 任务上下文.__new__(任务上下文)
        帧 = iter(帧序列)
        上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(side_effect=lambda *a, **k: next(帧)))
        上下文._点击页面识别器 = self.识别器
        上下文.停止事件 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.点击已确认安全按钮 = Mock(return_value=True)
        return 上下文

    def test_只点弹层外来源兵卡并确认回到战斗页(self):
        上下文 = self._上下文([读取(换兵弹层图), 宽屏("night_battle2_start")])
        self.assertTrue(上下文.关闭更换部队弹窗())
        上下文.点击已确认安全按钮.assert_called_once()
        x, y = 上下文.点击已确认安全按钮.call_args.args[:2]
        self.assertTrue(505 <= x <= 558 and y == 515, (x, y))
        self.assertTrue(any(
            "确认回到战斗页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_不是换兵弹层时不发送任何输入(self):
        上下文 = self._上下文([宽屏("night_battle2_start")])
        self.assertFalse(上下文.关闭更换部队弹窗())
        上下文.点击已确认安全按钮.assert_not_called()

    def test_弹层一直不收起时有限重试后失败(self):
        弹层 = 读取(换兵弹层图)
        上下文 = self._上下文([弹层] * 20)
        self.assertFalse(上下文.关闭更换部队弹窗(最多尝试=2))
        self.assertEqual(上下文.点击已确认安全按钮.call_count, 2)


class 第二场流程测试(unittest.TestCase):
    def setUp(self):
        原 = 回营模块.停止并等待英雄技能线程
        回营模块.停止并等待英雄技能线程 = lambda *a, **k: True
        self.addCleanup(setattr, 回营模块, "停止并等待英雄技能线程", 原)

    def test_换兵箭头只读确认第二场绝不点击(self):
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        任务.上下文 = SimpleNamespace(点击=Mock(return_value=True), 置脚本状态=Mock())
        任务.是否出现图片 = Mock(return_value=(True, (558, 600)))
        self.assertTrue(任务.是否出现换兵种箭头())
        任务.上下文.点击.assert_not_called()

    def test_等待第二场遇到换兵弹层先收起再按第二场下兵(self):
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        页面序列 = iter([
            (_页面("更换部队弹窗"), True),
            (_页面("战斗中"), True),
        ])
        任务._读取页面状态 = Mock(side_effect=lambda: next(页面序列))
        任务.是否出现换兵种箭头 = Mock(return_value=True)
        任务._第二场开始倒计时已出现 = Mock(return_value=False)
        任务.尝试点击回营按钮 = Mock(return_value=True)
        任务.上下文 = SimpleNamespace(
            页面恢复失败=False,
            关闭更换部队弹窗=Mock(return_value=True),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        with patch.object(回营模块, "下兵") as 下兵类:
            下兵类.return_value.执行.return_value = True
            self.assertTrue(任务.执行())
        任务.上下文.关闭更换部队弹窗.assert_called_once_with()
        下兵类.assert_called_once_with(任务.上下文, 第二场=True)
        self.assertFalse(任务.上下文.页面恢复失败)

    def test_换兵弹层收不起时安全失败不下兵(self):
        任务 = 等待回营或第二次战斗.__new__(等待回营或第二次战斗)
        任务._读取页面状态 = Mock(return_value=(_页面("更换部队弹窗"), True))
        任务.尝试点击回营按钮 = Mock(return_value=False)
        任务.上下文 = SimpleNamespace(
            页面恢复失败=False,
            关闭更换部队弹窗=Mock(return_value=False),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        with patch.object(回营模块, "下兵") as 下兵类:
            self.assertFalse(任务.执行())
        下兵类.assert_not_called()
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_下兵等待战斗页时收起换兵弹层后继续(self):
        任务 = 下兵.__new__(下兵)
        任务.第二场 = True
        任务.停止并等待英雄技能线程 = lambda *a, **k: True
        页面序列 = iter([_页面("更换部队弹窗"), _页面("战斗中")])
        任务.上下文 = SimpleNamespace(
            识别点击画面=Mock(side_effect=lambda: next(页面序列)),
            关闭更换部队弹窗=Mock(return_value=True),
            停止事件=threading.Event(),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        self.assertTrue(任务._等待真实战斗画面())
        任务.上下文.关闭更换部队弹窗.assert_called_once_with()

    def test_第二场只选择彩色可用兵卡(self):
        # 第二场开始帧：第 1~6 格灰色，只有第 7/8 格援军可选。
        self.assertEqual(
            下兵.识别彩色兵卡(宽屏("night_battle2_start")),
            [(531, 520), (592, 520)],
        )
        现场 = 下兵.识别彩色兵卡(读取(换兵弹层图))
        self.assertIn((531, 520), 现场)
        self.assertIn((592, 520), 现场)
        self.assertNotIn((152, 520), 现场)
        # 卡面中部选兵点必须避开卡底绿色换兵箭头（y≈560~585）。
        self.assertTrue(all(y < 550 for _, y in 现场))

    def test_第二场下兵按彩色兵卡选槽(self):
        任务 = 下兵.__new__(下兵)
        任务.第二场 = True
        任务._第二场可用兵卡 = Mock(return_value=[(531, 520), (592, 520)])
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=True),
            停止事件=threading.Event(),
            置脚本状态=Mock(),
        )
        self.assertTrue(任务.执行下兵操作())
        选槽 = [
            调用.args[:2] for 调用 in 任务.上下文.点击.call_args_list
            if 调用.args[1] == 520
        ]
        self.assertEqual(选槽, [(531, 520), (592, 520)])


class 安全待命结算与断线恢复测试(unittest.TestCase):
    def _创建机器人(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止事件 = threading.Event()
        机器人.继续事件 = threading.Event()
        机器人.继续事件.set()
        机器人.停止原因 = ""
        机器人.记录日志 = Mock()
        时间 = [0.0]

        def 等待(timeout=None):
            时间[0] += float(timeout or 0.0)
            return False

        机器人.停止事件.wait = Mock(side_effect=等待)
        计时器 = patch(
            "线程.自动化机器人._安全待命单调时间", side_effect=lambda: 时间[0]
        )
        计时器.start()
        self.addCleanup(计时器.stop)
        return 机器人

    def test_待命连续两帧结算页按原流程回营后恢复夜世界(self):
        机器人 = self._创建机器人()
        主页 = _页面("夜世界主页", "夜世界", 0.74)
        上下文 = SimpleNamespace(
            _待命恢复世界="夜世界",
            _战斗中=True,
            数据库=None,
            机器人标志="robot_test",
            获取模板识别器=Mock(),
            识别点击画面=Mock(side_effect=[
                _页面("战斗结算", None, 0.94),
                _页面("战斗结算", None, 0.94),
                主页, 主页, 主页,
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        with patch.object(
            等待回营或第二次战斗, "尝试点击回营按钮", return_value=True
        ) as 回营:
            self.assertTrue(机器人._等待人工恢复主世界(上下文, Mock()))
        回营.assert_called_once_with()
        self.assertFalse(上下文._战斗中)
        日志 = [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list]
        self.assertTrue(any("连续两帧确认夜世界战斗结算页" in 项 for 项 in 日志))
        self.assertTrue(any("结算页已点击回营" in 项 for 项 in 日志))

    def test_单帧结算页不点击回营(self):
        机器人 = self._创建机器人()
        次数 = {"n": 0}

        def 读取(**_):
            次数["n"] += 1
            if 次数["n"] >= 2:
                机器人.停止事件.set()
            return _页面("战斗结算", None, 0.94) if 次数["n"] == 1 else _页面("未知")

        上下文 = SimpleNamespace(
            _待命恢复世界="夜世界",
            识别点击画面=Mock(side_effect=读取),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        with patch.object(等待回营或第二次战斗, "尝试点击回营按钮") as 回营:
            self.assertFalse(机器人._等待人工恢复主世界(上下文, Mock()))
        回营.assert_not_called()

    def test_最后一次结算回营跳过统计复核避免永久卡结算页(self):
        机器人 = self._创建机器人()
        上下文 = SimpleNamespace(
            置脚本状态=Mock(), 脚本延时=Mock(), _战斗中=True,
            数据库=None, 机器人标志="robot_test", 获取模板识别器=Mock(),
        )
        记录 = {}

        def 回营(任务):
            记录["已记录"] = getattr(任务, "_夜世界结算统计已记录", False)
            记录["世界"] = 任务.结算战斗世界
            return True

        with patch.object(等待回营或第二次战斗, "尝试点击回营按钮", autospec=True, side_effect=回营):
            self.assertTrue(机器人._安全待命结算回营(上下文, "夜世界", 2, 2))
        self.assertTrue(记录["已记录"])
        self.assertEqual(记录["世界"], "夜世界")
        self.assertFalse(上下文._战斗中)

    def test_待命断线弹窗按现有断线重连流程恢复(self):
        机器人 = self._创建机器人()
        主页 = _页面("夜世界主页", "夜世界", 0.74)
        上下文 = SimpleNamespace(
            _待命恢复世界="夜世界",
            _战斗中=True,
            页面恢复失败=True,
            识别点击画面=Mock(side_effect=[
                _页面("断线弹窗", None, 0.98), 主页, 主页, 主页,
            ]),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        检测登录 = Mock()
        检测登录.执行.return_value = True
        self.assertTrue(机器人._等待人工恢复主世界(上下文, 检测登录))
        检测登录.执行.assert_called_once_with(首次登录=False)
        self.assertFalse(上下文._战斗中)
        日志 = [调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list]
        self.assertTrue(any("执行游戏内断线重连（第1/3次）" in 项 for 项 in 日志))

    def test_宝石保护已触发时断线也不自动重连(self):
        机器人 = self._创建机器人()
        次数 = {"n": 0}

        def 读取(**_):
            次数["n"] += 1
            if 次数["n"] >= 2:
                机器人.停止事件.set()
            return _页面("断线弹窗", None, 0.98)

        上下文 = SimpleNamespace(
            _宝石保护已触发=True,
            识别点击画面=Mock(side_effect=读取),
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        检测登录 = Mock()
        self.assertFalse(机器人._等待人工恢复主世界(上下文, 检测登录))
        检测登录.执行.assert_not_called()


class 夜世界金币OCR首位回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from 模块.检测.OCR识别器 import 安全OCR引擎

        cls.OCR = 安全OCR引擎()

    @staticmethod
    def _金币行(图):
        资源栏 = 图[3:105, 593:793]
        return 资源栏[: 资源栏.shape[0] // 2]

    def test_船旁现场金币按白色数字串裁剪后读对(self):
        # 旧裁剪把数字左侧的船帆读成多余首位：73 020 459。
        for 前缀 in ("night_home_boat_cart", "night_home_wall_menu"):
            with self.subTest(前缀=前缀):
                行 = self._金币行(宽屏(前缀))
                self.assertEqual(
                    单行资源识别(self.OCR, 行, 裁到数字范围=True), 3_020_459
                )

    def test_前导零截断读数不被int吞成短数字(self):
        行 = np.zeros((51, 200, 3), dtype=np.uint8)
        # 轻量彩色/二值都只读到 “020 459”，完整识别也只拆出 “3”：
        # 不能返回 20459 或 3，必须返回 0 让调用方保留旧快照。
        引擎 = Mock(side_effect=[
            ([("020 459", 0.9)], None),
            ([("020459", 0.9)], None),
            ([([[0, 0]], "3", 0.9)], None),
            ([([[0, 0]], "3", 0.9)], None),
        ])
        self.assertEqual(单行资源识别(引擎, 行), 0)

    def test_前导零截断后完整识别补回首位(self):
        行 = np.zeros((51, 200, 3), dtype=np.uint8)
        引擎 = Mock(side_effect=[
            ([("020 459", 0.9)], None),
            ([("020459", 0.9)], None),
            ([([[0, 0]], "3 020 459", 0.95)], None),
            ([([[0, 0]], "3 020 459", 0.95)], None),
        ])
        self.assertEqual(单行资源识别(引擎, 行), 3_020_459)


if __name__ == "__main__":
    unittest.main()
