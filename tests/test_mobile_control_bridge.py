import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from 数据库.任务数据库 import 机器人设置


class _Database:
    def __init__(self, settings):
        self.settings = settings
        self.last_log = SimpleNamespace(
            记录时间=10.0,
            日志内容="状态已更新",
        )

    def 获取机器人设置(self, _robot_id):
        return self.settings

    def 读取最后日志(self, _robot_id):
        return self.last_log

    def 查询日志历史(self, _robot_id, 起始时间=0, 截止时间=None, 最大条数=100):
        return [self.last_log]


class _Robot:
    def __init__(self, robot_id, state="已停止"):
        self.机器人标志 = robot_id
        self.当前状态 = state
        self.停止原因 = "手动停止"
        self.停止事件 = SimpleNamespace(is_set=lambda: state == "已停止")
        self.设备 = None
        self.暂停 = Mock()
        self.继续 = Mock()
        self.停止 = Mock()


class MobileControlBridgeTests(unittest.TestCase):
    def test_mobile_control_panel_imports_the_exported_qr_factory(self):
        import importlib

        panel = importlib.import_module("界面.手机控制面板")
        service = importlib.import_module("服务.局域网控制服务")

        self.assertIs(panel.create_pairing_qr_image, service.create_pairing_qr_image)

    def setUp(self):
        self.settings = 机器人设置(
            是否刷主世界=True,
            是否刷夜世界=False,
            开启刷墙=False,
            企业微信webhook="https://example.invalid/webhook/private-secret",
        )
        self.database = _Database(self.settings)
        self.robot = _Robot("robot_1")
        self.other_robot = _Robot("robot_2")
        self.monitor = SimpleNamespace(
            机器人池={"robot_1": self.robot, "robot_2": self.other_robot},
            启动机器人=Mock(),
        )

    def test_snapshot_exposes_only_selected_tasks_and_plan_changes_advance_revision(self):
        from 服务.桌面手机控制桥 import DesktopMobileBridge

        bridge = DesktopMobileBridge(
            database=self.database,
            monitor_center=self.monitor,
            state_directory="unused-test-path",
            version_provider=lambda: "rc117",
        )

        first = bridge.refresh_snapshot("robot_1")
        self.assertEqual(first["selected_tasks"], ["main_resource"])
        self.assertEqual(first["state"], "已停止")
        self.assertEqual(first["version"], "rc117")
        self.assertNotIn("private-secret", json.dumps(first, ensure_ascii=False))
        self.assertEqual(first["revision"], 1)

        unchanged = bridge.refresh_snapshot("robot_1")
        self.assertEqual(unchanged["revision"], first["revision"])

        self.database.settings = replace(self.settings, 欲进攻的最小资源=900000)
        changed = bridge.refresh_snapshot("robot_1")
        self.assertNotEqual(changed["plan_fingerprint"], first["plan_fingerprint"])
        self.assertEqual(changed["revision"], first["revision"] + 1)

    def test_recent_logs_are_ordered_and_webhook_secret_is_redacted(self):
        from 服务.桌面手机控制桥 import DesktopMobileBridge

        self.database.last_log = SimpleNamespace(
            记录时间=11.0,
            日志内容="请求 https://example.invalid/webhook/private-secret 已完成",
        )
        bridge = DesktopMobileBridge(
            database=self.database,
            monitor_center=self.monitor,
            state_directory="unused-test-path",
            version_provider=lambda: "rc117",
        )
        bridge.refresh_snapshot("robot_1")

        logs = bridge.get_recent_logs("robot_1", 0.0, 10)

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["time"], 11.0)
        self.assertNotIn("private-secret", logs[0]["message"])

    def test_commands_target_the_bound_robot_and_follow_its_state(self):
        from 服务.桌面手机控制桥 import DesktopMobileBridge

        bridge = DesktopMobileBridge(
            database=self.database,
            monitor_center=self.monitor,
            state_directory="unused-test-path",
            version_provider=lambda: "rc117",
        )

        bridge.execute_control("robot_1", "start")
        self.monitor.启动机器人.assert_called_once_with("robot_1")
        self.monitor.机器人池["robot_2"].停止.assert_not_called()

        self.robot.当前状态 = "暂停中"
        bridge.execute_control("robot_1", "start")
        self.robot.继续.assert_called_once_with()

        self.robot.当前状态 = "运行中"
        bridge.execute_control("robot_1", "pause")
        self.robot.暂停.assert_called_once_with()
        bridge.execute_control("robot_1", "stop")
        self.robot.停止.assert_called_once_with("手机控制停止", 等待=False)

    def test_device_disconnect_is_reported_and_blocks_start_until_reconnected(self):
        from 服务.桌面手机控制桥 import DesktopMobileBridge

        self.database.settings = replace(
            self.settings,
            ADB设备序列号="127.0.0.1:16384",
            ADB已确认模拟器=True,
        )
        self.robot.设备 = SimpleNamespace(
            _连续传输失败次数=2,
            _目标已验证=False,
        )
        bridge = DesktopMobileBridge(
            database=self.database,
            monitor_center=self.monitor,
            state_directory="unused-test-path",
            version_provider=lambda: "rc117",
        )

        disconnected = bridge.refresh_snapshot("robot_1")
        self.assertFalse(disconnected["adb_connected"])
        self.assertEqual(disconnected["adb_state"], "连接失败")
        with self.assertRaisesRegex(RuntimeError, "ADB"):
            bridge.execute_control("robot_1", "start")
        self.monitor.启动机器人.assert_not_called()

        self.robot.设备._连续传输失败次数 = 0
        reconnected = bridge.refresh_snapshot("robot_1")
        self.assertTrue(reconnected["adb_connected"])
        self.assertEqual(reconnected["adb_state"], "最近已连接")
        self.assertEqual(reconnected["revision"], disconnected["revision"] + 1)

    def test_unknown_robot_or_command_fails_closed(self):
        from 服务.桌面手机控制桥 import DesktopMobileBridge

        bridge = DesktopMobileBridge(
            database=self.database,
            monitor_center=self.monitor,
            state_directory="unused-test-path",
            version_provider=lambda: "rc117",
        )
        with self.assertRaises(KeyError):
            bridge.refresh_snapshot("robot_unknown")
        with self.assertRaises(ValueError):
            bridge.execute_control("robot_1", "change_tasks")
        self.monitor.启动机器人.assert_not_called()


if __name__ == "__main__":
    unittest.main()
