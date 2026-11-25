import gzip
import json
import os
import struct
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from 核心.ADB屏幕 import ADB屏幕
from 模块.ADB设备操作类 import ADB错误, ADB设备操作类
from 模块.MuMu高速截图 import MuMu高速截图
from 模块.截图后端 import (
    BACKEND_ADB_PNG,
    BACKEND_ADB_RAW,
    BACKEND_ADB_RAW_GZIP,
    BACKEND_MUMU_IPC,
    构造ADB截图命令参数,
    校验截图帧,
    画面像素一致,
    解码Gzip原始截图,
    解码PNG截图,
    解码原始截图,
)

ADB = sys.executable
在线模拟器 = b"List of devices attached\nemulator-5554 device product:LDPlayer model:LDPlayer\n"
MUMU设备列表 = b"List of devices attached\n127.0.0.1:16384 device product:MuMu model:MuMu\n"
MUMU窗口CoC = """FocusedWindows:
  displayId=6, name='Window{123 u0 com.supercell.clashofclans/com.supercell.titan.GameApp}'
FocusedApplications:
  displayId=6, name='com.supercell.clashofclans/com.supercell.titan.GameApp'
"""
MUMU显示层CoC = """
  DisplayViewport{type=INTERNAL, valid=true, displayId=0, uniqueId='local:111111'}
  DisplayViewport{type=INTERNAL, valid=true, displayId=6, uniqueId='local:4619827203584079877'}
"""


def 构造测试画面BGR(宽: int = 128, 高: int = 72) -> np.ndarray:
    画面 = np.zeros((高, 宽, 3), dtype=np.uint8)
    画面[:, :, 0] = 35
    画面[:16, :, :] = (24, 96, 220)
    画面[20:48, 16:88, :] = (210, 180, 45)
    画面[12:60, 92:, 1] = 240
    return 画面


def 编码PNG(画面BGR: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", 画面BGR)
    assert ok
    return buf.tobytes()


def 编码原始像素(
    画面BGR: np.ndarray,
    *,
    格式: int = 1,
    头长度: int = 16,
    前缀: bytes = b"",
) -> bytes:
    高, 宽 = 画面BGR.shape[:2]
    if 格式 in (1, 2):
        像素 = cv2.cvtColor(画面BGR, cv2.COLOR_BGR2RGBA)
        if 格式 == 2:
            像素[:, :, 3] = 255
    elif 格式 == 3:
        像素 = cv2.cvtColor(画面BGR, cv2.COLOR_BGR2RGB)
    elif 格式 == 4:
        像素 = cv2.cvtColor(画面BGR, cv2.COLOR_BGR2BGR565)
    elif 格式 == 5:
        像素 = cv2.cvtColor(画面BGR, cv2.COLOR_BGR2BGRA)
    else:
        raise ValueError(f"不支持的测试格式: {格式}")

    if 头长度 == 12:
        头部 = struct.pack("<III", 宽, 高, 格式)
    elif 头长度 == 16:
        头部 = struct.pack("<IIII", 宽, 高, 格式, 1)
    else:
        raise ValueError(f"不支持的头长度: {头长度}")
    return 前缀 + 头部 + 像素.tobytes()


class 模拟Clock:
    """确定性时钟：按当前活动后端耗时推进 perf_counter，消除真实 sleep 抖动。"""

    def __init__(self):
        self.perf = 100.0
        self.mono = 1000.0

    def perf_counter(self) -> float:
        return self.perf

    def monotonic(self) -> float:
        return self.mono

    def 推进毫秒(self, 毫秒: float) -> None:
        self.perf += float(毫秒) / 1000.0

    def 推进秒(self, 秒: float) -> None:
        self.mono += float(秒)
        self.perf += float(秒)


class 按命令路由Runner:
    """根据 ADB 命令路由返回值，并按每个后端耗时模拟确定性耗时。"""

    def __init__(self, *, 时钟: 模拟Clock | None = None, MuMu模式: bool = False):
        self.时钟 = 时钟
        self.MuMu模式 = MuMu模式
        self.命令历史: list[list[str]] = []
        self.后端延迟ms: dict[str, float] = {
            BACKEND_ADB_RAW: 30.0,
            BACKEND_ADB_RAW_GZIP: 18.0,
            BACKEND_ADB_PNG: 90.0,
        }
        self.后端响应队列: dict[str, list[object]] = {
            BACKEND_ADB_RAW: [],
            BACKEND_ADB_RAW_GZIP: [],
            BACKEND_ADB_PNG: [],
        }
        self.后端默认输出: dict[str, bytes] = {}
        self.窗口状态文本 = MUMU窗口CoC
        self.显示状态文本 = MUMU显示层CoC
        self.设备列表输出 = MUMU设备列表 if MuMu模式 else 在线模拟器

    def 设后端响应(self, 后端: str, *项) -> None:
        self.后端响应队列[后端] = list(项)

    def _取后端结果(self, 后端: str):
        if self.时钟 is not None:
            self.时钟.推进毫秒(self.后端延迟ms.get(后端, 20.0))
        队列 = self.后端响应队列.get(后端)
        if 队列:
            项 = 队列.pop(0)
            if isinstance(项, BaseException):
                raise 项
            if callable(项):
                项 = 项()
            if isinstance(项, SimpleNamespace):
                return 项
            return SimpleNamespace(returncode=0, stdout=项, stderr=b"")
        return SimpleNamespace(
            returncode=0,
            stdout=self.后端默认输出.get(后端, b""),
            stderr=b"",
        )

    def __call__(self, 命令, **kwargs):
        命令 = [str(x) for x in 命令]
        self.命令历史.append(命令)
        if "devices" in 命令 and "-l" in 命令:
            return SimpleNamespace(returncode=0, stdout=self.设备列表输出, stderr=b"")
        if "dumpsys" in 命令 and "input" in 命令:
            return SimpleNamespace(
                returncode=0,
                stdout=self.窗口状态文本.encode("utf-8"),
                stderr=b"",
            )
        if "dumpsys" in 命令 and "display" in 命令:
            return SimpleNamespace(
                returncode=0,
                stdout=self.显示状态文本.encode("utf-8"),
                stderr=b"",
            )
        if "exec-out" in 命令:
            if any("gzip" in 参数 for 参数 in 命令):
                return self._取后端结果(BACKEND_ADB_RAW_GZIP)
            if "-p" in 命令:
                return self._取后端结果(BACKEND_ADB_PNG)
            return self._取后端结果(BACKEND_ADB_RAW)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


class 假高速截图器:
    def __init__(self, 帧列表=None, *, 时钟: 模拟Clock | None = None, 延迟ms: float = 4.0):
        self.帧列表 = list(帧列表 or [])
        self.默认帧 = None
        self.时钟 = 时钟
        self.延迟ms = 延迟ms
        self.已停用 = False
        self.已关闭 = False
        self.调用次数 = 0

    def 截图(self):
        self.调用次数 += 1
        if self.时钟 is not None:
            self.时钟.推进毫秒(self.延迟ms)
        if self.已停用:
            return None
        if self.帧列表:
            项 = self.帧列表.pop(0)
            return 项() if callable(项) else 项
        return self.默认帧

    def 关闭(self):
        self.已关闭 = True
        self.已停用 = True


class 像素编码与后端模块测试(unittest.TestCase):
    def test_后端模块保持惰性导入重型图像库(self):
        项目根 = str(Path(__file__).resolve().parents[1])
        代码 = (
            "import json, sys\n"
            "import 模块.截图后端\n"
            "print(json.dumps({'cv2': 'cv2' in sys.modules, 'numpy': 'numpy' in sys.modules}))\n"
        )
        结果 = subprocess.run(
            [sys.executable, "-c", 代码],
            cwd=项目根,
            capture_output=True,
            text=True,
            check=True,
        )
        状态 = json.loads(结果.stdout.strip())
        self.assertEqual(状态, {"cv2": False, "numpy": False})

    def test_多格式原始像素与PNG和Gzip解码一致性(self):
        画面 = 构造测试画面BGR(96, 64)
        PNG基准 = 解码PNG截图(编码PNG(画面))
        self.assertTrue(np.array_equal(PNG基准, 画面))

        # RGBA / RGBX / RGB / BGRA（分别验证 12B 和 16B 头 + adb 警告前缀）
        前缀 = b"WARNING: Multiple displays were found, using default\n"
        for 格式, 头长 in ((1, 16), (1, 12), (2, 16), (3, 16), (5, 16)):
            with self.subTest(格式=格式, 头长=头长):
                原始流 = 编码原始像素(画面, 格式=格式, 头长度=头长, 前缀=前缀)
                解码图 = 解码原始截图(原始流)
                self.assertIsNotNone(解码图)
                self.assertTrue(np.array_equal(解码图, PNG基准))

                压缩流 = 前缀 + gzip.compress(原始流)
                解压图 = 解码Gzip原始截图(压缩流)
                self.assertIsNotNone(解压图)
                self.assertTrue(np.array_equal(解压图, PNG基准))

        # RGB_565 为有损 16-bit 格式，验证通道顺序正确且误差在 565 量化范围内
        原始565 = 编码原始像素(画面, 格式=4, 头长度=16)
        解码565 = 解码原始截图(原始565)
        self.assertIsNotNone(解码565)
        self.assertEqual(解码565.shape, 画面.shape)
        self.assertEqual(解码565.dtype, np.uint8)
        self.assertTrue(画面像素一致(解码565, PNG基准, 最大平均差异=8.0))

    def test_损坏截断Gzip与黑屏和非法帧均被拒绝(self):
        画面 = 构造测试画面BGR(64, 48)
        完整压缩 = gzip.compress(编码原始像素(画面))
        self.assertIsNone(解码Gzip原始截图(完整压缩[:-8]))
        self.assertIsNone(解码Gzip原始截图(b"not gzip stream"))
        self.assertIsNone(解码原始截图(b"bad header bytes"))
        self.assertIsNone(解码PNG截图(b"not png"))

        全黑 = np.zeros((48, 64, 3), dtype=np.uint8)
        self.assertEqual(校验截图帧(全黑)[0], False)
        self.assertEqual(校验截图帧(全黑, 允许全黑=True)[0], True)
        self.assertEqual(校验截图帧(画面, 期望尺寸=(80, 48))[0], False)
        self.assertEqual(校验截图帧(画面[:, :, :2])[0], False)

    def test_构造ADB截图命令参数支持多显ID并拦截非法显示ID(self):
        self.assertEqual(构造ADB截图命令参数(BACKEND_ADB_RAW, "461982"), ["exec-out", "screencap", "-d", "461982"])
        self.assertEqual(
            构造ADB截图命令参数(BACKEND_ADB_RAW_GZIP, "461982"),
            ["exec-out", "screencap -d 461982 | gzip -1"],
        )
        self.assertEqual(
            构造ADB截图命令参数(BACKEND_ADB_PNG, "461982"),
            ["exec-out", "screencap", "-d", "461982", "-p"],
        )
        with self.assertRaises(ValueError):
            构造ADB截图命令参数(BACKEND_ADB_RAW, "6; rm -rf /")


class 启动测速与自动回退测试(unittest.TestCase):
    def setUp(self):
        ADB设备操作类._全局最近ADB服务重置时间 = 0.0

    def _内存充足(self):
        return patch.object(
            ADB设备操作类,
            "_获取主机内存状态",
            return_value={
                "内存负载": 45,
                "可用物理内存": 8 * 1024 * 1024 * 1024,
                "可用提交额度": 8 * 1024 * 1024 * 1024,
            },
        )

    def test_启动自动测速按耗时选最快后端并仅测速一次复用缓存(self):
        时钟 = 模拟Clock()
        画面 = 构造测试画面BGR(128, 72)
        runner = 按命令路由Runner(时钟=时钟, MuMu模式=False)
        runner.后端延迟ms = {
            BACKEND_ADB_RAW: 42.0,
            BACKEND_ADB_RAW_GZIP: 14.0,
            BACKEND_ADB_PNG: 110.0,
        }
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(画面),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(画面)),
            BACKEND_ADB_PNG: 编码PNG(画面),
        }
        日志: list[str] = []
        设备 = ADB设备操作类(
            ADB,
            "emulator-5554",
            runner=runner,
            启用截图测速=True,
            日志回调=日志.append,
        )

        with (
            self._内存充足(),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            第一帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(设备._截图测速已完成)
            self.assertEqual(设备._已选截图后端, BACKEND_ADB_RAW_GZIP)
            self.assertEqual(
                设备._截图测速报告.可用后端顺序,
                (BACKEND_ADB_RAW_GZIP, BACKEND_ADB_RAW, BACKEND_ADB_PNG),
            )
            测速后命令数 = len(runner.命令历史)

            # 后续截图应直接复用已缓存的最快后端，不再重新跑测速流程
            第二帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            第三帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)

        self.assertTrue(np.array_equal(第一帧, 画面))
        self.assertTrue(np.array_equal(第二帧, 画面))
        self.assertTrue(np.array_equal(第三帧, 画面))
        后续命令 = runner.命令历史[测速后命令数:]
        self.assertEqual(len(后续命令), 2)
        self.assertTrue(all(any("gzip" in p for p in cmd) for cmd in 后续命令))
        self.assertTrue(any("已选最快通道：adb_raw_gzip" in 文本 for 文本 in 日志))

    def test_测速接入MuMuIPC择优并在运行期失败回退与冷却恢复(self):
        时钟 = 模拟Clock()
        画面 = 构造测试画面BGR(128, 72)
        runner = 按命令路由Runner(时钟=时钟, MuMu模式=True)
        runner.后端延迟ms = {
            BACKEND_ADB_RAW: 25.0,
            BACKEND_ADB_RAW_GZIP: 45.0,
            BACKEND_ADB_PNG: 95.0,
        }
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(画面),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(画面)),
            BACKEND_ADB_PNG: 编码PNG(画面),
        }
        高速器 = 假高速截图器(时钟=时钟, 延迟ms=3.0)
        高速器.默认帧 = 画面.copy()

        日志: list[str] = []
        设备 = ADB设备操作类(
            ADB,
            "127.0.0.1:16384",
            runner=runner,
            启用截图测速=True,
            日志回调=日志.append,
        )
        设备.设置目标包名("com.supercell.clashofclans")

        with (
            self._内存充足(),
            patch.object(设备, "_获取高速截图器", return_value=高速器),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            # 1) 启动自动测速选出 MuMu IPC，且每条 ADB 命令都绑定物理 display ID
            首帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(np.array_equal(首帧, 画面))
            self.assertEqual(设备._已选截图后端, BACKEND_MUMU_IPC)
            self.assertTrue(设备._高速截图已核对)
            for cmd in runner.命令历史:
                if "exec-out" in cmd:
                    cmd_str = " ".join(cmd)
                    self.assertIn("-d 4619827203584079877", cmd_str)

            # 2) 运行期高速截图突然返回 None -> 同帧无缝回退到次快的 adb_raw
            高速器.帧列表 = [None]
            回退帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(np.array_equal(回退帧, 画面))
            self.assertEqual(设备._已选截图后端, BACKEND_ADB_RAW)
            self.assertTrue(any("[截图回退] 后端 mumu_ipc 失败" in s and "adb_raw" in s for s in 日志))

            # 3) 冷却期内继续使用 adb_raw（不再请求高速截图）
            此前ipc调用 = 高速器.调用次数
            冷却期帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(np.array_equal(冷却期帧, 画面))
            self.assertEqual(高速器.调用次数, 此前ipc调用)

            # 4) 冷却期过后自动恢复优先尝试 mumu_ipc 并切回首选通道
            时钟.推进秒(设备._截图后端冷却秒数 + 1.0)
            恢复帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(np.array_equal(恢复帧, 画面))
            self.assertGreater(高速器.调用次数, 此前ipc调用)
            self.assertEqual(设备._已选截图后端, BACKEND_MUMU_IPC)

    def test_测速阶段淘汰黑屏_空帧_错分辨率_损坏流后仍选出有效后端(self):
        时钟 = 模拟Clock()
        画面 = 构造测试画面BGR(128, 72)
        全黑 = np.zeros((72, 128, 3), dtype=np.uint8)
        错尺寸画面 = 构造测试画面BGR(64, 48)

        runner = 按命令路由Runner(时钟=时钟, MuMu模式=False)
        runner.后端延迟ms = {
            BACKEND_ADB_RAW: 15.0,
            BACKEND_ADB_RAW_GZIP: 20.0,
            BACKEND_ADB_PNG: 60.0,
        }
        # adb_raw 返回全黑，adb_raw_gzip 返回截断无效流，adb_png 正常
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(全黑),
            BACKEND_ADB_RAW_GZIP: b"\x1f\x8b\x08broken",
            BACKEND_ADB_PNG: 编码PNG(画面),
        }

        # 高速截图返回分辨率不一致的画面，测速应淘汰它而不误选
        高速器 = 假高速截图器(时钟=时钟, 延迟ms=2.0)
        高速器.默认帧 = 错尺寸画面

        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner, 启用截图测速=True)
        设备.设置目标包名("com.supercell.clashofclans")
        with (
            self._内存充足(),
            patch.object(设备, "_获取高速截图器", return_value=高速器),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)

        self.assertTrue(np.array_equal(帧, 画面))
        self.assertEqual(设备._已选截图后端, BACKEND_ADB_PNG)
        self.assertEqual(设备._截图测速报告.可用后端顺序, (BACKEND_ADB_PNG,))
        结果按名 = {项.后端: 项 for 项 in 设备._截图测速报告.结果列表}
        self.assertIn("画面全黑", 结果按名[BACKEND_ADB_RAW].原因)
        self.assertFalse(结果按名[BACKEND_ADB_RAW_GZIP].可用)
        self.assertFalse(结果按名[BACKEND_MUMU_IPC].可用)

    def test_adb_raw运行期返回无法解析数据时永久禁用并回退到PNG(self):
        时钟 = 模拟Clock()
        画面 = 构造测试画面BGR(128, 72)
        runner = 按命令路由Runner(时钟=时钟, MuMu模式=False)
        runner.后端延迟ms = {
            BACKEND_ADB_RAW: 10.0,
            BACKEND_ADB_RAW_GZIP: 35.0,
            BACKEND_ADB_PNG: 70.0,
        }
        # 测速期 2 帧用有效 raw；随后运行期变成损坏原始字节，gzip 也置空触发继续回退到 PNG
        runner.设后端响应(
            BACKEND_ADB_RAW,
            编码原始像素(画面),
            编码原始像素(画面),
            b"corrupt_raw_payload",
        )
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: b"corrupt_raw_payload",
            BACKEND_ADB_RAW_GZIP: b"",
            BACKEND_ADB_PNG: 编码PNG(画面),
        }
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner, 启用截图测速=True)
        with (
            self._内存充足(),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            第一帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertEqual(设备._已选截图后端, BACKEND_ADB_RAW)

            # 第二帧：adb_raw 损坏 -> 回退 adb_raw_gzip（空数据）-> 回退 adb_png 成功
            第二帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertIn(BACKEND_ADB_RAW, 设备._永久禁用截图后端)
            self.assertTrue(设备._截图使用PNG)
            self.assertEqual(设备._已选截图后端, BACKEND_ADB_PNG)

        self.assertTrue(np.array_equal(第一帧, 画面))
        self.assertTrue(np.array_equal(第二帧, 画面))

    def test_目标包变化或全部测速失败时的重置与恢复行为(self):
        时钟 = 模拟Clock()
        画面 = 构造测试画面BGR(128, 72)
        runner = 按命令路由Runner(时钟=时钟, MuMu模式=False)
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(画面),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(画面)),
            BACKEND_ADB_PNG: 编码PNG(画面),
        }
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner, 启用截图测速=True)

        with (
            self._内存充足(),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(设备._截图测速已完成)

            # 切换目标包会清空测速状态，下一次截图自动重测
            设备.设置目标包名("com.supercell.clashofclans")
            self.assertFalse(设备._截图测速已完成)
            设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(设备._截图测速已完成)

        # 全黑失败后不能永久锁定空结果；画面恢复后下次仍可正常完成测速
        全黑 = np.zeros((72, 128, 3), dtype=np.uint8)
        runner2 = 按命令路由Runner(时钟=时钟, MuMu模式=False)
        runner2.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(全黑),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(全黑)),
            BACKEND_ADB_PNG: 编码PNG(全黑),
        }
        设备2 = ADB设备操作类(ADB, "emulator-5554", runner=runner2, 启用截图测速=True)
        with (
            self._内存充足(),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            with self.assertRaisesRegex(ADB错误, "截图测速未找到可用后端"):
                设备2.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertFalse(设备2._截图测速已完成)

            runner2.后端默认输出 = {
                BACKEND_ADB_RAW: 编码原始像素(画面),
                BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(画面)),
                BACKEND_ADB_PNG: 编码PNG(画面),
            }
            恢复帧 = 设备2.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(np.array_equal(恢复帧, 画面))
            self.assertTrue(设备2._截图测速已完成)

    def test_MuMuIPC延迟核对晋升与连续黑屏永久淘汰(self):
        时钟 = 模拟Clock()
        画面 = 构造测试画面BGR(128, 72)
        全黑 = np.zeros((72, 128, 3), dtype=np.uint8)
        runner = 按命令路由Runner(时钟=时钟, MuMu模式=True)
        runner.后端延迟ms = {
            BACKEND_ADB_RAW: 20.0,
            BACKEND_ADB_RAW_GZIP: 35.0,
            BACKEND_ADB_PNG: 80.0,
        }
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(画面),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(画面)),
            BACKEND_ADB_PNG: 编码PNG(画面),
        }
        # 测速期高速截图返回 None（游戏刚启动未渲染出层），但后续截图返回正常画面
        高速器 = 假高速截图器(帧列表=[None], 时钟=时钟, 延迟ms=2.0)
        高速器.默认帧 = 画面.copy()

        设备 = ADB设备操作类(ADB, "127.0.0.1:16384", runner=runner, 启用截图测速=True)
        设备.设置目标包名("com.supercell.clashofclans")
        with (
            self._内存充足(),
            patch.object(设备, "_获取高速截图器", return_value=高速器),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
        ):
            # 1) 测速暂时选 adb_raw，标记 _待核对高速截图
            设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertEqual(设备._已选截图后端, BACKEND_ADB_RAW)
            self.assertTrue(设备._待核对高速截图)

            # 2) 下一次截图 adb_raw 成功并完成高速截图核对，自动晋升 mumu_ipc 为首选
            设备.获取屏幕图像cv(0, 0, 2000, 2000)
            self.assertTrue(设备._高速截图已核对)
            self.assertEqual(设备._已选截图后端, BACKEND_MUMU_IPC)

            # 3) 连续 3 次返回全黑后永久停用 mumu_ipc，不再进入冷却重试
            高速器.默认帧 = 全黑
            for _ in range(3):
                帧 = 设备.获取屏幕图像cv(0, 0, 2000, 2000)
                self.assertTrue(np.array_equal(帧, 画面))
                时钟.推进秒(设备._截图后端冷却秒数 + 1.0)
            self.assertIn(BACKEND_MUMU_IPC, 设备._永久禁用截图后端)
            self.assertTrue(高速器.已关闭)

    def test_不绕过主机内存保护与MuMu多显FailClosed与实体设备拦截(self):
        画面 = 构造测试画面BGR(128, 72)
        runner = 按命令路由Runner(MuMu模式=True)
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(画面),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(画面)),
            BACKEND_ADB_PNG: 编码PNG(画面),
        }

        # 1) 宿主机内存不足必须立即中断，绝不跳过护栏继续测速
        设备1 = ADB设备操作类(ADB, "127.0.0.1:16384", runner=runner, 启用截图测速=True)
        设备1.设置目标包名("com.supercell.clashofclans")
        with patch.object(
            ADB设备操作类,
            "_获取主机内存状态",
            return_value={
                "内存负载": 96,
                "可用物理内存": 300 * 1024 * 1024,
                "可用提交额度": 400 * 1024 * 1024,
            },
        ):
            with self.assertRaisesRegex(ADB错误, "主机内存保护已触发"):
                设备1.获取屏幕图像cv(0, 0, 2000, 2000)

        # 2) MuMu 多显找不到 CoC display 时必须 fail-closed，绝不退回默认 display 0 测速
        runner.窗口状态文本 = "FocusedWindows:\n  displayId=0, name='Window{1 u0 com.mumu.launcher}'"
        设备2 = ADB设备操作类(ADB, "127.0.0.1:16384", runner=runner, 启用截图测速=True)
        设备2.设置目标包名("com.supercell.clashofclans")
        with (
            self._内存充足(),
            patch("模块.ADB设备操作类.time.sleep"),
        ):
            with self.assertRaisesRegex(ADB错误, "MuMu 游戏显示层"):
                设备2.获取屏幕图像cv(0, 0, 2000, 2000)
        self.assertFalse(any("exec-out" in cmd for cmd in runner.命令历史))

        # 3) 实体手机拦截优先于测速和截图
        真机runner = 按命令路由Runner(MuMu模式=False)
        真机runner.设备列表输出 = b"List of devices attached\nR58N999 device product:a55x model:SM_A5560\n"
        设备3 = ADB设备操作类(ADB, "R58N999", runner=真机runner, 启用截图测速=True)
        with self.assertRaisesRegex(ADB错误, "实体 Android 设备"):
            设备3.获取屏幕图像cv(0, 0, 2000, 2000)
        self.assertFalse(any("exec-out" in cmd for cmd in 真机runner.命令历史))

    def test_参考区域裁剪与ADB屏幕日志转发及05秒缓存复用(self):
        时钟 = 模拟Clock()
        大画面 = 构造测试画面BGR(1280, 720)
        runner = 按命令路由Runner(时钟=时钟, MuMu模式=False)
        runner.后端延迟ms = {
            BACKEND_ADB_RAW: 12.0,
            BACKEND_ADB_RAW_GZIP: 25.0,
            BACKEND_ADB_PNG: 80.0,
        }
        runner.后端默认输出 = {
            BACKEND_ADB_RAW: 编码原始像素(大画面),
            BACKEND_ADB_RAW_GZIP: gzip.compress(编码原始像素(大画面)),
            BACKEND_ADB_PNG: 编码PNG(大画面),
        }
        日志: list[str] = []
        设备 = ADB设备操作类(ADB, "emulator-5554", runner=runner, 启用截图测速=True)
        屏幕 = ADB屏幕(设备, 日志回调=日志.append)

        with (
            self._内存充足(),
            patch("模块.ADB设备操作类.time.perf_counter", side_effect=时钟.perf_counter),
            patch("模块.ADB设备操作类.time.monotonic", side_effect=时钟.monotonic),
            patch("time.monotonic", side_effect=时钟.monotonic),
        ):
            报告 = 屏幕.测速选择截图后端(采样帧数=1)
            self.assertEqual(报告.首选后端, BACKEND_ADB_RAW)
            self.assertTrue(any("已选最快通道：adb_raw" in 文本 for 文本 in 日志))

            全屏 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
            self.assertEqual(全屏.shape, (600, 800, 3))
            命令数 = len(runner.命令历史)

            # 0.5 秒内复用缓存，不产生新的 screencap
            局部 = 屏幕.获取屏幕图像cv(100, 50, 500, 350)
            self.assertEqual(局部.shape, (300, 400, 3))
            self.assertEqual(len(runner.命令历史), 命令数)

            # 绑定重置缓存与清理
            屏幕.安全清理()
            self.assertFalse(设备._截图测速已完成)
            屏幕.绑定(设备)
            self.assertIsNone(屏幕._原始截图缓存)


if __name__ == "__main__":
    unittest.main()
