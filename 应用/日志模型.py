"""运行日志的筛选、去重与聚合（与界面无关）。

日志有三个来源：
- 机器人线程写入 SQLite 的历史日志（完整、可追溯）；
- 机器人通过实时队列推送的消息（低延迟，可能丢弃最旧条目）；
- 界面操作日志（例如“已保存设置”）。

``日志聚合器`` 负责把三者合并、去重、按模式筛选并折叠连续重复项，
界面只需要把 ``渲染条目`` 画出来。
"""
from __future__ import annotations

import queue
import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

级别正常 = "正常"
级别警告 = "警告"
级别错误 = "错误"

筛选模式列表 = ("重点", "全部", "异常")

# 高频页面轮询、坐标尝试和截图缓存不适合默认占满观察区。
噪声片段 = (
    "点击护栏画面识别",
    "页面识别：页面=",
    "页面=战斗中，世界=未知，置信度=1.00",
    "截图缓存",
    "识别等待",
)
重点片段 = (
    "启动", "停止", "暂停", "继续", "连接", "ADB", "任务计划", "按任务计划",
    "失败", "异常", "错误", "警告", "危险", "资源不足", "缺少资源", "刷墙",
    "城墙", "升级", "战斗", "进攻", "战利品", "胜利", "星", "摧毁", "回营",
    "下一场", "主世界", "夜世界", "宝石", "商店", "下兵点未被游戏接受",
    "任务异常终止", "通知监控恢复", "线程即将死亡",
)

_实时前缀 = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")


def 去掉实时前缀(文本: object) -> str:
    """历史日志没有时间前缀，实时队列有；去掉后才能合并同一条记录。"""
    return _实时前缀.sub("", str(文本))


def 推断级别(文本: object, 默认级别: str = 级别正常) -> str:
    if 默认级别 in {级别警告, 级别错误}:
        return 默认级别
    文本 = str(文本).strip()
    if 文本.startswith("[错误]") or any(
        关键词 in 文本 for 关键词 in ("异常", "错误", "失败", "危险", "任务异常终止", "线程即将死亡")
    ):
        return 级别错误
    if 文本.startswith("[警告]") or any(
        关键词 in 文本 for 关键词 in ("警告", "资源不足", "未匹配", "被拒绝")
    ):
        return 级别警告
    return 级别正常


级别成功 = "成功"
级别次要 = "次要"
_成功关键词 = ("完成任务", "已完成", "成功", "胜利", "已连接", "已启动", "已确认", "直接接管", "已保存")
_级别前缀 = re.compile(r"^\[(?:警告|错误|操作)\]\s*")


def 展示级别(文本: object, 级别: str = 级别正常) -> str:
    """MAA 式着色：错误红、警告橙、成功绿、操作/次要灰，其余默认色。"""
    基础 = 推断级别(文本, 级别)
    if 基础 != 级别正常:
        return 基础
    文本 = 去掉实时前缀(文本)
    if 文本.startswith("[操作]"):
        return 级别次要
    if any(词 in 文本 for 词 in _成功关键词):
        return 级别成功
    return 级别正常


def 展示文本(文本: object) -> str:
    """去掉时间与 [警告]/[错误] 前缀——级别已经用颜色表达。"""
    return _级别前缀.sub("", 去掉实时前缀(文本)).strip()


def 是否重点(文本: object, 级别: str = 级别正常) -> bool:
    文本 = 去掉实时前缀(文本)
    if any(片段 in 文本 for 片段 in 噪声片段):
        return False
    return 推断级别(文本, 级别) != 级别正常 or any(片段 in 文本 for 片段 in 重点片段)


@dataclass(frozen=True)
class 日志条目:
    时间戳: float
    机器人ID: str
    内容: str
    级别: str = 级别正常


@dataclass(frozen=True)
class 渲染条目:
    时间戳: float
    机器人ID: str
    内容: str
    级别: str
    重复次数: int = 1

    @property
    def 时间文本(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.时间戳))


@dataclass(frozen=True)
class 渲染结果:
    条目: tuple[渲染条目, ...]
    模式: str
    过滤后数量: int
    异常数量: int
    总数量: int

    @property
    def 摘要(self) -> str:
        return (
            f"{self.模式} · 显示 {len(self.条目)}/{self.过滤后数量} 条 · "
            f"异常 {self.异常数量} · 总计 {self.总数量}"
        )


def 合并连续重复(日志列表: Iterable[日志条目], 窗口秒: float = 60) -> list[渲染条目]:
    """把 60 秒内连续出现的相同消息折叠成一行，保留重复次数。"""
    结果: list[渲染条目] = []
    for 项 in 日志列表:
        内容 = 去掉实时前缀(项.内容)
        级别 = 推断级别(内容, 项.级别)
        if 结果:
            上一条 = 结果[-1]
            if (
                上一条.机器人ID == str(项.机器人ID)
                and 上一条.内容 == 内容
                and 上一条.级别 == 级别
                and float(项.时间戳) - float(上一条.时间戳) <= 窗口秒
            ):
                结果[-1] = 渲染条目(
                    项.时间戳, 上一条.机器人ID, 上一条.内容, 上一条.级别,
                    上一条.重复次数 + 1,
                )
                continue
        结果.append(渲染条目(项.时间戳, str(项.机器人ID), 内容, 级别, 1))
    return 结果


class 日志聚合器:
    """合并实时队列、数据库历史与操作日志。线程不安全，只在界面线程调用。"""

    实时保留条数 = 1200
    历史保留条数 = 1800
    操作保留条数 = 200

    def __init__(
        self,
        日志队列: queue.Queue | None,
        读取历史: Callable[[str, float], list] | None = None,
        获取机器人列表: Callable[[], Iterable[str]] | None = None,
    ):
        self._队列 = 日志队列
        self._读取历史 = 读取历史
        self._获取机器人列表 = 获取机器人列表 or (lambda: ())
        self._实时: list[日志条目] = []
        self._操作: list[日志条目] = []
        self._历史: dict[str, list[日志条目]] = {}
        self._历史游标: dict[str, float] = {}
        self._隐藏截止 = 0.0
        self.最新阶段: dict[str, tuple[float, str]] = {}
        # 机器人ID → (时间戳, 任务键|None, 任务名称|None)：最近一条任务边界日志
        # （开始任务/完成任务/任务未完成/停止）。名称为 None 表示当前没有任务在执行。
        # 增量记录，不受日志保留条数限制：几小时的打鱼任务也能显示正确。
        self._任务边界: dict[str, tuple[float, str | None, str | None]] = {}

    def _记录任务边界(self, 机器人ID: str, 时间戳: float, 内容: str) -> None:
        边界 = 解析任务边界(内容)
        if 边界 is None or 机器人ID == "系统":
            return
        旧 = self._任务边界.get(机器人ID)
        if 旧 is not None and float(时间戳) < 旧[0]:
            return
        self._任务边界[机器人ID] = (float(时间戳), 边界[0], 边界[1])

    # ---- 输入 ----
    def 消费实时队列(self, 上限: int = 200) -> bool:
        """每次最多消费固定数量，避免日志洪峰阻塞界面线程。"""
        if self._队列 is None:
            return False
        有变化 = False
        for _ in range(上限):
            try:
                消息 = self._队列.get_nowait()
            except queue.Empty:
                break
            现在 = time.time()
            if isinstance(消息, Mapping):
                机器人ID = str(消息.get("机器人ID") or "系统")
                内容 = str(消息.get("内容", ""))
                级别 = str(消息.get("级别", 级别正常))
                try:
                    记录时间 = float(消息.get("记录时间", 现在))
                except (TypeError, ValueError):
                    记录时间 = 现在
                self._实时.append(日志条目(记录时间, 机器人ID, 内容, 级别))
                self._记录任务边界(机器人ID, 记录时间, 内容)
                if 机器人ID != "系统" and 是否重点(内容, 级别):
                    self.最新阶段[机器人ID] = (记录时间, 去掉实时前缀(内容)[:150])
            else:
                self._实时.append(日志条目(现在, "系统", str(消息), 级别正常))
            try:
                self._队列.task_done()
            except ValueError:
                pass
            有变化 = True
        if len(self._实时) > self.实时保留条数:
            self._实时 = self._实时[-self.实时保留条数:]
        return 有变化

    def 同步历史(self) -> bool:
        """增量读取每个机器人的数据库历史。"""
        if self._读取历史 is None:
            return False
        有变化 = False
        try:
            机器人列表 = list(self._获取机器人列表())
        except Exception:
            机器人列表 = []
        for 机器人ID in 机器人列表:
            标志 = str(机器人ID)
            try:
                记录 = self._读取历史(标志, self._历史游标.get(标志, 0) + 0.00001)
            except Exception:
                continue
            if not 记录:
                continue
            有变化 = True
            self._历史游标[标志] = max(float(项.记录时间) for 项 in 记录)
            for 项 in sorted(记录, key=lambda 项: float(项.记录时间)):
                self._记录任务边界(标志, float(项.记录时间), str(项.日志内容))
            列表 = self._历史.setdefault(标志, [])
            列表.extend(
                日志条目(float(项.记录时间), 标志, str(项.日志内容), 级别正常)
                for 项 in 记录
            )
            if len(列表) > self.历史保留条数:
                self._历史[标志] = 列表[-self.历史保留条数:]
        return 有变化

    def 记录操作(self, 内容: str) -> None:
        self._操作.append(日志条目(time.time(), "系统", f"[操作] {内容}", 级别正常))
        if len(self._操作) > self.操作保留条数:
            self._操作 = self._操作[-self.操作保留条数:]

    def 清空显示(self) -> None:
        """只隐藏当前之前的记录，数据库和任务引擎不受影响。"""
        self._隐藏截止 = time.time()
        self._实时 = [项 for 项 in self._实时 if 项.时间戳 >= self._隐藏截止]
        self._操作.clear()

    def 清空会话(self, 截止: float | None = None) -> None:
        """脚本停止后数据库日志已导出备份并清空：界面同步清掉 ``截止`` 之前的全部日志。

        截止之后写入的（例如刚重新开始的新会话）保留；历史游标不回退，之后只读
        新写入的日志。截止前的任务边界一并清掉（已停止，没有任务在执行）。
        """
        if 截止 is None:
            # 不给截止时间：此刻之前（含同一时钟刻度）的全部清掉。
            截止 = time.time()
            保留 = lambda 时间: float(时间) > 截止  # noqa: E731
        else:
            截止 = float(截止)
            保留 = lambda 时间: float(时间) >= 截止  # noqa: E731
        self._隐藏截止 = max(self._隐藏截止, 截止 + (0.0 if 保留(截止) else 1e-6))
        self._实时 = [项 for 项 in self._实时 if 保留(项.时间戳)]
        self._操作 = [项 for 项 in self._操作 if 保留(项.时间戳)]
        self._历史 = {
            标志: [项 for 项 in 列表 if 保留(项.时间戳)]
            for 标志, 列表 in self._历史.items()
        }
        self.最新阶段 = {键: 值 for 键, 值 in self.最新阶段.items() if 保留(值[0])}
        self._任务边界 = {键: 值 for 键, 值 in self._任务边界.items() if 保留(值[0])}

    # ---- 输出 ----
    def 全部条目(self) -> list[日志条目]:
        全部: list[日志条目] = []
        for 列表 in self._历史.values():
            全部.extend(列表)
        全部.extend(self._实时)
        全部.extend(self._操作)
        全部.sort(key=lambda 项: 项.时间戳)
        # 同一条运行日志同时存在于数据库历史和实时队列中。
        去重: list[日志条目] = []
        已见 = set()
        for 项 in 全部:
            键 = (项.机器人ID, round(float(项.时间戳), 6), 去掉实时前缀(项.内容))
            if 键 in 已见:
                continue
            已见.add(键)
            if 项.时间戳 >= self._隐藏截止:
                去重.append(项)
        return 去重

    @staticmethod
    def 筛选(条目: list[日志条目], 模式: str) -> list[日志条目]:
        if 模式 == "全部":
            return 条目
        if 模式 == "异常":
            return [项 for 项 in 条目 if 推断级别(项.内容, 项.级别) != 级别正常]
        return [项 for 项 in 条目 if 是否重点(项.内容, 项.级别)]

    def 渲染(self, 模式: str = "重点", 机器人ID: str | None = None) -> 渲染结果:
        全部 = self.全部条目()
        if 机器人ID:
            全部 = [项 for 项 in 全部 if 项.机器人ID in (机器人ID, "系统")]
        过滤 = self.筛选(全部, 模式)
        合并 = 合并连续重复(过滤)
        上限 = 260 if 模式 == "全部" else 180
        异常数 = sum(1 for 项 in 全部 if 推断级别(项.内容, 项.级别) != 级别正常)
        return 渲染结果(tuple(合并[-上限:]), 模式, len(过滤), 异常数, len(全部))

    def 最近异常(self, 晚于: float) -> 日志条目 | None:
        """晚于给定时间的最新一条警告/错误（主界面提醒条用）。"""
        for 项 in reversed(self.全部条目()):
            if 项.时间戳 <= 晚于:
                return None
            if 项.机器人ID != "系统" and 推断级别(项.内容, 项.级别) != 级别正常:
                return 项
        return None

    def 当前阶段(self, 机器人ID: str, 最长秒: float = 300) -> str | None:
        """机器人最近一条关键状态；超过时限视为过期。"""
        最新 = self.最新阶段.get(机器人ID)
        if 最新 is None:
            for 项 in reversed(self._历史.get(机器人ID, [])):
                if 是否重点(项.内容, 项.级别):
                    最新 = (项.时间戳, 项.内容[:150])
                    break
        if 最新 and time.time() - float(最新[0]) < 最长秒:
            return 最新[1]
        return None

    def 当前任务名称(self, 机器人ID: str) -> str | None:
        """引擎“开始任务：X”之后、“完成任务/任务未完成/停止”之前返回 X；否则 None。"""
        边界 = self._任务边界.get(str(机器人ID))
        return 边界[2] if 边界 else None

    def 当前任务键(self, 机器人ID: str, 最长秒: float = 900, 最多条数: int = 400) -> str | None:
        """正在执行的任务键。

        以引擎的任务边界日志为准：“开始任务：X”到“完成任务：X/任务未完成/停止”
        之间就是 X，结束后立即返回 None。打鱼期间的“世界识别：当前=夜世界”、
        打鱼间隙的“部落竞赛：…”都不会再把高亮带偏。没有任何边界日志（旧日志/
        测试）时才退回按关键词推断。
        """
        边界 = self._任务边界.get(str(机器人ID))
        if 边界 is not None:
            return 边界[1] if 边界[2] else None
        截止 = time.time() - 最长秒
        for 序号, 项 in enumerate(reversed(self.全部条目())):
            if 序号 >= 最多条数 or 项.时间戳 < 截止:
                return None
            if 项.机器人ID != 机器人ID:
                continue
            键 = 推断任务键(项.内容)
            if 键:
                return 键
        return None


_结束任务片段 = (
    "完成任务：", "任务未完成：", "收到停止事件", "收到外部停止请求", "安全待命结束",
    "没有启用任务，结束本次运行", "开始运行任务计划", "任务异常终止", "线程即将死亡",
)


def _任务名称到键() -> dict[str, str]:
    try:
        from 数据库.任务数据库 import 任务计划定义列表
        return {定义.名称: 定义.键 for 定义 in 任务计划定义列表}
    except Exception:
        return {}


def 解析任务边界(内容: str) -> tuple[str | None, str | None] | None:
    """引擎任务边界日志 → (任务键, 任务名称)；结束类返回 (None, None)；其它返回 None。

    “开始任务：启动游戏”这类不在任务计划里的固定步骤键为 None、名称照常返回。
    """
    文本 = 展示文本(内容)
    if 文本.startswith("开始任务："):
        名称 = 文本.split("开始任务：", 1)[1].strip()
        if not 名称:
            return None
        return _任务名称到键().get(名称), 名称
    if any(片段 in 文本 for 片段 in _结束任务片段):
        return None, None
    return None


# 从运行日志推断当前任务（主界面高亮任务行用）：先认引擎的“按任务计划执行：键”，
# 其余任务按特征词判断。
_任务特征词 = (
    ("event", ("部落竞赛",)),
    ("night_resource", ("夜世界",)),
    ("wall", ("刷墙", "城墙")),
    ("main_resource", ("搜敌", "进攻", "战斗", "下兵", "部署", "回营", "找鱼")),
)


def 推断任务键(内容: str) -> str | None:
    文本 = 去掉实时前缀(内容)
    if "按任务计划执行：" in 文本:
        余下 = 文本.split("按任务计划执行：", 1)[1].split()
        return 余下[0] if 余下 else None
    for 键, 词表 in _任务特征词:
        if any(词 in 文本 for 词 in 词表):
            return 键
    return None
