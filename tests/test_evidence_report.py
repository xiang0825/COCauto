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


def 同步保存(*参数, **关键字):
    """测试用：入队后等后台写完，返回实际目录（未写返回 None）。"""
    结果 = []
    已入队 = 异常留证.保存异常现场(*参数, 完成回调=结果.append, **关键字)
    异常留证.等待后台空闲()
    return 结果[0] if (已入队 and 结果) else None


def 记录并等待(缓存, 标志, 帧):
    已入队 = 缓存.记录(标志, 帧)
    异常留证.等待后台空闲()
    return 已入队


class 异常留证测试(unittest.TestCase):
    def setUp(self):
        self._临时 = tempfile.TemporaryDirectory(prefix="coc-evidence-")
        self.根 = Path(self._临时.name)
        异常留证._上次留证.clear()

    def tearDown(self):
        异常留证.等待后台空闲()
        self._临时.cleanup()

    def test_保存当前截图前序帧和摘要(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(帧数=3, 最短间隔秒=1.0, 时钟=钟)
        for 序号 in range(5):
            钟.值 += 2
            self.assertTrue(记录并等待(缓存, "r1", 图像(序号 * 10)))
        路径 = 同步保存(
            "心跳超时", "数据库最后日志记录已超时", 机器人标志="r1",
            当前图像=图像(200), 日志摘要=lambda: ["11-26 10:00:00 开始搜索"],
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
        self.assertTrue(记录并等待(缓存, "r1", 图像()))
        钟.值 += 0.5
        self.assertFalse(记录并等待(缓存, "r1", 图像()))
        钟.值 += 1.5
        self.assertTrue(记录并等待(缓存, "r1", 图像()))
        self.assertEqual(len(缓存.取出("r1")), 2)
        self.assertFalse(缓存.记录("r1", None))

    def test_截图路径只入队不同步编码(self):
        放行 = threading.Event()
        队列 = 异常留证.有界后台队列("测试-帧编码", 3)
        队列.提交(lambda: 放行.wait(5))  # 先堵住后台线程
        缓存 = 异常留证.近期帧缓存(时钟=时钟(), 编码队列=队列)
        开始 = time.monotonic()
        self.assertTrue(缓存.记录("r1", 图像()))
        self.assertLess(time.monotonic() - 开始, 0.2)
        self.assertEqual(缓存.取出("r1"), [])  # 还没编码：截图线程里没做编码
        放行.set()
        self.assertTrue(队列.等待空闲(5))
        self.assertEqual(len(缓存.取出("r1")), 1)

    def test_有界队列满了丢弃最旧任务且提交不阻塞(self):
        放行 = threading.Event()
        已开始 = threading.Event()
        已执行 = []
        队列 = 异常留证.有界后台队列("测试-有界", 2)
        队列.提交(lambda: (已开始.set(), 放行.wait(5)))
        self.assertTrue(已开始.wait(5))
        开始 = time.monotonic()
        for 序号 in range(4):
            队列.提交(lambda 序号=序号: 已执行.append(序号))
        self.assertLess(time.monotonic() - 开始, 0.2)
        放行.set()
        self.assertTrue(队列.等待空闲(5))
        self.assertEqual(已执行, [2, 3])
        self.assertEqual(队列.丢弃数, 2)

    def test_留证调用不等读库编码写盘(self):
        放行 = threading.Event()
        队列 = 异常留证.有界后台队列("测试-写盘", 4)
        结果 = []

        def 慢摘要():
            放行.wait(5)  # 模拟读库卡住
            return ["慢查询"]

        开始 = time.monotonic()
        已入队 = 异常留证.保存异常现场(
            "心跳超时", "卡住", 机器人标志="r1", 当前图像=图像(9),
            日志摘要=慢摘要, 根目录=self.根, 帧缓存=异常留证.近期帧缓存(),
            写盘队列=队列, 完成回调=结果.append,
        )
        self.assertTrue(已入队)
        self.assertLess(time.monotonic() - 开始, 0.2)
        self.assertEqual(异常留证.列出留证目录(self.根), [])
        放行.set()
        self.assertTrue(队列.等待空闲(5))
        self.assertEqual(len(结果), 1)
        self.assertTrue((结果[0] / "当前.png").is_file())

    def test_无当前截图时用最近缓存帧(self):
        钟 = 时钟()
        缓存 = 异常留证.近期帧缓存(时钟=钟)
        记录并等待(缓存, "r1", 图像(5))
        路径 = 同步保存(
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
            路径列表.append(同步保存(
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
        self.assertIsNotNone(同步保存("未知页面待命", "a", **参数))
        钟.值 += 10
        self.assertIsNone(同步保存("未知页面待命", "b", **参数))
        self.assertIsNotNone(同步保存("异常退出", "c", **参数))
        钟.值 += 100
        self.assertIsNone(同步保存("心跳超时", "d", 保留份数=0, **参数))
        self.assertIsNone(同步保存("其它", "e", 保留份数=lambda: 0, **参数))
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

    def _真实留证机器人(self, 数据库):
        from 线程.自动化机器人 import 自动化机器人

        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "r1"
        机器人.数据库 = 数据库
        机器人.op = SimpleNamespace(_原始截图缓存=图像(3))
        机器人.记录日志 = Mock()
        异常留证._上次留证.clear()
        return 机器人

    def test_保存异常现场写带路径的日志(self):
        with tempfile.TemporaryDirectory() as 目录:
            数据库 = Mock()
            数据库.文件路径 = 任务数据库.默认数据库路径()
            数据库.获取机器人设置.return_value = SimpleNamespace(异常现场保留份数=30)
            数据库.查询日志历史.return_value = []
            机器人 = self._真实留证机器人(数据库)
            with patch.object(异常留证, "程序目录", return_value=Path(目录)):
                self.assertTrue(机器人.保存异常现场("心跳超时", "超时"))
                异常留证.等待后台空闲()
            目录列表 = 异常留证.列出留证目录(Path(目录))
            self.assertEqual(len(目录列表), 1)
            self.assertTrue((目录列表[0] / "当前.png").is_file())
            self.assertIn(str(目录列表[0]), 机器人.记录日志.call_args.args[0])

    def test_心跳停止路径不等读库写盘(self):
        放行 = threading.Event()

        def 慢设置(*_):
            放行.wait(5)
            return SimpleNamespace(异常现场保留份数=30)

        with tempfile.TemporaryDirectory() as 目录:
            数据库 = Mock()
            数据库.文件路径 = 任务数据库.默认数据库路径()
            数据库.获取机器人设置.side_effect = 慢设置
            数据库.查询日志历史.return_value = []
            机器人 = self._真实留证机器人(数据库)
            with patch.object(异常留证, "程序目录", return_value=Path(目录)):
                开始 = time.monotonic()
                self.assertTrue(机器人.保存异常现场("心跳超时", "超时"))
                self.assertLess(time.monotonic() - 开始, 0.2)
                机器人.记录日志.assert_not_called()
                放行.set()
                异常留证.等待后台空闲()
            self.assertEqual(len(异常留证.列出留证目录(Path(目录))), 1)

    def test_测试或临时数据库不往程序目录留证(self):
        with tempfile.TemporaryDirectory() as 目录:
            数据库 = SimpleNamespace(文件路径=str(Path(目录) / "x.db"))
            机器人 = self._真实留证机器人(数据库)
            with patch.object(异常留证, "程序目录", return_value=Path(目录)):
                机器人.保存异常现场("异常退出", "boom")
                异常留证.等待后台空闲()
            self.assertEqual(异常留证.列出留证目录(Path(目录)), [])
            机器人.记录日志.assert_not_called()

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
    玩家名 = "风之谷的小明"
    玩家标签 = "#ABC123"
    部落名 = "雷霆王者CHN"
    部落标签 = "#2PQRLYUV"
    序列号 = "127.0.0.1:16384"

    def _准备(self, 根: Path):
        (根 / "数据库").mkdir()
        数据库 = 任务数据库(str(根 / "数据库" / "任务系统.db"))
        数据库.保存机器人设置("r1", 机器人设置(
            官方API令牌="eyJSECRETTOKEN123456",
            企业微信webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef123456",
            玩家标签=self.玩家标签,
            ADB设备序列号=self.序列号,
            ADB路径=r"C:\Users\zhangsan\AppData\Local\MuMu\adb.exe",
        ))
        现在 = time.time() + 60
        for 内容 in (
            "开始运行任务计划 key=abcdef123456",
            f"官方数据：{self.玩家名}（{self.玩家标签}）大本营16",
            f"部落：{self.部落名}（{self.部落标签}）同盟会",
            f"ADB 自动绑定模拟器：{self.序列号}；emulator-5556 备用",
            "公网 IP 203.0.113.45 变化，需重新创建 Key",
            r"截图保存到 C:\Users\zhangsan\Desktop\x.png",
            "部落竞赛：个人积分 3350/10000",
        ):
            数据库.记录日志("r1", 内容, 现在)
        数据库.更新状态("r1", "家乡资源", {"金币": 100})
        数据库.更新状态("r1", "官方账号数据", {
            "标签": self.玩家标签, "名字": self.玩家名, "大本营": 16,
            "部落": {"名字": self.部落名, "标签": self.部落标签},
        })
        (根 / "数据库" / "上次日志.bak.jsonl").write_text(
            json.dumps({"内容": f"上次 {self.玩家名} {self.部落名}"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (根 / "数据库" / "robot-error.log").write_text(
            f'Traceback File "C:\\Users\\zhangsan\\coc\\x.py" {self.玩家标签}\n', encoding="utf-8"
        )
        异常留证._上次留证.clear()
        结果 = []
        异常留证.保存异常现场(
            "异常退出", f"boom {self.玩家名}", 机器人标志="r1", 当前图像=图像(), 根目录=根,
            完成回调=结果.append,
        )
        异常留证.等待后台空闲()
        return 数据库, 结果[0]

    def _读包(self, 路径):
        with zipfile.ZipFile(路径) as 包:
            名称 = set(包.namelist())
            全文 = "".join(
                包.read(名).decode("utf-8", errors="ignore")
                for 名 in 名称 if not 名.endswith((".png", ".jpg"))
            )
            配置 = json.loads(包.read("配置.json").decode("utf-8"))
            状态 = json.loads(包.read("运行时状态.json").decode("utf-8"))
        return 名称, 全文, 配置, 状态

    def test_导出内容齐全且不含个人信息(self):
        with tempfile.TemporaryDirectory(prefix="coc-bundle-") as 目录:
            根 = Path(目录)
            数据库, 现场 = self._准备(根)
            with patch.dict("os.environ", {"USERNAME": "zhangsan", "COMPUTERNAME": "ZS-PC"}):
                路径 = 问题包.导出问题包(数据库, 根目录=根)
            self.assertEqual(路径.parent, 根)
            self.assertTrue(路径.name.startswith("问题包_") and 路径.suffix == ".zip")
            self.assertEqual(list(根.glob("*.tmp")), [])
            名称, 全文, 配置, 状态 = self._读包(路径)
            for 必需 in ("版本.txt", "系统信息.txt", "配置.json", "运行时状态.json",
                       "日志/最近日志.txt", "日志/上次日志.bak.jsonl", "日志/robot-error.log",
                       f"异常现场/{现场.name}/摘要.txt", "说明.txt"):
                self.assertIn(必需, 名称)
            # 截图默认不带（画面里可能有玩家名）
            self.assertNotIn(f"异常现场/{现场.name}/当前.png", 名称)
            for 个人信息 in (
                "eyJSECRETTOKEN123456", "abcdef123456", self.玩家名, self.玩家标签,
                self.部落名, self.部落标签, self.序列号, "127.0.0.1", "emulator-5556",
                "203.0.113.45", "zhangsan", "ZS-PC",
            ):
                self.assertNotIn(个人信息, 全文, 个人信息)
            self.assertEqual(配置["r1"]["官方API令牌"], 问题包.已去除)
            self.assertEqual(配置["r1"]["企业微信webhook"], 问题包.已去除)
            self.assertEqual(配置["r1"]["ADB设备序列号"], 问题包.已去除)
            # 排查需要的内容仍在
            self.assertIn("开始运行任务计划", 全文)
            self.assertIn("个人积分 3350/10000", 全文)
            self.assertEqual(状态["r1"]["家乡资源"], {"金币": 100})
            self.assertNotIn("官方账号数据", [键 for 键 in 状态["r1"] if not 键.startswith("_")])
            self.assertIn("官方账号数据", 状态["r1"]["_未导出的状态类型"])

    def test_用户确认后才附带截图(self):
        with tempfile.TemporaryDirectory(prefix="coc-bundle-") as 目录:
            根 = Path(目录)
            数据库, 现场 = self._准备(根)
            路径 = 问题包.导出问题包(数据库, 根目录=根, 包含截图=True)
            名称, _, _, _ = self._读包(路径)
            self.assertIn(f"异常现场/{现场.name}/当前.png", 名称)

    def test_敏感键判断(self):
        for 键 in ("官方API令牌", "企业微信webhook", "玩家标签", "api_key", "Password", "ADB设备序列号", "名字"):
            self.assertTrue(问题包.是敏感键(键), 键)
        for 键 in ("金币", "每日通知时间", "部落竞赛检查记录", "家乡资源"):
            self.assertFalse(问题包.是敏感键(键), 键)


class 问题包按钮测试(unittest.TestCase):
    def test_高级设置按钮导出后弹窗显示路径(self):
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
                self.assertFalse(hasattr(窗口, "_问题包按钮"))  # 入口在高级设置，不在主窗口侧栏
                窗口.打开高级设置("adv_general")
                for 选择 in (False, True):
                    with self.subTest(包含截图=选择), \
                            patch("应用.问题包.导出问题包", return_value=包路径) as 导出, \
                            patch("界面.高级设置.确认", return_value=选择), \
                            patch("界面.高级设置.后台执行", side_effect=lambda 函数, 成功, 失败: 成功(函数())), \
                            patch("界面.高级设置.提示信息") as 提示:
                        高级 = 窗口._高级设置
                        高级.问题包按钮.click()
                        导出.assert_called_once_with(数据库, 包含截图=选择)
                        self.assertIn(str(包路径), 提示.call_args.args[2])
                        self.assertTrue(高级.问题包按钮.isEnabled())
            finally:
                窗口._关闭中 = True
                窗口.close()
                QSettings("COCauto", "城控").clear()
                应用.processEvents()


class 每日通知不阻塞监控测试(unittest.TestCase):
    def test_监控循环里只启动后台检查(self):
        from 主入口 import 机器人监控中心

        中心 = 机器人监控中心.__new__(机器人监控中心)
        放行 = threading.Event()
        已开始 = threading.Event()

        def 慢检查():
            已开始.set()
            放行.wait(5)

        中心._执行每日通知检查 = 慢检查
        开始 = time.monotonic()
        中心._检查每日通知()
        self.assertLess(time.monotonic() - 开始, 0.2)
        self.assertTrue(已开始.wait(5))
        第一个线程 = 中心._每日通知线程
        中心._每日通知上次启动 = -1e9  # 间隔已到，但上一次还在跑：不重复启动
        中心._检查每日通知()
        self.assertIs(中心._每日通知线程, 第一个线程)
        放行.set()
        第一个线程.join(5)


if __name__ == "__main__":
    unittest.main()
