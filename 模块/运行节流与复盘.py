"""运行时动态节流、模型空闲懒释放、连续低星复盘留档与满仓顺手刷墙辅助模块。"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable


# ------------------------------------------------------------------ 动态降帧节能
活跃截图间隔秒 = 0.50
低频截图间隔秒 = 1.80
活跃点击缓存秒 = 0.20
战斗活跃点击缓存秒 = 0.75
低频点击缓存秒 = 1.60

场景_活跃 = "活跃"
场景_低频 = "低频"

_活跃场景名称 = frozenset({"活跃", "搜敌", "下兵", "确认点击", "常规", "主世界", "夜世界"})
_低频场景名称 = frozenset({"低频", "满仓待机", "战斗等待", "待命观察", "长时等待", "暂停"})


def 解析截图节流配置(
    场景: str,
    *,
    间隔秒: float | None = None,
    点击缓存秒: float | None = None,
) -> tuple[str, float, float]:
    """将业务场景名称归一化为 ``(规范场景, 最短截图间隔秒, 点击缓存窗口秒)``。"""
    原始 = str(场景 or "").strip()
    if 原始 in _低频场景名称:
        规范场景 = 场景_低频
        默认间隔 = 低频截图间隔秒
        默认点击缓存 = 低频点击缓存秒
    else:
        规范场景 = 场景_活跃
        默认间隔 = 活跃截图间隔秒
        默认点击缓存 = 活跃点击缓存秒

    最终间隔 = 默认间隔 if 间隔秒 is None else max(0.10, min(5.00, float(间隔秒)))
    最终点击缓存 = (
        默认点击缓存 if 点击缓存秒 is None else max(0.05, min(5.00, float(点击缓存秒)))
    )
    return 规范场景, 最终间隔, 最终点击缓存


# ------------------------------------------------------------------ 模型空闲懒释放
默认模型空闲释放秒数 = 600.0


class 模型空闲释放协调器:
    """避免正常打鱼间隙反复冷加载/卸载模型，仅在长时空闲或内存紧张时释放。"""

    def __init__(self, 默认阈值秒: float = 默认模型空闲释放秒数) -> None:
        self.默认阈值秒 = max(0.0, float(默认阈值秒))
        self.最后使用时间: float = 0.0
        self.最后检查时间: float = 0.0
        self.最近释放原因: str = ""
        self.释放次数: int = 0

    def 标记使用(self, 当前时间: float | None = None) -> float:
        现在 = time.monotonic() if 当前时间 is None else float(当前时间)
        self.最后使用时间 = 现在
        return 现在

    def 重置计时(self) -> None:
        self.最后使用时间 = 0.0

    def 评估释放条件(
        self,
        *,
        已有加载模型: bool,
        空闲阈值秒: float | None = None,
        当前时间: float | None = None,
        内存预算检查函数: Callable[..., tuple[bool, str]] | None = None,
        强制检查内存: bool = True,
    ) -> tuple[bool, str]:
        if not 已有加载模型:
            return False, ""

        现在 = time.monotonic() if 当前时间 is None else float(当前时间)

        # 1. 主机内存预算紧张时优先立即释放，避免拖垮宿主进程。
        if 强制检查内存 and callable(内存预算检查函数):
            try:
                try:
                    预算健康, 内存诊断 = 内存预算检查函数(强制刷新=False)
                except TypeError:
                    预算健康, 内存诊断 = 内存预算检查函数()
                if not 预算健康 and "暂不可用" not in str(内存诊断 or ""):
                    return True, f"宿主机内存预算紧张（{内存诊断 or '预算不足'}），立即释放识别模型"
            except Exception:
                pass

        # 2. 仅当空闲超过可配置阈值（默认 600 秒）才释放，避免连刷间隙抖动。
        阈值 = self.默认阈值秒 if 空闲阈值秒 is None else max(0.0, float(空闲阈值秒))
        if 阈值 <= 0 or self.最后使用时间 <= 0:
            return False, ""

        已空闲秒数 = max(0.0, 现在 - self.最后使用时间)
        if 已空闲秒数 >= 阈值:
            return (
                True,
                f"识别模型已空闲 {int(已空闲秒数)} 秒（超过阈值 {int(阈值)} 秒），执行懒释放",
            )
        return False, ""

    def 按需释放(
        self,
        上下文: Any,
        *,
        空闲阈值秒: float | None = None,
        当前时间: float | None = None,
        检查间隔秒: float = 0.0,
        强制检查内存: bool = True,
    ) -> tuple[bool, str]:
        """检查上下文当前模型状态并在满足条件时调用 ``上下文.释放识别模型()``。"""
        已有OCR = getattr(上下文, "_共享OCR引擎", None) is not None
        已有YOLO = getattr(上下文, "_共享YOLO检测器", None) is not None
        已有模型 = 已有OCR or 已有YOLO
        if not 已有模型:
            return False, ""

        现在 = time.monotonic() if 当前时间 is None else float(当前时间)
        if 检查间隔秒 > 0 and self.最后检查时间 > 0 and 现在 - self.最后检查时间 < 检查间隔秒:
            return False, ""
        self.最后检查时间 = 现在

        操作 = getattr(上下文, "op", None)
        内存检查 = getattr(操作, "检查主机内存预算", None)
        if 空闲阈值秒 is None:
            设置 = getattr(上下文, "设置", None)
            原始阈值 = getattr(设置, "模型空闲释放秒数", self.默认阈值秒)
            try:
                空闲阈值秒 = max(0.0, float(self.默认阈值秒 if 原始阈值 is None else 原始阈值))
            except (TypeError, ValueError):
                空闲阈值秒 = self.默认阈值秒

        应该释放, 原因 = self.评估释放条件(
            已有加载模型=已有模型,
            空闲阈值秒=空闲阈值秒,
            当前时间=现在,
            内存预算检查函数=内存检查 if callable(内存检查) else None,
            强制检查内存=强制检查内存,
        )
        if not 应该释放:
            return False, ""

        释放方法 = getattr(上下文, "释放识别模型", None)
        if callable(释放方法):
            释放方法()
            self.释放次数 += 1
            self.最近释放原因 = 原因
            self.重置计时()
            置状态 = getattr(上下文, "置脚本状态", None)
            if callable(置状态):
                try:
                    置状态(原因)
                except Exception:
                    pass
            return True, 原因
        return False, ""


# ------------------------------------------------------------------ 连续低星战局自动留档
默认低星复盘目录 = Path("数据集") / "低星复盘"
默认连续低星触发次数 = 2
默认低星摧毁率阈值 = 30
默认最大留档数 = 100
默认战斗世界 = "主世界"


def 规范化战斗世界(战斗世界: Any = None) -> str:
    """将战斗世界标识归一化为明确的世界名称（默认“主世界”）。"""
    原始 = str(战斗世界 or "").strip()
    if not 原始 or 原始 in {"主世界", "家乡", "Home Village", "home", "main"}:
        return "主世界"
    if 原始 in {"夜世界", "建筑大师", "Builder Base", "builder_base", "night"}:
        return "夜世界"
    return 原始


def _世界文件名标识(战斗世界: Any = None) -> str:
    规范世界 = 规范化战斗世界(战斗世界)
    清洗后 = "".join(
        "_" if ch in '\\/:*?"<>|\r\n\t ' else ch for ch in 规范世界
    ).strip("_")
    return 清洗后 or 默认战斗世界


def 是否低星战局(
    星数: Any,
    摧毁率: Any,
    *,
    摧毁率阈值: int = 默认低星摧毁率阈值,
) -> bool | None:
    """判定战局是否属于低星/低摧毁；未识别出有效结果时返回 ``None``。"""
    if 星数 is None and 摧毁率 is None:
        return None
    解析星数 = None
    解析摧毁率 = None
    if 星数 is not None:
        try:
            解析星数 = int(星数)
        except (TypeError, ValueError):
            解析星数 = None
    if 摧毁率 is not None:
        try:
            解析摧毁率 = float(摧毁率)
        except (TypeError, ValueError):
            解析摧毁率 = None
    if 解析星数 is None and 解析摧毁率 is None:
        return None
    if 解析星数 == 0:
        return True
    if 解析摧毁率 is not None and 解析摧毁率 < float(摧毁率阈值):
        return True
    return False


def _写入复盘PNG(目标路径: Path, 屏幕图像: Any) -> bool:
    import cv2

    编码成功, PNG数据 = cv2.imencode(".png", 屏幕图像)
    if not 编码成功:
        return False
    目标路径.write_bytes(PNG数据.tobytes())
    return True


class 低星战局复盘记录器:
    """连续出现低星/低摧毁战局时自动留档截图，按战斗世界隔离计数且严格只增不删。"""

    def __init__(
        self,
        输出目录: str | Path = 默认低星复盘目录,
        *,
        连续触发次数: int = 默认连续低星触发次数,
        摧毁率阈值: int = 默认低星摧毁率阈值,
        最大留档数: int = 默认最大留档数,
        战斗世界: str = 默认战斗世界,
    ) -> None:
        self.输出目录 = Path(输出目录)
        self.连续触发次数 = max(1, int(连续触发次数))
        self.摧毁率阈值 = max(1, min(100, int(摧毁率阈值)))
        self.最大留档数 = max(1, int(最大留档数))
        self.默认战斗世界 = 规范化战斗世界(战斗世界)
        self._世界连续低星次数: dict[str, int] = {}
        self.累计留档数: int = 0
        self._已提示上限: bool = False

    @property
    def 连续低星次数(self) -> int:
        return self._世界连续低星次数.get(self.默认战斗世界, 0)

    @连续低星次数.setter
    def 连续低星次数(self, 值: int) -> None:
        self._世界连续低星次数[self.默认战斗世界] = max(0, int(值))

    def 获取连续低星次数(self, 战斗世界: str | None = None) -> int:
        规范世界 = self.默认战斗世界 if 战斗世界 is None else 规范化战斗世界(战斗世界)
        return self._世界连续低星次数.get(规范世界, 0)

    @staticmethod
    def _日志(日志回调: Callable[..., Any] | None, 文本: str) -> None:
        if callable(日志回调):
            try:
                日志回调(文本)
            except Exception:
                pass

    def 记录战局(
        self,
        *,
        屏幕图像: Any,
        星数: Any,
        摧毁率: Any,
        结果: str = "",
        战斗世界: str | None = None,
        日志回调: Callable[..., Any] | None = None,
        时间文本: str | None = None,
    ) -> Path | None:
        规范世界 = self.默认战斗世界 if 战斗世界 is None else 规范化战斗世界(战斗世界)
        低星 = 是否低星战局(星数, 摧毁率, 摧毁率阈值=self.摧毁率阈值)
        if 低星 is None:
            return None
        if not 低星:
            self._世界连续低星次数[规范世界] = 0
            return None

        当前连续 = self._世界连续低星次数.get(规范世界, 0) + 1
        self._世界连续低星次数[规范世界] = 当前连续
        if 当前连续 < self.连续触发次数:
            return None

        if 屏幕图像 is None or getattr(屏幕图像, "size", 0) == 0:
            self._日志(
                日志回调,
                f"[{规范世界}] 连续低星战局已触发留档条件，但结算截图为空，跳过写入",
            )
            return None

        try:
            self.输出目录.mkdir(parents=True, exist_ok=True)
            现有数量 = sum(1 for _ in self.输出目录.glob("*.png"))
            if 现有数量 >= self.最大留档数:
                if not self._已提示上限:
                    self._已提示上限 = True
                    self._日志(
                        日志回调,
                        f"[{规范世界}] 低星复盘目录「{self.输出目录}」截图数已达上限 {self.最大留档数}，"
                        "已停止新增写入（严格保留已有文件，不执行删除）",
                    )
                return None

            现在 = time.time()
            时间戳 = 时间文本 or f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(现在))}_{int((现在 % 1) * 1000):03d}"
            世界标识 = _世界文件名标识(规范世界)
            星数标识 = "na" if 星数 is None else str(int(星数))
            摧毁标识 = "na" if 摧毁率 is None else str(int(round(float(摧毁率))))
            结果标识 = str(结果 or "").strip() or "unknown"
            文件名 = (
                f"low_star_{世界标识}_{时间戳}_streak{当前连续}"
                f"_s{星数标识}_d{摧毁标识}_{结果标识}.png"
            )
            目标路径 = self.输出目录 / 文件名
            if not _写入复盘PNG(目标路径, 屏幕图像):
                self._日志(日志回调, f"[{规范世界}] 低星复盘截图 PNG 编码失败，跳过留档")
                return None
            self.累计留档数 += 1
            self._日志(
                日志回调,
                f"[{规范世界}] 连续第 {当前连续} 场低星战局（星数={星数标识}，摧毁率={摧毁标识}%），"
                f"已自动留档复盘截图：{目标路径}",
            )
            return 目标路径
        except Exception as 异常:
            self._日志(日志回调, f"[{规范世界}] 低星战局复盘留档失败（不影响正常结算）：{异常}")
            return None


# ------------------------------------------------------------------ 满仓顺手刷墙策略
_已知储存上限档位 = (
    100_000, 200_000, 300_000, 500_000,
    1_000_000, 2_000_000, 4_000_000, 6_000_000,
    8_000_000, 10_000_000, 12_000_000, 14_000_000,
    16_000_000, 18_000_000, 20_000_000, 22_000_000,
    31_000_000,
)


def _安全整数(值: Any) -> int:
    try:
        return max(0, int(float(str(值).replace(",", "").strip())))
    except (TypeError, ValueError, OverflowError):
        return 0


def 推断金水储存参考上限(
    家乡资源: dict,
    历史峰值: dict | None = None,
    显式上限: dict | None = None,
) -> dict[str, int]:
    """基于显式上限、历史可信峰值或已满档位推断当前金币/圣水储存上限。"""
    from 工具包.工具函数 import _资源接近已知上限

    结果: dict[str, int] = {}
    for 类型 in ("金币", "圣水"):
        if isinstance(显式上限, dict):
            显式值 = _安全整数(显式上限.get(类型, 0))
            if 显式值 > 0:
                结果[类型] = 显式值
                continue

        峰值 = _安全整数(历史峰值.get(类型, 0)) if isinstance(历史峰值, dict) else 0
        if 峰值 > 0 and _资源接近已知上限(峰值, 类型):
            结果[类型] = min(_已知储存上限档位, key=lambda 档位: abs(峰值 - 档位))
            continue

        当前值 = _安全整数(家乡资源.get(类型, 0)) if isinstance(家乡资源, dict) else 0
        if 当前值 > 0 and _资源接近已知上限(当前值, 类型):
            结果[类型] = min(_已知储存上限档位, key=lambda 档位: abs(当前值 - 档位))
    return 结果


def 金水是否达到刷墙阈值(
    家乡资源: dict,
    阈值比例: int = 90,
    历史峰值: dict | None = None,
    显式上限: dict | None = None,
) -> tuple[bool, list[str]]:
    """判断主世界金币或圣水是否达到顺手刷墙阈值比例。"""
    if not isinstance(家乡资源, dict) or 家乡资源.get("识别成功") is False:
        return False, []
    try:
        比例 = max(50, min(100, int(阈值比例)))
    except (TypeError, ValueError):
        比例 = 90

    参考上限 = 推断金水储存参考上限(家乡资源, 历史峰值, 显式上限)
    命中说明: list[str] = []
    for 类型 in ("金币", "圣水"):
        上限 = 参考上限.get(类型, 0)
        当前值 = _安全整数(家乡资源.get(类型, 0))
        if 上限 > 0 and 当前值 >= int(上限 * (比例 / 100.0)):
            命中说明.append(f"{类型} {当前值:,}/{上限:,} ({当前值 / 上限:.0%})")
    return bool(命中说明), 命中说明


def 检查是否存在可用工人(
    上下文: Any,
    *,
    允许刷新: bool = True,
    工人刷新任务类: Any = None,
) -> tuple[bool, str]:
    """检查主世界是否存在真正空闲的建筑工人（排除哥布林假空闲 1/7）。"""
    def _读取状态() -> dict | None:
        数据库 = getattr(上下文, "数据库", None)
        if 数据库 is None:
            return None
        完整状态 = 数据库.获取最新完整状态(getattr(上下文, "机器人标志", ""))
        数据 = getattr(完整状态, "状态数据", None)
        if not isinstance(数据, dict):
            return None
        工人 = 数据.get("工人状态")
        return 工人 if isinstance(工人, dict) else None

    状态 = _读取状态()
    现在 = time.time()
    需要刷新 = (
        状态 is None
        or (现在 - float(状态.get("更新时间", 0) or 0)) > 120.0
    )
    if 需要刷新 and 允许刷新 and getattr(上下文, "op", None) is not None:
        try:
            if 工人刷新任务类 is None:
                from 任务流程.建筑升级.更新工人状态 import 更新工人状态任务
                工人刷新任务类 = 更新工人状态任务
            if bool(工人刷新任务类(上下文).执行()):
                状态 = _读取状态()
        except Exception as 异常:
            return False, f"刷新工人状态失败：{异常}"

    if not isinstance(状态, dict):
        return False, "缺少有效的建筑工人状态"
    try:
        空闲工人 = int(状态["空闲工人"])
        工人总数 = int(状态["工人总数"])
        更新时间 = float(状态["更新时间"])
    except (KeyError, TypeError, ValueError):
        return False, "建筑工人状态字段无效"

    if time.time() - 更新时间 > 120.0:
        return False, "建筑工人状态已过期（超过 2 分钟）"
    if 空闲工人 <= 0:
        return False, f"无空闲建筑工人（{空闲工人}/{工人总数}）"
    if 工人总数 == 7 and 空闲工人 == 1:
        return False, "检测到哥布林活动工人（1/7），实际无免费建筑工人"
    if not (0 < 空闲工人 <= 工人总数 <= 7):
        return False, f"建筑工人数量异常（{空闲工人}/{工人总数}）"
    return True, f"可用建筑工人 {空闲工人}/{工人总数}"


def 尝试满仓顺手刷墙(
    机器人: Any,
    上下文: Any,
    家乡资源: dict,
    历史峰值: dict | None = None,
    *,
    允许刷新工人: bool = True,
    显式上限: dict | None = None,
    墙任务类: Any = None,
    工人刷新任务类: Any = None,
) -> bool:
    """满仓/超阈值时安全顺手刷 1~2 块城墙，防止资源溢出且绝不阻塞主循环。"""
    设置 = getattr(机器人, "设置", None) or getattr(上下文, "设置", None)
    if not bool(getattr(设置, "满仓自动顺手刷墙", False)):
        return False

    try:
        阈值比例 = max(50, min(100, int(getattr(设置, "刷墙资源阈值比例", 90) or 90)))
    except (TypeError, ValueError):
        阈值比例 = 90
    try:
        最大块数 = max(1, min(2, int(getattr(设置, "单次顺手刷墙上限", 2) or 2)))
    except (TypeError, ValueError):
        最大块数 = 2

    达到阈值, 命中资源 = 金水是否达到刷墙阈值(
        家乡资源, 阈值比例=阈值比例, 历史峰值=历史峰值, 显式上限=显式上限
    )
    if not 达到阈值:
        return False

    置状态 = getattr(上下文, "置脚本状态", None)
    def _记录(文本: str) -> None:
        if callable(置状态):
            try:
                置状态(文本)
            except Exception:
                pass

    有可用工人, 工人说明 = 检查是否存在可用工人(
        上下文, 允许刷新=允许刷新工人, 工人刷新任务类=工人刷新任务类
    )
    if not 有可用工人:
        _记录(f"满仓顺手刷墙跳过：{工人说明}（{', '.join(命中资源)}）")
        return False

    _记录(
        f"触发满仓顺手刷墙（{', '.join(命中资源)}，{工人说明}）："
        f"本次最多尝试升级 {最大块数} 块城墙"
    )
    原需要资源 = bool(getattr(上下文, "刷墙需要资源", False))
    原顺手标记 = bool(getattr(上下文, "_顺手刷墙模式", False))
    上下文._顺手刷墙模式 = True
    上下文._本次顺手刷墙成功块数 = 0

    try:
        if 墙任务类 is None:
            from 任务流程.升级城墙 import 城墙升级任务
            墙任务类 = 城墙升级任务
        try:
            任务 = 墙任务类(上下文, 最大升级块数=最大块数, 忽略开关=True)
        except TypeError:
            任务 = 墙任务类(上下文)

        try:
            结果 = bool(任务.执行(最大升级块数=最大块数, 忽略开关=True))
        except TypeError:
            结果 = bool(任务.执行())
        实际升级数 = int(getattr(上下文, "_本次顺手刷墙成功块数", 0) or 0)
        if 实际升级数 > 0:
            上下文._最近存在合法消耗 = True
            _记录(f"满仓顺手刷墙完成：本次已升级 {实际升级数} 块城墙，继续原打鱼/任务流程")
            return True
        if 结果:
            _记录("满仓顺手刷墙检查完成：本次未升级城墙，安全继续原任务流程")
            return True
        _记录("满仓顺手刷墙未完成，已安全跳过并继续原打鱼/任务流程")
        return False
    except SystemExit:
        raise
    except Exception as 异常:
        from 核心.异常 import 主机内存保护暂停请求
        if isinstance(异常, 主机内存保护暂停请求):
            raise
        _记录(f"满仓顺手刷墙异常，已安全跳过不阻塞主循环：{异常}")
        return False
    finally:
        上下文.刷墙需要资源 = 原需要资源
        上下文._顺手刷墙模式 = 原顺手标记
