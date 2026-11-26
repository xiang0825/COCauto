import ctypes
import ctypes.wintypes
import gc
import importlib
import os
import queue
import random
import sys
import threading
import time

from 数据库.任务数据库 import (
    任务数据库,
    机器人设置,
    规范化任务计划顺序,
    任务计划是否启用,
    任务计划定义映射,
)
from 模块.ADB设备操作类 import ADB设备操作类
from 核心.异常 import 主机内存保护暂停请求
from 核心.核心异常们 import 图像获取失败


class _延迟导入对象:
    """兼容原有可调用入口，但把重型任务模块推迟到真正执行时。"""

    def __init__(self, 模块名: str, 对象名: str):
        self.模块名 = 模块名
        self.对象名 = 对象名
        self._对象 = None

    def _解析(self):
        if self._对象 is None:
            模块 = importlib.import_module(self.模块名)
            self._对象 = getattr(模块, self.对象名)
        return self._对象

    def __call__(self, *参数, **关键字):
        return self._解析()(*参数, **关键字)

    def __getattr__(self, 名称):
        return getattr(self._解析(), 名称)


到主世界任务 = _延迟导入对象("任务流程.世界跳转.到主世界任务", "到主世界任务")
到夜世界任务 = _延迟导入对象("任务流程.世界跳转.到夜世界任务", "到夜世界任务")
主世界打鱼任务 = _延迟导入对象("任务流程.主世界打鱼", "主世界打鱼任务")
城墙升级任务 = _延迟导入对象("任务流程.升级城墙", "城墙升级任务")
启动模拟器任务 = _延迟导入对象("任务流程.启动模拟器", "启动模拟器任务")
任务上下文 = _延迟导入对象("任务流程.基础任务框架", "任务上下文")
夜世界打鱼任务 = _延迟导入对象("任务流程.夜世界.夜世界打鱼", "夜世界打鱼任务")
收集圣水车任务 = _延迟导入对象("任务流程.夜世界.收集圣水车", "收集圣水车任务")
更新夜世界资源状态任务 = _延迟导入对象(
    "任务流程.夜世界.更新夜世界账号资源状态", "更新夜世界资源状态任务"
)
建筑升级任务 = _延迟导入对象("任务流程.建筑升级", "建筑升级任务")
收集资源任务 = _延迟导入对象("任务流程.收集资源", "收集资源任务")
战宠升级任务 = _延迟导入对象("任务流程.战宠升级", "战宠升级任务")
兵种或法术升级任务 = _延迟导入对象(
    "任务流程.兵种或法术升级", "兵种或法术升级任务"
)
更新家乡资源状态任务 = _延迟导入对象(
    "任务流程.更新主世界账号资源状态", "更新家乡资源状态任务"
)
检查图像任务 = _延迟导入对象("任务流程.检查图像", "检查图像任务")
编辑军队任务 = _延迟导入对象("任务流程.军队配置.编辑军队", "编辑军队任务")
检测游戏登录状态任务 = _延迟导入对象(
    "任务流程.检测游戏登录状态", "检测游戏登录状态任务"
)
是否家乡资源打满 = _延迟导入对象("工具包.工具函数", "是否家乡资源打满")
是否目标资源打满 = _延迟导入对象("工具包.工具函数", "是否目标资源打满")
是否夜世界资源打满 = _延迟导入对象("工具包.工具函数", "是否夜世界资源打满")
ADB屏幕 = _延迟导入对象("核心.ADB屏幕", "ADB屏幕")
键盘控制器 = _延迟导入对象("核心.键盘操作", "键盘控制器")
鼠标控制器 = _延迟导入对象("核心.鼠标操作", "鼠标控制器")
模板匹配引擎 = _延迟导入对象("模块.检测.模板匹配器", "模板匹配引擎")


def _安全控制台打印(*参数, **关键字):
    """控制台编码异常不能影响机器人线程或停止流程。"""
    try:
        print(*参数, **关键字)
    except (UnicodeEncodeError, OSError, ValueError):
        pass


class _进程内存计数EX(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _采集进程资源指标() -> dict:
    """采集当前进程 RSS、私有内存(MB)、线程数与句柄数，失败安全返回已有指标。"""
    指标: dict[str, float | int | None] = {
        "rss_mb": None,
        "private_mb": None,
        "threads": threading.active_count(),
        "handles": None,
    }
    if sys.platform != "win32":
        return 指标
    try:
        # 独立 WinDLL 实例并声明 64 位 HANDLE 原型：默认 c_int 会把
        # GetCurrentProcess 的伪句柄截成 32 位，调用全部静默失败。
        wt = ctypes.wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wt.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetProcessHandleCount.restype = wt.BOOL
        kernel32.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        当前进程 = kernel32.GetCurrentProcess()
        计数 = _进程内存计数EX()
        计数.cb = ctypes.sizeof(_进程内存计数EX)
        get_mem = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if get_mem is None:
            get_mem = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_mem.restype = wt.BOOL
        get_mem.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
        if get_mem(当前进程, ctypes.byref(计数), 计数.cb):
            指标["rss_mb"] = round(计数.WorkingSetSize / (1024 * 1024), 1)
            私有字节 = 计数.PrivateUsage or 计数.PagefileUsage
            指标["private_mb"] = round(私有字节 / (1024 * 1024), 1)
        句柄数 = ctypes.wintypes.DWORD(0)
        if kernel32.GetProcessHandleCount(当前进程, ctypes.byref(句柄数)):
            指标["handles"] = int(句柄数.value)
    except Exception:
        pass
    return 指标


class 自动化机器人:
    """为单个用户提供游戏自动化服务的机器人实例"""

    # 监控中心按秒轮询数据库，而任务线程写入心跳日志也可能恰好落在
    # 同一秒。保留一个很短的宽限，避免在“下一条心跳正在提交”的竞态
    # 窗口内误判无心跳并反复重启机器人。
    心跳超时宽限秒数 = 5
    资源趋势日志间隔秒 = 1800.0
    错误日志最大字节 = 5 * 1024 * 1024

    def _记录进程资源趋势(self, 上下文=None, *, 强制: bool = False) -> bool:
        """每 30 分钟节流记录一次当前进程 RSS/私有内存、线程数与句柄数。"""
        现在 = time.monotonic()
        上次 = float(getattr(self, "_上次资源趋势时间", 0.0) or 0.0)
        if not 强制 and 上次 > 0.0 and 现在 - 上次 < float(self.资源趋势日志间隔秒):
            return False
        self._上次资源趋势时间 = 现在
        try:
            指标 = _采集进程资源指标()
            片段 = []
            if 指标.get("rss_mb") is not None:
                片段.append(f"RSS={指标['rss_mb']:.1f}MB")
            if 指标.get("private_mb") is not None:
                片段.append(f"私有内存={指标['private_mb']:.1f}MB")
            if 指标.get("threads") is not None:
                片段.append(f"线程={指标['threads']}")
            if 指标.get("handles") is not None:
                片段.append(f"句柄={指标['handles']}")
            消息 = "[系统观测] 进程资源趋势：" + "，".join(片段)
            日志函数 = getattr(上下文, "置脚本状态", None) if 上下文 is not None else None
            if callable(日志函数):
                日志函数(消息)
            else:
                self.记录日志(消息)
            return True
        except Exception:
            return False

    def _获取错误日志路径(self) -> str:
        """返回基于数据库目录的 robot-error.log 绝对路径，避免依赖当前工作目录。"""
        数据库路径 = getattr(getattr(self, "数据库", None), "文件路径", None)
        if not 数据库路径 or str(数据库路径) == ":memory:":
            数据库路径 = 任务数据库.默认数据库路径()
        目录 = os.path.dirname(os.path.abspath(str(数据库路径))) or os.path.abspath(".")
        os.makedirs(目录, exist_ok=True)
        return os.path.join(目录, "robot-error.log")

    def _写入未处理异常日志(self, 诊断信息: str) -> str | None:
        """把未捕获异常追加到数据库同目录的 robot-error.log（绝对路径）。

        超过大小上限时把旧文件改名为 robot-error.<时间戳>.log 再写新文件；
        不使用 RotatingFileHandler 的 backupCount，绝不自动删除旧日志。
        """
        try:
            日志路径 = self._获取错误日志路径()
            try:
                if os.path.getsize(日志路径) >= int(self.错误日志最大字节):
                    根, 扩展名 = os.path.splitext(日志路径)
                    归档路径 = f"{根}.{time.strftime('%Y%m%d_%H%M%S')}{扩展名}"
                    if not os.path.exists(归档路径):
                        os.replace(日志路径, 归档路径)
            except OSError:
                pass
            with open(日志路径, "a", encoding="utf-8") as 日志文件:
                日志文件.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} [ERROR] "
                    + 诊断信息.rstrip("\r\n") + "\n"
                )
            return 日志路径
        except OSError:
            return None

    def __init__(self, 机器人标志: str, 消息队列: queue.Queue, 数据库: 任务数据库, 日志队列: queue.Queue):
        # 基础属性
        self.机器人标志 = 机器人标志
        self.消息队列 = 消息队列  # 用来给监控中心发送消息
        self.数据库 = 数据库
        self.日志队列 = 日志队列

        self.继续事件 = threading.Event()
        self.停止事件 = threading.Event()
        self.停止事件.set()  # 目前未启动线程,处于停止状态
        self.停止原因 = "未启动"

        self.op: ADB屏幕

    def 启动(self):
        设置 = self.数据库.获取机器人设置(self.机器人标志)
        if not self._任务计划顺序(设置):
            raise RuntimeError("没有启用任何任务；请先在任务计划中勾选要运行的任务。")
        包名 = getattr(设置, "部落冲突包名", None) or "com.supercell.clashofclans"
        # 连接页启用自动检测且尚未保存 serial 时，按 CoC 包名和当前前台
        # 状态安全绑定设备；多设备并列时仍要求用户手动确认，禁止猜测。
        if getattr(设置, "ADB自动检测路径", True):
            已保存序列号 = (getattr(设置, "ADB设备序列号", "") or "").strip()
            # 已有设备时沿用已保存/常见目录的 adb；没有设备时交给一键检测
            # 选择模拟器自带的 adb，常见目录里找不到也能继续。
            已解析路径 = ADB设备操作类.解析ADB路径(
                设置.ADB路径,
                自动检测=True,
            ) if 已保存序列号 else 设置.ADB路径
            校验设备 = ADB设备操作类(
                已解析路径,
                已保存序列号,
                # 路径已经解析完成，但仍要保留自动设备恢复开关；
                # 模拟器重启后 serial 可能从 127.0.0.1:16416 变成
                # emulator-5556，确认在线时需要允许唯一候选接管。
                自动检测路径=True,
            ) if 已保存序列号 else None
            if 校验设备 is not None:
                校验设备.设置目标包名(包名)
                当前设备 = 校验设备.确认在线()
                设备 = 当前设备
                if 当前设备.序列号 != 已保存序列号:
                    self.数据库.记录日志(
                        self.机器人标志,
                        f"ADB 自动修复失效设备：{已保存序列号} -> {当前设备.序列号}",
                        time.time() + 60,
                    )
            else:
                # 未保存设备时按 MAA 方式一键检测：找到模拟器、连接端口，
                # 只有能唯一确定游戏所在实例时才自动绑定。
                from 模块.模拟器探测 import 检测并选择

                已解析路径, 设备 = 检测并选择(包名, 已解析路径)
            设置.ADB路径 = 已解析路径
            设置.ADB设备序列号 = 设备.序列号
            设置.ADB已确认模拟器 = True
            self.数据库.保存机器人设置(self.机器人标志, 设置)
            self.数据库.记录日志(
                self.机器人标志,
                f"ADB 自动绑定模拟器：{设备.序列号}；前台 CoC 包名已确认",
                time.time() + 60,
            )
        if not 设置.ADB已确认模拟器 or not 设置.ADB设备序列号:
            raise RuntimeError("请先在“模拟器连接”页选择 ADB 设备、确认它是模拟器并保存。")
        # 在创建后台任务前验证路径，避免线程因配置错误静默退出。
        ADB设备操作类.解析ADB路径(
            设置.ADB路径,
            自动检测=getattr(设置, "ADB自动检测路径", True),
        )
        self.数据库.记录日志(self.机器人标志, "开始运行任务计划", time.time() + 60)
        if self.停止事件.is_set():
            self.停止原因 = ""
            # 在启动线程前就进入运行态。否则 F1 后初始化期间会短暂显示
            # “暂停中”，且此时按 F2 的暂停可能被上下文初始化重新 set 覆盖。
            self.继续事件.set()
            self.停止事件.clear()
            #线程执行完毕后不可重复 start，因此在检测到停止事件后需新建线程实例，用于重新启动任务流程。，所以创建线程操作放在启动里面
            self.主线程 = threading.Thread(
                target=self._任务流程,
                name=f"任务线程-{self.机器人标志}",
                daemon=True
            )
            self.主线程.start()

        else:
            _安全控制台打印("目前线程未停止,无需再次启动")

    def _获取防休眠控制器(self):
        控制器 = getattr(self, "_防休眠控制器", None)
        if 控制器 is None:
            from 模块.防休眠 import 防休眠控制器

            控制器 = 防休眠控制器(日志回调=getattr(self, "置脚本状态", None))
            self._防休眠控制器 = 控制器
        return 控制器

    def 暂停(self):
        """标记暂停状态"""
        _安全控制台打印("已暂停")
        self.继续事件.clear()

    def 继续(self):
        """清除暂停状态"""
        _安全控制台打印("已继续")
        曾暂停 = not self.继续事件.is_set()
        if 曾暂停 and not self.停止事件.is_set():
            # 暂停时没有任务日志；先延长数据库心跳窗口，再让监控线程
            # 继续判定，避免 F1 刚恢复就被旧日志的截止时间误停。
            self.记录日志("机器人已从暂停状态继续，等待下一条任务心跳", 120)
        self.继续事件.set()

    def 停止(self, 停止原因="", 等待=True, 超时: float = 10.0):
        """标记终止状态

        注意：此方法由监控中心调用，用于外部强制停止。
        如果是任务异常导致的停止，线程会自己设置停止事件并退出。
        """
        # 窗口关闭和主入口的 finally 都会尝试清理同一实例；保留最初
        # 的停止原因，避免后续“控制台关闭”覆盖界面停止或真实异常。
        if self.停止事件.is_set() and self.停止原因:
            return
        self.停止原因 = (停止原因 or "外部停止").strip()
        try:
            self.记录日志(f"收到外部停止请求：{self.停止原因}", 300, "警告")
        except Exception:
            pass
        self.停止事件.set()
        self.继续()  # 唤醒可能已经暂停的线程
        # 等待线程停止,如果未启动则没有主线程属性,加一层判断
        if 等待 and hasattr(self, "主线程") and self.主线程.is_alive():
            try:
                等待超时 = max(0.1, float(超时))
            except (TypeError, ValueError):
                等待超时 = 10.0
            self.主线程.join(timeout=等待超时)
            if self.主线程.is_alive():
                try:
                    self.记录日志(
                        f"等待任务线程停止超时（{等待超时:g}秒），主线程仍未退出（停止原因：{self.停止原因}）",
                        60,
                        "警告",
                    )
                except Exception:
                    pass

    @property
    def 设置(self) -> 机器人设置:
        配置 = self.数据库.获取机器人设置(self.机器人标志)
        return 配置

    @property
    def 当前状态(self) -> str:
        if self.停止事件.is_set():
            return "已停止"
        elif not self.继续事件.is_set():
            return "暂停中"
        else:
            return "运行中"

    def 记录日志(self, 日志内容: str, 超时的时间: float = 60, 级别: str = "正常"):
        """记录日志到数据库并通过队列发送到UI
        级别: "正常" | "警告" | "错误"（默认"正常"）。保持原有调用兼容，新增关键字参数 级别。
        """

        # 规范级别取值
        合法级别 = {"正常", "警告", "错误"}
        if 级别 not in 合法级别:
            级别 = "正常"

        # 根据级别为文本添加可解析前缀（仅非“正常”时）
        带级别前缀的内容 = 日志内容
        if 级别 != "正常" and not (日志内容.startswith("[警告]") or 日志内容.startswith("[错误]")):
            前缀 = "[警告]" if 级别 == "警告" else "[错误]"
            带级别前缀的内容 = f"{前缀} {日志内容}"

        # 写入数据库（保持原表结构，内容中包含级别前缀）
        记录时间 = self.数据库.记录日志(
            self.机器人标志,
            带级别前缀的内容,
            time.time() + 超时的时间,
        )

        # 发送到UI日志队列（携带结构化级别，便于实时渲染）
        if self.日志队列:
            try:
                self.日志队列.put_nowait({
                    '内容': f"[{time.strftime('%H:%M:%S')}] {带级别前缀的内容}",
                    '机器人ID': self.机器人标志,
                    '类型': '运行',
                    '级别': 级别,
                    '记录时间': 记录时间,
                })
            except queue.Full:
                # 实时队列只服务 UI；满载时丢弃最旧的实时显示消息，
                # 不能让机器人线程阻塞在日志上。完整记录已经写入 SQLite。
                try:
                    self.日志队列.get_nowait()
                    self.日志队列.task_done()
                    self.日志队列.put_nowait({
                        '内容': f"[{time.strftime('%H:%M:%S')}] {带级别前缀的内容}",
                        '机器人ID': self.机器人标志,
                        '类型': '运行',
                        '级别': 级别,
                        '记录时间': 记录时间,
                    })
                except (queue.Empty, queue.Full):
                    pass

        # Windows 的 time.strftime 使用系统 locale，不能在格式串里放中文字符。
        # 控制台只是辅助输出；即使终端编码异常，也不能中断机器人任务线程。
        try:
            print(
                f"[机器人消息] {self.机器人标志} "
                f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {带级别前缀的内容}"
            )
        except Exception:
            pass

    def _任务计划顺序(self, 设置: 机器人设置) -> list[str]:
        """返回规范化的启用任务顺序，顺序完全来自任务计划页面。"""
        顺序 = 规范化任务计划顺序(getattr(设置, "任务计划顺序", None))
        return [任务键 for 任务键 in 顺序 if self._任务是否启用(设置, 任务键)]

    @staticmethod
    def _任务是否启用(设置: 机器人设置, 任务键: str) -> bool:
        """将任务计划中的键映射到实际配置开关。"""
        return 任务计划是否启用(设置, 任务键)

    def _接管启动时战斗(self, 上下文, 检测登录) -> bool:
        """接管机器人启动前已经存在的战斗/结算页。

        已经开始的战斗只等待自然结束；若启动时 OCR 明确看到“战斗开始”
        倒计时，则接管本场下兵，避免机器人启动/重启时把一场尚未部署的
        战斗白白等待到 0%。OCR 无法确认阶段时仍保守等待，不猜测输入。
        """
        if not getattr(上下文, "_启动时已有战斗", False):
            return True
        上下文.置脚本状态(
            "接管启动时已有战斗，跳过任务计划前的主世界/夜世界入口点击"
        )
        if bool(getattr(上下文, "_启动时战斗需要部署", False)):
            from 任务流程.主世界打鱼.进攻 import 进攻任务

            上下文.置脚本状态(
                "启动时战斗仍处于部署阶段，接管本场资源目标识别和下兵"
            )
            if not 进攻任务(上下文).执行():
                上下文.页面恢复失败 = True
                上下文.置脚本状态(
                    "启动时战斗下兵接管失败，禁止继续任务计划和任何入口点击"
                )
                return False
        from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务

        if not 等待战斗结束并回营任务(上下文).执行():
            上下文.页面恢复失败 = True
            上下文.置脚本状态(
                "启动时已有战斗未能完成回营，禁止继续任务计划和任何入口点击"
            )
            return False
        if getattr(上下文, "页面恢复失败", False) or self.停止事件.is_set():
            return False
        if not 检测登录.执行(首次登录=False):
            上下文.页面恢复失败 = True
            上下文.置脚本状态(
                "启动时战斗回营后未能重新确认连接，停止后续任务"
            )
            return False
        上下文._启动时已有战斗 = False
        上下文._启动时战斗页面 = None
        上下文._入口已进入战斗 = False
        上下文._入口已进入结算 = False
        上下文.置脚本状态("启动时已有战斗已回营，允许继续执行任务计划")
        return True

    def _确保主世界主页面(
            self,
            上下文,
            最少ESC次数: int = 0,
            最大ESC次数: int = 1,
    ) -> bool:
        """关闭弹窗/面板并确认主世界主页后，才允许继续点击。

        主世界资源图标本身可能在城墙面板或资源不足弹窗后面仍然可见，
        因此不能只调用“已经在主世界”的世界判断。先用当前截图确认
        主世界主页；已经在主页时绝不发送 ESC。只有确实不是主页时才
        发送一次 ESC 并立即复核，避免第一次关闭面板后第二次 ESC 把
        游戏退到 Android 启动器。确认失败时设置页面恢复失败标志，
        调用方必须停止后续点击。
        """
        上下文.页面恢复失败 = False
        键盘 = getattr(上下文, "键盘", None)
        按字符按压 = getattr(键盘, "按字符按压", None)
        if not callable(按字符按压):
            上下文.页面恢复失败 = True
            上下文.置脚本状态("无法恢复主世界主页：缺少键盘控制器，停止后续点击")
            return False

        识图引擎 = 模板匹配引擎()
        def 宝石提示遮挡(屏幕图像) -> bool:
            from 模块.检测.页面识别器 import 页面识别器

            if 页面识别器.定位哥布林宝石提示关闭按钮(屏幕图像) is None:
                return False
            上下文.页面恢复失败 = True
            上下文.置脚本状态(
                "主世界被哥布林10宝石提示遮挡，已安全停止；"
                "不点击宝石或底层任务按钮，请关闭提示后重新启动"
            )
            try:
                上下文.停止事件.set()
            except (AttributeError, TypeError):
                pass
            return True

        def 已确认主世界主页(屏幕图像) -> bool:
            """主页锚点同时命中才算可继续；不执行任何输入。"""
            有家乡进攻按钮, _, _ = 识图引擎.执行匹配(
                屏幕图像,
                "家乡进攻图标.bmp|家乡进攻图标1.bmp|家乡进攻图标2.bmp|家乡进攻图标3.bmp",
                相似度阈值=0.75,
            )
            有主世界资源栏, _, _ = 识图引擎.执行匹配(
                屏幕图像,
                "主世界圣水图标.bmp",
                相似度阈值=0.80,
            )
            return bool(有家乡进攻按钮 and 有主世界资源栏)

        def 页面级确认主世界主页() -> bool:
            """允许世界转场的最后一帧通过页级识别安全确认。

            世界切换任务确认成功后，资源栏模板可能还在一帧过渡画面中
            尚未出现。此时直接发送 ESC 会把安全的转场误判成残留面板，
            导致主世界任务被提前终止。页级识别已经要求主页、主世界和
            足够置信度同时成立，因此只读确认不会扩大点击范围。
            """
            识别 = getattr(上下文, "识别点击画面", None)
            if not callable(识别):
                return False
            try:
                try:
                    结果 = 识别(强制=True)
                except TypeError:
                    结果 = 识别()
                return bool(
                    getattr(结果, "页面", "") == "主世界主页"
                    and getattr(结果, "世界", "") == "主世界"
                    and float(getattr(结果, "可信度", 0.0) or 0.0) >= 0.70
                )
            except Exception as 异常:
                上下文.置脚本状态(f"主世界页级确认暂不可用：{异常}")
                return False

        if 最少ESC次数 <= 0:
            try:
                屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
                if 宝石提示遮挡(屏幕图像):
                    return False
                if 已确认主世界主页(屏幕图像):
                    # 主世界 HUD 锚点会透过详情弹窗继续可见；先处理已确认
                    # 的升级/资源详情窗。关闭器只点经几何和页面证据确认的
                    # 红 X，关闭后必须重新取帧并再次确认主页，不能沿用旧帧。
                    关闭升级详情 = getattr(上下文, "关闭升级详情弹窗", None)
                    if callable(关闭升级详情):
                        try:
                            if 关闭升级详情(屏幕图像):
                                try:
                                    屏幕图像 = 上下文.op.获取屏幕图像cv(
                                        0, 0, 800, 600, 强制刷新=True
                                    )
                                except TypeError:
                                    屏幕图像 = 上下文.op.获取屏幕图像cv(
                                        0, 0, 800, 600
                                    )
                                if 宝石提示遮挡(屏幕图像):
                                    return False
                                if not 已确认主世界主页(屏幕图像):
                                    上下文.页面恢复失败 = True
                                    上下文.置脚本状态(
                                        "升级详情关闭后未在新画面确认主世界主页，禁止启动下一步"
                                    )
                                    return False
                                上下文.置脚本状态(
                                    "已安全关闭主世界详情窗，并以新画面确认主页锚点"
                                )
                            elif getattr(上下文, "页面恢复失败", False):
                                return False
                        except Exception as 异常:
                            上下文.页面恢复失败 = True
                            上下文.置脚本状态(
                                f"主世界详情窗安全复核失败，禁止后续点击：{异常}"
                            )
                            return False
                    # 活动/奖励弹窗会保留主页锚点但吞掉后续点击；先关闭
                    # 明确识别到的右上角红色 X，再处理中央教程提示。
                    清理活动 = getattr(上下文, "清理主世界活动弹窗", None)
                    清理活动次数 = 0
                    if callable(清理活动):
                        for _ in range(4):
                            if not 清理活动(屏幕图像):
                                break
                            清理活动次数 += 1
                            上下文.脚本延时(180)
                            屏幕图像 = 上下文.op.获取屏幕图像cv(
                                0, 0, 800, 600, 强制刷新=True
                            )
                    if 清理活动次数:
                        if not 已确认主世界主页(屏幕图像):
                            上下文.页面恢复失败 = True
                            上下文.置脚本状态(
                                "活动弹窗关闭后未确认主世界主页，禁止启动下一步"
                            )
                            return False
                        上下文.置脚本状态(
                            f"已关闭{清理活动次数}个主世界活动弹窗，确认页面可操作"
                        )
                    # 主世界锚点可能仍露在教程/活动对话框后面。逐页处理
                    # 已确认的中央气泡；每次点击后强制读取新帧，避免把
                    # 被遮挡的旧主页继续交给进攻入口。
                    清理次数 = 0
                    清理提示 = getattr(上下文, "清理中央游戏提示", None)
                    if callable(清理提示):
                        for _ in range(8):
                            if not 清理提示(屏幕图像):
                                break
                            清理次数 += 1
                            上下文.脚本延时(180)
                            屏幕图像 = 上下文.op.获取屏幕图像cv(
                                0, 0, 800, 600, 强制刷新=True
                            )
                    if 清理次数:
                        if 已确认主世界主页(屏幕图像):
                            上下文.置脚本状态(
                                f"已处理{清理次数}页中央提示，确认回到可操作的主世界主页"
                            )
                            return True
                        上下文.页面恢复失败 = True
                        上下文.置脚本状态(
                            "中央提示处理后未确认主世界主页，禁止启动下一步"
                        )
                        return False
                    上下文.置脚本状态("已确认处于主世界主页，不发送ESC，允许启动下一步任务")
                    return True
                # 世界转场确认成功后，模板可能比主页识别晚一至数帧。
                # 在发送 ESC 前给当前画面一个短暂、无输入的稳定窗口；
                # 没有页级识别器时保持旧的单次安全恢复行为。
                if callable(getattr(上下文, "识别点击画面", None)):
                    for _ in range(6):
                        if 页面级确认主世界主页():
                            上下文.置脚本状态(
                                "页面级识别已确认主世界主页，跳过转场期间ESC"
                            )
                            return True
                        上下文.脚本延时(350)
            except Exception as 异常:
                # 主页截图失败时进入一次受限恢复；后续点击仍会经过安全护栏。
                上下文.置脚本状态(f"主世界主页预检失败，准备单次安全恢复：{异常}")

        for ESC次数 in range(1, max(最少ESC次数, 最大ESC次数) + 1):
            安全返回键 = getattr(上下文, "安全返回键", None)
            if callable(安全返回键):
                if not 安全返回键(f"主页面校验第{ESC次数}次"):
                    return False
            else:
                按字符按压("esc")
            上下文.置脚本状态(f"主页面校验：发送第{ESC次数}次ESC关闭残留面板")
            上下文.脚本延时(450)

            屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            if 宝石提示遮挡(屏幕图像):
                return False
            if (
                ESC次数 >= 最少ESC次数
                and 已确认主世界主页(屏幕图像)
            ):
                上下文.置脚本状态("已确认处于主世界主页，允许启动下一步任务")
                return True

        上下文.页面恢复失败 = True
        上下文.置脚本状态(
            f"主世界主页校验失败：已发送{最大ESC次数}次ESC，禁止继续点击"
        )
        return False

    def _断线时恢复游戏连接(self, 上下文, 检测登录) -> bool:
        """在世界任务开始/采集后发现断线弹窗时先完成游戏内重连。

        以前只有一场战斗结束后才调用登录检测。若 CoC 在夜世界主页
        空闲超时，资源收集或打开进攻页会先被点击护栏阻止，随后任务在
        未连接页面上继续尝试并安全失败。这里只在轻量页面识别明确返回
        “断线弹窗”时调用已有的游戏内重连流程；其他未知页面不猜测，
        也不发送 ESC、重启 CoC 或切换 Android 应用。
        """
        识别页面 = getattr(上下文, "识别点击画面", None)
        if not callable(识别页面):
            # 旧测试替身/极简适配器没有页面识别能力时，不凭空判定断线；
            # 正式任务上下文始终提供该接口，实际运行仍然走下方护栏。
            return True
        try:
            识别结果 = 识别页面(强制=True)
        except Exception as 异常:
            上下文.置脚本状态(f"连接状态预检失败，禁止继续输入：{异常}")
            上下文.页面恢复失败 = True
            return False
        if getattr(识别结果, "页面", "") != "断线弹窗":
            return True
        上下文.置脚本状态("任务开始前检测到 CoC 断线弹窗，尝试游戏内重新登入")
        if 检测登录.执行(首次登录=False):
            # 断线输入护栏可能已经留下失败标记；登录检测成功且重新
            # 确认主页后，当前调用方才可以安全继续本任务。
            上下文.页面恢复失败 = False
            上下文.置脚本状态("CoC 断线恢复完成，重新确认当前世界后继续任务")
            return True
        上下文.页面恢复失败 = True
        上下文.置脚本状态("CoC 断线恢复失败，保留游戏前台并停止后续点击")
        return False

    def _战后连续确认主世界主页(self, 上下文, 超时秒: float = 30.0) -> bool:
        """在启动下一轮前用连续新帧确认确实已回到主世界。

        结算页点击回营后，测试服偶尔会先渲染一帧带主页底图的过渡画面。
        单帧命中主页特征会让外层资源循环过早开始 OCR/点击，随后就会把
        结算页描述成“自动开启下一轮”。这里只读取页面识别结果，并要求两帧
        连续的主世界主页；识别不到主页就保持当前画面并让上层安全停止。
        唯一的例外是明确识别到胜利之星敲宝箱页（固定槽位的黄色擀面杖）时，
        按用户规则敲开宝箱一次。
        """
        页面识别 = getattr(上下文, "识别点击画面", None)
        if not callable(页面识别):
            return True
        try:
            超时秒 = max(2.0, float(超时秒))
        except (TypeError, ValueError):
            超时秒 = 10.0
        停止事件 = getattr(上下文, "停止事件", None)
        截止时间 = time.monotonic() + 超时秒
        连续确认 = 0
        上次状态 = None
        已试宝箱 = False
        while time.monotonic() < 截止时间:
            if 停止事件 is not None and 停止事件.is_set():
                return False
            try:
                try:
                    结果 = 页面识别(强制=True)
                except TypeError:
                    结果 = 页面识别()
            except Exception as 异常:
                连续确认 = 0
                if 上次状态 != "识别异常":
                    上下文.置脚本状态(f"战后主页确认暂时失败，继续等待：{异常}")
                    上次状态 = "识别异常"
                if hasattr(上下文, "脚本延时"):
                    上下文.脚本延时(500)
                continue

            页面 = str(getattr(结果, "页面", "未知") or "未知")
            try:
                可信度 = float(getattr(结果, "可信度", 0.0) or 0.0)
            except (TypeError, ValueError):
                可信度 = 0.0
            if 页面 == "主世界主页" and 可信度 >= 0.50:
                连续确认 += 1
                if 连续确认 >= 2:
                    上下文.置脚本状态(
                        f"战后连续确认主世界主页（置信度{可信度:.2f}），允许下一轮"
                    )
                    return True
            else:
                连续确认 = 0
                if 页面 != 上次状态:
                    上下文.置脚本状态(
                        f"战后主页确认中：当前={页面}，置信度{可信度:.2f}"
                    )
                    上次状态 = 页面
                if 页面 == "宝箱领奖页" and not getattr(上下文, "页面恢复失败", False):
                    清理领奖 = getattr(上下文, "清理宝箱领奖页", None)
                    if callable(清理领奖):
                        try:
                            if 清理领奖():
                                截止时间 = max(截止时间, time.monotonic() + 20.0)
                                continue
                        except Exception as 异常:
                            上下文.置脚本状态(f"战后宝箱领奖页处理异常：{异常}")
                # 实机 rc137：领取胜利之星奖励后才出现敲宝箱页，页面识别为“未知”，
                # 30 秒后进入安全待命。看到宝箱页就按用户规则敲开（每次确认只试一次）。
                if 页面 == "未知" and not 已试宝箱:
                    try:
                        from 任务流程.主世界打鱼 import 奖励宝箱
                        图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
                        if 奖励宝箱.识别宝箱页(图像) is not None:
                            已试宝箱 = True
                            奖励宝箱.开启奖励宝箱(上下文)
                            截止时间 = max(截止时间, time.monotonic() + 20.0)
                            continue
                    except Exception as 异常:
                        已试宝箱 = True
                        上下文.置脚本状态(f"战后宝箱处理异常，继续原流程：{异常}")
            if hasattr(上下文, "脚本延时"):
                上下文.脚本延时(500)
        上下文.置脚本状态(
            "战后主页确认超时，禁止开始下一轮；保留当前游戏画面"
        )
        return False

    def _执行主世界刷资源计划(self, 上下文, 检测登录) -> bool:
        上下文.置脚本状态("开始执行主世界打鱼任务,当打满资源时结束本项")
        上下文._待命恢复世界 = "主世界"
        上下文._内层让出外层调度 = False
        # True 还表示“军队未满、稍后重试”等可恢复结果，不能让外层
        # 调度器把所有 True 都当成资源已打满。每次进入资源计划先清零，
        # 只有明确识别到容量已满时才置为 True。
        上下文._资源计划已打满 = False
        # 刷墙面板/资源不足弹窗可能仍覆盖在主世界上；先完成世界转场，
        # 再用主页特征确认，避免把“看起来在主世界”的残留画面当成可进攻页面。
        if not self._进入并确认主世界(
            上下文, "刷资源前", 允许模式选择页=True
        ):
            上下文.页面恢复失败 = True
            上下文.置脚本状态("无法进入主世界，禁止启动进攻")
            return False
        if not self._断线时恢复游戏连接(上下文, 检测登录):
            return False
        主世界战斗选择页 = bool(
            getattr(上下文, "_主世界战斗模式选择页", False)
        )
        if 主世界战斗选择页:
            # 多人模式选择层遮住了部分村庄；即使能读到右侧资源栏，
            # 收集任务的地图点击也可能落在遮罩上。保留该已确认页面，
            # 跳过收集并交给进攻入口的双帧按钮识别安全继续。
            上下文.置脚本状态(
                "确认当前停在主世界战斗模式选择页；跳过被遮挡的收集点击，直接恢复普通对战流程"
            )
        elif not 收集资源任务(上下文).执行():
            上下文.置脚本状态("主世界资源收集未确认完成，停止后续进攻")
            上下文.页面恢复失败 = True
            return False
        配兵设置 = getattr(上下文, "设置", None)
        if (
            not 主世界战斗选择页
            and getattr(配兵设置, "是否自动配置军队", False)
            and (
                getattr(配兵设置, "配兵兵种", None)
                or getattr(配兵设置, "配兵法术", None)
                or getattr(配兵设置, "配兵攻城", "")
                or getattr(配兵设置, "阵容预设", "自定义勾选") != "自定义勾选"
            )
        ):
            # 勾选了兵种时，进攻前按勾选编辑军队；每次启动核对一次，之后
            # 只在勾选变化时重配。失败只退出编辑页，照常用现有军队进攻。
            if not 编辑军队任务(上下文).执行():
                上下文.页面恢复失败 = True
                return False
        主世界进攻次数 = 0
        资源未确认连续次数 = 0
        资源识别恢复轮数 = 0
        资源识别恢复上限 = 3
        while not self.停止事件.is_set():
            记录趋势 = getattr(self, "_记录进程资源趋势", None)
            if callable(记录趋势):
                记录趋势(上下文)
            # 收集资源或上一场战后可能新打开英雄详情；进入下一轮资源 OCR
            # 之前重新检查连接并用既有英雄专用关闭器收尾，不能让遮挡页
            # 泄漏到打鱼入口。普通主页上关闭器不发送任何输入。
            if not self._断线时恢复游戏连接(上下文, 检测登录):
                return False
            if not self._清理残留英雄升级详情(上下文):
                上下文.页面恢复失败 = True
                上下文.置脚本状态(
                    "下一场资源读取前英雄详情未安全关闭，禁止进攻"
                )
                return False
            if not self._打鱼间隙检查部落竞赛(上下文):
                return False
            上下文._允许待校准快照落盘 = bool(
                getattr(上下文, "_待校准资源快照", None)
            )
            try:
                本轮资源识别成功 = 更新家乡资源状态任务(上下文).执行()
            finally:
                上下文._允许待校准快照落盘 = False
            当前状态 = 上下文.数据库.获取最新完整状态(self.机器人标志)
            家乡资源 = self._取已确认家乡资源(当前状态)
            if 家乡资源 is None:
                # 首次运行或 OCR 连续失败时，数据库可能还没有这类状态。
                # 不能把缺失状态当作 0，否则会直接误开战；下一轮重试。
                上下文.置脚本状态(
                    "主世界资源尚未确认，禁止判断资源是否打满和发起进攻；稍后重试"
                )
                资源未确认连续次数 += 1
                # OCR/弹窗卡住时主动清理页面并重新确认主页，避免在同一张
                # 残留画面上无限循环。恢复失败则安全退出，不做任何猜测点击。
                if 资源未确认连续次数 >= 3:
                    上下文.置脚本状态("资源连续3次未确认，重新校验主世界主页")
                    if not self._进入并确认主世界(上下文, "资源识别恢复"):
                        上下文.置脚本状态("资源识别恢复失败，停止后续点击")
                        return False
                    资源未确认连续次数 = 0
                    资源识别恢复轮数 += 1
                    if 资源识别恢复轮数 >= 资源识别恢复上限:
                        请求等待 = getattr(上下文, "请求任务计划等待", None)
                        if callable(请求等待):
                            请求等待(60, "主世界资源连续无法识别")
                        else:
                            上下文.任务计划等待秒 = max(
                                60.0,
                                float(getattr(上下文, "任务计划等待秒", 0.0) or 0.0),
                            )
                            上下文._任务计划等待原因 = "主世界资源连续无法识别"
                        上下文.置脚本状态(
                            "主世界资源连续3轮无法确认；已安全退避60秒，稍后重新检查"
                        )
                        return True
                上下文.脚本延时(1500)
                continue
            资源未确认连续次数 = 0
            资源识别恢复轮数 = 0
            历史峰值 = 上下文.数据库.获取近期家乡资源峰值(self.机器人标志)
            当前优先级 = getattr(
                getattr(self, "设置", None), "战利品优先级", "均衡"
            )
            黑油储存上限 = getattr(
                getattr(self, "设置", None), "黑油储存上限", 500_000
            )
            已满仓 = 是否目标资源打满(
                家乡资源, 当前优先级, 历史峰值, 黑油储存上限
            )
            当前设置 = getattr(self, "设置", None) or getattr(上下文, "设置", None)
            if getattr(当前设置, "满仓自动顺手刷墙", False):
                from 模块.运行节流与复盘 import (
                    尝试满仓顺手刷墙,
                    金水是否达到刷墙阈值,
                )

                阈值比例 = getattr(当前设置, "刷墙资源阈值比例", 90)
                金水达标, _ = 金水是否达到刷墙阈值(
                    家乡资源, 阈值比例=阈值比例, 历史峰值=历史峰值
                )
                if (已满仓 or 金水达标) and 尝试满仓顺手刷墙(
                    self, 上下文, 家乡资源, 历史峰值
                ):
                    try:
                        if 更新家乡资源状态任务(上下文).执行():
                            最新状态 = 上下文.数据库.获取最新完整状态(self.机器人标志)
                            新资源 = self._取已确认家乡资源(最新状态)
                            if 新资源 is not None:
                                家乡资源 = 新资源
                                当前状态 = 最新状态
                                已满仓 = 是否目标资源打满(
                                    家乡资源, 当前优先级, 历史峰值, 黑油储存上限
                                )
                    except Exception:
                        pass
            if 已满仓 and self._满仓继续打鱼(上下文, "主世界"):
                pass
            elif 已满仓:
                上下文._资源计划已打满 = True
                上下文.置脚本状态(
                    f"战利品优先级[{当前优先级}]对应资源已接近已知储存容量；"
                    "按设置进入资源满仓处理，不再启动下一场进攻。"
                )
                上下文.置脚本状态("资源已打满,结束循环家乡打鱼")
                return True

            if not 本轮资源识别成功:
                上下文.置脚本状态(
                    "本轮资源 OCR 失败，继续使用上一份已确认资源快照；不覆盖数据库"
                )

            # 保存本场战斗开始前的资源，回营后再读取一次，形成近似净变化。
            # 该数据用于诊断“目标资源少/摧毁率低/战斗未成功”等问题。
            上下文._最近存在合法消耗 = False
            上下文._资源待校准 = False
            上下文.本场战前资源 = dict(当前状态.状态数据.get("家乡资源", {}))
            上下文.脚本延时(random.randint(500, 3000))
            本场战斗成功 = 主世界打鱼任务(上下文).执行()
            # 主世界入口明确发现军队容量未满时，这不是一场已经结束的
            # 战斗。不能进入下面的战后 OCR/资源净变化流程，也不能把
            # 半满兵栏再次带入下一场；把状态提升为本次资源计划已安全
            # 完成，由外层任务计划按请求的 60 秒冷却重新检查。
            if getattr(上下文, "_军队未满待机", False):
                上下文._军队未满待机 = False
                请求等待 = getattr(上下文, "请求任务计划等待", None)
                if callable(请求等待):
                    请求等待(60, "军队容量未满")
                else:
                    上下文.任务计划等待秒 = max(
                        60.0,
                        float(getattr(上下文, "任务计划等待秒", 0.0) or 0.0),
                    )
                    上下文._任务计划等待原因 = "军队容量未满"
                上下文.置脚本状态(
                    "军队容量未满，本轮未发起战斗；等待训练完成后重新检查"
                )
                return True
            # 进攻任务发现画面未就绪时会安全停止，而不是猜测性点击、
            # 发送 ESC 或继续进入登录恢复。这里必须立刻返回，避免在
            # 战斗/过渡画面上又执行下一轮主页检测。
            if getattr(上下文, "页面恢复失败", False) or self.停止事件.is_set():
                上下文.置脚本状态(
                    "本场画面未确认可安全继续，已停止刷资源循环并保留游戏前台"
                )
                return False
            if not 本场战斗成功:
                # 回营任务失败时绝不能把结算页/战斗页当作主世界，
                # 否则下面的“到循环头”会再次点击进攻入口并卡死在结果页。
                上下文.页面恢复失败 = True
                上下文.置脚本状态(
                    "本场战斗未确认回到主世界，禁止开始下一轮；"
                    "保留当前游戏画面等待人工处理"
                )
                return False
            if 本场战斗成功 and not self.停止事件.is_set():
                # 主世界打鱼任务内部已经做过一次回营确认，但外层资源循环
                # 仍然不能把“子任务返回 True”当成“当前画面就是主页”。
                # 真实测试服会在结算按钮点击后短暂露出主页底图、结算遮罩
                # 或过渡帧；如果此时直接进入下一轮，表现就是“结算页直接
                # 开启下一场”。这里在下一轮资源 OCR/入口点击之前再做一层
                # 连续两帧主页确认。没有页面识别接口的旧测试上下文保持原
                # 有行为，真实运行上下文始终具备该接口。
                页面识别 = getattr(上下文, "识别点击画面", None)
                if callable(页面识别):
                    if not self._战后连续确认主世界主页(上下文):
                        上下文.页面恢复失败 = True
                        上下文.置脚本状态(
                            "战斗任务已返回但未连续确认主世界主页，"
                            "禁止进入下一轮并保留当前游戏画面"
                        )
                        return False
                # 雷电的 Android 系统日志显示：上一场大量截图/连点后立刻
                # 打开下一场，guest 会短暂失去响应，LMKD 会杀掉 CoC 并回到
                # 启动器。先释放大截图、给游戏和模拟器 10 秒稳定窗口；
                # 这不是盲等，期间不再运行 OCR/YOLO/ADB 输入。
                for 属性名 in (
                    "_战斗开始兵栏画面", "_战斗结束截图", "_点击识别截图",
                    "_部署红色掩码", "当前兵栏清单",
                ):
                    setattr(上下文, 属性名, None)
                gc.collect()
                上下文.置脚本状态(
                    "战后稳定窗口：已释放截图缓存，暂停10秒避免模拟器无响应杀掉游戏"
                )
                上下文.脚本延时(10_000)
                if self.停止事件.is_set():
                    return False
                # 战后稳定窗口期间 CoC 可能弹出“因闲置过久而中断连接”。
                # 资源 OCR 对该弹窗拿不到数字，某些 OCR 后端还会抛出
                # ``object of type 'int' has no len()``；先做游戏内断线
                # 恢复，再读取资源，避免把断线弹窗当资源页处理。
                if not self._断线时恢复游戏连接(上下文, 检测登录):
                    return False
                战后资源识别成功 = 更新家乡资源状态任务(上下文).执行()
                战后状态 = 上下文.数据库.获取最新完整状态(self.机器人标志)
                战后资源 = self._取已确认家乡资源(战后状态)
                战前资源 = getattr(上下文, "本场战前资源", {})
                if getattr(上下文, "_最近存在合法消耗", False):
                    无消耗负跳变字段 = []
                else:
                    from 任务流程.更新主世界账号资源状态 import 检测无消耗大幅负跳变

                    无消耗负跳变字段 = 检测无消耗大幅负跳变(战前资源, 战后资源)
                if (
                    战后资源识别成功
                    and 战后资源
                    and 战前资源
                    and (
                        not self._资源快照变化可信(战前资源, 战后资源)
                        or 无消耗负跳变字段
                    )
                ):
                    # OCR 可能把结果页/过渡帧的数字识别成一组“完整但
                    # 错位”的资源。不能因为字段齐全就写出数百万级负收益，
                    # 否则下一轮会错误判断资源状态。恢复战前已确认快照，
                    # 让下一轮在稳定主世界重新采集。
                    恢复资源 = dict(战前资源)
                    恢复资源["金币"] = int(恢复资源.get("金币", 0) or 0)
                    恢复资源["圣水"] = int(恢复资源.get("圣水", 0) or 0)
                    恢复资源["黑油"] = int(恢复资源.get("黑油", 0) or 0)
                    恢复资源["总资源"] = 恢复资源["金币"] + 恢复资源["圣水"]
                    恢复资源["识别成功"] = True
                    上下文._资源待校准 = True
                    if 无消耗负跳变字段:
                        上下文._待校准资源快照 = dict(战后资源)
                    上下文.数据库.更新状态(
                        self.机器人标志, "家乡资源", 恢复资源
                    )
                    上下文.置脚本状态(
                        "战后资源 OCR 与战前快照差异异常（或无消耗大幅负跳变），"
                        "已恢复战前资源并标记待校准；本场净变化暂不记录，下一轮重新识别"
                    )
                    战后资源识别成功 = False
                    战后资源 = None
                if (
                    not 战后资源
                    or not 战后资源识别成功
                    or getattr(上下文, "_资源待校准", False)
                ):
                    上下文.置脚本状态(
                        "战后资源 OCR 未确认或待校准，本场资源净变化暂不记录；禁止用异常值覆盖真实数据"
                    )
                    主世界进攻次数 += 1
                    if 主世界进攻次数 % 5 == 0:
                        if not 收集资源任务(上下文).执行():
                            上下文.置脚本状态("战后资源收集未确认完成，停止后续进攻")
                            上下文.页面恢复失败 = True
                            return False
                    if not 检测登录.执行():
                        return False
                    到期任务 = self._存在已到检查点的外层任务(上下文)
                    if 到期任务 is not None:
                        上下文._资源计划已打满 = False
                        上下文._内层让出外层调度 = True
                        上下文.置脚本状态(
                            f"外层任务[{到期任务}]已到检查点，主世界打鱼本场结束后安全让出回外层调度"
                        )
                        return True
                    上下文.置脚本状态("进攻完毕，资源未确认，回到循环头重试")
                    continue
                净变化 = {
                    资源: int(战后资源.get(资源, 0) or 0) - int(战前资源.get(资源, 0) or 0)
                    for 资源 in ("金币", "圣水", "黑油")
                }
                上下文.数据库.更新状态(
                    self.机器人标志,
                    "战斗资源分析",
                    {
                        "目标战利品": getattr(上下文, "本场目标战利品", {}),
                        "战前资源": 战前资源,
                        "战后资源": 战后资源,
                        "本场净变化": 净变化,
                        "说明": "净变化为近似值，可能包含收集、升级或其他消耗",
                    },
                )
                上下文.置脚本状态(
                    f"本场资源净变化：金币 {净变化['金币']:+d}，圣水 {净变化['圣水']:+d}，黑油 {净变化['黑油']:+d}"
                )
                self._记录阵容收益(上下文, 净变化)
                from 数据库 import 今日统计
                if not 今日统计.记录收益(上下文.数据库, self.机器人标志, 净变化):
                    上下文.置脚本状态("本场资源净变化读数不可信，不计入今日收益")
            主世界进攻次数 += 1
            if 主世界进攻次数 % 5 == 0:
                if not 收集资源任务(上下文).执行():
                    上下文.置脚本状态("周期资源收集未确认完成，停止后续进攻")
                    上下文.页面恢复失败 = True
                    return False
            if not 检测登录.执行():
                return False
            到期任务 = self._存在已到检查点的外层任务(上下文)
            if 到期任务 is not None:
                上下文._资源计划已打满 = False
                上下文._内层让出外层调度 = True
                上下文.置脚本状态(
                    f"外层任务[{到期任务}]已到检查点，主世界打鱼本场结束后安全让出回外层调度"
                )
                return True
            上下文.置脚本状态("进攻完毕,到循环头")
        return False

    def _存在已到检查点的外层任务(self, 上下文) -> str | None:
        """检查除主世界刷资源外，是否有其他已启用外层任务已到执行检查点。

        仅启用 main_resource（或未配置外层任务键）时始终返回 None，确保连打不中断。
        """
        启用任务 = getattr(上下文, "_启用任务键集合", None)
        if not 启用任务 or len(启用任务) <= 1:
            return None
        候选顺序 = getattr(上下文, "_任务计划当前顺序", None) or tuple(启用任务)
        下次检查表 = getattr(上下文, "_外层任务下次检查时间", None)
        if not isinstance(下次检查表, dict):
            下次检查表 = {}
        本轮已完成 = getattr(上下文, "_本轮已完成任务键", None)
        if not isinstance(本轮已完成, (set, frozenset)):
            本轮已完成 = set()
        现在 = time.monotonic()
        现在时间戳 = time.time()
        for 任务键 in 候选顺序:
            if 任务键 == "main_resource" or 任务键 not in 启用任务:
                continue
            if 任务键 == "event":
                if "event" in 下次检查表:
                    if 现在 >= float(下次检查表["event"] or 0.0):
                        return "event"
                    continue
                记录 = None
                获取状态 = getattr(
                    getattr(上下文, "数据库", None), "获取最新完整状态", None
                )
                if callable(获取状态):
                    try:
                        完整 = 获取状态(self.机器人标志)
                        状态数据 = getattr(完整, "状态数据", None)
                        if isinstance(状态数据, dict):
                            记录 = 状态数据.get("部落竞赛检查记录")
                    except Exception:
                        记录 = None
                if (
                    isinstance(记录, dict)
                    and float(记录.get("下次检查时间", 0) or 0) > 现在时间戳
                ):
                    continue
                if "event" not in 本轮已完成:
                    return "event"
                continue
            if 任务键 in 下次检查表:
                if 现在 >= float(下次检查表[任务键] or 0.0):
                    return 任务键
                continue
            if 任务键 not in 本轮已完成:
                return 任务键
        return None

    @staticmethod
    def _取已确认家乡资源(状态) -> dict | None:
        """从完整状态中取出可用于决策的家乡资源快照。

        缺失、类型错误或字段不完整都代表“未知”，绝不能隐式变成
        金币/圣水/黑油为 0。这样首次 OCR 失败时不会误开战或误判墙体资源不足。
        """
        数据 = getattr(状态, "状态数据", None)
        资源 = 数据.get("家乡资源") if isinstance(数据, dict) else None
        if not isinstance(资源, dict):
            return None
        必要字段 = ("金币", "圣水", "黑油")
        if any(字段 not in 资源 for 字段 in 必要字段):
            return None
        try:
            return {
                字段: int(资源[字段] or 0)
                for 字段 in 必要字段
            }
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _资源快照变化可信(战前资源: dict, 战后资源: dict) -> bool:
        """过滤完整字段但明显错位的战后资源 OCR。

        一场战斗不会把一个十万级以上主资源截断到原来的三分之一；
        这种模式通常是 OCR 读到了过渡画面或错行数字。战斗过程中不会
        执行建筑升级或宝石消费，因此单个资源出现这种数量级下降也不能
        当作正常消耗。阈值只用于诊断和保护状态，不影响战斗结果，也不
        把正常的小幅消费/收集判为错误。
        """
        try:
            资源名 = ("金币", "圣水", "黑油")
            前 = [int(战前资源.get(资源, 0) or 0) for 资源 in 资源名]
            后 = [int(战后资源.get(资源, 0) or 0) for 资源 in 资源名]
        except (AttributeError, TypeError, ValueError):
            return False
        严重下降 = sum(
            之前 >= 100_000
            and 之后 < 之前 * 0.35
            and 之前 - 之后 >= 100_000
            for 之前, 之后 in zip(前, 后)
        )
        return 严重下降 == 0

    def _执行夜世界刷资源计划(self, 上下文, 检测登录) -> bool:
        上下文.置脚本状态("开始执行夜世界打鱼任务,当打满资源时结束本项")
        上下文._待命恢复世界 = "主世界"
        # 夜世界入口暂不可用也是 True（表示安全跳过并退避），不能
        # 误触发外层“资源已打满后退出/待机”分支。
        上下文._资源计划已打满 = False
        if not 到夜世界任务(上下文).执行():
            if getattr(上下文, "_夜世界入口暂不可用", False):
                # 入口视觉漏检/转场帧暂不可用是可恢复状态。保持主世界，
                # 让任务计划按请求的退避时间重试；绝不能在主世界继续
                # 执行夜世界收集、资源 OCR 或攻击点击。
                请求等待 = getattr(上下文, "请求任务计划等待", None)
                if callable(请求等待):
                    请求等待(60, "夜世界入口暂不可用")
                else:
                    上下文.任务计划等待秒 = max(
                        60.0,
                        float(getattr(上下文, "任务计划等待秒", 0.0) or 0.0),
                    )
                    上下文._任务计划等待原因 = "夜世界入口暂不可用"
                上下文.页面恢复失败 = False
                上下文.置脚本状态(
                    "夜世界入口本轮未确认，已安全跳过夜世界任务；"
                    "保持主世界，稍后自动重试"
                )
                return True
            上下文.页面恢复失败 = True
            上下文.置脚本状态("进入夜世界失败，禁止继续点击和读取资源")
            return False
        上下文._待命恢复世界 = "夜世界"
        if not self._断线时恢复游戏连接(上下文, 检测登录):
            return False
        if not 收集资源任务(上下文).执行():
            上下文.置脚本状态("夜世界资源收集未确认完成，停止后续进攻")
            上下文.页面恢复失败 = True
            return False
        if not self._断线时恢复游戏连接(上下文, 检测登录):
            return False
        夜世界成功进攻次数 = 0
        夜世界资源未确认连续次数 = 0
        while not self.停止事件.is_set():
            本轮资源识别成功 = 更新夜世界资源状态任务(上下文).执行()
            当前状态 = 上下文.数据库.获取最新完整状态(self.机器人标志)
            夜世界资源 = self._取已确认夜世界资源(当前状态)
            if 夜世界资源 is None:
                夜世界资源未确认连续次数 += 1
                上下文.置脚本状态(
                    f"夜世界资源尚未确认（第{夜世界资源未确认连续次数}次），"
                    "禁止判断打满和发起下一场进攻"
                )
                if 夜世界资源未确认连续次数 >= 3:
                    上下文.页面恢复失败 = True
                    上下文.置脚本状态(
                        "夜世界资源连续3次未确认，停止任务并保留当前游戏画面"
                    )
                    return False
                上下文.脚本延时(1500)
                continue
            夜世界资源未确认连续次数 = 0
            if not 本轮资源识别成功:
                上下文.置脚本状态(
                    "本轮夜世界资源 OCR 失败，继续使用上一份已确认资源快照"
                )
            是否资源打满 = 是否夜世界资源打满(
                夜世界资源,
                模式="夜世界",
                等级=getattr(上下文, "_夜世界大本营等级", None),
            )
            if 是否资源打满 and self._满仓继续打鱼(上下文, "夜世界"):
                pass
            elif 是否资源打满:
                上下文._资源计划已打满 = True
                上下文.置脚本状态(
                    "触发夜世界资源已打满条件：金币和圣水均接近已知储存容量。"
                )
                上下文.置脚本状态("资源已打满,结束循环夜世界打鱼")
                return True

            if 夜世界成功进攻次数 % 5 == 0:
                上下文.置脚本状态(F"夜世界打鱼次数到了{夜世界成功进攻次数},收集圣水车")
                圣水车实例 = 收集圣水车任务(上下文)
                圣水车收集成功 = 圣水车实例.执行()
                本轮未发现圣水车 = (
                    getattr(圣水车实例, "_本轮未发现可收集圣水车", False)
                    is True
                )
                if not 圣水车收集成功 and not 本轮未发现圣水车:
                    # 收集流程会在每个候选点后复核世界。若期间误切回主世界、
                    # 详情页关闭失败或页面识别异常，禁止把后续夜世界坐标
                    # 继续发送到当前画面；由外层任务统一结束本轮并保留画面。
                    上下文.页面恢复失败 = True
                    上下文.置脚本状态(
                        "圣水车任务未确认完成，禁止继续执行夜世界收集和下一场战斗"
                    )
                    return False
                if 本轮未发现圣水车:
                    上下文.置脚本状态(
                        "本轮未发现可安全确认的圣水车，已跳过收集并继续夜世界资源流程"
                    )
                if not 收集资源任务(上下文).执行():
                    上下文.置脚本状态("夜世界周期资源收集未确认完成，停止后续进攻")
                    上下文.页面恢复失败 = True
                    return False
            本场战斗成功 = 夜世界打鱼任务(上下文).执行()
            if (
                not 本场战斗成功
                or getattr(上下文, "页面恢复失败", False)
                or self.停止事件.is_set()
            ):
                上下文.页面恢复失败 = True
                上下文.置脚本状态(
                    "夜世界本场战斗未确认完成，禁止开启下一场，保留当前画面"
                )
                return False
            上下文.脚本延时(random.randint(500, 3000))
            if not 检测登录.执行():
                return False
            夜世界成功进攻次数 += 1
        return False

    @staticmethod
    def _取已确认夜世界资源(状态) -> dict | None:
        """读取完整且成功确认的夜世界资源，失败时返回未知而不是 0。"""
        数据 = getattr(状态, "状态数据", None)
        资源 = 数据.get("夜世界资源") if isinstance(数据, dict) else None
        if not isinstance(资源, dict):
            return None
        if "识别成功" in 资源 and not bool(资源.get("识别成功")):
            return None
        必要字段 = ("金币", "圣水")
        if any(字段 not in 资源 for 字段 in 必要字段):
            return None
        try:
            结果 = {字段: int(资源[字段] or 0) for 字段 in 必要字段}
        except (TypeError, ValueError):
            return None
        if any(值 < 0 for 值 in 结果.values()):
            return None
        return 结果

    def _进入并确认主世界(
        self,
        上下文,
        阶段说明: str = "",
        *,
        允许模式选择页: bool = False,
    ) -> bool:
        """切回主世界并确认主页，防止墙任务误在夜世界继续点击。"""
        if 阶段说明:
            上下文.置脚本状态(f"{阶段说明}：确认主世界主页")
        try:
            识别页面 = getattr(上下文, "识别点击画面", None)
            清理领奖 = getattr(上下文, "清理宝箱领奖页", None)
            if callable(识别页面) and callable(清理领奖):
                try:
                    初始页 = 识别页面(强制=True)
                except TypeError:
                    初始页 = 识别页面()
                if getattr(初始页, "页面", "") == "宝箱领奖页":
                    if not 清理领奖():
                        上下文.页面恢复失败 = True
                        上下文.置脚本状态(
                            f"{阶段说明 or '任务'}：宝箱领奖页未能安全收起，禁止继续"
                        )
                        return False
            if callable(识别页面):
                初始图像 = getattr(上下文, "_点击识别截图", None)
                if 初始图像 is None:
                    取图 = getattr(getattr(上下文, "op", None), "获取屏幕图像cv", None)
                    if callable(取图):
                        try:
                            初始图像 = 取图(0, 0, 800, 600, 强制刷新=True)
                        except TypeError:
                            初始图像 = 取图(0, 0, 800, 600)
                if 初始图像 is not None:
                    from 任务流程.主世界打鱼 import 奖励宝箱
                    if 奖励宝箱.识别宝箱页(初始图像) is not None:
                        清理敲宝箱 = getattr(上下文, "清理敲宝箱页", None)
                        开箱成功 = (
                            bool(清理敲宝箱(初始图像))
                            if callable(清理敲宝箱)
                            else bool(奖励宝箱.开启奖励宝箱(上下文))
                        )
                        if not 开箱成功:
                            上下文.页面恢复失败 = True
                            上下文.置脚本状态(
                                f"{阶段说明 or '任务'}：敲宝箱页未能安全开启，禁止继续"
                            )
                            return False
            if 允许模式选择页 and self._连续确认主世界战斗模式选择页(上下文):
                上下文._主世界战斗模式选择页 = True
                上下文.置脚本状态(
                    f"{阶段说明 or '任务'}：两帧确认主世界战斗模式选择页；不拖动地图，交给普通对战流程"
                )
                return True
            if not 到主世界任务(上下文).执行():
                上下文.置脚本状态(f"{阶段说明 or '任务'}：主世界转场失败")
                return False
            关闭升级面板 = getattr(上下文, "关闭升级详情弹窗", None)
            if callable(关闭升级面板):
                关闭升级面板()
                if getattr(上下文, "页面恢复失败", False):
                    上下文.置脚本状态(
                        f"{阶段说明 or '任务'}：升级详情弹窗关闭后未确认主世界主页"
                    )
                    return False
            # 英雄详情页与普通建筑详情页共用主页 HUD。通用关闭器会
            # 有意把英雄详情留给英雄任务，但这里若只看主页锚点，仍会
            # 把残留英雄详情误当成可操作主页，随后再次点击顶部入口，
            # 造成英雄任务卡在“识别/寻找”。先用英雄专用收尾器清掉
            # 残留详情，禁止 ESC/BACK 和立即完成/宝石输入。
            if not self._清理残留英雄升级详情(上下文):
                上下文.页面恢复失败 = True
                上下文.置脚本状态(
                    f"{阶段说明 or '任务'}：残留英雄升级详情未能安全关闭，禁止继续点击"
                )
                return False
            return self._确保主世界主页面(上下文)
        except Exception as 异常:
            上下文.页面恢复失败 = True
            上下文.置脚本状态(f"{阶段说明 or '任务'}：主世界确认异常：{异常}")
            return False

    @staticmethod
    def _连续确认主世界战斗模式选择页(上下文) -> bool:
        """两帧只读确认重启后保留的普通/排位战斗选择层。"""
        识别 = getattr(上下文, "识别点击画面", None)
        if not callable(识别):
            return False
        连续确认 = 0
        for 序号 in range(2):
            try:
                try:
                    结果 = 识别(强制=True)
                except TypeError:
                    结果 = 识别()
                if not (
                    getattr(结果, "页面", "") == "主世界战斗模式选择"
                    and getattr(结果, "世界", "") == "主世界"
                    and float(getattr(结果, "可信度", 0.0) or 0.0) >= 0.90
                ):
                    return False
                连续确认 += 1
            except Exception as 异常:
                上下文.置脚本状态(
                    f"主世界战斗模式选择页复核失败：{异常}；不发送输入"
                )
                return False
            if 序号 == 0:
                延时 = getattr(上下文, "脚本延时", None)
                if callable(延时):
                    延时(250)
        return 连续确认 >= 2

    def _清理残留英雄升级详情(self, 上下文) -> bool:
        """在任务入口清理英雄详情/殿堂残留，不把它当主页。"""
        if getattr(上下文, "_主世界战斗模式选择页", False):
            return True
        取图 = getattr(getattr(上下文, "op", None), "获取屏幕图像cv", None)
        识别英雄详情 = getattr(上下文, "_当前画面是英雄升级详情", None)
        if not callable(取图) or not callable(识别英雄详情):
            return True
        try:
            try:
                画面 = 取图(0, 0, 800, 600, 强制刷新=True)
            except TypeError:
                画面 = 取图(0, 0, 800, 600)
            是英雄详情 = bool(识别英雄详情(画面))
        except Exception as 异常:
            上下文.置脚本状态(f"残留英雄升级详情预检失败：{异常}")
            return False

        try:
            from 任务流程.建筑升级.升级英雄 import 升级英雄任务
            关闭任务 = 升级英雄任务.__new__(升级英雄任务)
            关闭任务.上下文 = 上下文
            # 这里是轻量收尾器，不能走完整任务构造器反复创建 YOLO；
            # 但英雄殿堂列表复核仍需要共享 OCR 引擎，避免 __new__ 后
            # ``执行OCR识别`` 因缺少 ocr引擎而失败。
            获取OCR = getattr(上下文, "获取OCR引擎", None)
            if callable(获取OCR):
                关闭任务.ocr引擎 = 获取OCR()
            if 是英雄详情:
                上下文.置脚本状态(
                    "检测到残留英雄升级详情，交由英雄专用关闭器安全收尾；"
                    "禁止点击立即完成、宝石和商店"
                )
                return bool(关闭任务.关闭英雄升级页面())

            # 英雄详情关闭后，测试服可能只留下英雄殿堂列表；该列表
            # 仍会露出主页 HUD，页面识别器会误报主世界。只能点击已确认
            # 的顶部英雄入口，不能点右上角相似 X，更不能发送 ESC/BACK。
            if 关闭任务._英雄殿堂文本仍在():
                上下文.置脚本状态(
                    "检测到残留英雄殿堂列表，使用顶部英雄入口安全关闭；"
                    "禁止点击立即完成和宝石"
                )
                return bool(关闭任务._安全关闭英雄殿堂入口())
            return True
        except Exception as 异常:
            上下文.置脚本状态(f"残留英雄面板安全收尾失败：{异常}")
            return False

    def _执行升级计划(self, 任务键: str, 上下文, 检测登录=None) -> bool:
        """在任务计划指定的位置执行一次升级任务。"""
        if not self._进入并确认主世界(上下文, f"{任务键}任务前"):
            上下文.页面恢复失败 = True
            上下文.置脚本状态(f"{任务键}任务前未确认主世界，禁止执行升级操作")
            return False
        # CoC 可能在主世界空闲阶段断线。底层主页 HUD 仍可能露在断线
        # 弹窗后面，因此主世界确认不能替代连接确认；升级、刷墙、英雄、
        # 战宠和研究入口前都必须复用游戏内重新登入流程。
        if 检测登录 is not None and not self._断线时恢复游戏连接(上下文, 检测登录):
            上下文.页面恢复失败 = True
            上下文.置脚本状态(
                f"{任务键}任务前断线恢复失败，禁止执行升级操作"
            )
            return False
        if 任务键 == "wall":
            return 城墙升级任务(上下文).执行()
        elif 任务键 in {"building", "hero"}:
            return 建筑升级任务(上下文).执行()
        elif 任务键 == "pet":
            return 战宠升级任务(上下文).执行()
        elif 任务键 == "research":
            return 兵种或法术升级任务(上下文).执行()
        return False

    def _执行刷墙计划(
        self,
        上下文,
        检测登录,
        允许自动刷资源: bool = True,
    ) -> bool:
        """执行刷墙；只有用户同时选中主世界刷资源时才允许补资源。"""
        上下文.刷墙需要资源 = False
        墙体阶段成功 = self._执行升级计划("wall", 上下文, 检测登录)
        if getattr(上下文, "页面恢复失败", False):
            return False
        if not 墙体阶段成功 and not getattr(上下文, "刷墙需要资源", False):
            上下文.置脚本状态(
                "城墙任务异常结束且未确认资源不足，禁止继续其他任务和点击"
            )
            上下文.页面恢复失败 = True
            return False
        if not getattr(上下文, "刷墙需要资源", False) or self.停止事件.is_set():
            # “没有可升级墙段/资源未确认”可以是本轮正常无操作；只有页面
            # 恢复失败才应阻断后续任务，不能把普通 no-op 当作导航故障。
            return not getattr(上下文, "页面恢复失败", False)

        if not 允许自动刷资源:
            上下文.置脚本状态(
                "刷墙检测到资源不足，但主世界刷资源未选中；"
                "跳过资源补充，等待下一次只检查刷墙"
            )
            请求等待 = getattr(上下文, "请求任务计划等待", None)
            if callable(请求等待):
                请求等待(60, "刷墙资源不足且主世界刷资源未选中")
            else:
                上下文.任务计划等待秒 = max(
                    60.0,
                    float(getattr(上下文, "任务计划等待秒", 0.0) or 0.0),
                )
                上下文._任务计划等待原因 = "刷墙资源不足且主世界刷资源未选中"
            return True

        # 城墙任务已经记录了“最低等级墙段 + 实际费用 + 当前资源”，此处
        # 才切换到刷资源，不再因为起始阈值不足而直接结束机器人线程。
        上下文.刷墙需要资源 = False
        上下文.置脚本状态(
            "城墙升级检测到资源不足，已退出到主世界；"
            "禁止使用宝石和进入商店，启动主世界刷资源"
        )
        # 刷墙任务已经用 ESC 关闭墙体面板；这里仅确认仍在主世界，
        # 不点击商店、宝石或任何立即完成入口。
        资源阶段成功 = self._执行主世界刷资源计划(上下文, 检测登录)
        if (
            self.停止事件.is_set()
            or getattr(上下文, "页面恢复失败", False)
            or not 资源阶段成功
        ):
            if not self.停止事件.is_set() and not 资源阶段成功:
                上下文.置脚本状态("主世界刷资源任务未完成，禁止重新打开城墙面板")
            return False

        上下文.置脚本状态("资源补充阶段结束，重新扫描最低等级城墙")
        self._执行升级计划("wall", 上下文, 检测登录)
        if getattr(上下文, "页面恢复失败", False):
            return False
        if getattr(上下文, "刷墙需要资源", False):
            上下文.置脚本状态("刷资源后仍不足以升级当前最低等级城墙，等待下一次任务计划")
        return not getattr(上下文, "页面恢复失败", False)

    def _执行任务计划项(self, 任务键: str, 上下文, 检测登录) -> tuple[bool, bool]:
        """执行一个已规范化的任务键，返回 ``(任务成功, 资源已打满)``。

        任务循环只负责顺序、停止和失败策略；具体任务分派集中在这里，
        防止以后新增任务时把条件分支继续堆进主循环。
        """
        if 任务键 in {
            "event", "main_resource", "wall", "building", "hero", "pet", "research",
            "keep_busy", "donate_troops", "capital_donate",
        }:
            上下文._待命恢复世界 = "主世界"

        if 任务键 == "event":
            结果 = self._执行部落竞赛计划(上下文)
        elif 任务键 == "main_resource":
            结果 = self._执行主世界刷资源计划(上下文, 检测登录)
        elif 任务键 == "night_resource":
            结果 = self._执行夜世界刷资源计划(上下文, 检测登录)
        elif 任务键 == "wall":
            上下文.置脚本状态("按任务计划执行：wall")
            启用任务 = getattr(上下文, "_启用任务键集合", None)
            允许自动刷资源 = (
                True if 启用任务 is None else "main_resource" in 启用任务
            )
            结果 = self._执行刷墙计划(
                上下文,
                检测登录,
                允许自动刷资源=允许自动刷资源,
            )
        elif 任务键 in {"building", "hero", "pet", "research"}:
            上下文.置脚本状态(f"按任务计划执行：{任务键}")
            if self._官方数据显示已满级(任务键, 上下文):
                return True, False
            结果 = self._执行升级计划(任务键, 上下文, 检测登录)
        elif 任务键 == "night_star_bonus":
            上下文.置脚本状态("按任务计划执行：night_star_bonus")
            结果 = self._执行夜世界星星计划(上下文, 检测登录)
        elif 任务键 in {"donate_troops", "capital_donate"}:
            上下文.置脚本状态(f"按任务计划执行：{任务键}")
            结果 = self._执行主世界面板日常计划(任务键, 上下文, 检测登录)
        elif 任务键 == "keep_busy":
            上下文.置脚本状态("按任务计划执行：keep_busy")
            结果 = self._执行保持不闲计划(上下文, 检测登录)
        else:
            上下文.置脚本状态(f"任务计划包含未知任务键：{任务键}")
            return False, False

        资源已打满 = (
            任务键 in {"main_resource", "night_resource"}
            and bool(getattr(上下文, "_资源计划已打满", False))
        )
        return bool(结果), 资源已打满

    def _日常任务前确认主世界(self, 上下文, 检测登录, 阶段: str) -> bool:
        if not self._进入并确认主世界(上下文, 阶段):
            上下文.页面恢复失败 = True
            上下文.置脚本状态(f"{阶段}未确认主世界，禁止继续点击")
            return False
        if 检测登录 is not None and not self._断线时恢复游戏连接(上下文, 检测登录):
            上下文.页面恢复失败 = True
            上下文.置脚本状态(f"{阶段}断线恢复失败，禁止继续点击")
            return False
        return True

    def _执行保持不闲计划(self, 上下文, 检测登录) -> bool:
        """D. 实验室和工人不闲：研究段 → 重新确认主世界 → 工人段。"""
        from 任务流程.日常.保持不闲 import 保持不闲任务

        任务 = 保持不闲任务(上下文)
        if 任务.冷却中():
            return True
        if not self._日常任务前确认主世界(上下文, 检测登录, "实验室不闲研究段前"):
            return False
        if not 任务.执行研究段():
            return False
        if self.停止事件.is_set():
            return True
        if not self._日常任务前确认主世界(上下文, 检测登录, "工人不闲升级段前"):
            return False
        if not 任务.执行工人段():
            return False
        任务.记录完成()
        return True

    def _执行主世界面板日常计划(self, 任务键: str, 上下文, 检测登录) -> bool:
        """B 捐兵 / C1 都城捐金币：未校准/冷却在确认页面前就安全跳过。"""
        if 任务键 == "donate_troops":
            from 任务流程.日常.捐兵 import 捐兵任务 as 任务类
        else:
            from 任务流程.日常.都城捐金币 import 都城捐金币任务 as 任务类
        任务 = 任务类(上下文)
        if not 任务.可以运行():
            return True
        if not self._日常任务前确认主世界(上下文, 检测登录, f"{任务键}前"):
            return False
        任务.可以运行 = lambda: True  # 已检查过，避免重复写日志/等待
        结果 = 任务.执行()
        if not 结果:
            return False
        return self._日常任务前确认主世界(上下文, 检测登录, f"{任务键}后")

    def _执行夜世界星星计划(self, 上下文, 检测登录) -> bool:
        """A. 夜世界打满星星奖励：进夜世界后逐场打，今日领满或到上限即停。"""
        from 任务流程.日常.夜世界星星 import 夜世界星星任务

        任务 = 夜世界星星任务(上下文)
        上下文._待命恢复世界 = "主世界"
        if 任务.今日已完成():
            return True
        if not 到夜世界任务(上下文).执行():
            if getattr(上下文, "_夜世界入口暂不可用", False):
                上下文.页面恢复失败 = False
                请求等待 = getattr(上下文, "请求任务计划等待", None)
                if callable(请求等待):
                    请求等待(60, "夜世界入口暂不可用")
                上下文.置脚本状态("夜世界星星：入口本轮未确认，安全跳过，稍后重试")
                return True
            上下文.页面恢复失败 = True
            上下文.置脚本状态("夜世界星星：进入夜世界失败，禁止继续点击")
            return False
        上下文._待命恢复世界 = "夜世界"
        while not self.停止事件.is_set():
            if not self._断线时恢复游戏连接(上下文, 检测登录):
                return False
            结果 = 任务.打一场()
            if 结果 == "完成":
                任务.今日已完成()
                return True
            if 结果 == "失败":
                上下文.页面恢复失败 = True
                上下文.置脚本状态("夜世界星星：本场未确认完成，保留当前画面")
                return False
        return True

    def _满仓继续打鱼(self, 上下文, 世界: str) -> bool:
        """资源打满后动作为“继续打鱼”时返回 True，调用方照常发起下一场进攻。"""
        try:
            动作 = getattr(self.设置, "资源打满后动作", "退出")
        except Exception:
            动作 = "退出"
        if 动作 != "继续打鱼":
            return False
        已提示 = getattr(上下文, "_满仓继续打鱼已提示", set())
        if 世界 not in 已提示:
            上下文.置脚本状态(
                f"{世界}资源已接近储存上限；按设置“继续打鱼”照常进攻，"
                "多出的战利品不会入库"
            )
            上下文._满仓继续打鱼已提示 = set(已提示) | {世界}
        return True

    def _打鱼间隙检查部落竞赛(self, 上下文) -> bool:
        """连续打鱼时主世界刷资源不会结束本轮，任务计划里的 event 项
        就再也轮不到。每场进攻前（已在主页）顺带检查一次：模块自带
        冷却，未到时间只读一次数据库、不做任何点击。"""
        启用任务 = getattr(上下文, "_启用任务键集合", None)
        if not 启用任务 or "event" not in 启用任务:
            return True
        if self._执行部落竞赛计划(上下文, 进攻前=True):
            return True
        上下文.页面恢复失败 = True
        上下文.置脚本状态("打鱼间隙的部落竞赛检查未能确认回到主页，禁止进攻")
        return False

    def _执行部落竞赛计划(self, 上下文, 进攻前: bool = False) -> bool:
        """部落竞赛接任务；冷却、活动结束、识别不清都返回 True 让打鱼继续。"""
        from 任务流程.活动.部落竞赛 import 部落竞赛任务

        摘要 = self._同步官方账号数据(上下文)
        return 部落竞赛任务(上下文, 官方摘要=摘要).执行(进攻前=进攻前)

    def _记录阵容收益(self, 上下文, 净变化: dict) -> None:
        """把本场资源净变化记到当前阵容名下；每满 5 场收益输出一次阵容对比。"""
        签名 = str(getattr(上下文, "本场阵容签名", "") or "")
        if not 签名:
            return
        try:
            from 任务流程.主世界打鱼 import 阵容学习
            if not 阵容学习.记录资源收益(上下文.数据库, self.机器人标志, 签名, 净变化):
                上下文.置脚本状态(f"阵容学习：本场净变化 {净变化} 明显不合理（疑似 OCR 误读），不计入阵容收益")
                return
            学习 = 阵容学习.读取(上下文.数据库, self.机器人标志)
            if 学习["阵容"].get(签名, {}).get("收益场次", 0) % 5 == 0:
                优先级 = getattr(self.设置, "战利品优先级", "均衡")
                上下文.置脚本状态(阵容学习.对比日志(学习, 签名, 优先级))
        except Exception as 异常:
            上下文.置脚本状态(f"阵容学习：收益记录失败，不影响刷资源：{异常}")

    def _同步官方账号数据(self, 上下文, 强制: bool = False):
        """按间隔读取官方 API 账号数据；未配置或失败时返回 None，不影响任务。"""
        try:
            设置 = self.设置
        except Exception:
            return None
        令牌 = str(getattr(设置, "官方API令牌", "") or "").strip()
        标签 = str(getattr(设置, "玩家标签", "") or "").strip()
        if not 令牌 or not 标签:
            return None
        try:
            间隔秒 = max(5, int(getattr(设置, "官方数据同步间隔分钟", 30))) * 60
        except (TypeError, ValueError):
            间隔秒 = 30 * 60
        上次 = getattr(self, "_官方账号摘要", None)
        if not 强制 and 上次 is not None and time.time() - 上次.同步时间 < 间隔秒:
            return 上次
        from 服务 import 官方API
        try:
            摘要 = 官方API.同步账号(令牌, 标签)
        except Exception as 异常:  # 网络或 Token 问题只降级，不能打断游戏操作
            上下文.置脚本状态(f"[警告] 官方数据同步失败，升级任务按原流程执行：{异常}", 60)
            return 上次
        self._官方账号摘要 = 摘要
        上下文.置脚本状态(摘要.日志文本())
        try:
            上下文.数据库.更新状态(self.机器人标志, "官方账号数据", 摘要.转为字典())
        except Exception as 异常:
            _安全控制台打印(f"保存官方账号数据失败：{异常}")
        return 摘要

    def _官方数据显示已满级(self, 任务键: str, 上下文) -> bool:
        """官方数据确认目标全部满级时返回 True，调用方应跳过该升级任务。

        只在能确定时跳过；目标不在官方数据里、未配置或同步失败都返回 False。
        """
        if 任务键 not in {"hero", "pet", "research"}:
            return False
        摘要 = self._同步官方账号数据(上下文)
        if 摘要 is None:
            return False
        设置 = self.设置
        if 任务键 == "research":
            类别, 目标 = "研究", [getattr(设置, "欲升级的兵种或法术", "")]
        elif 任务键 == "pet":
            类别, 目标 = "战宠", [getattr(设置, "欲升级的战宠", "")]
        else:
            类别, 目标 = "英雄", list(getattr(设置, "欲升级的英雄或建筑", None) or [])
        目标 = [str(名).strip() for 名 in 目标 if str(名).strip()]
        if not 目标 or not all(摘要.是否满级(类别, 名) is True for 名 in 目标):
            return False
        建议 = 摘要.未满级(类别)
        上下文.置脚本状态(
            f"官方数据显示{'、'.join(目标)}已满级，跳过本次{类别}升级"
            + (f"；可改为：{'、'.join(建议[:5])}" if 建议 else f"；所有{类别}均已满级")
        )
        # 满级状态在下次同步前不会变化，避免任务计划每 5 秒重复跳过刷屏。
        try:
            等待秒 = float(max(5, int(getattr(设置, "官方数据同步间隔分钟", 30))) * 60)
        except (TypeError, ValueError):
            等待秒 = 1800.0
        请求等待 = getattr(上下文, "请求任务计划等待", None)
        if callable(请求等待):
            请求等待(等待秒, f"官方数据显示{类别}已满级")
        return True

    def _初始化任务上下文(self):
        """创建设备、输入控制器和任务上下文。"""
        设置 = self.数据库.获取机器人设置(self.机器人标志)
        if not 设置.ADB已确认模拟器:
            raise RuntimeError("请先在“模拟器连接”页确认目标是 Android 模拟器并保存连接。")
        if not 设置.ADB设备序列号:
            raise RuntimeError("尚未配置 ADB 设备序列号；请先扫描并选择模拟器。")
        self.设备 = ADB设备操作类(
            设置.ADB路径,
            设置.ADB设备序列号,
            自动检测路径=getattr(设置, "ADB自动检测路径", True),
            内存保护提交额度阈值MB=getattr(设置, "内存保护提交额度阈值MB", 1536),
        )
        self.设备.设置目标包名(设置.部落冲突包名)
        self.op = ADB屏幕(self.设备, 日志回调=self.记录日志)
        try:
            from 应用.异常留证 import 安装帧缓存

            安装帧缓存(self.op, self.机器人标志)
        except Exception:
            pass
        企业微信通知器实例 = None
        if 设置.企业微信webhook:
            try:
                from 工具包.企业微信通知 import 企业微信通知器
                企业微信通知器实例 = 企业微信通知器(设置.企业微信webhook)
            except Exception as e:
                _安全控制台打印(f"初始化企业微信通知器失败: {e}")
        # 即使后续输入控制器或任务上下文初始化失败，调用方也能拿到
        # 这个部分初始化对象并关闭它，避免后台通知线程泄漏。
        self._初始化通知器 = 企业微信通知器实例

        运行鼠标 = 鼠标控制器(self.设备)
        上下文 = 任务上下文(
            机器人标志=self.机器人标志,
            消息队列=self.消息队列,
            数据库=self.数据库,
            停止事件=self.停止事件,
            继续事件=self.继续事件,
            置脚本状态=self.记录日志,
            op=self.op,
            设备=self.设备,
            鼠标=运行鼠标,
            键盘=键盘控制器(self.设备),
            企业微信通知器=企业微信通知器实例,
            上次上报时间=time.time(),  # 初始化为当前时间
            上报间隔秒=设置.状态上报间隔分钟 * 60,  # 转换为秒
            上次检查上报时间=time.time()  # 初始化为当前时间
        )
        # 所有原始鼠标路径（包括连点、长按、直接按下）共用轻量页面
        # 识别和宝石安全检查；识别结果在极短缓存内复用，避免高频下兵
        # 为每个物理点击重复 ADB screencap。
        运行鼠标._安全点击检查回调 = 上下文.输入前安全检查
        # 上下文.置脚本状态("开始执行",1000)
        # 双击源码入口或从未配置 UTF-8 的控制台启动时，stdout 可能仍是
        # cp1252。设置内容包含中文，不能让辅助日志的编码异常杀死任务线程。
        try:
            _安全控制台打印("本次运行时的设置为" + self.设置.__str__())
        except (UnicodeEncodeError, OSError, ValueError):
            pass
        self._初始化通知器 = None
        return 设置, 上下文, 企业微信通知器实例

    def _等待人工恢复主世界(self, 上下文, 检测登录) -> bool:
        """安全待命入口：待命内部（如断线重连）再次触发宿主机内存保护时，
        暂停请求不能冒泡到线程顶层把线程结束，而要回到预算轮询继续等待。
        用户的停止请求始终优先。"""
        for _ in range(1000):
            try:
                return self._安全待命单次(上下文, 检测登录)
            except 主机内存保护暂停请求 as 内存暂停:
                if self.停止事件.is_set() or self.停止原因:
                    return False
                上下文.置脚本状态(
                    f"安全待命期间再次触发宿主机内存保护，继续只读等待预算恢复：{内存暂停}"
                )
                上下文.页面恢复失败 = True
        self.停止事件.set()
        上下文.置脚本状态("安全待命期间内存保护反复触发，保持停止，需人工复核")
        return False

    def _安全待命单次(self, 上下文, 检测登录) -> bool:
        """任务进入安全停机分支后只读待命，确认回城后再接续任务。"""
        待命恢复世界 = str(
            getattr(上下文, "_待命恢复世界", "主世界") or "主世界"
        ).strip()
        待命恢复世界 = (
            "夜世界" if 待命恢复世界 in {"夜世界", "建筑大师", "Builder Base"}
            else "主世界"
        )
        内存保护已触发 = bool(getattr(上下文, "_内存保护已触发", False))
        检查可恢复 = getattr(上下文, "是否可自动恢复主机内存保护", None)
        可恢复主机内存 = callable(检查可恢复) and bool(检查可恢复())
        if 内存保护已触发 and not 可恢复主机内存:
            # OCR/native 分配失败等未分类内存错误没有可验证的恢复条件；
            # 保留停止状态，不能用截图检查是否“看起来恢复了”。
            self.停止事件.set()
            上下文.置脚本状态(
                "检测到非宿主机预算类型的内存保护，保持停止；不截图、不重连，需人工复核"
            )
            return False

        if self.停止事件.is_set():
            if self.停止原因:
                上下文.置脚本状态(
                    f"收到明确停止请求（{self.停止原因}），不等待页面恢复"
                )
                return False
            # 页面保护分支会先置停止事件以阻止后续点击；这类保护停机
            # 应进入只读复核，不能被同一事件挡在待命循环之外。
            self.停止事件.clear()
            # 与外部停止并发时，停止原因优先，防止清除刚到达的停止信号。
            if self.停止原因:
                self.停止事件.set()
                上下文.置脚本状态(
                    f"等待恢复时收到明确停止请求（{self.停止原因}），保持停止"
                )
                return False
            上下文.置脚本状态(
                "页面保护已进入只读恢复等待；继续复核画面，不发送游戏输入"
            )
        连续主世界帧 = 0
        上次心跳 = time.monotonic()
        待命开始时间 = 上次心跳
        已发送待命超时通知 = False
        try:
            原始阈值 = getattr(getattr(上下文, "设置", None), "未知页面待命通知秒数", None)
            if 原始阈值 is None and getattr(self, "数据库", None) is not None:
                原始阈值 = getattr(self.设置, "未知页面待命通知秒数", 180)
            待命通知阈值秒 = max(0, int(180 if 原始阈值 is None else 原始阈值))
        except Exception:
            待命通知阈值秒 = 180
        上次截图失败状态 = 0.0
        上次内存状态 = 0.0
        断线自动恢复已尝试 = False
        宝箱领奖自动处理已失败 = False
        敲宝箱自动处理已失败 = False
        敲宝箱尝试次数 = 0
        敲宝箱最多尝试次数 = 3
        最近页面 = getattr(上下文, "_最近点击页面结果", None)
        最近页面名称 = str(getattr(最近页面, "页面", "") or "")
        已确认战后流程 = bool(
            getattr(上下文, "_战斗结束已确认", False)
            or 最近页面名称 in {"战斗结算", "战斗奖励选择", "战斗星级奖励"}
        )
        if 已确认战后流程:
            # 结果页失败后人工点击回营时，可能先出现限时宝箱动画。
            # 安全待命也要在这段窗口识别其明确的“跳过/领取”按钮，
            # 否则只读页面循环会永远停在未知动画页。
            # 进入此分支的证据来自已确认的结果页，不再把该场标记为
            # 仍在战斗；这只影响页面识别分流，不会发送任何输入。
            上下文._战斗中 = False
            上下文._战后星级奖励检查截止时间 = max(
                float(
                    getattr(上下文, "_战后星级奖励检查截止时间", 0.0)
                    or 0.0
                ),
                time.monotonic() + 180.0,
            )
            上下文._战后奖励OCR检查时间 = 0.0
        上下文.置脚本状态(
            f"任务已进入安全待命：暂停所有游戏输入，等待人工处理并确认回到{待命恢复世界}主页"
        )
        self.记录日志("安全待命：等待人工处理或游戏内恢复；当前不发送游戏输入", 120)

        节流设置 = getattr(上下文, "设置运行节流场景", None)
        原节流场景 = getattr(上下文, "_运行节流场景", "活跃")
        if callable(节流设置):
            节流设置("待命观察")
        防休眠 = getattr(self, "_获取防休眠控制器", lambda: None)()
        检查释放 = getattr(上下文, "检查空闲或内存释放识别模型", None)

        try:
          while not self.停止事件.is_set():
            继续事件 = getattr(self, "继续事件", None)
            if 继续事件 is not None and not 继续事件.is_set():
                等待暂停 = getattr(上下文, "等待暂停恢复", None)
                if callable(等待暂停):
                    等待暂停(轮询秒=0.5)
                else:
                    while (
                        not 继续事件.is_set()
                        and not self.停止事件.is_set()
                    ):
                        if 防休眠 is not None:
                            防休眠.允许休眠()
                        if callable(检查释放):
                            检查释放(检查间隔秒=10.0)
                        继续事件.wait(timeout=0.5)
                    if (
                        not self.停止事件.is_set()
                        and 防休眠 is not None
                        and 继续事件.is_set()
                    ):
                        防休眠.保持唤醒()
            if self.停止事件.is_set():
                break
            if 防休眠 is not None and (继续事件 is None or 继续事件.is_set()):
                防休眠.保持唤醒()
            if callable(检查释放):
                检查释放(检查间隔秒=10.0)

            if callable(检查可恢复) and 检查可恢复():
                检查预算恢复 = getattr(上下文, "检查主机内存预算恢复", None)
                if not callable(检查预算恢复):
                    self.停止事件.set()
                    上下文.置脚本状态(
                        "主机内存保护恢复接口不可用，保持停止且不截图"
                    )
                    return False
                try:
                    预算已恢复, 内存诊断 = 检查预算恢复()
                except Exception as 异常:
                    预算已恢复 = False
                    内存诊断 = f"主机内存预算复核异常：{异常}"

                if not 预算已恢复:
                    当前时间 = time.monotonic()
                    if 当前时间 - 上次内存状态 >= 60.0:
                        上下文.置脚本状态(
                            f"主机内存仍未连续恢复，暂不截图：{内存诊断}；10秒后复查"
                        )
                        上次内存状态 = 当前时间
                    if self.停止事件.wait(timeout=10.0):
                        break
                    continue

                # 外部停止在资源检查期间到达时，必须优先于恢复标记清理。
                if self.停止原因 or self.停止事件.is_set():
                    break
                清除内存保护 = getattr(上下文, "清除主机内存保护", None)
                if not callable(清除内存保护):
                    self.停止事件.set()
                    上下文.置脚本状态(
                        "主机内存保护清理接口不可用，保持停止且不截图"
                    )
                    return False
                清除内存保护()
                if getattr(上下文, "_内存保护已触发", False):
                    self.停止事件.set()
                    上下文.置脚本状态(
                        "主机内存保护未能安全清除，保持停止且不截图"
                    )
                    return False
                上下文.置脚本状态(
                    f"主机内存预算已连续恢复：{内存诊断}；开始只读页面复核"
                )
                # 下一轮才允许截图，并且仍需现有的连续双帧目标主页确认。
                continue

            try:
                页面结果 = 上下文.识别点击画面(强制=True)
            except 图像获取失败 as 异常:
                页面结果 = None
                当前时间 = time.monotonic()
                if 当前时间 - 上次截图失败状态 >= 60.0:
                    上下文.置脚本状态(
                        f"安全待命期间截图暂不可用，继续低频等待：{异常}"
                    )
                    上次截图失败状态 = 当前时间

            # 页面复核截图也可能首次触发宿主机提交额度护栏。上下文会先
            # 设置停止事件来阻断所有截图/点击；这里必须把它转成预算轮询，
            # 否则下一次循环会因停止事件直接退出，绕过上面的安全恢复流程。
            if callable(检查可恢复) and 检查可恢复():
                if self.停止原因:
                    上下文.置脚本状态(
                        f"等待内存预算恢复时收到明确停止请求（{self.停止原因}），保持停止"
                    )
                    return False
                self.停止事件.clear()
                # 与外部停止并发时，停止原因优先，不能清除用户刚发出的停止。
                if self.停止原因:
                    self.停止事件.set()
                    上下文.置脚本状态(
                        f"内存预算复核时收到明确停止请求（{self.停止原因}），保持停止"
                    )
                    return False
                上下文.置脚本状态(
                    "待命截图触发宿主机内存保护；停止截图，切换为低频预算复核"
                )
                continue

            页面 = str(getattr(页面结果, "页面", "") or "")
            世界 = str(getattr(页面结果, "世界", "") or "")
            try:
                可信度 = float(getattr(页面结果, "可信度", 0.0) or 0.0)
            except (TypeError, ValueError):
                可信度 = 0.0

            if 页面 == "断线弹窗":
                连续主世界帧 = 0
                if not 断线自动恢复已尝试:
                    断线自动恢复已尝试 = True
                    上下文.置脚本状态("已明确识别游戏断线弹窗，尝试一次受控的游戏内重连")
                    恢复成功 = False
                    try:
                        恢复成功 = bool(检测登录.执行(首次登录=False))
                    except 图像获取失败 as 异常:
                        上下文.置脚本状态(f"游戏内重连截图失败，保持安全待命：{异常}")
                    if self.停止原因:
                        return False
                    if self.停止事件.is_set():
                        # 登录恢复器会用停止事件阻止失败后的任何输入。该事件
                        # 属于本次自动恢复失败时，待命线程应切回只读轮询，
                        # 不能因此退出；用户明确停止仍由上面的停止原因拦截。
                        if getattr(上下文, "_内存保护已触发", False):
                            if not callable(检查可恢复) or not 检查可恢复():
                                return False
                        self.停止事件.clear()
                        if self.停止原因:
                            self.停止事件.set()
                            return False
                    if not 恢复成功:
                        上下文.页面恢复失败 = True
                        上下文.置脚本状态(
                            "自动重连未完成；停止后续自动点击，继续只读待命，等待人工处理后复核主页"
                        )
                    else:
                        上下文.置脚本状态(
                            f"自动重连流程已返回；继续只读复核，需连续确认两帧{待命恢复世界}主页才接续任务"
                        )
            elif 页面 == "战斗星级奖励":
                连续主世界帧 = 0
                处理奖励 = getattr(
                    上下文, "处理战斗星级奖励弹窗", None
                )
                if callable(处理奖励):
                    try:
                        处理奖励()
                    except Exception as 异常:
                        上下文.置脚本状态(
                            f"安全待命处理已确认的战后奖励页失败：{异常}"
                        )
                上下文.置脚本状态(
                    "已确认战后奖励页；阻断普通输入并继续复核主页"
                )
            elif 页面 == "宝箱领奖页":
                连续主世界帧 = 0
                if not 宝箱领奖自动处理已失败 and not getattr(上下文, "_宝石保护已触发", False):
                    清理领奖 = getattr(上下文, "清理宝箱领奖页", None)
                    if callable(清理领奖):
                        try:
                            if 清理领奖():
                                上下文.置脚本状态(
                                    "安全待命已安全收起宝箱领奖页，继续复核主页"
                                )
                            else:
                                宝箱领奖自动处理已失败 = True
                                上下文.置脚本状态(
                                    "宝箱领奖页未通过安全校验或已达点击上限，停止自动点击并保持只读待命"
                                )
                        except Exception as 异常:
                            宝箱领奖自动处理已失败 = True
                            上下文.置脚本状态(
                                f"安全待命处理宝箱领奖页失败，停止自动点击并保持只读待命：{异常}"
                            )
            elif (
                页面 == f"{待命恢复世界}主页"
                and 世界 == 待命恢复世界
                and 可信度 >= 0.70
            ) or (
                待命恢复世界 == "主世界"
                and 页面 == "主世界战斗模式选择"
                and 世界 == "主世界"
                and 可信度 >= 0.90
            ):
                连续主世界帧 += 1
                if 连续主世界帧 >= 2:
                    是战斗模式选择页 = (
                        待命恢复世界 == "主世界"
                        and 页面 == "主世界战斗模式选择"
                    )
                    上下文._主世界战斗模式选择页 = 是战斗模式选择页
                    页面说明 = (
                        "主世界战斗模式选择页"
                        if 是战斗模式选择页
                        else f"{待命恢复世界}主页"
                    )
                    上下文.置脚本状态(
                        f"人工处理后连续{连续主世界帧}帧确认{页面说明}，重新开始任务计划"
                    )
                    self.记录日志(
                        f"人工处理后已连续确认{页面说明}，接续任务计划", 120
                    )
                    恢复 = getattr(上下文, "桌面通知已恢复", None)
                    if callable(恢复):
                        恢复("待命", f"已确认回到{页面说明}，继续任务计划")
                    return True
            else:
                连续主世界帧 = 0
                if (
                    not 敲宝箱自动处理已失败
                    and 敲宝箱尝试次数 < 敲宝箱最多尝试次数
                    and not getattr(上下文, "_宝石保护已触发", False)
                    and not getattr(上下文, "_正在开启奖励宝箱", False)
                    and not self.停止事件.is_set()
                ):
                    屏幕图像 = getattr(上下文, "_点击识别截图", None)
                    if 屏幕图像 is None:
                        取图 = getattr(getattr(上下文, "op", None), "获取屏幕图像cv", None)
                        if callable(取图):
                            try:
                                屏幕图像 = 取图(0, 0, 800, 600, 强制刷新=True)
                            except TypeError:
                                屏幕图像 = 取图(0, 0, 800, 600)
                            except Exception:
                                屏幕图像 = None
                    if 屏幕图像 is not None:
                        from 任务流程.主世界打鱼 import 奖励宝箱
                        if 奖励宝箱.识别宝箱页(屏幕图像) is not None:
                            敲宝箱尝试次数 += 1
                            开箱成功 = False
                            try:
                                开箱成功 = bool(奖励宝箱.开启奖励宝箱(上下文))
                            except Exception as 异常:
                                敲宝箱自动处理已失败 = True
                                上下文.置脚本状态(
                                    f"安全待命处理敲宝箱页失败，停止自动点击并保持只读待命：{异常}"
                                )
                            上下文._点击识别截图 = None
                            上下文._点击识别截图时间 = 0.0
                            if self.停止事件.is_set():
                                break
                            if 开箱成功:
                                上下文.置脚本状态(
                                    "安全待命已安全开启奖励宝箱，继续复核主页"
                                )
                                continue
                            if not 敲宝箱自动处理已失败:
                                敲宝箱自动处理已失败 = True
                                上下文.置脚本状态(
                                    "安全待命开启奖励宝箱未完成，停止自动点击并保持只读待命"
                                )

            当前时间 = time.monotonic()
            if (
                not 已发送待命超时通知
                and 待命通知阈值秒 > 0
                and 当前时间 - 待命开始时间 >= 待命通知阈值秒
            ):
                已发送待命超时通知 = True
                self._处理待命超时通知(
                    上下文,
                    f"安全待命已超过 {int(当前时间 - 待命开始时间)} 秒仍未确认回到{待命恢复世界}主页"
                    f"（当前页面：{页面 or '未知'}）",
                )
            if 当前时间 - 上次心跳 >= 60.0:
                self.记录日志(f"安全待命仍在运行：等待{待命恢复世界}主页复核", 120)
                上次心跳 = 当前时间

            # Event.wait 不会在等待期间处理异步教程/弹窗，也不会产生输入。
            # 停止和暂停都可及时中断/冻结这段低频页面复核。
            if self.停止事件.wait(timeout=5.0):
                break
        finally:
            if callable(节流设置):
                节流设置(原节流场景)

        return False

    def 保存异常现场(self, 类别: str, 原因: str, 当前图像=None) -> bool:
        """安排一份异常现场（当前画面、前几帧、最近日志）到 EXE 同级 异常现场/。

        不阻塞调用方（心跳停止、任务退出、待命路径）：这里只取最后一帧的
        引用和前序帧快照后入队；判断正式数据库、读设置、读日志、编码、写盘
        和写“已保存”日志都在后台写盘线程里做。不调用 ADB。返回是否已入队。
        只在使用正式数据库时留证；测试/临时数据库不往程序目录写现场。
        """
        try:
            from 应用 import 异常留证

            数据库 = getattr(self, "数据库", None)
            文件路径 = getattr(数据库, "文件路径", None)
            if not isinstance(文件路径, str):
                return False
            if 当前图像 is None:
                # 截图提供器里最后一张真实帧（不触发新的 screencap）。
                当前图像 = getattr(getattr(self, "op", None), "_原始截图缓存", None)
            标志 = self.机器人标志

            def 是正式数据库() -> bool:
                return os.path.normcase(os.path.abspath(文件路径)) == os.path.normcase(
                    os.path.abspath(任务数据库.默认数据库路径())
                )

            def 保留份数() -> int:
                return int(getattr(数据库.获取机器人设置(标志), "异常现场保留份数", 异常留证.默认保留份数))

            def 日志摘要() -> list[str]:
                return 异常留证.格式化日志摘要(数据库.查询日志历史(标志, 最大条数=40), 40)

            def 已保存(路径) -> None:
                try:
                    self.记录日志(f"[异常留证] 已保存{类别}现场：{路径}", 300, "警告")
                except Exception:
                    pass

            return 异常留证.保存异常现场(
                类别,
                原因,
                机器人标志=标志,
                当前图像=当前图像,
                日志摘要=日志摘要,
                保留份数=保留份数,
                前置检查=是正式数据库,
                完成回调=已保存,
            )
        except Exception:
            return False

    def _处理待命超时通知(self, 上下文, 原因: str) -> None:
        """待命超阈值后触发一次现场留图与多渠道通知，绝不抛出异常。"""
        self.保存异常现场("未知页面待命", 原因)
        try:
            保存并通知 = getattr(上下文, "保存待命现场截图并通知", None)
            if callable(保存并通知):
                保存并通知(原因)
                return
            from 任务流程.基础任务框架 import 任务上下文 as _任务上下文类

            _任务上下文类.保存待命现场截图并通知(上下文, 原因)
        except Exception as 异常:
            try:
                self.记录日志(f"待命超时通知处理失败（不影响安全待命）：{异常}", 120, "警告")
            except Exception:
                pass

    满仓待机保活间隔秒 = 240.0

    def _满仓待机安全轻拖(self, 上下文, 页面结果) -> bool:
        """仅在确认主世界且长时间满仓待机时轻拖地图，重置游戏闲置计时。"""
        if (
            getattr(页面结果, "页面", "") != "主世界主页"
            or getattr(页面结果, "世界", "") != "主世界"
            or float(getattr(页面结果, "可信度", 0.0) or 0.0) < 0.70
            or getattr(上下文, "页面恢复失败", False)
            or getattr(上下文, "_战斗中", False)
            or self.停止事件.is_set()
        ):
            return False

        继续事件 = getattr(上下文, "继续事件", None)
        if 继续事件 is not None and not 继续事件.is_set():
            return False

        现在 = time.monotonic()
        上次保活 = getattr(上下文, "_满仓待机上次保活时间", None)
        if 上次保活 is None:
            上下文._满仓待机上次保活时间 = 现在
            return False
        try:
            上次保活 = float(上次保活)
        except (TypeError, ValueError):
            上下文._满仓待机上次保活时间 = 现在
            return False
        if 现在 - 上次保活 < self.满仓待机保活间隔秒:
            return False

        设备 = getattr(上下文, "设备", None)
        滑动 = getattr(设备, "滑动", None)
        if not callable(滑动):
            上下文._满仓待机上次保活时间 = 现在
            上下文.置脚本状态("满仓待机保活未执行：模拟器滑动接口不可用，继续安全待机")
            return False

        try:
            # 800×600参考画面中央空地上的短滑动只移动村庄视角，不点击建筑、
            # 战斗入口或资源按钮。ADB 输入层会再次验证 CoC 仍在前台。
            if 滑动((300, 260), (340, 260), 时长毫秒=350) is False:
                上下文._满仓待机上次保活时间 = 现在
                上下文.置脚本状态("满仓待机保活手势被输入层拒绝；继续安全待机")
                return False
        except Exception as 异常:
            上下文._满仓待机上次保活时间 = 现在
            上下文.置脚本状态(f"满仓待机保活手势失败；继续安全待机：{异常}")
            return False

        上下文._满仓待机上次保活时间 = 现在
        上下文.置脚本状态("满仓待机保活：主页已确认，轻拖村庄视角以刷新游戏闲置计时")
        return True

    def _满仓待机并监测断线(self, 上下文, 检测登录) -> bool:
        """满仓待机时复核连接和资源；资源下降后请求任务计划继续刷资源。"""
        待机资源世界 = str(
            getattr(上下文, "_待命恢复世界", "主世界") or "主世界"
        ).strip()
        待机资源世界 = (
            "夜世界" if 待机资源世界 in {"夜世界", "建筑大师", "Builder Base"}
            else "主世界"
        )
        上下文.置脚本状态("资源已达到目标，按设置进入待机；每分钟复核连接，不启动战斗")
        节流设置 = getattr(上下文, "设置运行节流场景", None)
        原节流场景 = getattr(上下文, "_运行节流场景", "活跃")
        if callable(节流设置):
            节流设置("满仓待机")
        try:
          while not self.停止事件.is_set():
            原长时间等待状态 = bool(
                getattr(上下文, "_任务计划长时间等待", False)
            )
            上下文._任务计划长时间等待 = True
            try:
                上下文.脚本延时(60_000)
            finally:
                上下文._任务计划长时间等待 = 原长时间等待状态
            if self.停止事件.is_set():
                break

            识别页面 = getattr(上下文, "识别点击画面", None)
            if not callable(识别页面):
                continue
            try:
                页面结果 = 识别页面(强制=True)
            except Exception as 异常:
                上下文.置脚本状态(f"满仓待机连接复核失败，继续低频等待：{异常}")
                continue

            if getattr(页面结果, "页面", "") != "断线弹窗":
                主页名称 = f"{待机资源世界}主页"
                if not (
                    getattr(页面结果, "页面", "") == 主页名称
                    and getattr(页面结果, "世界", "") == 待机资源世界
                    and float(getattr(页面结果, "可信度", 0.0) or 0.0) >= 0.70
                ):
                    continue

                try:
                    更新任务 = (
                        更新夜世界资源状态任务
                        if 待机资源世界 == "夜世界"
                        else 更新家乡资源状态任务
                    )
                    资源刷新成功 = bool(更新任务(上下文).执行())
                    if (
                        not 资源刷新成功
                        or (
                            待机资源世界 == "主世界"
                            and getattr(上下文, "_最近资源识别成功", None) is False
                        )
                    ):
                        上下文.置脚本状态(
                            "满仓待机资源复核未成功；保留待机，不基于旧数值启动战斗"
                        )
                        continue
                    当前状态 = 上下文.数据库.获取最新完整状态(self.机器人标志)
                    if 待机资源世界 == "夜世界":
                        当前资源 = self._取已确认夜世界资源(当前状态)
                    else:
                        当前资源 = self._取已确认家乡资源(当前状态)
                    if 当前资源 is None:
                        上下文.置脚本状态(
                            "满仓待机未取得完整资源快照；保留待机，不基于未知数值启动战斗"
                        )
                        continue
                    if 待机资源世界 == "夜世界":
                        当前等级 = getattr(上下文, "_夜世界大本营等级", None)
                        if 当前等级 is None:
                            当前等级 = getattr(
                                getattr(self, "设置", None),
                                "夜世界大本营等级",
                                None,
                            )
                        仍然打满 = 是否夜世界资源打满(
                            当前资源, 模式="夜世界", 等级=当前等级
                        )
                    else:
                        历史峰值 = 上下文.数据库.获取近期家乡资源峰值(self.机器人标志)
                        当前优先级 = getattr(
                            getattr(self, "设置", None), "战利品优先级", "均衡"
                        )
                        仍然打满 = 是否目标资源打满(
                            当前资源,
                            当前优先级,
                            历史峰值,
                            getattr(
                                getattr(self, "设置", None),
                                "黑油储存上限",
                                500_000,
                            ),
                        )
                    if not 仍然打满:
                        上下文.置脚本状态(
                            f"{待机资源世界}资源已从满仓状态下降，返回任务计划继续刷资源"
                        )
                        return True
                    if 待机资源世界 == "主世界":
                        self._满仓待机安全轻拖(上下文, 页面结果)
                except Exception as 异常:
                    上下文.置脚本状态(
                        f"满仓待机资源复核失败；保留待机，不启动战斗：{异常}"
                    )
                continue

            上下文.置脚本状态("满仓待机检测到断线弹窗，交给受控重新登入流程")
            上下文.页面恢复失败 = True
            if self._等待人工恢复主世界(上下文, 检测登录):
                上下文.页面恢复失败 = False
                上下文.置脚本状态("满仓待机中的连接已恢复并复核主页；继续待机，不启动战斗")
                continue
            if self.停止原因 or self.停止事件.is_set():
                break
        finally:
            if callable(节流设置):
                节流设置(原节流场景)

        return False

    def _任务流程(self):
        """主任务逻辑；初始化失败也必须留下可诊断的停止状态。"""
        企业微信通知器实例 = None
        上下文 = None
        self._初始化通知器 = None
        try:
            设置, 上下文, 企业微信通知器实例 = self._初始化任务上下文()
        except Exception as 异常:
            self.停止原因 = f"初始化失败：{异常}"
            self.停止事件.set()
            try:
                self.记录日志(f"[错误] 机器人初始化失败：{异常}", 300, "错误")
            except Exception:
                pass
            _安全控制台打印(f"机器人[{self.机器人标志}]初始化失败：{异常}")
            try:
                部分初始化通知器 = getattr(self, "_初始化通知器", None)
                if 企业微信通知器实例 or 部分初始化通知器:
                    (企业微信通知器实例 or 部分初始化通知器).关闭()
            except Exception as 关闭异常:
                _安全控制台打印(f"初始化失败后的通知器关闭失败：{关闭异常}")
            self._初始化通知器 = None
            try:
                if getattr(self, "op", None) is not None:
                    self.op.安全清理()
            except Exception as 清理异常:
                _安全控制台打印(f"初始化失败后的 ADB 清理失败：{清理异常}")
            return

        try:
            防休眠 = self._获取防休眠控制器()
            绑定 = getattr(防休眠, "绑定线程", None)
            if callable(绑定):
                绑定()
            上下文._防休眠控制器 = 防休眠
            继续事件 = getattr(self, "继续事件", None)
            停止事件 = getattr(self, "停止事件", None)
            if (继续事件 is None or 继续事件.is_set()) and not (
                停止事件 is not None and 停止事件.is_set()
            ):
                防休眠.保持唤醒()

            检测登录 = 检测游戏登录状态任务(上下文)#检测任务需要重复调用，这里先创建，但是不执行


            阶段日志 = getattr(上下文, "置脚本状态", None) or (lambda *_参数, **_关键字: None)
            阶段日志("开始任务：启动游戏")
            if not 启动模拟器任务(上下文).执行():
                return
            阶段日志("完成任务：启动游戏")

            # 截图与输入始终使用同一个明确选定的 ADB 序列号。

            if not 检查图像任务(上下文).执行():
                return

            # 发送启动通知
            from datetime import datetime
            上下文.发送企业微信通知(
                f"✅ 机器人已启动\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                包含截图=True
            )

            if not 检测登录.执行():
                return
            # 重新启动并已登录：之前弹过的“停止/异常退出”通知补一条已恢复。
            from 工具包.桌面通知 import 机器人桌面恢复

            for 键 in ("停止", "线程异常"):
                机器人桌面恢复(self.机器人标志, 键, "机器人已重新启动并登录，继续执行任务计划")

            if not self._接管启动时战斗(上下文, 检测登录):
                return


            设置 = self.设置
            self._同步官方账号数据(上下文, 强制=True)
            任务顺序 = self._任务计划顺序(设置)
            # 子任务不得越过用户的任务计划调用另一个未选中的任务。
            # 目前唯一存在跨任务补充链的是“刷墙 -> 主世界刷资源”。
            上下文._启用任务键集合 = frozenset(任务顺序)
            上下文._任务计划当前顺序 = tuple(任务顺序)
            上下文._外层任务下次检查时间 = {}
            上下文.置脚本状态("任务计划顺序：" + " → ".join(任务顺序 or ["无启用任务"]))
            是否有资源打满 = False

            if not 任务顺序:
                上下文.置脚本状态("没有启用任务，结束本次运行")
            else:
                任务轮次 = 0
                while not self.停止事件.is_set():
                    是否有资源打满 = False
                    重新开始本轮 = False
                    上下文._本轮已完成任务键 = set()
                    上下文._内层让出外层调度 = False
                    任务轮次 += 1
                    self._记录进程资源趋势(上下文)
                    if 任务轮次 > 1:
                        上下文.置脚本状态(
                            f"第{任务轮次}轮任务计划开始：上一轮未达到结束条件，继续执行"
                        )
                    # 每一轮都从可恢复状态开始；页面确认失败仍由下面的
                    # 安全分支终止，不能靠循环掩盖真实异常。
                    上下文.页面恢复失败 = False
                    # 默认保留原有的 5 秒轮询；冷却型任务可以在本轮内请求
                    # 更长等待，避免每 5 秒重复截图/OCR。
                    上下文.任务计划等待秒 = 5.0
                    上下文._任务计划等待原因 = "常规轮询"

                    # 任务计划中的每一个项目只在自己的位置执行，避免旧版固定顺序覆盖用户选择。
                    for 任务键 in 任务顺序:
                        if self.停止事件.is_set():
                            break
                        任务名称 = getattr(任务计划定义映射.get(任务键), "名称", 任务键)
                        上下文.置脚本状态(f"开始任务：{任务名称}")
                        上下文._本项请求等待秒 = 0.0
                        try:
                            任务结果, 本项资源打满 = self._执行任务计划项(
                                任务键, 上下文, 检测登录
                            )
                        except 主机内存保护暂停请求 as 内存暂停:
                            上下文.置脚本状态(
                                f"任务[{任务键}]触发宿主机内存保护暂停，转入只读恢复等待：{内存暂停}"
                            )
                            上下文.页面恢复失败 = True
                            任务结果, 本项资源打满 = False, False
                        except 图像获取失败 as 截图异常:
                            判断内存 = getattr(上下文, "是否内存异常", None)
                            if (
                                callable(判断内存)
                                and 判断内存(截图异常)
                                and "主机内存保护已触发" in str(截图异常)
                            ):
                                触发保护 = getattr(上下文, "触发内存保护", None)
                                if callable(触发保护):
                                    触发保护(f"任务[{任务键}]截图", 截图异常)
                                上下文.页面恢复失败 = True
                                任务结果, 本项资源打满 = False, False
                            else:
                                raise
                        if 任务结果:
                            上下文.置脚本状态(f"完成任务：{任务名称}")
                            上下文._本轮已完成任务键.add(任务键)
                            if 任务键 != "main_resource":
                                项等待 = float(
                                    getattr(上下文, "_本项请求等待秒", 0.0) or 0.0
                                )
                                if 项等待 > 0.0:
                                    上下文._外层任务下次检查时间[任务键] = (
                                        time.monotonic() + 项等待
                                    )
                                elif 任务键 in {"building", "hero"}:
                                    共享到期 = max(
                                        float(
                                            上下文._外层任务下次检查时间.get("building", 0.0)
                                            or 0.0
                                        ),
                                        float(
                                            上下文._外层任务下次检查时间.get("hero", 0.0)
                                            or 0.0
                                        ),
                                    )
                                    if 共享到期 > time.monotonic():
                                        上下文._外层任务下次检查时间[任务键] = 共享到期
                                    else:
                                        上下文._外层任务下次检查时间[任务键] = (
                                            time.monotonic() + 300.0
                                        )
                                elif 任务键 != "event":
                                    上下文._外层任务下次检查时间[任务键] = (
                                        time.monotonic() + 300.0
                                    )
                        elif not self.停止事件.is_set():
                            上下文.置脚本状态(f"[警告] 任务未完成：{任务名称}", 60)
                        是否有资源打满 = 是否有资源打满 or 本项资源打满
                        if not 任务结果 and not getattr(上下文, "页面恢复失败", False):
                            上下文.置脚本状态(
                                f"任务[{任务键}]未完成，停止本轮后续任务，避免在未知页面继续点击"
                            )
                            上下文.页面恢复失败 = True
                        if getattr(上下文, "页面恢复失败", False):
                            if self._等待人工恢复主世界(上下文, 检测登录):
                                上下文.页面恢复失败 = False
                                重新开始本轮 = True
                            else:
                                上下文.置脚本状态("安全待命结束，停止后续任务和所有点击")
                            break

                    if self.停止事件.is_set():
                        break
                    if 重新开始本轮:
                        continue
                    if getattr(上下文, "页面恢复失败", False):
                        break
                    if 是否有资源打满:
                        try:
                            继续刷资源 = (
                                设置.资源打满后动作 == "待机"
                                and not self.停止事件.is_set()
                                and self._满仓待机并监测断线(上下文, 检测登录)
                            )
                        except 主机内存保护暂停请求 as 内存暂停:
                            上下文.置脚本状态(
                                f"满仓待机期间触发宿主机内存保护暂停，转入只读恢复等待：{内存暂停}"
                            )
                            上下文.页面恢复失败 = True
                            if self._等待人工恢复主世界(上下文, 检测登录):
                                上下文.页面恢复失败 = False
                                是否有资源打满 = False
                                continue
                            break
                        if 继续刷资源:
                            是否有资源打满 = False
                            continue
                        break

                    if getattr(上下文, "_内层让出外层调度", False):
                        上下文._内层让出外层调度 = False
                        上下文.置脚本状态("主世界打鱼已让出至外层调度，立即继续执行任务计划")
                        continue

                    # 没有达到结束条件时，任务计划完成一轮后自动继续，
                    # 不再把正常完成一轮误标记为线程死亡。研究/战宠等
                    # 冷却型任务可以请求小时级等待，但仍走可中断延时。
                    try:
                        等待秒 = max(5.0, min(
                            3600.0, float(getattr(上下文, "任务计划等待秒", 5.0))
                        ))
                    except (TypeError, ValueError):
                        等待秒 = 5.0
                    等待原因 = str(getattr(上下文, "_任务计划等待原因", "") or "")
                    if 等待秒 >= 60:
                        上下文.置脚本状态(
                            f"本轮任务计划完成，约{int(等待秒 // 60)}分钟后重新检查"
                            + (f"（{等待原因}）" if 等待原因 else "")
                        )
                    else:
                        上下文.置脚本状态(
                            f"本轮任务计划完成，{int(等待秒)}秒后自动开始下一轮"
                        )
                    上下文._任务计划长时间等待 = 等待秒 >= 60
                    节流设置 = getattr(上下文, "设置运行节流场景", None)
                    原节流场景 = getattr(上下文, "_运行节流场景", "活跃")
                    if 上下文._任务计划长时间等待 and callable(节流设置):
                        节流设置("长时等待")
                    try:
                        上下文.脚本延时(int(等待秒 * 1000))
                    except 主机内存保护暂停请求 as 内存暂停:
                        上下文.置脚本状态(
                            f"轮次等待期间触发宿主机内存保护暂停，转入只读恢复等待：{内存暂停}"
                        )
                        上下文.页面恢复失败 = True
                        if self._等待人工恢复主世界(上下文, 检测登录):
                            上下文.页面恢复失败 = False
                            continue
                        break
                    finally:
                        # 下一轮必须恢复普通维护频率；异常/停止也不能把
                        # 这个运行期标志带入后续任务。
                        上下文._任务计划长时间等待 = False
                        if callable(节流设置):
                            节流设置(原节流场景)

            if 是否有资源打满 and 设置.资源打满后动作 != "待机":
                上下文.置脚本状态("资源已达到目标，按设置退出任务")
            #升级英雄(上下文,"野蛮人之王").执行()
           # 建筑升级任务(上下文).执行()
            # 寻找建筑(上下文,["亡灵王子","大守护者","复合机械塔"]).执行()


            _安全控制台打印("-"*10+F"{self.机器人标志} 任务线程退出"+"-"*10)
            if getattr(上下文, "页面恢复失败", False):
                if not self.停止原因:
                    self.停止原因 = "页面恢复失败，已停止后续任务；请查看最后日志"
            elif not self.停止事件.is_set():
                self.停止原因 = "任务自然完成"
            elif not self.停止原因:
                self.停止原因 = "任务触发停止事件，请查看最后日志"
            self.停止事件.set()  # 标志目前线程已经停止了,以免监控中心一直启动

        except 图像获取失败 as e:
            self.停止原因 = f"图像获取失败：{e}"
            上下文.发送死亡通知(f"异常: {str(e)}")
            _安全控制台打印("-"*10+F"{self.机器人标志} 任务线程因图像异常退出"+"-"*10+f"异常: {str(e)}")
        except 主机内存保护暂停请求 as e:
            if not self.停止原因:
                self.停止原因 = f"宿主机内存保护退出：{e}"
            self.停止事件.set()
            _安全控制台打印("-"*10+F"{self.机器人标志} 因宿主机内存保护结束待命"+"-"*10)
        except SystemExit as e:
            if not self.停止原因:
                self.停止原因 = "收到外部停止事件"
            _安全控制台打印("-"*10+F"{self.机器人标志} 任务线程收到停止信号退出"+"-"*10)
            _安全控制台打印(F"具体信息:{str(e)}")
        except Exception as e:
            self.停止原因 = f"未处理异常：{e}"
            import traceback
            诊断信息 = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            _安全控制台打印(诊断信息)
            self.记录日志(f"[错误] 初始化或任务执行失败：{e}", 300, "错误")
            self._写入未处理异常日志(诊断信息)
            self.停止事件.set()
        finally:
            try:
                防休眠 = self._获取防休眠控制器()
                防休眠.允许休眠()
                解绑 = getattr(防休眠, "解除绑定线程", None)
                if callable(解绑):
                    解绑()
            except Exception:
                pass
            # 早期检查直接 return、截图异常和任务分支主动退出都必须把
            # 线程状态收敛为“已停止”；保留已有的外部停止或异常原因。
            if not self.停止原因:
                self.停止原因 = "任务流程提前结束，请查看最后日志"
            self.停止事件.set()
            self._异常退出留证(上下文)
            self._桌面通知线程停止()
            # 在清理 op 之前发送停止通知（此时 op 还活着，可以截图）
            try:
                if 企业微信通知器实例:
                    from datetime import datetime
                    停止原因 = self.停止原因 or "线程退出"

                    # 获取截图（内存保护已触发时禁止二次截图）
                    截图 = None
                    if not getattr(上下文, "_内存保护已触发", False):
                        try:
                            截图 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
                        except Exception:
                            pass  # 截图失败不影响通知发送

                    # 停止通知必须同步发送，确保截图在线程退出前完成 HTTP 请求
                    企业微信通知器实例._同步发送状态消息(
                        机器人标志=self.机器人标志,
                        状态文本=f"⛔ 机器人已停止\n原因: {停止原因}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        截图=截图
                    )
            except Exception as e:
                _安全控制台打印(f"发送停止通知失败: {e}")

            if 上下文 is not None:
                try:
                    上下文.释放识别模型()
                except Exception as e:
                    _安全控制台打印(f"释放识别模型失败: {e}")
                try:
                    上下文.op.安全清理()
                except Exception as e:
                    _安全控制台打印(f"ADB 屏幕清理失败: {e}")
            elif getattr(self, "op", None) is not None:
                try:
                    self.op.安全清理()
                except Exception as e:
                    _安全控制台打印(f"初始化阶段 ADB 屏幕清理失败: {e}")
            try:
                if 企业微信通知器实例:
                    企业微信通知器实例.关闭()
            except Exception as e:
                _安全控制台打印(f"关闭企业微信通知线程失败: {e}")

    def 只读确认主世界主页(self, 帧数: int = 2, 间隔秒: float = 2.0) -> tuple[bool, str]:
        """自动重启前的只读复核：连续多帧新截图都识别为主世界主页才返回 True。

        只截图和识别，绝不发送任何输入；线程运行中调用直接拒绝。
        """
        if not self.停止事件.is_set():
            return False, "机器人仍在运行"
        设置 = self.数据库.获取机器人设置(self.机器人标志)
        if not getattr(设置, "ADB已确认模拟器", False) or not getattr(设置, "ADB设备序列号", ""):
            return False, "未配置模拟器连接"
        设备 = ADB设备操作类(
            设置.ADB路径,
            设置.ADB设备序列号,
            自动检测路径=getattr(设置, "ADB自动检测路径", True),
            内存保护提交额度阈值MB=getattr(设置, "内存保护提交额度阈值MB", 1536),
        )
        屏幕 = ADB屏幕(设备, 日志回调=self.记录日志)
        try:
            from 模块.检测.模板匹配器 import 模板匹配引擎
            from 模块.检测.页面识别器 import 页面识别器

            识别器 = 页面识别器(模板匹配引擎())
            说明 = ""
            for 序号 in range(max(1, int(帧数))):
                if 序号:
                    time.sleep(max(0.0, float(间隔秒)))
                try:
                    图像 = 屏幕.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
                except TypeError:
                    图像 = 屏幕.获取屏幕图像cv(0, 0, 800, 600)
                结果 = 识别器.识别(图像, 战斗中=False)
                页面 = str(getattr(结果, "页面", "") or "")
                世界 = str(getattr(结果, "世界", "") or "")
                可信度 = float(getattr(结果, "可信度", 0.0) or 0.0)
                说明 = f"页面={页面 or '未知'} 世界={世界 or '未知'} 置信度={可信度:.2f}"
                if not (页面 == "主世界主页" and 世界 == "主世界" and 可信度 >= 0.70):
                    return False, 说明
            return True, 说明
        except Exception as 异常:
            return False, f"截图/识别失败：{异常}"
        finally:
            try:
                屏幕.安全清理()
            except Exception:
                pass

    人工停止原因 = frozenset({"控制台关闭", "手动终止", "界面停止按钮", "未启动"})

    # 心跳超时由监控中心在停止前留证；人工停止和任务自然完成不留证。
    _不留证停止原因 = frozenset({"任务自然完成", "无心跳"})

    def _异常退出留证(self, 上下文) -> None:
        try:
            原因 = str(self.停止原因 or "")
            if 原因 in self.人工停止原因 or 原因 in self._不留证停止原因:
                return
            self.保存异常现场("异常退出", 原因)
        except Exception:
            pass

    def _桌面通知线程停止(self) -> None:
        """线程结束时弹桌面通知；人工停止（界面按钮/关窗）不弹。"""
        try:
            原因 = str(self.停止原因 or "线程退出")
            if 原因 in self.人工停止原因:
                return
            from 工具包.桌面通知 import 机器人桌面通知

            try:
                设置 = self.设置
            except Exception:
                设置 = None
            if 原因.startswith("未处理异常") or 原因.startswith("图像获取失败") or 原因.startswith("初始化失败"):
                机器人桌面通知(设置, self.机器人标志, "线程异常", "线程异常退出", 原因[:300], 级别="错误")
            elif 原因 == "任务自然完成":
                机器人桌面通知(设置, self.机器人标志, "停止", "任务计划已完成，脚本停止", 原因, 级别="信息")
            else:
                机器人桌面通知(设置, self.机器人标志, "停止", "脚本已停止", 原因[:300])
        except Exception:
            pass

    def 检查超时(self) -> tuple[bool, str]:
        """检查是否超时，返回 (是否超时, 原因)。未超时返回 (False, '')"""

        最后日志 = self.数据库.读取最后日志(self.机器人标志)
        # 无历史日志的情况
        if not 最后日志:
            return (False, "无历史日志记录")  # 无日志视为第一次启动,不是超时的异常状态

        # 主动停止不视为超时
        if self.停止事件.is_set():

            return (False, F"{self.机器人标志} 线程已主动停止,不是异常状态")
        if hasattr(self, "继续事件") and not self.继续事件.is_set():
            return (False, "机器人已暂停，不计算任务心跳超时")

        当前时间 = time.time()
        宽限截止时间 = 最后日志.下次超时 + self.心跳超时宽限秒数
        if 当前时间 > 宽限截止时间:
            实际间隔 = round(当前时间 - 最后日志.记录时间)
            超时阈值 = round(最后日志.下次超时 - 最后日志.记录时间)

            原因 = (
                f"数据库最后日志记录已超时（内容：[{最后日志.日志内容}]），"
                f"实际间隔 {实际间隔} 秒超过阈值 {超时阈值} 秒（含{self.心跳超时宽限秒数}秒宽限）"
            )

            return True, 原因

        return (False, "")
