"""PySide6 界面测试（offscreen 平台，不需要真实桌面）。"""
import os
import queue
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - 未安装 PySide6 的环境
    QApplication = None


@unittest.skipIf(QApplication is None, "未安装 PySide6")
class 主窗口测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.应用 = QApplication.instance() or QApplication([])
        # 测试中任何意外弹窗都会阻塞 offscreen 事件循环；统一改为直接失败。
        cls._弹窗补丁 = [
            mock.patch(f"PySide6.QtWidgets.QMessageBox.{名称}", side_effect=AssertionError(f"意外弹窗 {名称}"))
            for 名称 in ("critical", "information", "question", "warning")
        ]
        for 补丁 in cls._弹窗补丁:
            补丁.start()

    @classmethod
    def tearDownClass(cls):
        for 补丁 in cls._弹窗补丁:
            补丁.stop()

    def setUp(self):
        from PySide6.QtCore import QSettings
        from 数据库.任务数据库 import 任务数据库
        from 应用.控制器 import 应用控制器
        from 界面.主窗口 import 主窗口

        QSettings("COCauto", "城控").clear()
        self.数据库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.池 = {}

        def 创建机器人(机器人标志, 初始设置=None):
            self.池[机器人标志] = SimpleNamespace(
                机器人标志=机器人标志, 当前状态="已停止", 停止原因="未启动",
                停止=mock.Mock(), 暂停=mock.Mock(), 继续=mock.Mock(),
            )

        self.监控中心 = SimpleNamespace(
            机器人池=self.池, 数据库=self.数据库, 创建机器人=创建机器人,
            启动机器人=mock.Mock(), 关闭=mock.Mock(), 运行标志=True,
        )
        self.控制器 = 应用控制器(self.监控中心)
        self.队列 = queue.Queue()
        with mock.patch("界面.主窗口.全局快捷键"):
            self.窗口 = 主窗口(self.控制器, self.队列, "rc-test")
        with mock.patch.object(self.窗口, "_检查更新"), mock.patch("模块.自动启动管理器.自动启动管理器") as 管理器:
            管理器.return_value.获取所有自动启动配置.return_value = {}
            self.窗口.show()
            self.窗口.载入()
        self.应用.processEvents()
        self.实例 = self.池["robot_1"]
        self.运行页 = self.窗口._页面["一键运行"]

    def tearDown(self):
        self.窗口._关闭中 = True
        self.窗口.close()
        from PySide6.QtCore import QSettings
        QSettings("COCauto", "城控").clear()

    def test_只有一个游戏且没有机器人管理入口(self):
        self.assertEqual(list(self.池), ["robot_1"])
        self.assertEqual(list(self.窗口._导航按钮), ["一键运行", "模拟器连接", "手机控制", "自动启动"])
        self.assertFalse(hasattr(self.窗口, "机器人选择"))

    def test_全部页面可打开且主题可切换(self):
        for 名称 in ("一键运行", "模拟器连接", "手机控制", "自动启动"):
            self.窗口.打开页面(名称)
            self.窗口._每秒刷新()
            self.assertEqual(self.窗口._页标题.text(), 名称)
        原 = self.窗口._配色.名称
        self.窗口._切换主题()
        self.assertNotEqual(self.窗口._配色.名称, 原)

    def test_运行控制按钮跟随状态(self):
        self.窗口._刷新运行控制()
        self.assertTrue(self.窗口.主按钮.isEnabled())
        self.assertFalse(self.窗口.暂停按钮.isEnabled())
        self.实例.当前状态 = "运行中"
        self.窗口._刷新运行控制()
        self.assertFalse(self.窗口.主按钮.isEnabled())
        self.assertTrue(self.窗口.暂停按钮.isEnabled() and self.窗口.停止按钮.isEnabled())
        self.实例.当前状态 = "暂停中"
        self.窗口._刷新运行控制()
        self.assertEqual(self.窗口.主按钮.text(), "继续")

    def test_开始前先保存尚未提交的任务设置(self):
        计划 = self.运行页.计划
        计划.任务列表.item(0).setCheckState(Qt.Checked)
        self.assertTrue(计划.有未保存修改)
        self.窗口._主按钮点击()
        self.监控中心.启动机器人.assert_called_once_with("robot_1")
        self.assertTrue(self.数据库.获取机器人设置("robot_1").是否刷主世界)

    def test_非法参数不会保存(self):
        计划 = self.运行页.计划
        计划._编辑器["欲进攻资源建筑靠近地图边缘最小比例"].setText("5")
        self.assertFalse(计划.保存())
        self.assertIn("未保存", 计划.状态.text())
        self.assertNotEqual(
            self.数据库.获取机器人设置("robot_1").欲进攻资源建筑靠近地图边缘最小比例, 5,
        )

    def test_官方账号数据页可填写保存且令牌遮挡(self):
        from PySide6.QtWidgets import QLineEdit
        计划 = self.运行页.计划
        for 行 in range(计划.选项列表.count()):
            if 计划.选项列表.item(行).data(Qt.UserRole + 1) == "official_api":
                计划.选项列表.setCurrentRow(行)
                break
        self.应用.processEvents()
        self.assertEqual(计划.参数标题.text(), "官方账号数据")
        令牌框 = 计划._编辑器["官方API令牌"]
        self.assertEqual(令牌框.echoMode(), QLineEdit.Password)
        令牌框.setText("测试令牌")
        计划._编辑器["玩家标签"].setText("#ABC123")
        计划._编辑器["官方数据同步间隔分钟"].setText("60")
        self.assertTrue(计划.保存())
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual((设置.官方API令牌, 设置.玩家标签, 设置.官方数据同步间隔分钟),
                         ("测试令牌", "#ABC123", 60))
        截图路径 = os.environ.get("COC_UI_SNAPSHOT")
        if 截图路径:
            self.窗口.resize(1280, 800)
            self.应用.processEvents()
            self.窗口.grab().save(截图路径)

    def test_兵种选择页勾选可保存(self):
        计划 = self.运行页.计划
        for 行 in range(计划.选项列表.count()):
            if 计划.选项列表.item(行).data(Qt.UserRole + 1) == "troop_selection":
                计划.选项列表.setCurrentRow(行)
                break
        self.应用.processEvents()
        兵种框 = 计划._编辑器["配兵兵种"].勾选框
        self.assertIn("超级哥布林", 兵种框)
        self.assertEqual(兵种框["超级哥布林"].text(), "隐秘哥布林（超级兵种）")
        self.assertIn("资源", 兵种框["超级哥布林"].toolTip())
        计划._编辑器["是否自动配置军队"].setChecked(True)
        兵种框["超级野蛮人"].setChecked(True)
        兵种框["超级哥布林"].setChecked(True)
        self.assertTrue(计划.保存())
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertTrue(设置.是否自动配置军队)
        self.assertEqual(设置.配兵兵种, ["超级哥布林", "超级野蛮人"])
        截图路径 = os.environ.get("COC_UI_SNAPSHOT")
        if 截图路径:
            self.窗口.resize(1280, 860)
            self.应用.processEvents()
            self.窗口.grab().save(截图路径)

    def test_调整顺序与全选会保存(self):
        计划 = self.运行页.计划
        计划.任务列表.setCurrentRow(2)
        计划._移动(-1)
        计划.保存()
        self.assertEqual(self.数据库.获取机器人设置("robot_1").任务计划顺序[1], "wall")
        计划._全部勾选(True)
        计划.保存()
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertTrue(设置.是否刷主世界 and 设置.开启刷墙)

    def test_悬浮窗隐藏主界面并在关闭后恢复(self):
        self.窗口.切换悬浮窗()
        悬浮 = self.窗口._悬浮窗
        self.assertIsNotNone(悬浮)
        悬浮.刷新()
        self.窗口._隐藏到悬浮窗()
        self.assertFalse(self.窗口.isVisible())
        self.assertTrue(悬浮.isVisible())
        悬浮.close()
        self.assertIsNone(self.窗口._悬浮窗)
        self.assertTrue(self.窗口.isVisible())

    def test_实时日志显示在运行页(self):
        self.队列.put({"内容": "[10:00:00] 进攻完成：2 星", "机器人ID": "robot_1", "记录时间": 1e9})
        self.窗口._消费日志()
        self.窗口.打开页面("一键运行")
        self.assertIn("进攻完成", self.运行页.视图.toPlainText())

    def test_热键只在合法状态下动作(self):
        self.实例.当前状态 = "运行中"
        self.窗口._处理热键("F1")
        self.监控中心.启动机器人.assert_not_called()
        self.窗口._处理热键("F2")
        self.实例.暂停.assert_called_once()

    def test_停止按钮传递明确原因(self):
        with mock.patch("应用.控制器.threading.Thread") as 线程:
            self.窗口._停止()
        self.assertEqual(线程.call_args.kwargs["args"], ("界面停止按钮",))

    def test_更新检查在后台执行(self):
        with mock.patch("界面.主窗口.后台执行") as 后台:
            self.窗口._检查更新(手动=False)
        后台.assert_called_once()
        self.assertFalse(self.窗口._更新按钮.isEnabled())


if __name__ == "__main__":
    unittest.main()
