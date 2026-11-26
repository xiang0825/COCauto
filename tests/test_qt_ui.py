"""PySide6 界面测试（offscreen 平台，不需要真实桌面）。"""
import os
import queue
import tempfile
import time
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

        # 界面偏好写到临时 ini，不碰本机真实的“城控”设置（主题、窗口尺寸）。
        界面设置路径 = os.path.join(tempfile.mkdtemp(), "ui.ini")
        self._设置补丁 = mock.patch(
            "界面.主窗口.界面设置", lambda: QSettings(界面设置路径, QSettings.IniFormat),
        )
        self._设置补丁.start()
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
        with mock.patch.object(self.窗口, "_检查更新"):
            self.窗口.show()
            self.窗口.载入()
        self.应用.processEvents()
        self.实例 = self.池["robot_1"]
        self.运行页 = self.窗口.运行页

    def tearDown(self):
        self.窗口._关闭中 = True
        if self.窗口._高级设置 is not None:
            self.窗口._高级设置.close()
        self.窗口.close()
        self._设置补丁.stop()
        self.应用.setQuitOnLastWindowClosed(True)

    def _打开高级页(self, 键):
        with mock.patch.object(self.窗口, "_检查更新"):
            self.窗口.打开高级设置(键)
        self.应用.processEvents()
        return self.窗口._高级设置

    # ------------------------------------------------------------ 结构
    def test_只有一个游戏且单屏没有导航页(self):
        self.assertEqual(list(self.池), ["robot_1"])
        self.assertFalse(hasattr(self.窗口, "机器人选择"))
        self.assertFalse(hasattr(self.窗口, "_导航按钮"))
        self.assertEqual(self.窗口.minimumWidth(), 800)
        # 手机控制、自动启动已取消：主界面和高级设置都没有入口。
        设置窗 = self._打开高级页("connection")
        导航 = [设置窗.导航.item(行).text() for 行 in range(设置窗.导航.count())]
        self.assertNotIn("手机控制", 导航)
        self.assertNotIn("自动启动", 导航)
        self.assertEqual(导航[0], "模拟器连接")

    def test_主题可切换(self):
        原 = self.窗口._配色.名称
        self.窗口._切换主题()
        self.窗口._每秒刷新()
        self.assertNotEqual(self.窗口._配色.名称, 原)

    def test_任务列表八项全部可见(self):
        """旧版通用设置列表把任务列表挤到只剩 3 行；现在 800×540 下 8 项都要露出来。"""
        self.窗口.resize(800, 540)
        self.应用.processEvents()
        列表 = self.运行页.计划.任务列表
        from 数据库.任务数据库 import 任务计划定义列表

        self.assertEqual(列表.count(), len(任务计划定义列表))
        视口 = 列表.viewport().rect()
        for 行 in range(列表.count()):
            区域 = 列表.visualItemRect(列表.item(行))
            self.assertTrue(视口.contains(区域), f"第 {行 + 1} 项被遮住：{区域} 不在 {视口}")

    def test_兵种多选在高级设置里不重叠(self):
        设置窗 = self._打开高级页("adv_combat")
        设置窗.resize(900, 640)
        self.应用.processEvents()
        框 = list(设置窗.页面["adv_combat"].表单.编辑器["配兵兵种"].勾选框.values())
        区域 = [项.geometry() for 项 in 框]
        for 甲 in range(len(区域)):
            for 乙 in range(甲 + 1, len(区域)):
                self.assertFalse(区域[甲].intersects(区域[乙]), f"{框[甲].text()} 与 {框[乙].text()} 重叠")

    # ------------------------------------------------------------ 运行控制
    def test_运行控制按钮跟随状态(self):
        self.窗口._刷新运行控制()
        self.assertEqual(self.窗口.主按钮.text(), "开始")
        self.assertFalse(self.窗口.停止按钮.isEnabled())
        self.实例.当前状态 = "运行中"
        self.窗口._刷新运行控制()
        self.assertEqual(self.窗口.主按钮.text(), "暂停")
        self.assertTrue(self.窗口.停止按钮.isEnabled())
        self.窗口._主按钮点击()
        self.实例.暂停.assert_called_once()
        self.实例.当前状态 = "暂停中"
        self.窗口._刷新运行控制()
        self.assertEqual(self.窗口.主按钮.text(), "继续")
        self.窗口._主按钮点击()
        self.实例.继续.assert_called_once()

    def test_开始前先保存尚未提交的任务设置(self):
        计划 = self.运行页.计划
        计划.任务列表.item(1).setCheckState(Qt.Checked)
        self.assertTrue(计划.有未保存修改)
        self.窗口._主按钮点击()
        self.监控中心.启动机器人.assert_called_once_with("robot_1")
        self.assertTrue(self.数据库.获取机器人设置("robot_1").是否刷主世界)

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

    def test_运行中显示当前动作与已运行时长(self):
        self.实例.当前状态 = "运行中"
        self.控制器._开始时间 = time.time() - 3700
        self.窗口.聚合器.最新阶段["robot_1"] = (time.time(), "搜索第 12 个村庄")
        self.窗口._每秒刷新()
        self.assertIn("搜索第 12 个村庄", self.窗口.当前动作.全文())
        self.assertIn("已运行 1:01", self.窗口.当前动作.全文())

    def test_停止后显示停止原因(self):
        self.实例.停止原因 = "资源已满"
        self.窗口._每秒刷新()
        self.assertIn("资源已满", self.窗口.当前动作.全文())

    # ------------------------------------------------------------ 参数
    def test_主界面只显示常用参数(self):
        计划 = self.运行页.计划
        计划.选择任务("main_resource")
        self.assertIn("欲进攻的最小资源", 计划._编辑器)
        self.assertIn("阵容预设", 计划._编辑器)
        self.assertNotIn("YOLO连续失败熔断次数", 计划._编辑器)
        self.assertNotIn("配兵兵种", 计划._编辑器)

    def test_非法参数不会保存(self):
        计划 = self.运行页.计划
        计划.选择任务("main_resource")
        计划._编辑器["欲进攻的最小资源"].setText("abc")
        self.assertFalse(计划.保存())
        self.assertIn("未保存", 计划.状态.text())
        设置窗 = self._打开高级页("adv_search")
        页 = 设置窗.页面["adv_search"]
        页.表单.编辑器["欲进攻资源建筑靠近地图边缘最小比例"].setText("5")
        self.assertFalse(页.保存())
        self.assertIn("未保存", 页.状态.text())
        self.assertNotEqual(
            self.数据库.获取机器人设置("robot_1").欲进攻资源建筑靠近地图边缘最小比例, 5,
        )

    def test_官方账号数据页可填写保存且令牌遮挡(self):
        from PySide6.QtWidgets import QLineEdit
        设置窗 = self._打开高级页("adv_official")
        self.assertEqual(设置窗.当前页键, "adv_official")
        页 = 设置窗.页面["adv_official"]
        令牌框 = 页.表单.编辑器["官方API令牌"]
        self.assertEqual(令牌框.echoMode(), QLineEdit.Password)
        令牌框.setText("测试令牌")
        页.表单.编辑器["玩家标签"].setText("#ABC123")
        页.表单.编辑器["官方数据同步间隔分钟"].setText("60")
        self.assertTrue(页.保存())
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual((设置.官方API令牌, 设置.玩家标签, 设置.官方数据同步间隔分钟),
                         ("测试令牌", "#ABC123", 60))

    def test_兵种选择可保存(self):
        计划 = self.运行页.计划
        计划.选择任务("main_resource")
        计划._编辑器["是否自动配置军队"].setChecked(True)
        self.assertTrue(计划.保存())
        设置窗 = self._打开高级页("adv_combat")
        页 = 设置窗.页面["adv_combat"]
        兵种框 = 页.表单.编辑器["配兵兵种"].勾选框
        self.assertIn("超级哥布林", 兵种框)
        self.assertEqual(兵种框["超级哥布林"].text(), "隐秘哥布林（超级兵种）")
        self.assertIn("资源", 兵种框["超级哥布林"].toolTip())
        兵种框["超级野蛮人"].setChecked(True)
        兵种框["超级哥布林"].setChecked(True)
        self.assertTrue(页.保存())
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertTrue(设置.是否自动配置军队)
        self.assertEqual(设置.配兵兵种, ["超级哥布林", "超级野蛮人"])
        截图路径 = os.environ.get("COC_UI_SNAPSHOT")
        if 截图路径:
            设置窗.grab().save(截图路径)

    def test_更多参数跳到对应高级页(self):
        计划 = self.运行页.计划
        计划.选择任务("main_resource")
        with mock.patch.object(self.窗口, "_检查更新"):
            计划._更多参数()
        self.assertEqual(self.窗口._高级设置.当前页键, "adv_search")
        self.窗口.设备按钮.click()
        self.assertEqual(self.窗口._高级设置.当前页键, "connection")

    def test_高级设置与主界面共用设置不会互相覆盖(self):
        计划 = self.运行页.计划
        计划.选择任务("wall")
        设置窗 = self._打开高级页("adv_search")
        页 = 设置窗.页面["adv_search"]
        页.表单.编辑器["最大搜索次数"].setText("321")
        self.assertTrue(页.保存())
        计划._编辑器["刷墙起始金币"].setText("7654321")
        self.assertTrue(计划.保存())
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual((设置.最大搜索次数, 设置.刷墙起始金币), (321, 7654321))

    def test_恢复默认只恢复本页(self):
        from 数据库.任务数据库 import 机器人设置
        设置窗 = self._打开高级页("adv_search")
        页 = 设置窗.页面["adv_search"]
        页.表单.编辑器["最大搜索次数"].setText("321")
        self.assertTrue(页.保存())
        计划 = self.运行页.计划
        计划.选择任务("wall")
        计划._编辑器["刷墙起始金币"].setText("7654321")
        self.assertTrue(计划.保存())
        页.恢复默认()
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual(设置.最大搜索次数, 机器人设置().最大搜索次数)
        self.assertEqual(设置.刷墙起始金币, 7654321)

    def test_服务器在常规页保存(self):
        设置窗 = self._打开高级页("adv_general")
        设置窗.服务器.setCurrentText("调试服务器")
        self.assertEqual(self.数据库.获取机器人设置("robot_1").服务器, "调试服务器")

    def test_自动重启开关在常规页可关闭(self):
        设置窗 = self._打开高级页("adv_general")
        页 = 设置窗.页面["adv_general"]
        开关 = 页.表单.编辑器["非人工停止后自动重启"]
        self.assertTrue(开关.isChecked())
        开关.setChecked(False)
        self.assertTrue(页.保存())
        self.assertFalse(self.数据库.获取机器人设置("robot_1").非人工停止后自动重启)

    def test_通知页可发送测试桌面通知(self):
        设置窗 = self._打开高级页("adv_notification")
        页 = 设置窗.页面["adv_notification"]
        self.assertIn("桌面通知", 页.表单.编辑器)
        with mock.patch("工具包.桌面通知.发送测试通知", return_value=True) as 发送:
            设置窗._发送测试桌面通知()
        发送.assert_called_once()
        self.assertIn("已发送", 页.状态.text())

    def test_保存任务设置不覆盖引擎新绑定的模拟器(self):
        计划 = self.运行页.计划
        计划.选择任务("wall")
        # 引擎在运行中自动绑定了新设备（直接写库）；界面手里还是旧设置对象。
        库中 = self.数据库.获取机器人设置("robot_1")
        库中.ADB设备序列号 = "127.0.0.1:16416"
        库中.ADB已确认模拟器 = True
        self.数据库.保存机器人设置("robot_1", 库中)
        计划._编辑器["刷墙起始金币"].setText("1234567")
        self.assertTrue(计划.保存())
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual(设置.ADB设备序列号, "127.0.0.1:16416")
        self.assertEqual(设置.刷墙起始金币, 1234567)

    def test_调整顺序与全选会保存(self):
        计划 = self.运行页.计划
        计划.任务列表.setCurrentRow(3)
        计划._移动(-1)
        计划.保存()
        self.assertEqual(self.数据库.获取机器人设置("robot_1").任务计划顺序[2], "wall")
        计划._全部勾选(True)
        计划.保存()
        设置 = self.数据库.获取机器人设置("robot_1")
        self.assertTrue(设置.是否刷主世界 and 设置.开启刷墙)

    # ------------------------------------------------------------ 数据与日志
    def test_今日数据条显示统计与竞赛积分(self):
        from 数据库 import 今日统计
        for 结果 in ("胜利", "胜利", "失败"):
            今日统计.记录战斗(self.数据库, "robot_1", 结果, 2)
        今日统计.记录收益(self.数据库, "robot_1", {"金币": 1_200_000, "圣水": 900_000, "黑油": 3000})
        self.数据库.更新状态("robot_1", "部落竞赛检查记录", {
            "个人积分": [2350, 4000], "个人积分时间": time.time(), "当前任务": "掠夺（200分）",
        })
        self.控制器._概况缓存 = None
        self.窗口._每秒刷新()
        self.assertEqual(self.窗口.数据项["场次"].值.text(), "3")
        self.assertEqual(self.窗口.数据项["胜率"].值.text(), "67%")
        self.assertEqual(self.窗口.数据项["金币"].值.text(), "+1.2M")
        self.assertEqual(self.窗口.数据项["黑油"].值.text(), "+3.0k")
        self.assertIn("2350 / 4000", self.窗口.竞赛文字.text())
        self.assertEqual(self.窗口.竞赛进度.value(), 2350)
        self.assertIn("掠夺", self.窗口.竞赛文字.toolTip())

    def test_没有数据时数据条显示占位(self):
        self.窗口._每秒刷新()
        self.assertEqual(self.窗口.数据项["场次"].值.text(), "0")
        self.assertEqual(self.窗口.数据项["胜率"].值.text(), "—")
        self.assertEqual(self.窗口.数据项["金币"].值.text(), "—")
        self.assertIn("暂无积分", self.窗口.竞赛文字.text())

    def test_实时日志显示在运行页(self):
        self.队列.put({"内容": "[10:00:00] 进攻完成：2 星", "机器人ID": "robot_1", "记录时间": 1e9})
        self.窗口._消费日志()
        self.窗口.打开页面("一键运行")
        self.assertIn("进攻完成", self.运行页.视图.toPlainText())

    def test_日志三档筛选(self):
        现在 = time.time()
        self.队列.put({"内容": "页面识别：页面=主世界主页", "机器人ID": "robot_1", "记录时间": 现在})
        self.队列.put({"内容": "[警告] 资源不足，跳过刷墙", "机器人ID": "robot_1", "记录时间": 现在 + 1})
        self.窗口._消费日志()
        self.运行页.切换模式("全部")
        self.assertIn("页面识别", self.运行页.视图.toPlainText())
        self.运行页.切换模式("异常")
        文本 = self.运行页.视图.toPlainText()
        self.assertIn("资源不足", 文本)
        self.assertNotIn("页面识别", 文本)

    def test_提醒条显示最近异常并可关闭和查看(self):
        self.队列.put({"内容": "未知页面超过 180 秒，进入安全待命失败", "机器人ID": "robot_1", "记录时间": time.time()})
        self.窗口._消费日志()
        self.窗口._每秒刷新()
        self.assertFalse(self.窗口._提醒外框.isHidden())
        self.assertIn("安全待命", self.窗口.提醒文字.全文())
        self.窗口._查看提醒()
        self.assertEqual(self.运行页.模式, "异常")
        self.窗口._关闭提醒()
        self.assertTrue(self.窗口._提醒外框.isHidden())

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

    def test_更新检查在后台执行(self):
        设置窗 = self._打开高级页("adv_general")
        with mock.patch("界面.主窗口.后台执行") as 后台:
            self.窗口._检查更新(手动=False)
        后台.assert_called_once()
        self.assertFalse(设置窗.更新按钮.isEnabled())

    # ------------------------------------------------------------ 方案 A 高级感
    def test_默认高级暗黑主题并记住切换(self):
        self.assertEqual(self.窗口._配色.名称, "高级暗黑")
        self.窗口._切换主题()
        self.assertEqual(self.窗口._设置.value("主题v2"), self.窗口._配色.名称)
        self.assertNotEqual(self.窗口._配色.名称, "高级暗黑")

    def test_呼吸灯与光条跟随运行状态(self):
        self.窗口._每秒刷新()
        self.assertEqual(self.窗口.指示灯.状态, "待机")
        self.assertEqual(self.窗口.光条.状态, "已停止")
        self.实例.当前状态 = "运行中"
        self.窗口._每秒刷新()
        self.assertEqual(self.窗口.指示灯.状态, "运行中")
        self.assertEqual(self.窗口.光条.状态, "运行中")
        self.assertEqual(self.窗口.光条.height(), 3)
        self.assertFalse(self.窗口.主按钮.icon().isNull())
        self.实例.当前状态 = "暂停中"
        self.窗口._每秒刷新()
        self.assertEqual(self.窗口.指示灯.状态, "暂停中")

    def test_运行中高亮当前任务行(self):
        self.实例.当前状态 = "运行中"
        self.队列.put({"内容": "按任务计划执行：wall", "机器人ID": "robot_1", "记录时间": time.time()})
        self.窗口._消费日志()
        self.窗口._每秒刷新()
        计划 = self.运行页.计划
        self.assertEqual(计划.运行任务键, "wall")
        文本 = [计划.任务列表.item(行).text() for 行 in range(计划.任务列表.count())]
        self.assertTrue(any("刷墙" in 项 and "执行中" in 项 for 项 in 文本), 文本)
        self.实例.当前状态 = "已停止"
        self.窗口._每秒刷新()
        self.assertIsNone(计划.运行任务键)
        self.assertFalse(any("执行中" in 计划.任务列表.item(行).text() for 行 in range(计划.任务列表.count())))

    def test_布尔参数使用滑动开关(self):
        from 界面.高级主题 import 滑动开关

        设置窗 = self._打开高级页("adv_general")
        开关 = 设置窗.页面["adv_general"].表单.编辑器["非人工停止后自动重启"]
        self.assertIsInstance(开关, 滑动开关)

    def test_日志胶囊分类与异常行现场图(self):
        import cv2
        import numpy as np
        from 应用.现场图服务 import 现场图服务
        from 界面.方案A部件 import 现场图索引

        根 = tempfile.mkdtemp()
        os.makedirs(os.path.join(根, "待命现场"))
        现在 = time.time()
        名称 = time.strftime("%Y%m%d_%H%M%S", time.localtime(现在))
        cv2.imencode(".png", np.zeros((40, 60, 3), np.uint8))[1].tofile(
            os.path.join(根, "待命现场", f"未知页面_{名称}.png"))
        索引 = 现场图索引(现场图服务(根))
        索引.刷新(同步=True)
        self.运行页.现场图 = 索引
        self.运行页.视图.现场图查找 = 索引.查找
        self.队列.put({"内容": "[警告] 未知页面，进入待命", "机器人ID": "robot_1", "记录时间": 现在 + 5})
        self.队列.put({"内容": "部落竞赛：接取任务", "机器人ID": "robot_1", "记录时间": 现在 + 6})
        self.窗口._消费日志()
        self.运行页.切换模式("全部")
        文本 = self.运行页.视图.toPlainText()
        self.assertIn("异常", 文本)
        self.assertIn("竞赛", 文本)
        self.assertIn("现场图", 文本)
        self.assertEqual(len(self.运行页.视图._链接), 1)
        时间戳, 日志 = next(iter(self.运行页.视图._链接.values()))
        弹窗 = self.运行页.打开现场图(时间戳, 日志)
        self.assertIsNotNone(弹窗)
        self.assertTrue(弹窗.等待加载())
        弹窗.close()

    def test_战报窗口显示今日与昨日(self):
        from 应用.战报服务 import 战报服务

        with mock.patch("界面.方案A部件.后台执行"):
            战报 = self.窗口.打开战报()
        战报.显示(战报服务(self.数据库).生成战报("robot_1"))
        self.assertIn("对比昨日", 战报.副标题.text())
        self.assertEqual(set(战报.单元), {键 for 键, *_ in 战报.指标})
        战报.曲线.grab()
        战报.close()

    def test_配置方案预览应用并撤销(self):
        方案窗 = self.窗口.打开方案()
        self.assertTrue(方案窗.等待空闲())
        名称 = [方案窗.列表.item(行).data(Qt.UserRole) for 行 in range(方案窗.列表.count())]
        self.assertTrue({"隐哥冲黑油", "冲部落竞赛", "日常均衡刷墙"} <= set(名称))
        方案窗.列表.setCurrentRow(名称.index("隐哥冲黑油"))
        self.assertTrue(方案窗.等待空闲())
        self.assertGreater(方案窗.差异表.rowCount(), 0)
        原值 = self.数据库.获取机器人设置("robot_1").战利品优先级
        方案窗._应用()
        self.assertTrue(方案窗.等待空闲())
        self.assertEqual(self.数据库.获取机器人设置("robot_1").战利品优先级, "黑水")
        self.assertEqual(self.运行页.计划.设置.战利品优先级, "黑水")
        self.assertTrue(方案窗.撤销按钮.isEnabled())
        方案窗._撤销()
        self.assertTrue(方案窗.等待空闲())
        self.assertEqual(self.数据库.获取机器人设置("robot_1").战利品优先级, 原值)
        self.assertEqual(self.运行页.计划.设置.战利品优先级, 原值)
        路径 = os.path.join(tempfile.mkdtemp(), "方案.json")
        方案窗.导出文件("隐哥冲黑油", 路径)
        self.assertTrue(方案窗.等待空闲())
        self.assertTrue(os.path.exists(路径))
        方案窗.导入文件(路径)
        self.assertTrue(方案窗.等待空闲())
        # 内置方案不会被导入覆盖，而是另存为「…（导入）」并选中等待确认。
        self.assertEqual(方案窗.当前方案名, "隐哥冲黑油（导入）")
        self.assertTrue(方案窗.服务.获取预设("隐哥冲黑油").内置)
        方案窗.close()

    def test_配置方案读取不在界面线程执行(self):
        """预设列表、差异预览和导入都交给后台线程；界面线程只渲染结果。"""
        with mock.patch("界面.方案A部件.后台执行") as 后台:
            方案窗 = self.窗口.打开方案()
            self.assertEqual(方案窗.列表.count(), 0)
            self.assertTrue(方案窗.忙)
            后台.assert_called()
            路径 = os.path.join(tempfile.mkdtemp(), "x.json")
            with open(路径, "w", encoding="utf-8") as 文件:
                文件.write("{}")
            方案窗._进行中 = 0  # 只验证导入本身不在界面线程读文件
            with mock.patch("builtins.open", side_effect=AssertionError("界面线程读文件")):
                方案窗.导入文件(路径)
            self.assertEqual(方案窗.状态.text(), "正在导入…")
        方案窗.close()

    def test_配置方案关闭后迟到的结果被丢弃(self):
        方案窗 = self.窗口.打开方案()
        方案窗.close()
        self.assertTrue(方案窗.等待空闲())
        self.assertEqual(方案窗.列表.count(), 0)
        # 再次打开会重新载入
        self.窗口.打开方案()
        self.assertTrue(方案窗.等待空闲())
        self.assertGreater(方案窗.列表.count(), 0)
        方案窗.close()

    def _捕获后台(self):
        任务 = []
        return mock.patch("界面.方案A部件.后台执行",
                          side_effect=lambda 函数, 成功, 失败: 任务.append((函数, 成功, 失败))), 任务

    def test_配置方案忙时所有操作都禁用(self):
        补丁, 任务 = self._捕获后台()
        with 补丁:
            方案窗 = self.窗口.打开方案()
            self.assertTrue(方案窗.忙)
            for 按钮 in (方案窗.应用按钮, 方案窗.撤销按钮, 方案窗.保存当前按钮, 方案窗.导入按钮, 方案窗.导出按钮):
                self.assertFalse(按钮.isEnabled(), 按钮.text())
            数量 = len(任务)
            方案窗.保存当前为方案("新方案")
            方案窗.导入文件(os.path.join(tempfile.mkdtemp(), "a.json"))
            方案窗.导出文件("隐哥冲黑油", os.path.join(tempfile.mkdtemp(), "b.json"))
            方案窗._应用()
            方案窗._撤销()
            self.assertEqual(len(任务), 数量)
            # 载入（及随后的差异预览）完成后恢复可用
            while 任务:
                函数, 成功, _ = 任务.pop(0)
                成功(函数())
        self.assertFalse(方案窗.忙)
        for 按钮 in (方案窗.保存当前按钮, 方案窗.导入按钮, 方案窗.导出按钮):
            self.assertTrue(按钮.isEnabled(), 按钮.text())
        方案窗.close()

    def test_配置方案关闭后马上重开旧回调不更新新窗口(self):
        from 应用.预设服务 import 方案预设

        补丁, 任务 = self._捕获后台()
        with 补丁:
            方案窗 = self.窗口.打开方案()
            旧载入 = 任务[-1]
            方案窗.close()
            self.assertIs(self.窗口.打开方案(), 方案窗)
            新载入 = 任务[-1]
            self.assertIsNot(新载入, 旧载入)
            旧列表 = [方案预设(名称="旧会话的方案", 说明="", 参数={"战利品优先级": "黑水"}, 内置=False)]
            旧载入[1](旧列表)  # 上一次打开的迟到结果
            self.assertEqual(方案窗.列表.count(), 0)
            新载入[1](新载入[0]())
            名称 = [方案窗.列表.item(行).data(Qt.UserRole) for 行 in range(方案窗.列表.count())]
            self.assertNotIn("旧会话的方案", 名称)
            self.assertIn("隐哥冲黑油", 名称)
        方案窗.close()

    def test_配置方案重开后新会话先完成旧回调后完成按钮恢复(self):
        补丁, 任务 = self._捕获后台()
        with 补丁:
            方案窗 = self.窗口.打开方案()
            旧载入 = 任务.pop()
            方案窗.close()
            self.窗口.打开方案()
            # 新会话（载入及随后的预览）先全部完成
            while 任务:
                函数, 成功, _ = 任务.pop(0)
                成功(函数())
            self.assertTrue(方案窗.忙)  # 旧会话的读取还没回来
            self.assertFalse(方案窗.保存当前按钮.isEnabled())
            名称 = [方案窗.列表.item(行).data(Qt.UserRole) for 行 in range(方案窗.列表.count())]
            # 旧回调最后完成：不改列表，但按钮要恢复可用
            旧载入[1]([])
            self.assertFalse(方案窗.忙)
            self.assertEqual([方案窗.列表.item(行).data(Qt.UserRole) for 行 in range(方案窗.列表.count())], 名称)
            for 按钮 in (方案窗.保存当前按钮, 方案窗.导入按钮, 方案窗.导出按钮):
                self.assertTrue(按钮.isEnabled(), 按钮.text())
            self.assertEqual(方案窗.应用按钮.isEnabled(), 方案窗._可应用)
        方案窗.close()

    def test_配置方案旧会话失败回调后完成也恢复按钮且不显示旧错误(self):
        补丁, 任务 = self._捕获后台()
        with 补丁:
            方案窗 = self.窗口.打开方案()
            旧载入 = 任务.pop()
            方案窗.close()
            self.窗口.打开方案()
            while 任务:
                函数, 成功, _ = 任务.pop(0)
                成功(函数())
            旧载入[2]("旧会话读取失败")
        self.assertFalse(方案窗.忙)
        self.assertTrue(方案窗.导入按钮.isEnabled())
        self.assertNotIn("旧会话读取失败", 方案窗.状态.text())
        方案窗.close()

    def test_关闭窗口后应用结果仍通知主界面(self):
        方案窗 = self.窗口.打开方案()
        方案窗.等待空闲()
        方案窗.列表.setCurrentRow(0)
        方案窗.等待空闲()
        while 方案窗.当前方案名 != "隐哥冲黑油":
            方案窗.列表.setCurrentRow(方案窗.列表.currentRow() + 1)
            方案窗.等待空闲()
        补丁, 任务 = self._捕获后台()
        with 补丁:
            方案窗._应用()
            方案窗.close()
            函数, 成功, _ = 任务[-1]
            成功(函数())
        self.assertEqual(self.运行页.计划.设置.战利品优先级, "黑水")
        self.assertNotIn("已切换", 方案窗.状态.text())

    def test_常规页可设置内存保护阈值(self):
        设置窗 = self._打开高级页("adv_general")
        页 = 设置窗.页面["adv_general"]
        编辑器 = 页.表单.编辑器["内存保护提交额度阈值MB"]
        self.assertEqual(编辑器.text(), "1536")
        编辑器.setText("2048")
        self.assertTrue(页.保存())
        self.assertEqual(self.数据库.获取机器人设置("robot_1").内存保护提交额度阈值MB, 2048)
        编辑器.setText("100")
        self.assertFalse(页.保存())
        self.assertEqual(self.数据库.获取机器人设置("robot_1").内存保护提交额度阈值MB, 2048)
        设置窗.close()
        self.窗口._高级设置 = None
        设置窗 = self._打开高级页("adv_general")
        self.assertEqual(设置窗.页面["adv_general"].表单.编辑器["内存保护提交额度阈值MB"].text(), "2048")

    def _假托盘(self):
        托盘 = mock.Mock()
        托盘.是否可用 = True
        托盘.显示.return_value = True
        return mock.patch("界面.系统托盘.系统托盘控制器", return_value=托盘), 托盘

    def test_托盘默认关闭且关窗真正退出(self):
        self.assertFalse(self.窗口.最小化到托盘)
        self.assertIsNone(self.窗口.托盘)
        self.assertTrue(self.应用.quitOnLastWindowClosed())
        with mock.patch("界面.主窗口.退出应用") as 退出,                 mock.patch.object(self.控制器, "关闭", wraps=self.控制器.关闭) as 控制器关闭:
            self.窗口.close()
        self.assertFalse(self.窗口.isVisible())
        self.assertTrue(self.窗口._关闭中)
        控制器关闭.assert_called_once()
        退出.assert_called_once()
        self.assertIsNone(self.窗口.托盘)

    def test_关窗退出时运行中先确认(self):
        self.实例.当前状态 = "运行中"
        with mock.patch("界面.主窗口.确认", return_value=False), mock.patch("界面.主窗口.退出应用") as 退出:
            self.窗口.close()
        self.assertTrue(self.窗口.isVisible())
        退出.assert_not_called()
        with mock.patch("界面.主窗口.确认", return_value=True), mock.patch("界面.主窗口.退出应用") as 退出:
            self.窗口.close()
        self.assertFalse(self.窗口.isVisible())
        退出.assert_called_once()

    def test_常规页勾选最小化到托盘后关窗隐藏(self):
        补丁, 托盘 = self._假托盘()
        设置窗 = self._打开高级页("adv_general")
        self.assertTrue(设置窗.托盘开关.isVisible())
        self.assertFalse(设置窗.托盘开关.isChecked())
        with 补丁, mock.patch("界面.主窗口.退出应用") as 退出:
            设置窗.托盘开关.setChecked(True)
            self.assertTrue(self.窗口.最小化到托盘)
            self.assertIs(self.窗口.托盘, 托盘)
            托盘.显示.assert_called_once()
            self.assertFalse(self.应用.quitOnLastWindowClosed())
            self.窗口.close()
            self.assertFalse(self.窗口.isVisible())
            self.assertFalse(self.窗口._关闭中)
            退出.assert_not_called()
            托盘.发送提示.assert_called_once()
            self.窗口._托盘显隐()
            self.assertTrue(self.窗口.isVisible())
            # 取消勾选：托盘图标立即移除，关窗恢复为直接退出。
            设置窗.托盘开关.setChecked(False)
            托盘.关闭.assert_called_once()
            self.assertIsNone(self.窗口.托盘)
            self.assertTrue(self.应用.quitOnLastWindowClosed())
        设置窗.close()

    def test_托盘菜单退出能真正退出(self):
        补丁, 托盘 = self._假托盘()
        with 补丁, mock.patch("界面.主窗口.退出应用") as 退出:
            self.窗口.设置最小化到托盘(True)
            self.窗口.close()
            self.assertFalse(self.窗口.isVisible())
            self.窗口.退出程序()
        self.assertTrue(self.窗口._关闭中)
        退出.assert_called_once()
        托盘.关闭.assert_called_once()
        self.assertIsNone(self.窗口.托盘)

    def test_托盘设置保存在界面偏好里(self):
        补丁, _托盘 = self._假托盘()
        with 补丁:
            self.窗口.设置最小化到托盘(True)
        self.assertTrue(self.窗口.最小化到托盘)
        self.assertNotIn("托盘", "".join(vars(self.数据库.获取机器人设置("robot_1"))))
        self.窗口.设置最小化到托盘(False)
        self.assertFalse(self.窗口.最小化到托盘)

if __name__ == "__main__":
    unittest.main()
