"""异常自动留证：卡住、未知页面、任务异常退出时把现场保存到 EXE 同级 ``异常现场/``。

每次留证一个子目录 ``异常现场/<YYYYMMDD_HHMMSS_mmm>_<类别>/``，内含：
- ``当前.png``：触发时的画面（调用方提供，或取最近缓存帧）；
- ``前序_<序号>_<时分秒>.jpg``：触发前最近几帧（截图时顺手缓存）；
- ``摘要.txt``：类别、原因、时间、版本号和最近日志摘要。

不阻塞调用方：截图路径只做节流判断并把帧引用交给后台线程缩放/编码；
心跳停止、任务退出路径只做节流判断和取引用，读库、PNG/JPG 编码、写盘和
轮转全部在后台写盘线程里做。两条后台队列都有界，满了丢弃最旧的任务。

只保留最近 N 份（默认 30，可在设置里改；0 表示关闭留证），超出时删除最旧的
留证子目录。主人已批准 **仅在 ``异常现场/`` 目录内** 自动轮转；删除前校验目录名
符合本模块生成的格式，绝不碰其它文件。所有函数吞掉异常，留证失败绝不影响脚本。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

目录名 = "异常现场"
默认保留份数 = 30
前序帧数 = 5
帧缓存最短间隔秒 = 1.5
同类留证最短间隔秒 = 60.0
_留证目录正则 = re.compile(r"^\d{8}_\d{6}_\d{3}_[^\\/]{1,44}$")
_非法文件名字符 = re.compile(r'[\\/:*?"<>|\s]+')


def 程序目录() -> Path:
    """打包版在 Windows 为 EXE 所在目录、macOS .app 为用户数据目录；源码运行为仓库根目录。"""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            from 工具包.运行路径 import 获取macOS数据根目录

            return 获取macOS数据根目录(创建=True)
        return Path(os.path.abspath(sys.executable)).parent
    return Path(__file__).resolve().parent.parent


def 读取版本号(根目录: Optional[Path] = None) -> str:
    try:
        from 工具包.版本管理 import 获取本地版本号

        版本 = str(获取本地版本号() or "").strip()
        if 版本:
            return 版本
    except Exception:
        pass
    try:
        return (Path(根目录 or 程序目录()) / "版本号.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return "未知"


class 有界后台队列:
    """单个守护线程按顺序执行任务；队列满时丢弃最旧的任务，提交永不阻塞。"""

    def __init__(self, 名称: str, 容量: int):
        self.名称 = 名称
        self.容量 = max(1, int(容量))
        self.丢弃数 = 0
        self._队列: deque = deque()
        self._条件 = threading.Condition()
        self._进行中 = 0
        self._线程: Optional[threading.Thread] = None

    def 提交(self, 任务: Callable[[], object]) -> bool:
        with self._条件:
            if len(self._队列) >= self.容量:
                self._队列.popleft()
                self.丢弃数 += 1
            self._队列.append(任务)
            if self._线程 is None or not self._线程.is_alive():
                self._线程 = threading.Thread(target=self._循环, name=self.名称, daemon=True)
                self._线程.start()
            self._条件.notify_all()
        return True

    def _循环(self) -> None:
        while True:
            with self._条件:
                while not self._队列:
                    self._条件.wait()
                任务 = self._队列.popleft()
                self._进行中 += 1
            try:
                任务()
            except Exception:
                pass
            finally:
                with self._条件:
                    self._进行中 -= 1
                    self._条件.notify_all()

    def 等待空闲(self, 超时: float = 10.0) -> bool:
        """测试/退出用：等队列清空且没有正在执行的任务。"""
        with self._条件:
            return self._条件.wait_for(
                lambda: not self._队列 and self._进行中 == 0, timeout=超时
            )


帧编码队列 = 有界后台队列("异常留证-帧编码", 3)
留证写盘队列 = 有界后台队列("异常留证-写盘", 8)


def 等待后台空闲(超时: float = 10.0) -> bool:
    return 帧编码队列.等待空闲(超时) and 留证写盘队列.等待空闲(超时)


class 近期帧缓存:
    """按机器人缓存最近几帧（JPEG 字节），供留证时还原“前几步”的画面。"""

    def __init__(self, 帧数: int = 前序帧数, 最短间隔秒: float = 帧缓存最短间隔秒,
                 时钟=time.time, 编码队列: Optional[有界后台队列] = None):
        self._帧数 = max(1, int(帧数))
        self._最短间隔秒 = float(最短间隔秒)
        self._时钟 = 时钟
        self._编码队列 = 编码队列 or 帧编码队列
        self._锁 = threading.Lock()
        self._缓存: dict[str, deque] = {}
        self._上次记录: dict[str, float] = {}

    def 记录(self, 机器人标志: str, 图像) -> bool:
        """节流后把帧交给后台编码；截图线程里只做判断和入队，返回是否入队。"""
        try:
            if 图像 is None or not hasattr(图像, "shape") or getattr(图像, "size", 0) == 0:
                return False
            标志 = str(机器人标志)
            现在 = float(self._时钟())
            with self._锁:
                上次 = self._上次记录.get(标志)
                if 上次 is not None and 现在 - 上次 < self._最短间隔秒:
                    return False
                self._上次记录[标志] = 现在
            # 截图提供器每次都换新数组、返回裁剪副本，不会原地改这张图，
            # 后台线程持有引用是安全的。
            return self._编码队列.提交(lambda: self._编码并追加(标志, 现在, 图像))
        except Exception:
            return False

    def _编码并追加(self, 标志: str, 时间: float, 图像) -> None:
        import cv2

        高, 宽 = 图像.shape[:2]
        if 宽 > 800:
            图像 = cv2.resize(图像, (800, max(1, round(高 * 800 / 宽))), interpolation=cv2.INTER_AREA)
        成功, 数据 = cv2.imencode(".jpg", 图像, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not 成功:
            return
        with self._锁:
            self._缓存.setdefault(标志, deque(maxlen=self._帧数)).append((时间, 数据.tobytes()))

    def 取出(self, 机器人标志: str) -> list[tuple[float, bytes]]:
        with self._锁:
            return list(self._缓存.get(str(机器人标志), ()))

    def 清空(self, 机器人标志: Optional[str] = None) -> None:
        with self._锁:
            if 机器人标志 is None:
                self._缓存.clear()
                self._上次记录.clear()
            else:
                self._缓存.pop(str(机器人标志), None)
                self._上次记录.pop(str(机器人标志), None)


共享帧缓存 = 近期帧缓存()
_上次留证: dict[tuple[str, str], float] = {}
_留证锁 = threading.Lock()
_上次目录名 = {"名称": "", "序号": 0}


def 安装帧缓存(op, 机器人标志: str, 缓存: Optional[近期帧缓存] = None) -> None:
    """让截图提供器在取到新帧时顺手写入近期帧缓存。"""
    目标 = 缓存 or 共享帧缓存
    try:
        op._新帧回调 = lambda 图像: 目标.记录(机器人标志, 图像)
    except Exception:
        pass


def 异常现场根目录(根目录: Optional[Path] = None) -> Path:
    return Path(根目录 or 程序目录()) / 目录名


def 列出留证目录(根目录: Optional[Path] = None) -> list[Path]:
    """按时间升序列出本模块生成的留证子目录（名称不符合格式的一律忽略）。"""
    根 = 异常现场根目录(根目录)
    if not 根.is_dir():
        return []
    try:
        return sorted(
            项 for 项 in 根.iterdir()
            if 项.is_dir() and not 项.is_symlink() and _留证目录正则.match(项.name)
        )
    except OSError:
        return []


def 轮转留证目录(保留份数: int, 根目录: Optional[Path] = None) -> list[Path]:
    """只在 ``异常现场/`` 内删除最旧的留证子目录，返回被删除的目录。"""
    保留 = max(0, int(保留份数))
    全部 = 列出留证目录(根目录)
    多余 = 全部[: max(0, len(全部) - 保留)]
    根 = 异常现场根目录(根目录).resolve()
    已删除 = []
    for 目录 in 多余:
        try:
            if 目录.resolve().parent != 根:
                continue
            shutil.rmtree(目录)
            已删除.append(目录)
        except OSError:
            continue
    return 已删除


def _安全类别(类别: str) -> str:
    文本 = _非法文件名字符.sub("_", str(类别 or "异常")).strip("_.")
    return (文本 or "异常")[:40]


def _生成目录名(类别: str, 现在: float) -> str:
    """纯内存生成唯一目录名（同一毫秒同类别追加序号），不做任何 IO。"""
    名称 = (
        time.strftime("%Y%m%d_%H%M%S", time.localtime(现在))
        + f"_{int((现在 % 1) * 1000):03d}_{_安全类别(类别)}"
    )
    with _留证锁:
        if _上次目录名["名称"] == 名称:
            _上次目录名["序号"] += 1
            return f"{名称}{_上次目录名['序号']}"
        _上次目录名.update(名称=名称, 序号=1)
    return 名称


def 写入异常现场(
    目录名称: str,
    类别: str,
    原因: str,
    *,
    机器人标志: str = "",
    当前图像=None,
    前序帧: Iterable[tuple[float, bytes]] = (),
    日志摘要: Iterable[str] = (),
    保留份数: int = 默认保留份数,
    根目录: Optional[Path] = None,
    触发时间: Optional[float] = None,
) -> Optional[Path]:
    """同步写一份留证（在后台写盘线程里调用）；失败返回 None。"""
    try:
        前序帧 = list(前序帧)
        根 = 异常现场根目录(根目录)
        根.mkdir(parents=True, exist_ok=True)
        目录 = 根 / 目录名称
        序号 = 1
        while 目录.exists():
            序号 += 1
            目录 = 根 / f"{目录名称}_{序号}"
        目录.mkdir()

        已保存当前 = False
        if 当前图像 is not None and hasattr(当前图像, "shape"):
            try:
                import cv2

                成功, 数据 = cv2.imencode(".png", 当前图像)
                if 成功:
                    (目录 / "当前.png").write_bytes(数据.tobytes())
                    已保存当前 = True
            except Exception:
                pass
        if not 已保存当前 and 前序帧:
            # 线程已卡住/截图已失败时不再调用 ADB，用最近缓存帧当“当前”画面。
            (目录 / "当前_最近缓存帧.jpg").write_bytes(前序帧[-1][1])
        for 索引, (帧时间, 数据) in enumerate(前序帧, start=1):
            帧名 = f"前序_{索引:02d}_{time.strftime('%H%M%S', time.localtime(帧时间))}.jpg"
            (目录 / 帧名).write_bytes(数据)

        时间 = time.localtime(time.time() if 触发时间 is None else 触发时间)
        摘要行 = [
            f"类别：{类别}",
            f"原因：{原因}",
            f"机器人：{机器人标志 or '-'}",
            f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', 时间)}",
            f"版本：{读取版本号(根目录)}",
            f"前序帧：{len(前序帧)} 张",
            "",
            "—— 最近日志 ——",
            *[str(行) for 行 in 日志摘要],
        ]
        (目录 / "摘要.txt").write_text("\n".join(摘要行) + "\n", encoding="utf-8")
        轮转留证目录(保留份数, 根目录)
        return 目录
    except Exception:
        return None


def _求值(值, 默认):
    try:
        return 值() if callable(值) else 值
    except Exception:
        return 默认


def 保存异常现场(
    类别: str,
    原因: str,
    *,
    机器人标志: str = "",
    当前图像=None,
    日志摘要: Union[Iterable[str], Callable[[], Iterable[str]]] = (),
    保留份数: Union[int, Callable[[], int]] = 默认保留份数,
    根目录: Optional[Path] = None,
    帧缓存: Optional[近期帧缓存] = None,
    时钟=time.time,
    同类最短间隔秒: float = 同类留证最短间隔秒,
    前置检查: Optional[Callable[[], bool]] = None,
    完成回调: Optional[Callable[[Path], object]] = None,
    写盘队列: Optional[有界后台队列] = None,
) -> bool:
    """非阻塞地安排一份留证，返回是否已入队。

    调用线程只做同类节流判断、取前序帧快照和入队；``前置检查``、``保留份数``、
    ``日志摘要`` 可以传可调用对象，在后台线程里才求值（读设置/读库不阻塞调用方）。
    写完后在后台线程调用 ``完成回调(实际目录)``。
    """
    try:
        if not callable(保留份数):
            try:
                if int(保留份数) <= 0:
                    return False
            except (TypeError, ValueError):
                保留份数 = 默认保留份数
        现在 = float(时钟())
        键 = (str(机器人标志), str(类别))
        with _留证锁:
            上次 = _上次留证.get(键)
            if 上次 is not None and 0 <= 现在 - 上次 < float(同类最短间隔秒):
                return False
            _上次留证[键] = 现在
        前序帧 = (帧缓存 or 共享帧缓存).取出(机器人标志)
        目录名称 = _生成目录名(类别, 现在)

        def 任务():
            if 前置检查 is not None and not _求值(前置检查, False):
                return
            try:
                保留 = int(_求值(保留份数, 默认保留份数))
            except (TypeError, ValueError):
                保留 = 默认保留份数
            if 保留 <= 0:
                return
            摘要 = list(_求值(日志摘要, ()) or ())
            路径 = 写入异常现场(
                目录名称, 类别, 原因,
                机器人标志=机器人标志, 当前图像=当前图像, 前序帧=前序帧,
                日志摘要=摘要, 保留份数=保留, 根目录=根目录, 触发时间=现在,
            )
            if 路径 is not None and 完成回调 is not None:
                完成回调(路径)

        return (写盘队列 or 留证写盘队列).提交(任务)
    except Exception:
        return False


def 格式化日志摘要(日志列表, 条数: int = 40) -> list[str]:
    """把数据库 ``任务日志`` 记录（新→旧）整理成按时间正序的文本行。"""
    行列表 = []
    try:
        for 日志 in list(日志列表 or [])[: max(0, int(条数))]:
            时间 = time.strftime(
                "%m-%d %H:%M:%S", time.localtime(float(getattr(日志, "记录时间", 0) or 0))
            )
            行列表.append(f"{时间} {getattr(日志, '日志内容', '')}")
    except Exception:
        pass
    行列表.reverse()
    return 行列表
