"""桌面通知：节流、恢复、设置开关、各触发点接线（rc147）。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from 工具包 import 桌面通知 as 模块
from 工具包.桌面通知 import 桌面通知器, 机器人桌面通知, 机器人桌面恢复


class _时钟:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _新通知器():
    记录 = []
    时钟 = _时钟()
    通知器 = 桌面通知器(弹出=lambda 标题, 正文, 级别="警告": 记录.append((标题, 正文, 级别)) or True,
                   时钟=时钟)
    return 通知器, 记录, 时钟


class 节流与恢复测试(unittest.TestCase):
    def test_同一原因十分钟内只弹一次(self):
        通知器, 记录, 时钟 = _新通知器()
        self.assertTrue(通知器.通知("r1:待命", "待命", "a"))
        时钟.t += 300
        self.assertFalse(通知器.通知("r1:待命", "待命", "b"))
        时钟.t += 301
        self.assertTrue(通知器.通知("r1:待命", "待命", "c"))
        self.assertEqual([项[1] for 项 in 记录], ["a", "c"])

    def test_不同原因互不节流(self):
        通知器, 记录, _ = _新通知器()
        通知器.通知("r1:待命", "待命", "a")
        通知器.通知("r1:内存保护", "内存", "b")
        self.assertEqual(len(记录), 2)

    def test_恢复只对弹过的问题发一次且清除节流(self):
        通知器, 记录, 时钟 = _新通知器()
        self.assertFalse(通知器.恢复("r1:待命"))
        通知器.通知("r1:待命", "安全待命超时", "a")
        self.assertTrue(通知器.恢复("r1:待命", "回到主世界"))
        self.assertEqual(记录[-1], ("已恢复：安全待命超时", "回到主世界", "恢复"))
        self.assertFalse(通知器.恢复("r1:待命"))
        时钟.t += 5  # 恢复后同一问题再出现要立即提醒
        self.assertTrue(通知器.通知("r1:待命", "安全待命超时", "again"))

    def test_信息类通知不触发恢复(self):
        通知器, 记录, _ = _新通知器()
        通知器.通知("r1:x", "完成", "a", 需要恢复通知=False, 级别="信息")
        self.assertFalse(通知器.恢复("r1:x"))
        self.assertEqual(记录[0][2], "信息")


class 设置开关测试(unittest.TestCase):
    def setUp(self):
        self.通知器, self.记录, _ = _新通知器()
        补丁 = patch.object(模块, "获取桌面通知器", return_value=self.通知器)
        补丁.start()
        self.addCleanup(补丁.stop)

    def test_关闭开关不弹(self):
        self.assertFalse(机器人桌面通知(SimpleNamespace(桌面通知=False), "robot_1", "停止", "脚本已停止"))
        self.assertEqual(self.记录, [])

    def test_默认开启并带机器人标志(self):
        self.assertTrue(机器人桌面通知(SimpleNamespace(), "robot_1", "停止", "脚本已停止", "无心跳"))
        self.assertEqual(self.记录[0][0], "robot_1｜脚本已停止")
        self.assertTrue(机器人桌面恢复("robot_1", "停止"))

    def test_默认设置字段为开启(self):
        from 数据库.任务数据库 import 机器人设置

        self.assertTrue(机器人设置().桌面通知)

    def test_设置页有桌面通知开关(self):
        from 应用.任务计划 import 任务参数表

        self.assertIn("桌面通知", [字段.字段 for 字段 in 任务参数表["notification"].字段])


class 弹出实现测试(unittest.TestCase):
    def test_标题正文走环境变量且不阻塞(self):
        with patch.object(模块.sys, "platform", "win32"), patch.object(模块.subprocess, "Popen") as 进程:
            self.assertTrue(模块.弹出Windows通知("标题'; rm -rf", "正文$(x)"))
        参数, 关键字 = 进程.call_args
        命令 = 参数[0]
        self.assertEqual(命令[0], "powershell.exe")
        self.assertNotIn("rm -rf", " ".join(命令))
        self.assertEqual(关键字["env"]["COC_TOAST_TITLE"], "标题'; rm -rf")
        self.assertEqual(关键字["env"]["COC_TOAST_BODY"], "正文$(x)")
        self.assertTrue(关键字["creationflags"])

    def test_启动失败返回False不抛异常(self):
        with patch.object(模块.sys, "platform", "win32"), patch.object(模块.subprocess, "Popen", side_effect=OSError):
            self.assertFalse(模块.弹出Windows通知("a", "b"))


class 触发点接线测试(unittest.TestCase):
    def test_人工停止不弹_异常退出弹错误(self):
        from 线程 import 自动化机器人 as 线程模块

        with patch("工具包.桌面通知.机器人桌面通知") as 通知:
            机器人 = 线程模块.自动化机器人.__new__(线程模块.自动化机器人)
            机器人.机器人标志 = "robot_1"
            with patch.object(线程模块.自动化机器人, "设置", SimpleNamespace(桌面通知=True), create=True):
                机器人.停止原因 = "界面停止按钮"
                机器人._桌面通知线程停止()
                通知.assert_not_called()
                机器人.停止原因 = "未处理异常：boom"
                机器人._桌面通知线程停止()
                self.assertEqual(通知.call_args[0][2], "线程异常")
                self.assertEqual(通知.call_args[1]["级别"], "错误")
                机器人.停止原因 = "无心跳"
                机器人._桌面通知线程停止()
                self.assertEqual(通知.call_args[0][2:4], ("停止", "脚本已停止"))

    def test_搜敌上限触发桌面通知(self):
        from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务 as 搜索敌人任务

        调用 = []
        上下文 = SimpleNamespace(置脚本状态=lambda *a, **k: None,
                             发送桌面通知=lambda *a, **k: 调用.append(a))
        搜索敌人任务._触发搜索安全退出(上下文, "已达最大搜索次数上限（150次）")
        self.assertEqual(调用[0][0], "搜敌上限")

    def test_内存保护触发与恢复(self):
        from 任务流程.基础任务框架 import 任务上下文

        调用 = []
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.发送桌面通知 = lambda *a, **k: 调用.append(("通知",) + a)
        上下文.桌面通知已恢复 = lambda *a, **k: 调用.append(("恢复",) + a)
        上下文.释放识别模型 = lambda: None
        上下文.置脚本状态 = lambda *a, **k: None
        上下文.停止事件 = SimpleNamespace(set=lambda: None)
        上下文.内存保护标志 = None
        上下文._内存保护已触发 = False
        上下文.触发内存保护("截图", "主机内存保护已触发：提交额度不足")
        self.assertEqual(调用[0][:2], ("通知", "内存保护"))
        上下文.是否可自动恢复主机内存保护 = lambda: True
        上下文.清除主机内存保护()
        self.assertEqual(调用[-1][:2], ("恢复", "内存保护"))


if __name__ == "__main__":
    unittest.main()
