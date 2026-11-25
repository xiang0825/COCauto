"""异常现场与复盘截图只读索引服务（与界面无关）。

扫描 ``数据集/待命现场/`` 与 ``数据集/低星复盘/`` 中的截图文件：
- 解析文件名时间戳与截图分类（无法解析时安全回退到文件修改时间）；
- 支持按日志时间窗口（如 ±60 秒内最近一张）反查关联截图路径；
- 返回最近 N 张现场图清单（含时间、分类、文件路径、文件大小）。

纯只读扫描：绝不创建、修改或删除任何截图文件；目录不存在时安全返回空列表。
"""
from __future__ import annotations

import bisect
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

支持图片后缀 = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})

_带毫秒时间戳正则 = re.compile(r"(?<!\d)(\d{8})[_-](\d{6})[_-](\d{3})(?!\d)")
_紧凑时间戳正则 = re.compile(r"(?<!\d)(\d{8})[_-](\d{6})(?!\d)")
_分隔时间戳正则 = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[_T-](\d{2})[:-](\d{2})[:-](\d{2})(?!\d)"
)
_毫秒纪元正则 = re.compile(r"(?<!\d)(1\d{12})(?!\d)")
_秒纪元正则 = re.compile(r"(?<!\d)(1\d{9})(?!\d)")


def _解析本地时间(
    年: int, 月: int, 日: int, 时: int, 分: int, 秒: int, 毫秒: int = 0
) -> float | None:
    try:
        dt = datetime(年, 月, 日, 时, 分, 秒, 毫秒 * 1000)
        return dt.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def 解析截图文件名时间(文件名: str) -> float | None:
    """从截图文件名中尽力解析 Unix 时间戳（秒）；无法解析返回 None。"""
    名称 = Path(str(文件名 or "")).stem

    匹配 = _带毫秒时间戳正则.search(名称)
    if 匹配:
        日期, 时分秒, 毫秒 = 匹配.groups()
        ts = _解析本地时间(
            int(日期[:4]), int(日期[4:6]), int(日期[6:8]),
            int(时分秒[:2]), int(时分秒[2:4]), int(时分秒[4:6]),
            int(毫秒),
        )
        if ts is not None:
            return ts

    匹配 = _紧凑时间戳正则.search(名称)
    if 匹配:
        日期, 时分秒 = 匹配.groups()
        ts = _解析本地时间(
            int(日期[:4]), int(日期[4:6]), int(日期[6:8]),
            int(时分秒[:2]), int(时分秒[2:4]), int(时分秒[4:6]),
        )
        if ts is not None:
            return ts

    匹配 = _分隔时间戳正则.search(名称)
    if 匹配:
        年, 月, 日, 时, 分, 秒 = map(int, 匹配.groups())
        ts = _解析本地时间(年, 月, 日, 时, 分, 秒)
        if ts is not None:
            return ts

    匹配 = _毫秒纪元正则.search(名称)
    if 匹配:
        return int(匹配.group(1)) / 1000.0

    匹配 = _秒纪元正则.search(名称)
    if 匹配:
        return float(int(匹配.group(1)))

    return None


def 推断截图分类(文件名: str, 目录分类: str) -> str:
    """根据文件名前缀或所在目录推断截图类型。"""
    小写 = str(文件名 or "").lower()
    if 小写.startswith("standby_") or "待命" in 文件名:
        return "待命现场"
    if (
        小写.startswith(("lowstar_", "low_star_", "review_"))
        or "低星" in 文件名
        or "复盘" in 文件名
    ):
        return "低星复盘"
    return 目录分类


@dataclass(frozen=True)
class 现场截图条目:
    时间戳: float
    分类: str
    文件路径: str
    文件名: str
    文件大小: int
    时间来源: str = "文件名"

    @property
    def 时间文本(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.时间戳))

    def to_dict(self) -> dict[str, Any]:
        return {
            "时间戳": self.时间戳,
            "时间文本": self.时间文本,
            "分类": self.分类,
            "文件路径": self.文件路径,
            "文件名": self.文件名,
            "文件大小": self.文件大小,
            "时间来源": self.时间来源,
        }


class 现场图服务:
    """纯只读扫描异常/复盘现场截图并提供按日志时间关联检索。"""

    def __init__(
        self,
        数据集根目录: str | Path | None = None,
        *,
        目录映射: Mapping[str, str | Path] | None = None,
    ):
        if 目录映射 is not None:
            self._目录映射: tuple[tuple[str, Path], ...] = tuple(
                (str(分类), Path(路径)) for 分类, 路径 in 目录映射.items()
            )
        else:
            根 = Path(数据集根目录) if 数据集根目录 is not None else Path("数据集")
            self._目录映射 = (
                ("待命现场", 根 / "待命现场"),
                ("低星复盘", 根 / "低星复盘"),
            )

    def 扫描全部(self, 分类: str | None = None) -> list[现场截图条目]:
        """只读扫描已配置目录，按时间倒序返回所有可用现场图。"""
        结果: list[现场截图条目] = []
        已见路径: set[str] = set()

        for 目录分类, 目录 in self._目录映射:
            if not 目录.is_dir():
                continue
            try:
                目录项列表 = list(os.scandir(目录))
            except OSError:
                continue
            for 目录项 in 目录项列表:
                try:
                    if not 目录项.is_file():
                        continue
                    后缀 = Path(目录项.name).suffix.lower()
                    if 后缀 not in 支持图片后缀:
                        continue
                    规范路径 = os.path.normcase(os.path.abspath(目录项.path))
                    if 规范路径 in 已见路径:
                        continue
                    已见路径.add(规范路径)

                    状态 = 目录项.stat()
                    条目分类 = 推断截图分类(目录项.name, 目录分类)
                    if 分类 is not None and 条目分类 != 分类:
                        continue

                    解析时间 = 解析截图文件名时间(目录项.name)
                    if 解析时间 is not None:
                        时间戳 = 解析时间
                        来源 = "文件名"
                    else:
                        时间戳 = float(状态.st_mtime)
                        来源 = "文件修改时间"

                    结果.append(
                        现场截图条目(
                            时间戳=时间戳,
                            分类=条目分类,
                            文件路径=str(Path(目录项.path).resolve()),
                            文件名=目录项.name,
                            文件大小=int(状态.st_size),
                            时间来源=来源,
                        )
                    )
                except OSError:
                    continue

        结果.sort(key=lambda 项: (项.时间戳, 项.文件名), reverse=True)
        return 结果

    def 获取最近截图(
        self,
        数量: int = 20,
        分类: str | None = None,
    ) -> list[现场截图条目]:
        上限 = max(0, int(数量))
        if 上限 == 0:
            return []
        return self.扫描全部(分类=分类)[:上限]

    def 查找窗口内截图(
        self,
        日志时间: float,
        窗口秒: float = 60.0,
        *,
        分类: str | None = None,
        上限: int = 10,
    ) -> list[现场截图条目]:
        """返回 [日志时间 - 窗口秒, 日志时间 + 窗口秒] 内按距离升序排列的截图。"""
        目标时间 = float(日志时间)
        窗口 = max(0.0, float(窗口秒))
        候选 = [
            项
            for 项 in self.扫描全部(分类=分类)
            if abs(项.时间戳 - 目标时间) <= 窗口
        ]
        候选.sort(key=lambda 项: (abs(项.时间戳 - 目标时间), -项.时间戳))
        return 候选[: max(0, int(上限))]

    def 查找关联截图(
        self,
        日志时间: float,
        窗口秒: float = 60.0,
        *,
        分类: str | None = None,
    ) -> 现场截图条目 | None:
        匹配 = self.查找窗口内截图(日志时间, 窗口秒, 分类=分类, 上限=1)
        return 匹配[0] if 匹配 else None

    def 关联日志截图路径(
        self,
        日志时间: float,
        窗口秒: float = 60.0,
        *,
        分类: str | None = None,
    ) -> str | None:
        条目 = self.查找关联截图(日志时间, 窗口秒, 分类=分类)
        return 条目.文件路径 if 条目 is not None else None

    def 批量关联日志(
        self,
        时间戳列表: Iterable[float],
        窗口秒: float = 60.0,
        *,
        分类: str | None = None,
    ) -> dict[float, 现场截图条目]:
        """单次扫描后用二分检索为多条日志时间批量匹配最近现场图。"""
        全部 = self.扫描全部(分类=分类)
        if not 全部:
            return {}
        按时间升序 = sorted(全部, key=lambda 项: 项.时间戳)
        时间轴 = [项.时间戳 for 项 in 按时间升序]
        窗口 = max(0.0, float(窗口秒))

        结果: dict[float, 现场截图条目] = {}
        for 原始时间 in 时间戳列表:
            ts = float(原始时间)
            位置 = bisect.bisect_left(时间轴, ts)
            最佳: 现场截图条目 | None = None
            最佳差 = 窗口 + 1.0
            for idx in (位置 - 1, 位置, 位置 + 1):
                if 0 <= idx < len(按时间升序):
                    差 = abs(按时间升序[idx].时间戳 - ts)
                    if 差 <= 窗口 and 差 < 最佳差:
                        最佳 = 按时间升序[idx]
                        最佳差 = 差
            if 最佳 is not None:
                结果[原始时间] = 最佳
        return 结果
