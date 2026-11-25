"""多套方案预设管理、差异预览、备份回退与 JSON 导入导出服务（与界面无关）。

提供 3 套开箱即用的内置方案预设，并支持：
- 保存当前配置为用户自定义预设（持久化到数据库 ``系统配置`` 表）；
- 应用前差异预览（精确比较归一化后的前后字段值）；
- 一键应用预设并在应用前自动保存上一份完整快照，支持一键撤销/回退；
- JSON 字符串导入导出与指定路径写入（不提供任何删除磁盘文件的接口）。
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

from 数据库.任务数据库 import (
    任务数据库,
    机器人设置,
    部落竞赛默认白名单,
)

自定义预设配置键 = "配置预设_自定义"
回退快照配置键前缀 = "配置预设_回退快照:"
最大回退快照数 = 10

# 设备连接与账号凭据属于本机环境信息，不随策略预设保存/导入/覆盖。
环境隔离字段 = frozenset(
    {
        "ADB路径",
        "ADB自动检测路径",
        "ADB设备序列号",
        "ADB已确认模拟器",
        "部落冲突包名",
        "官方API令牌",
        "玩家标签",
        "企业微信webhook",
    }
)


@dataclass(frozen=True)
class 方案预设:
    名称: str
    说明: str
    参数: dict[str, Any]
    内置: bool = False
    标签: tuple[str, ...] = ()
    创建时间: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "名称": self.名称,
            "说明": self.说明,
            "内置": self.内置,
            "标签": list(self.标签),
            "创建时间": self.创建时间,
            "参数": copy.deepcopy(self.参数),
        }


@dataclass(frozen=True)
class 预设差异项:
    字段: str
    显示名称: str
    当前值: Any
    目标值: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "字段": self.字段,
            "显示名称": self.显示名称,
            "当前值": copy.deepcopy(self.当前值),
            "目标值": copy.deepcopy(self.目标值),
        }


@dataclass(frozen=True)
class 预设差异结果:
    预设名称: str
    变更项: tuple[预设差异项, ...]

    @property
    def 是否有变更(self) -> bool:
        return bool(self.变更项)

    @property
    def 摘要(self) -> str:
        if not self.变更项:
            return f"方案「{self.预设名称}」与当前设置完全一致，无需改动"
        return f"应用「{self.预设名称}」将修改 {len(self.变更项)} 项配置"

    def to_dict(self) -> dict[str, Any]:
        return {
            "预设名称": self.预设名称,
            "是否有变更": self.是否有变更,
            "摘要": self.摘要,
            "变更项": [项.to_dict() for 项 in self.变更项],
        }


@dataclass(frozen=True)
class 应用预设结果:
    成功: bool
    预设名称: str
    已备份: bool
    变更项: tuple[预设差异项, ...]
    新设置: 机器人设置

    def to_dict(self) -> dict[str, Any]:
        return {
            "成功": self.成功,
            "预设名称": self.预设名称,
            "已备份": self.已备份,
            "变更数": len(self.变更项),
            "变更项": [项.to_dict() for 项 in self.变更项],
        }


@dataclass(frozen=True)
class 回退结果:
    成功: bool
    原预设名称: str = ""
    恢复字段数: int = 0
    说明: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "成功": self.成功,
            "原预设名称": self.原预设名称,
            "恢复字段数": self.恢复字段数,
            "说明": self.说明,
        }


内置预设列表: tuple[方案预设, ...] = (
    方案预设(
        名称="隐哥冲黑油",
        说明="黑油优先 + 适配隐秘哥布林刷资源与三阶段黑油搜敌参数，兼顾边缘采集器。",
        内置=True,
        标签=("黑油", "隐秘哥布林", "主世界"),
        参数={
            "是否刷主世界": True,
            "战利品优先级": "黑水",
            "欲进攻的最小资源": 500_000,
            "黑水优先最低黑油": 11_000,
            "黑水优先前期候选数上限": 25,
            "黑水优先放宽后最低黑油": 6_500,
            "黑水优先放宽候选数上限": 55,
            "欲进攻资源建筑靠近地图边缘最小比例": 0.5,
            "资源易窃取最低评分": 5.0,
            "资源边缘距离阈值": 80.0,
            "搜索目标递减间隔次数": 10,
            "搜索目标每次降幅比例": 0.10,
            "搜索目标最低下限": 100_000,
            "是否快速刷资源": False,
            "是否自动配兵": True,
            "自动配兵玩法": "资源优先",
            "是否自动配置军队": True,
            "阵容预设": "隐秘哥布林刷资源",
        },
    ),
    方案预设(
        名称="冲部落竞赛",
        说明="开启部落竞赛自动接取打鱼可完成任务，资源满仓后继续打鱼刷积分。",
        内置=True,
        标签=("部落竞赛", "继续打鱼"),
        参数={
            "是否部落竞赛接任务": True,
            "部落竞赛任务白名单": list(部落竞赛默认白名单),
            "部落竞赛检查间隔分钟": 15,
            "是否刷主世界": True,
            "资源打满后动作": "继续打鱼",
            "战利品优先级": "均衡",
            "欲进攻的最小资源": 500_000,
            "资源易窃取最低评分": 4.5,
            "是否自动配兵": True,
            "自动配兵玩法": "资源优先",
        },
    ),
    方案预设(
        名称="日常均衡刷墙",
        说明="均衡双资源搜敌，开启高水位自动刷墙防爆仓浪费，打满后进入安全待机。",
        内置=True,
        标签=("均衡", "刷墙", "防爆仓"),
        参数={
            "是否刷主世界": True,
            "战利品优先级": "均衡",
            "欲进攻的最小资源": 700_000,
            "开启刷墙": True,
            "刷墙起始金币": 15_000_000,
            "刷墙起始圣水": 15_000_000,
            "资源打满后动作": "待机",
            "资源易窃取最低评分": 5.0,
            "欲进攻资源建筑靠近地图边缘最小比例": 0.5,
            "是否自动配兵": True,
            "自动配兵玩法": "资源优先",
        },
    ),
)

内置预设映射: dict[str, 方案预设] = {方案.名称: 方案 for 方案 in 内置预设列表}


def _字段显示名(字段名: str) -> str:
    字段定义 = 机器人设置.__dataclass_fields__.get(字段名)
    if 字段定义 is None:
        return 字段名
    return str(字段定义.metadata.get("显示名称") or 字段名)


def _过滤策略参数(原始参数: Mapping[str, Any]) -> dict[str, Any]:
    规范化 = 任务数据库._规范化机器人设置JSON(dict(原始参数))
    return {
        键: copy.deepcopy(值)
        for 键, 值 in 规范化.items()
        if 键 not in 环境隔离字段
    }


def _完整设置字典(设置: 机器人设置) -> dict[str, Any]:
    结果 = {}
    for 字段 in fields(机器人设置):
        结果[字段.name] = copy.deepcopy(getattr(设置, 字段.name))
    return 任务数据库._规范化机器人设置JSON(结果)


class 预设服务:
    """多套配置预设管理、差异预览、应用备份与撤销回退服务。"""

    def __init__(self, 数据库: 任务数据库 | None = None):
        self.数据库 = 数据库 or 任务数据库()

    # ---------------------------------------------------------- 系统配置持久化
    def _读取配置项(self, 键: str) -> Any:
        with self.数据库._获取连接() as conn:
            行 = conn.execute(
                "SELECT 配置值 FROM 系统配置 WHERE 配置键 = ?",
                (键,),
            ).fetchone()
        if not 行 or 行[0] is None:
            return None
        try:
            return json.loads(行[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _写入配置项(self, 键: str, 值: Any) -> None:
        序列化 = json.dumps(值, ensure_ascii=False, separators=(",", ":"))
        with self.数据库._获取连接() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO 系统配置 (配置键, 配置值, 更新时间) VALUES (?, ?, ?)",
                (键, 序列化, time.time()),
            )
            conn.commit()

    def _读取自定义字典(self) -> dict[str, dict[str, Any]]:
        原始 = self._读取配置项(自定义预设配置键)
        if not isinstance(原始, dict):
            return {}
        有效: dict[str, dict[str, Any]] = {}
        for 名称, 数据 in 原始.items():
            if not isinstance(名称, str) or not 名称.strip() or not isinstance(数据, dict):
                continue
            参数 = _过滤策略参数(数据.get("参数") or {})
            有效[名称.strip()] = {
                "名称": 名称.strip(),
                "说明": str(数据.get("说明") or ""),
                "标签": [str(x) for x in (数据.get("标签") or [])],
                "创建时间": 数据.get("创建时间"),
                "参数": 参数,
            }
        return 有效

    def _保存自定义字典(self, 字典: Mapping[str, dict[str, Any]]) -> None:
        self._写入配置项(自定义预设配置键, dict(字典))

    # ---------------------------------------------------------- 查询与创建
    def 获取内置预设列表(self) -> list[方案预设]:
        return list(内置预设列表)

    def 获取自定义预设列表(self) -> list[方案预设]:
        结果: list[方案预设] = []
        for 名称, 数据 in self._读取自定义字典().items():
            结果.append(
                方案预设(
                    名称=名称,
                    说明=数据["说明"],
                    参数=copy.deepcopy(数据["参数"]),
                    内置=False,
                    标签=tuple(数据.get("标签") or ()),
                    创建时间=数据.get("创建时间"),
                )
            )
        return 结果

    def 获取预设列表(self) -> list[方案预设]:
        return self.获取内置预设列表() + self.获取自定义预设列表()

    def 获取预设(self, 名称: str) -> 方案预设:
        目标名 = str(名称 or "").strip()
        if 目标名 in 内置预设映射:
            return 内置预设映射[目标名]
        for 方案 in self.获取自定义预设列表():
            if 方案.名称 == 目标名:
                return 方案
        raise ValueError(f"找不到预设：{目标名}")

    def _解析方案(self, 预设: str | 方案预设) -> 方案预设:
        if isinstance(预设, 方案预设):
            return 预设
        return self.获取预设(预设)

    def 保存自定义预设(
        self,
        名称: str,
        参数: Mapping[str, Any],
        说明: str = "",
        *,
        标签: tuple[str, ...] | list[str] = (),
        覆盖: bool = True,
    ) -> 方案预设:
        目标名 = str(名称 or "").strip()
        if not 目标名:
            raise ValueError("预设名称不能为空")
        if 目标名 in 内置预设映射:
            raise ValueError(f"不能覆盖内置预设：{目标名}")
        过滤参数 = _过滤策略参数(参数)
        if not 过滤参数:
            raise ValueError("预设参数中没有有效的机器人设置字段")

        现有 = self._读取自定义字典()
        if 目标名 in 现有 and not 覆盖:
            raise ValueError(f"自定义预设已存在：{目标名}")

        现在 = time.time()
        标签元组 = tuple(str(x) for x in 标签 if str(x).strip())
        现有[目标名] = {
            "名称": 目标名,
            "说明": str(说明 or "").strip(),
            "标签": list(标签元组),
            "创建时间": 现在,
            "参数": 过滤参数,
        }
        self._保存自定义字典(现有)
        return 方案预设(
            名称=目标名,
            说明=str(说明 or "").strip(),
            参数=copy.deepcopy(过滤参数),
            内置=False,
            标签=标签元组,
            创建时间=现在,
        )

    def 保存当前为预设(
        self,
        机器人ID: str,
        名称: str,
        说明: str = "",
        *,
        覆盖: bool = True,
    ) -> 方案预设:
        当前设置 = self.数据库.获取机器人设置(机器人ID)
        策略参数 = _过滤策略参数(_完整设置字典(当前设置))
        return self.保存自定义预设(
            名称=名称,
            参数=策略参数,
            说明=说明 or f"保存自 {机器人ID} 当前配置",
            标签=("自定义",),
            覆盖=覆盖,
        )

    # ---------------------------------------------------------- 预览、应用与回退
    def _计算应用后设置(
        self, 当前设置: 机器人设置, 方案: 方案预设
    ) -> 机器人设置:
        合并字典 = _完整设置字典(当前设置)
        补丁 = _过滤策略参数(方案.参数)
        合并字典.update(补丁)
        return 机器人设置(**合并字典)

    def 预览差异(
        self,
        机器人ID: str,
        预设: str | 方案预设,
    ) -> 预设差异结果:
        方案 = self._解析方案(预设)
        当前设置 = self.数据库.获取机器人设置(机器人ID)
        目标设置 = self._计算应用后设置(当前设置, 方案)

        变更列表: list[预设差异项] = []
        for 字段 in fields(机器人设置):
            字段名 = 字段.name
            if 字段名 in 环境隔离字段:
                continue
            当前值 = getattr(当前设置, 字段名)
            目标值 = getattr(目标设置, 字段名)
            if 当前值 != 目标值:
                变更列表.append(
                    预设差异项(
                        字段=字段名,
                        显示名称=_字段显示名(字段名),
                        当前值=copy.deepcopy(当前值),
                        目标值=copy.deepcopy(目标值),
                    )
                )

        return 预设差异结果(
            预设名称=方案.名称,
            变更项=tuple(变更列表),
        )

    def _快照键(self, 机器人ID: str) -> str:
        return f"{回退快照配置键前缀}{机器人ID}"

    def _读取快照列表(self, 机器人ID: str) -> list[dict[str, Any]]:
        数据 = self._读取配置项(self._快照键(机器人ID))
        if not isinstance(数据, list):
            return []
        return [项 for 项 in 数据 if isinstance(项, dict) and isinstance(项.get("设置"), dict)]

    def 是否有回退快照(self, 机器人ID: str) -> bool:
        return bool(self._读取快照列表(机器人ID))

    def 获取回退快照信息(self, 机器人ID: str) -> list[dict[str, Any]]:
        return [
            {
                "时间": 项.get("时间"),
                "目标预设": str(项.get("目标预设") or ""),
            }
            for 项 in self._读取快照列表(机器人ID)
        ]

    def 应用预设(
        self,
        机器人ID: str,
        预设: str | 方案预设,
    ) -> 应用预设结果:
        方案 = self._解析方案(预设)
        当前设置 = self.数据库.获取机器人设置(机器人ID)
        差异 = self.预览差异(机器人ID, 方案)
        新设置 = self._计算应用后设置(当前设置, 方案)

        快照记录 = {
            "时间": time.time(),
            "目标预设": 方案.名称,
            "设置": _完整设置字典(当前设置),
        }
        快照列表 = self._读取快照列表(机器人ID)
        快照列表.append(快照记录)
        if len(快照列表) > 最大回退快照数:
            快照列表 = 快照列表[-最大回退快照数:]
        self._写入配置项(self._快照键(机器人ID), 快照列表)

        self.数据库.保存机器人设置(机器人ID, 新设置)
        return 应用预设结果(
            成功=True,
            预设名称=方案.名称,
            已备份=True,
            变更项=差异.变更项,
            新设置=新设置,
        )

    def 回退预设(self, 机器人ID: str) -> 回退结果:
        快照列表 = self._读取快照列表(机器人ID)
        if not 快照列表:
            return 回退结果(
                成功=False,
                说明="没有可回退的配置快照",
            )
        最新快照 = 快照列表.pop()
        self._写入配置项(self._快照键(机器人ID), 快照列表)

        当前设置 = self.数据库.获取机器人设置(机器人ID)
        当前字典 = _完整设置字典(当前设置)
        快照设置字典 = 任务数据库._规范化机器人设置JSON(最新快照["设置"])
        恢复设置 = 机器人设置(**快照设置字典)
        恢复字典 = _完整设置字典(恢复设置)
        恢复字段数 = sum(1 for 键, 值 in 恢复字典.items() if 当前字典.get(键) != 值)

        self.数据库.保存机器人设置(机器人ID, 恢复设置)
        原预设名称 = str(最新快照.get("目标预设") or "")
        return 回退结果(
            成功=True,
            原预设名称=原预设名称,
            恢复字段数=恢复字段数,
            说明=f"已撤销「{原预设名称}」并恢复上一份配置快照",
        )

    # ---------------------------------------------------------- JSON 导入导出（无删除接口）
    def 导出预设JSON(self, 预设: str | 方案预设) -> str:
        方案 = self._解析方案(预设)
        载荷 = {
            "格式版本": 1,
            "名称": 方案.名称,
            "说明": 方案.说明,
            "标签": list(方案.标签),
            "参数": copy.deepcopy(方案.参数),
        }
        return json.dumps(载荷, ensure_ascii=False, indent=2)

    def 导出当前配置JSON(
        self,
        机器人ID: str,
        名称: str = "当前配置",
        说明: str = "",
    ) -> str:
        当前设置 = self.数据库.获取机器人设置(机器人ID)
        临时方案 = 方案预设(
            名称=str(名称 or "当前配置").strip() or "当前配置",
            说明=str(说明 or f"导出自 {机器人ID}"),
            参数=_过滤策略参数(_完整设置字典(当前设置)),
            内置=False,
            标签=("导出",),
        )
        return self.导出预设JSON(临时方案)

    def 写入预设JSON文件(
        self,
        预设: str | 方案预设,
        目标路径: str | Path,
    ) -> Path:
        """只向指定路径写入导出的 JSON 文本，不提供任何删除磁盘文件的功能。"""
        路径 = Path(目标路径)
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(self.导出预设JSON(预设), encoding="utf-8")
        return 路径

    def 导入预设JSON(
        self,
        json文本: str,
        *,
        覆盖名称: str | None = None,
        保存为自定义: bool = True,
        覆盖同名: bool = True,
    ) -> 方案预设:
        try:
            载荷 = json.loads(str(json文本 or ""))
        except (TypeError, ValueError, json.JSONDecodeError) as 异常:
            raise ValueError(f"预设 JSON 格式无效：{异常}") from None

        if not isinstance(载荷, dict):
            raise ValueError("预设 JSON 根节点必须是对象")

        if isinstance(载荷.get("参数"), Mapping):
            原始参数 = dict(载荷["参数"])
            默认名称 = str(载荷.get("名称") or "").strip()
            说明 = str(载荷.get("说明") or "").strip()
            标签 = tuple(str(x) for x in (载荷.get("标签") or ()) if str(x).strip())
        else:
            # 兼容直接传入设置字段字典的 JSON
            原始参数 = dict(载荷)
            默认名称 = ""
            说明 = "从 JSON 导入的预设"
            标签 = ("导入",)

        目标名 = str(覆盖名称 if 覆盖名称 is not None else 默认名称).strip()
        过滤参数 = _过滤策略参数(原始参数)
        if not 过滤参数:
            raise ValueError("JSON 中不包含有效的机器人设置参数")

        if not 保存为自定义:
            return 方案预设(
                名称=目标名 or "临时导入方案",
                说明=说明,
                参数=过滤参数,
                内置=False,
                标签=标签,
                创建时间=time.time(),
            )

        if not 目标名:
            raise ValueError("导入自定义预设需要提供 名称 或 覆盖名称")
        return self.保存自定义预设(
            名称=目标名,
            参数=过滤参数,
            说明=说明,
            标签=标签,
            覆盖=覆盖同名,
        )
