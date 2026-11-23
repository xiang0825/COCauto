import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from 任务流程.启动模拟器 import 启动模拟器任务
from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务


class 启动模拟器状态测试(unittest.TestCase):
    def _上下文(self, 设备):
        日志 = []
        设置 = SimpleNamespace(部落冲突包名="com.supercell.clashofclans")
        上下文 = SimpleNamespace(
            机器人标志="robot_test",
            数据库=SimpleNamespace(获取机器人设置=Mock(return_value=设置)),
            设备=设备,
            置脚本状态=lambda 文本, *_参数, **_关键字: 日志.append(文本),
            脚本延时=Mock(),
        )
        return 上下文, 日志

    def test_已在前台运行时复用现有游戏实例(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.return_value = "com.supercell.clashofclans"
        上下文, 日志 = self._上下文(设备)

        self.assertTrue(启动模拟器任务(上下文).执行())
        设备.打开应用.assert_not_called()
        self.assertTrue(any("直接接管" in 文本 for 文本 in 日志))
        上下文.脚本延时.assert_not_called()

    def test_启动后等待前台确认而不是立即误判未开启(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.side_effect = ["app.lawnchair", "app.lawnchair", "com.supercell.clashofclans"]
        设备.执行.return_value = b"package:com.supercell.clashofclans\n"
        上下文, 日志 = self._上下文(设备)

        self.assertTrue(启动模拟器任务(上下文).执行())
        设备.打开应用.assert_called_once_with("com.supercell.clashofclans")
        self.assertEqual(上下文.脚本延时.call_count, 1)
        self.assertTrue(any("正在启动部落冲突" in 文本 for 文本 in 日志))

    def test_未安装游戏时不尝试启动(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.return_value = "app.lawnchair"
        设备.执行.return_value = b""
        上下文, 日志 = self._上下文(设备)
        self.assertFalse(启动模拟器任务(上下文).执行())
        设备.打开应用.assert_not_called()
        self.assertTrue(any("没有安装" in 文本 for 文本 in 日志))

    def test_关闭自动启动时不打开游戏(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.return_value = "app.lawnchair"
        上下文, 日志 = self._上下文(设备)
        上下文.数据库.获取机器人设置.return_value.自动启动游戏 = False
        self.assertFalse(启动模拟器任务(上下文).执行())
        设备.打开应用.assert_not_called()

    def test_一直未进入前台时安全停止(self):
        设备 = Mock()
        设备.是否已启动.return_value = True
        设备.获取当前前台包名.return_value = "app.lawnchair"
        设备.执行.return_value = b"package:com.supercell.clashofclans\n"
        上下文, 日志 = self._上下文(设备)
        with patch.object(启动模拟器任务, "前台等待秒", 3):
            self.assertFalse(启动模拟器任务(上下文).执行())
        self.assertTrue(any("仍未进入前台" in 文本 for 文本 in 日志))


class 启动残留英雄详情测试(unittest.TestCase):
    def test_启动时英雄详情安全关闭后才继续(self):
        上下文 = SimpleNamespace(
            _当前画面是英雄升级详情=Mock(return_value=True),
            关闭意外英雄升级详情弹窗=Mock(return_value=True),
            置脚本状态=Mock(),
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文

        self.assertTrue(任务._启动阶段处理英雄升级详情(None))
        上下文.关闭意外英雄升级详情弹窗.assert_called_once_with(None)
        self.assertFalse(hasattr(上下文, "_启动时英雄升级详情"))
        self.assertTrue(any(
            "不执行未选中的英雄升级任务" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_启动时英雄详情未能确认回主页则停止(self):
        停止事件 = Mock()
        上下文 = SimpleNamespace(
            _当前画面是英雄升级详情=Mock(return_value=True),
            关闭意外英雄升级详情弹窗=Mock(return_value=False),
            置脚本状态=Mock(),
            停止事件=停止事件,
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文

        self.assertTrue(任务._启动阶段处理英雄升级详情(None))
        self.assertTrue(上下文.页面恢复失败)
        停止事件.set.assert_called_once_with()

    def test_启动时没有英雄详情不会登记(self):
        上下文 = SimpleNamespace(
            _当前画面是英雄升级详情=Mock(return_value=False),
            置脚本状态=Mock(),
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文

        self.assertFalse(任务._启动阶段处理英雄升级详情(None))
        self.assertFalse(hasattr(上下文, "页面恢复失败"))


class 启动残留研究目标页测试(unittest.TestCase):
    def test_启动时研究目标页交给研究页安全收尾器(self):
        上下文 = SimpleNamespace(
            获取OCR引擎=Mock(return_value=object()),
            置脚本状态=Mock(),
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文

        清理任务 = SimpleNamespace(
            _研究面板已确认=Mock(return_value=True),
            _清理残留研究面板=Mock(return_value=True),
        )
        class 假研究任务:
            def __new__(cls):
                return 清理任务

        with patch(
            "任务流程.兵种或法术升级.打开研究面板.打开研究面板任务",
            new=假研究任务,
        ):
            self.assertTrue(任务._启动阶段处理研究目标页(None))

        清理任务._研究面板已确认.assert_called_once_with()
        清理任务._清理残留研究面板.assert_called_once_with()
        self.assertTrue(any(
            "残留研究目标页" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_启动时研究目标页清理失败会停止输入(self):
        停止事件 = Mock()
        上下文 = SimpleNamespace(
            获取OCR引擎=Mock(return_value=object()),
            置脚本状态=Mock(),
            停止事件=停止事件,
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文

        清理任务 = SimpleNamespace(
            _研究面板已确认=Mock(return_value=True),
            _清理残留研究面板=Mock(return_value=False),
        )
        class 假研究任务:
            def __new__(cls):
                return 清理任务

        with patch(
            "任务流程.兵种或法术升级.打开研究面板.打开研究面板任务",
            new=假研究任务,
        ):

            self.assertTrue(任务._启动阶段处理研究目标页(None))

        self.assertTrue(上下文.页面恢复失败)
        停止事件.set.assert_called_once_with()


class 首次启动稳定性复核测试(unittest.TestCase):
    包名 = "com.supercell.clashofclans"

    def _建立任务(self, *, 前台接口=True):
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        设备 = SimpleNamespace()
        if 前台接口:
            设备.获取当前前台包名 = Mock(return_value=self.包名)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                设备=设备,
                获取屏幕图像cv=Mock(return_value=屏幕),
            ),
            设置=SimpleNamespace(部落冲突包名=self.包名),
            停止事件=threading.Event(),
            页面恢复失败=False,
            置脚本状态=Mock(),
            脚本延时=Mock(),
        )
        任务 = 检测游戏登录状态任务.__new__(检测游戏登录状态任务)
        任务.上下文 = 上下文
        return 任务, 上下文, 屏幕

    def test_缺少前台核验接口不能放行首次缩放(self):
        任务, 上下文, _屏幕 = self._建立任务(前台接口=False)

        self.assertFalse(任务._确认首次启动稳定())
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(上下文.停止事件.is_set())

    def test_稳定观察期间出现断线页立即失败不放行手势(self):
        任务, 上下文, 屏幕 = self._建立任务()
        页面识别 = Mock()
        页面识别.识别.side_effect = [
            SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.82),
            SimpleNamespace(页面="断线弹窗", 世界=None, 可信度=0.98),
        ]

        with patch(
            "任务流程.检测游戏登录状态.time.monotonic",
            side_effect=[0.0, 0.0, 2.0],
        ):
            self.assertFalse(任务._确认首次启动稳定(页面识别))

        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(上下文.停止事件.is_set())
        self.assertEqual(页面识别.识别.call_count, 2)
        上下文.op.获取屏幕图像cv.assert_called()

    def test_持续确认主世界主页才通过稳定观察(self):
        任务, 上下文, _屏幕 = self._建立任务()
        页面识别 = Mock()
        页面识别.识别.return_value = SimpleNamespace(
            页面="主世界主页", 世界="主世界", 可信度=0.82
        )

        with patch(
            "任务流程.检测游戏登录状态.time.monotonic",
            side_effect=[0.0, 0.0, 12.0],
        ):
            self.assertTrue(任务._确认首次启动稳定(页面识别))

        self.assertFalse(上下文.页面恢复失败)
        self.assertFalse(上下文.停止事件.is_set())
        self.assertGreaterEqual(页面识别.识别.call_count, 2)


if __name__ == "__main__":
    unittest.main()
