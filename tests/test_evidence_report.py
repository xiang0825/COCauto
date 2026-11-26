"""异常自动留证 / 每日完成通知 / 一键导出问题包。"""

import json
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 应用 import 异常留证, 每日通知, 问题包
from 数据库.任务数据库 import 任务数据库, 机器人设置, 规范化每日通知时间


def 图像(值=0):
    return np.full((600, 800, 3), 值, dtype=np.uint8)


class 时钟:
    def __init__(self, 起点=1_800_000_000.0):
        self.值 = 起点

    def __call__(self):
        return self.值


class 异常留证测试(unittest.TestCase):
    def setUp(self):
        self._临时 = tempfile.TemporaryDirectory(prefix="coc-evidence-")
        self.根 = Path(self._临时.name)
        异常留证._上次留证.clear()

    def tearDown(self):
        self._临时.cleanup()

    def test_保存当前截图前序帧和摘要(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(帧数=3, 最短间隔秒=1.0, 时钟=钟)
        for 序号 in range(5):
            钟.值 += 2
            self.assertTrue(缓存.记录("r1", 图像(序号 * 10)))
        路径 = 异常留证.保存异常现场(
            "心跳超时", "数据库最后日志记录已超时", 机器人标志="r1",
            当前图像=图像(200), 日志摘要=["11-26 10:00:00 开始搜索"],
            根目录=self.根, 帧缓存=缓存, 时钟=钟,
        )
        self.assertIsNotNone(路径)
        self.assertEqual(路径.parent, self.根 / "异常现场")
        名称 = sorted(项.name for 项 in 路径.iterdir())
        self.assertIn("当前.png", 名称)
        self.assertEqual(sum(1 for 名 in 名称 if 名.startswith("前序_")), 3)
        摘要 = (路径 / "摘要.txt").read_text(encoding="utf-8")
        self.assertIn("心跳超时", 摘要)
        self.assertIn("开始搜索", 摘要)

    def test_帧缓存节流(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(帧数=5, 最短间隔秒=1.5, 时钟=钟)
        self.assertTrue(缓存.记录("r1", 图像()))
        钟.值 += 0.5
        self.assertFalse(缓存.记录("r1", 图像()))
        钟.值 += 1.5
        self.assertTrue(缓存.记录("r1", 图像()))
        self.assertEqual(len(缓存.取出("r1")), 2)
        self.assertFalse(缓存.记录("r1", None))

    def test_无当前截图时用最近缓存帧(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(时钟=钟)
        缓存.记录("r1", 图像(5))
        路径 = 异常留证.保存异常现场(
            "异常退出", "未处理异常", 机器人标志="r1", 根目录=self.根, 帧缓存=缓存, 时钟=钟,
        )
        self.assertTrue((路径 / "当前_最近缓存帧.jpg").is_file())

    def test_只保留最近N份且不碰其它文件(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(时钟=钟)
        现场 = self.根 / "异常现场"
        现场.mkdir()
        (现场 / "说明.txt").write_text("用户文件", encoding="utf-8")
        (现场 / "我的截图").mkdir()
        路径列表 = []
        for 序号 in range(5):
            钟.值 += 100
            路径列表.append(异常留证.保存异常现场(
                f"类别{序号}", "原因", 机器人标志="r1", 根目录=self.根,
                帧缓存=缓存, 时钟=钟, 保留份数=3,
            ))
        剩余 = 异常留证.列出留证目录(self.根)
        self.assertEqual(剩余, sorted(路径列表[-3:]))
        self.assertTrue((现场 / "说明.txt").is_file())
        self.assertTrue((现场 / "我的截图").is_dir())

    def test_同类留证节流与关闭(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(时钟=钟)
        参数 = dict(机器人标志="r1", 根目录=self.根, 帧缓存=缓存, 时钟=钟)
        self.assertIsNotNone(异常留证.保存异常现场("未知页面待命", "a", **参数))
        钟.值 += 10
        self.assertIsNone(异常留证.保存异常现场("未知页面待命", "b", **参数))
        self.assertIsNotNone(异常留证.保存异常现场("异常退出", "c", **参数))
        钟.值 += 100
        self.assertIsNone(异常留证.保存异常现场("心跳超时", "d", 保留份数=0, **参数))
        self.assertEqual(len(异常留证.列出留证目录(self.根)), 2)

    def test_截图提供器取新帧时回调且缓存帧不重复回调(self):
        from 核心.ADB屏幕 import ADB屏幕

        设备 = SimpleNamespace(
            参考宽度=800, 参考高度=600,
            获取屏幕图像cv=Mock(return_value=图像(1)),
        )
        屏幕 = ADB屏幕.__new__(ADB屏幕)
        屏幕.设备 = 设备
        屏幕._原始截图缓存 = None
        屏幕._原始截图缓存时间 = 0.0
        屏幕._最短截图间隔秒 = 60.0
        屏幕._已告警分辨率 = set()
        屏幕._日志回调 = None
        回调 = Mock(side_effect=RuntimeError("回调异常不能影响截图"))
        屏幕._新帧回调 = 回调
        屏幕.获取屏幕图像cv(0, 0, 800, 600)
        屏幕.获取屏幕图像cv(0, 0, 800, 600)
        回调.assert_called_once()


class 机器人留证接线测试(unittest.TestCase):
    def _机器人(self, 停止原因):
        from 线程.自动化机器人 import 自动化机器人

        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.停止原因 = 停止原因
        机器人.保存异常现场 = Mock()
        return 机器人

    def test_人工停止和自然完成不留证(self):
        for 原因 in ("界面停止按钮", "控制台关闭", "任务自然完成", "无心跳"):
            with self.subTest(原因=原因):
                机器人 = self._机器人(原因)
                机器人._异常退出留证(None)
                机器人.保存异常现场.assert_not_called()

    def test_异常退出留证(self):
        机器人 = self._机器人("未处理异常：boom")
        机器人._异常退出留证(None)
        机器人.保存异常现场.assert_called_once_with("异常退出", "未处理异常：boom")

    def test_待命超时留证(self):
        机器人 = self._机器人("")
        机器人.记录日志 = Mock()
        上下文 = SimpleNamespace(保存待命现场截图并通知=Mock())
        机器人._处理待命超时通知(上下文, "未知页面 180 秒")
        机器人.保存异常现场.assert_called_once_with("未知页面待命", "未知页面 180 秒")
        上下文.保存待命现场截图并通知.assert_called_once()

    def test_保存异常现场写带路径的日志(self):
        from 线程.自动化机器人 import 自动化机器人

        with tempfile.TemporaryDirectory() as 目录:
            机器人 = 自动化机器人.__new__(自动化机器人)
            机器人.机器人标志 = "r1"
            机器人.数据库 = Mock()
            机器人.数据库.文件路径 = 任务数据库.默认数据库路径()
            机器人.数据库.获取机器人设置.return_value = SimpleNamespace(异常现场保留份数=30)
            机器人.数据库.查询日志历史.return_value = []
            机器人.op = SimpleNamespace(_原始截图缓存=图像(3))
            机器人.记录日志 = Mock()
            异常留证._上次留证.clear()
            with patch.object(异常留证, "程序目录", return_value=Path(目录)):
                路径 = 机器人.保存异常现场("心跳超时", "超时")
            self.assertIsNotNone(路径)
            self.assertTrue((路径 / "当前.png").is_file())
            日志 = 机器人.记录日志.call_args.args[0]
            self.assertIn(str(路径), 日志)

    def test_测试或临时数据库不往程序目录留证(self):
        from 线程.自动化机器人 import 自动化机器人

        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "r1"
        机器人.数据库 = SimpleNamespace(文件路径=str(Path(tempfile.gettempdir()) / "x.db"))
        with patch.object(异常留证, "保存异常现场") as 保存:
            self.assertIsNone(机器人.保存异常现场("异常退出", "boom"))
        保存.assert_not_called()

    def test_监控中心心跳超时先留证再停止(self):
        from 主入口 import 机器人监控中心

        中心 = 机器人监控中心.__new__(机器人监控中心)
        顺序 = []
        线程 = SimpleNamespace(
            检查超时=Mock(return_value=(True, "超时原因")),
            保存异常现场=Mock(side_effect=lambda *a: 顺序.append("留证")),
        )

        def 停止(*_):
            顺序.append("停止")
            中心.运行标志 = False

        线程.停止 = 停止
        中心.机器人池 = {"r1": 线程}
        中心.运行标志 = True
        中心._加入全局消息队列 = Mock()
        中心._检查自动重启 = Mock()
        中心._处理消息 = Mock()
        中心._检查每日通知 = Mock()
        with patch("主入口.time.sleep"):
            中心._监控循环()
        self.assertEqual(顺序, ["留证", "停止"])
        线程.保存异常现场.assert_called_once_with("心跳超时", "超时原因")


class 每日通知测试(unittest.TestCase):
    def setUp(self):
        self._临时 = tempfile.TemporaryDirectory(prefix="coc-daily-")
        self.数据库 = 任务数据库(str(Path(self._临时.name) / "任务系统.db"))
        self.数据库.保存机器人设置("r1", 机器人设置())
        self.今天 = datetime(2026, 11, 26, 23, 40).timestamp()

    def tearDown(self):
        self._临时.cleanup()

    def _写日志(self, 时间, 内容):
        with self.数据库._获取连接() as conn:
            conn.execute(
                "INSERT INTO 任务日志 (机器人标志, 记录时间, 日志内容, 下次超时) VALUES (?, ?, ?, ?)",
                ("r1", 时间, 内容, 时间 + 60),
            )
            conn.commit()

    def test_通知时间规范化(self):
        self.assertEqual(规范化每日通知时间("7:05"), "07:05")
        self.assertEqual(规范化每日通知时间("23：30"), "23:30")
        self.assertEqual(规范化每日通知时间("25:00"), "23:30")
        self.assertEqual(机器人设置(每日通知时间="abc").每日通知时间, "23:30")

    def test_部落竞赛汇总解析(self):
        日志 = [
            (1, "部落竞赛：个人积分 3000/10000"),
            (2, "部落竞赛：已接任务：掠夺金币（150分）在单场多人对战中掠夺"),
            (3, "部落竞赛：已接任务（收起详情后确认）：摧毁资源建筑（200分）摧毁"),
            (4, "部落竞赛：个人积分 3350/10000"),
        ]
        结果 = 每日通知.汇总部落竞赛(日志)
        self.assertEqual(结果["已接任务"], ["掠夺金币150分", "摧毁资源建筑200分"])
        self.assertEqual(结果["个人积分"], (3350, 10000))
        self.assertEqual(结果["今日积分增加"], 350)
        self.assertFalse(结果["可领奖"])
        self.assertTrue(每日通知.汇总部落竞赛([(1, "部落竞赛：个人积分 10000/10000")])["可领奖"])
        self.assertTrue(每日通知.汇总部落竞赛(
            [(1, "部落竞赛：部落竞赛已结束、可以领奖了，请自己去选择并领取奖励（脚本不会点领奖）。")]
        )["可领奖"])

    def test_生成摘要含场次胜率收益和竞赛(self):
        基 = self.今天 - 3600
        self._写日志(基, "战斗结果：胜利；星数：2；摧毁率：65%")
        self._写日志(基 + 1, "本场资源净变化：金币 +300000，圣水 +200000，黑油 +1500")
        self._写日志(基 + 600, "战斗结果：失败；星数：0；摧毁率：30%")
        self._写日志(基 + 601, "本场资源净变化：金币 +100000，圣水 +50000，黑油 +0")
        self._写日志(基 + 700, "部落竞赛：个人积分 10000/10000")
        标题, 正文, 有内容 = 每日通知.生成每日摘要(self.数据库, "r1", self.今天)
        self.assertTrue(有内容)
        self.assertIn("11-26", 标题)
        self.assertIn("场次 2", 正文)
        self.assertIn("胜率 50%", 正文)
        self.assertIn("金+400k", 正文)
        self.assertIn("积分 10000/10000", 正文)
        self.assertIn("可领奖", 正文)
        self.assertIn("不会自动领奖", 正文)

    def test_备份日志里今天的记录也计入(self):
        备份 = Path(self.数据库.文件路径).with_name("上次日志.bak.jsonl")
        行 = [
            {"id": 1, "机器人": "r1", "ts": self.今天 - 7200, "内容": "战斗结果：胜利；星数：3；摧毁率：100%"},
            {"id": 2, "机器人": "r2", "ts": self.今天 - 7200, "内容": "战斗结果：胜利；星数：3；摧毁率：100%"},
        ]
        备份.write_text("\n".join(json.dumps(项, ensure_ascii=False) for 项 in 行) + "\n", encoding="utf-8")
        _, 正文, 有内容 = 每日通知.生成每日摘要(self.数据库, "r1", self.今天)
        self.assertTrue(有内容)
        self.assertIn("场次 1", 正文)

    def test_调度器到点只发一次且可关闭(self):
        self._写日志(self.今天 - 60, "战斗结果：胜利；星数：2；摧毁率：65%")
        发送 = Mock(return_value=True)
        钟 = 时钟(datetime(2026, 11, 26, 23, 0).timestamp())
        调度 = 每日通知.每日通知调度器(self.数据库, lambda: ["r1"], 发送=发送, 时钟=钟)
        self.assertEqual(调度.检查(强制=True), [])  # 未到 23:30
        钟.值 = self.今天
        self.assertEqual(调度.检查(强制=True), ["r1"])
        self.assertEqual(调度.检查(强制=True), [])  # 今天已发
        _, _, 标题, 正文 = 发送.call_args.args
        self.assertIn("场次 1", 正文)
        # 新调度器（模拟重启）同一天也不重复发
        self.assertEqual(每日通知.每日通知调度器(self.数据库, lambda: ["r1"], 发送=发送, 时钟=钟).检查(), [])

        设置 = 机器人设置(每日完成通知=False)
        self.数据库.保存机器人设置("r2", 设置)
        self.assertEqual(每日通知.每日通知调度器(self.数据库, lambda: ["r2"], 发送=发送, 时钟=钟).检查(), [])

    def test_今天没有内容不弹空通知(self):
        发送 = Mock(return_value=True)
        调度 = 每日通知.每日通知调度器(self.数据库, lambda: ["r1"], 发送=发送, 时钟=时钟(self.今天))
        self.assertEqual(调度.检查(强制=True), [])
        发送.assert_not_called()
        self.assertIsNone(self.数据库.读取系统配置("每日通知已发送:r1"))


class 问题包测试(unittest.TestCase):
    def test_导出内容齐全且去掉账号密钥(self):
        with tempfile.TemporaryDirectory(prefix="coc-bundle-") as 目录:
            根 = Path(目录)
            (根 / "数据库").mkdir()
            数据库 = 任务数据库(str(根 / "数据库" / "任务系统.db"))
            数据库.保存机器人设置("r1", 机器人设置(
                官方API令牌="eyJSECRETTOKEN123456",
                企业微信webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef123456",
                玩家标签="#ABC123",
            ))
            数据库.记录日志("r1", "开始运行任务计划 key=abcdef123456", time.time() + 60)
            数据库.更新状态("r1", "家乡资源", {"金币": 100})
            (根 / "数据库" / "上次日志.bak.jsonl").write_text('{"内容": "上次"}\n', encoding="utf-8")
            (根 / "数据库" / "robot-error.log").write_text("Traceback boom\n", encoding="utf-8")
            异常留证._上次留证.clear()
            现场 = 异常留证.保存异常现场("异常退出", "boom", 机器人标志="r1", 当前图像=图像(), 根目录=根)
            self.assertIsNotNone(现场)

            路径 = 问题包.导出问题包(数据库, 根目录=根)
            self.assertEqual(路径.parent, 根)
            self.assertTrue(路径.name.startswith("问题包_") and 路径.suffix == ".zip")
            self.assertEqual(list(根.glob("*.tmp")), [])
            with zipfile.ZipFile(路径) as 包:
                名称 = set(包.namelist())
                全文 = "".join(
                    包.read(名).decode("utf-8", errors="ignore") for 名 in 名称 if not 名.endswith((".png", ".jpg"))
                )
                配置 = json.loads(包.read("配置.json").decode("utf-8"))
            for 必需 in ("版本.txt", "系统信息.txt", "配置.json", "运行时状态.json",
                       "日志/最近日志.txt", "日志/上次日志.bak.jsonl", "日志/robot-error.log",
                       f"异常现场/{现场.name}/当前.png", f"异常现场/{现场.name}/摘要.txt"):
                self.assertIn(必需, 名称)
            for 秘密 in ("eyJSECRETTOKEN123456", "abcdef123456", "#ABC123"):
                self.assertNotIn(秘密, 全文)
            self.assertEqual(配置["r1"]["官方API令牌"], 问题包.已去除)
            self.assertEqual(配置["r1"]["企业微信webhook"], 问题包.已去除)
            self.assertIn("开始运行任务计划", 全文)

    def test_敏感键判断(self):
        for 键 in ("官方API令牌", "企业微信webhook", "玩家标签", "api_key", "Password"):
            self.assertTrue(问题包.是敏感键(键), 键)
        for 键 in ("金币", "ADB设备序列号", "每日通知时间"):
            self.assertFalse(问题包.是敏感键(键), 键)


if __name__ == "__main__":
    unittest.main()


class 问题包按钮测试(unittest.TestCase):
    def test_侧栏按钮导出后弹窗显示路径(self):
        import os
        import queue

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication
        except ImportError:  # pragma: no cover
            self.skipTest("未安装 PySide6")
        from 应用.控制器 import 应用控制器
        from 界面.主窗口 import 主窗口

        应用 = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as 目录:
            数据库 = 任务数据库(os.path.join(目录, "t.db"))
            池 = {}
            监控中心 = SimpleNamespace(
                机器人池=池, 数据库=数据库,
                创建机器人=lambda 标志, 初始设置=None: 池.__setitem__(标志, SimpleNamespace(
                    机器人标志=标志, 当前状态="已停止", 停止原因="未启动",
                    停止=Mock(), 暂停=Mock(), 继续=Mock())),
                启动机器人=Mock(), 关闭=Mock(), 运行标志=True,
            )
            with patch("界面.主窗口.全局快捷键"):
                窗口 = 主窗口(应用控制器(监控中心), queue.Queue(), "rc-test")
            try:
                包路径 = Path(目录) / "问题包_x.zip"
                with patch("应用.问题包.导出问题包", return_value=包路径) as 导出, \
                        patch("界面.主窗口.后台执行", side_effect=lambda 函数, 成功, 失败: 成功(函数())), \
                        patch("界面.主窗口.提示信息") as 提示:
                    窗口._问题包按钮.click()
                导出.assert_called_once_with(数据库)
                self.assertIn(str(包路径), 提示.call_args.args[2])
                self.assertTrue(窗口._问题包按钮.isEnabled())
            finally:
                窗口._关闭中 = True
                窗口.close()
                QSettings("COCauto", "城控").clear()
                应用.processEvents()
