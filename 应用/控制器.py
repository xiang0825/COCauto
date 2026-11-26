"""游戏控制服务：界面和快捷键共用的启停入口。

控制台只控制一个游戏（一个模拟器里的一个 CoC），类似 MAA 的单实例
模式：一份连接设置、一份任务计划、一组开始/暂停/停止按钮。

引擎内部仍用一个“机器人标志”区分数据库里的设置和日志。旧版本可能
存了多份机器人配置，这里按“最近一次有运行日志的那份”自动选用，其余
配置原样保留在数据库里，不会被删除。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from 数据库 import 今日统计
from 数据库.任务数据库 import 任务数据库, 机器人设置
from 应用.任务计划 import 已启用任务名称

状态运行中 = "运行中"
状态暂停中 = "暂停中"
状态已停止 = "已停止"

默认实例ID = "robot_1"


def 选择主实例ID(数据库) -> str:
    """从已有配置中选出要控制的那一份；没有配置时返回默认 ID。

    规则固定、与界面无关，命令行入口和自动启动脚本也用同一规则：
    1. 有运行日志的配置里，选最后一条日志最新的；
    2. 否则优先 ``robot_1``；
    3. 否则按名称排序取第一份。
    """
    try:
        所有配置 = list(数据库.查询所有机器人设置())
    except Exception:
        所有配置 = []
    if not 所有配置:
        return 默认实例ID
    最新: tuple[float, str] | None = None
    for 标志 in 所有配置:
        try:
            日志 = 数据库.读取最后日志(标志)
        except Exception:
            日志 = None
        if 日志 is not None:
            时间 = float(getattr(日志, "记录时间", 0) or 0)
            if 最新 is None or 时间 > 最新[0]:
                最新 = (时间, 标志)
    if 最新 is not None:
        return 最新[1]
    if 默认实例ID in 所有配置:
        return 默认实例ID
    return sorted(所有配置)[0]


@dataclass(frozen=True)
class 运行快照:
    """界面一次刷新所需的只读状态，避免界面直接访问线程对象。"""

    状态: str
    停止原因: str
    设备序列号: str
    设备已确认: bool
    已选任务: tuple[str, ...]
    最近日志: str
    最近日志时间: float | None = None
    已运行秒: float | None = None

    @property
    def 设备描述(self) -> str:
        if self.设备序列号 and self.设备已确认:
            return f"已确认 · {self.设备序列号}"
        if self.设备序列号:
            return f"未确认 · {self.设备序列号}"
        return "未配置"


@dataclass(frozen=True)
class 今日概况:
    今日: 今日统计.今日数据
    竞赛: dict

    @property
    def 竞赛积分(self) -> tuple[int, int] | None:
        积分 = self.竞赛.get("个人积分")
        if isinstance(积分, (list, tuple)) and len(积分) == 2:
            try:
                return int(积分[0]), int(积分[1])
            except (TypeError, ValueError):
                return None
        return None


class 应用控制器:
    """包装 ``机器人监控中心``，只暴露一个游戏实例。所有方法可在界面线程调用。"""

    def __init__(self, 监控中心, 数据库: 任务数据库 | None = None):
        self.监控中心 = 监控中心
        self.数据库 = 数据库 or getattr(监控中心, "数据库", None) or 任务数据库()
        self.实例ID = 默认实例ID
        self._设置缓存: tuple[float, 机器人设置] | None = None
        self._开始时间: float | None = None
        self._概况缓存: tuple[float, 今日概况] | None = None
        self._上次状态 = 状态已停止
        self._日志清理中 = False

    # ---------------------------------------------------------- 初始化
    def 准备(self) -> str:
        """选定要控制的配置并创建引擎实例，返回实例 ID。"""
        self.实例ID = 选择主实例ID(self.数据库)
        if not self.数据库.查询所有机器人设置():
            self.数据库.保存机器人设置(self.实例ID, 机器人设置())
        if self.实例ID not in self.监控中心.机器人池:
            self.监控中心.创建机器人(
                机器人标志=self.实例ID,
                初始设置=self.数据库.获取机器人设置(self.实例ID),
            )
        return self.实例ID

    @property
    def _实例(self):
        return self.监控中心.机器人池.get(self.实例ID)

    # ---------------------------------------------------------- 设置
    def 获取设置(self) -> 机器人设置:
        return self.数据库.获取机器人设置(self.实例ID)

    # 连接字段只由设备服务和引擎（自动绑定模拟器）直接写库；界面手里的设置对象
    # 可能是很久以前载入的，保存任务参数时不能把较新的连接信息改回去。
    连接字段 = ("ADB路径", "ADB自动检测路径", "ADB设备序列号", "ADB已确认模拟器")

    def 保存任务设置(self, 设置: 机器人设置) -> None:
        """界面保存任务参数用：连接字段沿用库里的最新值，其余按传入对象保存。"""
        try:
            库中 = self.数据库.获取机器人设置(self.实例ID)
        except Exception:
            库中 = None
        if 库中 is not None:
            for 字段 in self.连接字段:
                if hasattr(库中, 字段):
                    setattr(设置, 字段, getattr(库中, 字段))
        self.保存设置(设置)

    def 保存设置(self, 设置: 机器人设置) -> None:
        post = getattr(设置, "__post_init__", None)
        if callable(post):
            post()
        self.数据库.保存机器人设置(self.实例ID, 设置)
        self._设置缓存 = None

    def 设置已变更(self) -> None:
        """其它服务直接写了数据库（例如连接页保存设备）后调用，刷新快照。"""
        self._设置缓存 = None

    def _缓存设置(self, 最长秒: float = 3.0) -> 机器人设置:
        现在 = time.monotonic()
        if self._设置缓存 and 现在 - self._设置缓存[0] < 最长秒:
            return self._设置缓存[1]
        设置 = self.数据库.获取机器人设置(self.实例ID)
        self._设置缓存 = (现在, 设置)
        return 设置

    # ---------------------------------------------------------- 运行控制
    @property
    def 状态(self) -> str:
        实例 = self._实例
        return str(getattr(实例, "当前状态", 状态已停止)) if 实例 else 状态已停止

    def 启动(self) -> None:
        if self._实例 is None:
            raise RuntimeError("控制台尚未初始化完成")
        self.监控中心.启动机器人(self.实例ID)
        self._开始时间 = time.time()

    def 暂停(self) -> None:
        if self._实例 is not None:
            self._实例.暂停()

    def 继续(self) -> None:
        实例 = self._实例
        if 实例 is None:
            return
        if self.状态 == 状态已停止:
            # 已退出的线程不能“继续”，必须重新走启动护栏。
            self.启动()
            return
        实例.继续()

    def 停止(self, 原因: str = "界面停止按钮") -> threading.Thread | None:
        """在后台线程中停止并等待任务线程退出，界面不会卡住。"""
        实例 = self._实例
        if 实例 is None:
            return None
        线程 = threading.Thread(
            target=实例.停止, args=(原因,), name="停止任务", daemon=True,
        )
        线程.start()
        return 线程

    # ---------------------------------------------------------- 停止后清空日志
    停止后清空等待秒 = 2.0
    等待线程退出秒 = 60.0

    def 检测到停止(self) -> bool:
        """界面每秒调用：从运行/暂停变为已停止的那一次返回 True（之后不重复）。

        停止按钮、任务计划正常结束、异常/无心跳停止都会走到这里；清理正在
        进行时不再触发第二次。
        """
        状态 = self.状态
        上次, self._上次状态 = self._上次状态, 状态
        if 上次 in (状态运行中, 状态暂停中) and 状态 == 状态已停止 and not self._日志清理中:
            self._日志清理中 = True
            return True
        return False

    def _有机器人在运行(self) -> bool:
        for 机器人 in list(getattr(self.监控中心, "机器人池", {}).values()):
            if str(getattr(机器人, "当前状态", 状态已停止)) != 状态已停止:
                return True
        return False

    def 停止后清空日志(self, 睡眠=time.sleep) -> tuple[int, float] | None:
        """后台线程执行：等任务线程退出后导出备份（只留上一份）并清空任务日志。

        返回 ``(导出条数, 清空截止时间戳)``；有机器人仍在运行或刚被重新启动时
        返回 None，什么都不删。只动 任务日志 表，运行时状态等其它表不碰。
        """
        try:
            实例 = self._实例
            主线程 = getattr(实例, "主线程", None)
            if 主线程 is not None and 主线程 is not threading.current_thread():
                try:
                    主线程.join(timeout=self.等待线程退出秒)
                except RuntimeError:
                    pass
            # 留一点时间给停止前最后几条日志落库、异常留证读取日志摘要。
            睡眠(self.停止后清空等待秒)
            if self._有机器人在运行():
                print("[控制器] 有任务仍在运行，本次不清空日志")
                return None
            from 数据库.日志轮转 import 停止后导出并清空

            截止 = time.time()
            条数 = 停止后导出并清空(getattr(self.数据库, "文件路径", 任务数据库.默认数据库路径()))
            return 条数, 截止
        finally:
            self._日志清理中 = False

    def 开始或继续(self) -> bool:
        """F1：只启动已停止的任务，或恢复已暂停的任务。"""
        if self._实例 is None:
            return False
        if self.状态 == 状态暂停中:
            self.继续()
            return True
        if self.状态 == 状态已停止:
            self.启动()
            return True
        return False

    def 仅暂停(self) -> bool:
        """F2：只暂停正在运行的任务，不会误启动。"""
        if self.状态 != 状态运行中:
            return False
        self.暂停()
        return True

    # ---------------------------------------------------------- 快照
    def 快照(self) -> 运行快照:
        实例 = self._实例
        try:
            设置 = self._缓存设置()
        except Exception:
            设置 = 机器人设置()
        try:
            日志 = self.数据库.读取最后日志(self.实例ID)
        except Exception:
            日志 = None
        return 运行快照(
            状态=self.状态,
            停止原因=str(getattr(实例, "停止原因", "") or ""),
            设备序列号=str(getattr(设置, "ADB设备序列号", "") or "").strip(),
            设备已确认=bool(getattr(设置, "ADB已确认模拟器", False)),
            已选任务=tuple(已启用任务名称(设置)),
            最近日志=(str(日志.日志内容)[:200] if 日志 else ""),
            最近日志时间=(float(日志.记录时间) if 日志 else None),
            已运行秒=(
                time.time() - self._开始时间
                if self._开始时间 is not None and self.状态 != 状态已停止 else None
            ),
        )

    def 今日概况(self, 最长秒: float = 5.0) -> "今日概况":
        """今日战斗/收益与部落竞赛进度；界面每秒调用，内部最多每 5 秒查一次库。"""
        现在 = time.monotonic()
        if self._概况缓存 and 现在 - self._概况缓存[0] < 最长秒:
            return self._概况缓存[1]
        概况 = 今日概况(
            今日=今日统计.读取今日(self.数据库, self.实例ID),
            竞赛=今日统计.读取部落竞赛(self.数据库, self.实例ID),
        )
        self._概况缓存 = (现在, 概况)
        return 概况

    def 关闭(self) -> None:
        try:
            self.监控中心.关闭()
        except Exception:
            self.监控中心.运行标志 = False
