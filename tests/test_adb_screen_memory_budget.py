import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 核心.ADB屏幕 import ADB屏幕
from 模块.ADB设备操作类 import ADB设备操作类
from 模块.运行节流与复盘 import 模型空闲释放协调器


def _命令结果(输出: str = "", 返回码: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=返回码, stdout=输出, stderr="")


class ADB屏幕内存预算接口测试(unittest.TestCase):
    def test_内存预算检查转发到实际ADB设备(self):
        设备 = Mock()
        设备.检查主机内存预算.return_value = (True, "健康")
        屏幕 = ADB屏幕(设备)

        self.assertEqual(
            屏幕.检查主机内存预算(强制刷新=True),
            (True, "健康"),
        )
        设备.检查主机内存预算.assert_called_once_with(强制刷新=True)

    def test_macOS内存充足时返回健康预算且不反复卸载OCR(self):
        # 16 GB 总内存，页大小 16384B，free+inactive+speculative 约 6.7 GB
        vm_stat输出 = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                                   167928.\n"
            "Pages active:                                 251488.\n"
            "Pages inactive:                               244589.\n"
            "Pages speculative:                              6244.\n"
            "Pages wired down:                             111820.\n"
        )

        def 假运行(命令, **_kwargs):
            if 命令[:2] == ["sysctl", "-n"] and 命令[2] == "hw.memsize":
                return _命令结果(f"{16 * 1024 ** 3}\n")
            if 命令 == ["vm_stat"]:
                return _命令结果(vm_stat输出)
            if 命令[:2] == ["sysctl", "-n"] and 命令[2] == "vm.swapusage":
                return _命令结果("total = 0.00M  used = 0.00M  free = 0.00M  (encrypted)\n")
            return _命令结果("", 1)

        设备 = ADB设备操作类(sys.executable, "emulator-5554", runner=Mock(), 自动检测路径=False)
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"), \
             patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行):
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)

            self.assertTrue(健康, 诊断)
            self.assertIn("主机内存预算健康", 诊断)
            self.assertIn("可用物理内存", 诊断)

            # 接入模型空闲释放协调器：120s (<600s空闲阈值) 内反复检查不会卸载 OCR
            协调器 = 模型空闲释放协调器(默认阈值秒=600.0)
            协调器.标记使用(当前时间=100.0)
            上下文 = SimpleNamespace(
                _共享OCR引擎=object(),
                _共享YOLO检测器=None,
                op=ADB屏幕(设备),
                设置=SimpleNamespace(模型空闲释放秒数=600.0),
                释放识别模型=Mock(),
                置脚本状态=Mock(),
            )
            for 秒 in (130.0, 160.0, 190.0, 220.0):
                已释放, 原因 = 协调器.按需释放(上下文, 当前时间=秒, 检查间隔秒=10.0)
                self.assertFalse(已释放, 原因)
            上下文.释放识别模型.assert_not_called()

    def test_macOS内存吃紧时返回False并触发模型释放(self):
        # 8 GB 总内存，可用页仅约 400 MB（负载约 95%）
        vm_stat输出 = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                                    12000.\n"
            "Pages active:                                 300000.\n"
            "Pages inactive:                                13000.\n"
            "Pages speculative:                               600.\n"
        )

        def 假运行(命令, **_kwargs):
            if 命令[:2] == ["sysctl", "-n"] and 命令[2] == "hw.memsize":
                return _命令结果(f"{8 * 1024 ** 3}\n")
            if 命令 == ["vm_stat"]:
                return _命令结果(vm_stat输出)
            if 命令[:2] == ["sysctl", "-n"] and 命令[2] == "vm.swapusage":
                return _命令结果("total = 1024.00M  used = 900.00M  free = 124.00M\n")
            return _命令结果("", 1)

        设备 = ADB设备操作类(sys.executable, "emulator-5554", runner=Mock(), 自动检测路径=False)
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"), \
             patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行):
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertFalse(健康)
            self.assertIn("主机内存保护已触发", 诊断)

            协调器 = 模型空闲释放协调器(默认阈值秒=600.0)
            协调器.标记使用(当前时间=100.0)
            上下文 = SimpleNamespace(
                _共享OCR引擎=object(),
                _共享YOLO检测器=None,
                op=ADB屏幕(设备),
                设置=SimpleNamespace(模型空闲释放秒数=600.0),
                释放识别模型=Mock(),
                置脚本状态=Mock(),
            )
            已释放, 原因 = 协调器.按需释放(上下文, 当前时间=115.0)
            self.assertTrue(已释放)
            self.assertIn("宿主机内存预算紧张", 原因)
            上下文.释放识别模型.assert_called_once()

    def test_macOS读取异常及其他POSIX平台安全回退不崩溃(self):
        设备 = ADB设备操作类(sys.executable, "emulator-5554", runner=Mock(), 自动检测路径=False)
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"), \
             patch("模块.ADB设备操作类.subprocess.run", side_effect=OSError("sysctl unavailable")):
            self.assertIsNone(ADB设备操作类._获取主机内存状态())
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertTrue(健康)
            self.assertIn("暂不可用", 诊断)

        # 未知 POSIX 平台也安全回退
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "freebsd14"):
            self.assertIsNone(ADB设备操作类._获取主机内存状态())
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertTrue(健康)
            self.assertIn("安全回退", 诊断)

        # Windows 路径不可用时仍保持原有保守 False 判定
        with patch.object(os, "name", "nt"), \
             patch.object(ADB设备操作类, "_获取主机内存状态", return_value=None):
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertFalse(健康)
            self.assertIn("暂不可用", 诊断)


if __name__ == "__main__":
    unittest.main()
