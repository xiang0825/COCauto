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

        # Windows 路径不可用时仍保持原有保守 False 判定，并立即触发模型释放
        with patch.object(os, "name", "nt"), \
             patch.object(ADB设备操作类, "_获取主机内存状态", return_value=None):
            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertFalse(健康)
            self.assertIn("暂不可用", 诊断)

            协调器 = 模型空闲释放协调器(默认阈值秒=600.0)
            协调器.标记使用(当前时间=100.0)
            上下文 = SimpleNamespace(
                _共享OCR引擎=object(),
                _共享YOLO检测器=object(),
                op=ADB屏幕(设备),
                设置=SimpleNamespace(模型空闲释放秒数=600.0),
                释放识别模型=Mock(),
                置脚本状态=Mock(),
            )
            已释放, 原因 = 协调器.按需释放(上下文, 当前时间=110.0)
            self.assertTrue(已释放)
            self.assertIn("暂不可用", 原因)
            上下文.释放识别模型.assert_called_once()

        # macOS 路径暂不可用时返回安全放行，不触发模型释放
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"), \
             patch.object(ADB设备操作类, "_获取主机内存状态", return_value=None):
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
            已释放, 原因 = 协调器.按需释放(上下文, 当前时间=110.0)
            self.assertFalse(已释放, 原因)
            上下文.释放识别模型.assert_not_called()

    def test_macOS优先使用kern_memorystatus_level且跳过提交额度判定(self):
        # 8 GB Mac：kern.memorystatus_level=54%，vm_stat 即使仅报告少量 free/inactive 且 swap=0
        # 也不应误停，且应跳过提交额度判定（即使提交额度阈值设到 4096MB）。
        vm_stat输出 = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                                    18000.\n"
            "Pages active:                                 210000.\n"
            "Pages inactive:                                45000.\n"
            "Pages speculative:                              2000.\n"
            "Pages wired down:                              95000.\n"
            "Pages purgeable:                                6000.\n"
            "File-backed pages:                             85000.\n"
        )
        调用命令 = []

        def 假运行(命令, **_kwargs):
            调用命令.append(list(命令))
            if 命令 == ["sysctl", "-n", "hw.memsize"]:
                return _命令结果(f"{8 * 1024 ** 3}\n")
            if 命令 == ["sysctl", "-n", "kern.memorystatus_level"]:
                return _命令结果("54\n")
            if 命令 == ["vm_stat"]:
                return _命令结果(vm_stat输出)
            return _命令结果("", 1)

        设备 = ADB设备操作类(
            sys.executable,
            "emulator-5554",
            runner=Mock(),
            自动检测路径=False,
            内存保护提交额度阈值MB=4096,
        )
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"), \
             patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行):
            状态 = ADB设备操作类._获取主机内存状态()
            self.assertIsNotNone(状态)
            self.assertEqual(状态["系统可用内存百分比"], 54)
            self.assertEqual(状态["内存负载"], 46)
            self.assertTrue(状态["跳过提交额度判定"])
            self.assertNotIn(["sysctl", "-n", "vm.swapusage"], 调用命令)

            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertTrue(健康, 诊断)
            self.assertIn("macOS可用内存54%", 诊断)
            self.assertIn("跳过提交额度判定", 诊断)

    def test_macOS回退vm_stat计入file_backed与purgeable且正常8GB不误停(self):
        # 8 GB Mac，kern.memorystatus_level 不可用时回退 vm_stat：
        # free+inactive+speculative 仅约 360MB（旧算法会误停），
        # 计入 file-backed + purgeable 后可用物理约 2703MB，正常 8GB Mac 不误停。
        vm_stat输出 = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                                    10000.\n"
            "Pages active:                                 180000.\n"
            "Pages inactive:                                12000.\n"
            "Pages speculative:                              1000.\n"
            "Pages wired down:                              90000.\n"
            "Pages purgeable:                               20000.\n"
            "File-backed pages:                            130000.\n"
        )

        def 假运行(命令, **_kwargs):
            if 命令 == ["sysctl", "-n", "hw.memsize"]:
                return _命令结果(f"{8 * 1024 ** 3}\n")
            if 命令 == ["sysctl", "-n", "kern.memorystatus_level"]:
                return _命令结果("", 1)
            if 命令 == ["vm_stat"]:
                return _命令结果(vm_stat输出)
            return _命令结果("", 1)

        设备 = ADB设备操作类(
            sys.executable,
            "emulator-5554",
            runner=Mock(),
            自动检测路径=False,
            内存保护提交额度阈值MB=3072,
        )
        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"), \
             patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行):
            状态 = ADB设备操作类._获取主机内存状态()
            self.assertIsNotNone(状态)
            self.assertIsNone(状态["系统可用内存百分比"])
            self.assertGreater(状态["可用物理内存"], 2500 * 1024 * 1024)
            self.assertLess(状态["内存负载"], 70)

            健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
            self.assertTrue(健康, 诊断)
            self.assertIn("主机内存预算健康", 诊断)
            self.assertIn("跳过提交额度判定", 诊断)

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
            已释放, 原因 = 协调器.按需释放(上下文, 当前时间=120.0)
            self.assertFalse(已释放, 原因)
            上下文.释放识别模型.assert_not_called()

    def test_macOS真正极低可用内存拦截而缓存高占用不误停(self):
        # 1) kern.memorystatus_level=8% 且物理可用仅 ~312MB -> 必须拦截
        低内存vm = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                                     4000.\n"
            "Pages active:                                 320000.\n"
            "Pages inactive:                                 5000.\n"
            "Pages speculative:                               200.\n"
            "Pages wired down:                             150000.\n"
            "Pages purgeable:                                 800.\n"
            "File-backed pages:                             10000.\n"
        )
        # 2) kern.memorystatus_level=10% 但仍有 ~1.7GB file-backed 可回收缓存 -> 不误停
        缓存充足vm = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                                     6000.\n"
            "Pages active:                                 240000.\n"
            "Pages inactive:                                15000.\n"
            "Pages speculative:                               500.\n"
            "Pages wired down:                             120000.\n"
            "Pages purgeable:                                5000.\n"
            "File-backed pages:                             85000.\n"
        )

        设备 = ADB设备操作类(sys.executable, "emulator-5554", runner=Mock(), 自动检测路径=False)

        with patch.object(os, "name", "posix"), \
             patch.object(sys, "platform", "darwin"):
            # 极低 level + 极低物理可用 -> 拦截
            def 假运行极低(命令, **_kwargs):
                if 命令 == ["sysctl", "-n", "hw.memsize"]:
                    return _命令结果(f"{8 * 1024 ** 3}\n")
                if 命令 == ["sysctl", "-n", "kern.memorystatus_level"]:
                    return _命令结果("8\n")
                if 命令 == ["vm_stat"]:
                    return _命令结果(低内存vm)
                return _命令结果("", 1)

            with patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行极低):
                健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
                self.assertFalse(健康)
                self.assertIn("主机内存保护已触发", 诊断)
                self.assertIn("macOS可用内存8%", 诊断)

            # 极端 level <= 5% 即使 vm_stat 失败也拦截
            def 假运行极端(命令, **_kwargs):
                if 命令 == ["sysctl", "-n", "hw.memsize"]:
                    return _命令结果(f"{16 * 1024 ** 3}\n")
                if 命令 == ["sysctl", "-n", "kern.memorystatus_level"]:
                    return _命令结果("4\n")
                return _命令结果("", 1)

            with patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行极端):
                健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
                self.assertFalse(健康)
                self.assertIn("主机内存保护已触发", 诊断)
                self.assertIn("macOS可用内存4%", 诊断)

            # level=10% 但可回收缓存充足 -> 不误停
            def 假运行缓存充足(命令, **_kwargs):
                if 命令 == ["sysctl", "-n", "hw.memsize"]:
                    return _命令结果(f"{8 * 1024 ** 3}\n")
                if 命令 == ["sysctl", "-n", "kern.memorystatus_level"]:
                    return _命令结果("10\n")
                if 命令 == ["vm_stat"]:
                    return _命令结果(缓存充足vm)
                return _命令结果("", 1)

            with patch("模块.ADB设备操作类.subprocess.run", side_effect=假运行缓存充足):
                健康, 诊断 = 设备.检查主机内存预算(强制刷新=True)
                self.assertTrue(健康, 诊断)
                self.assertIn("主机内存预算健康", 诊断)


if __name__ == "__main__":
    unittest.main()
