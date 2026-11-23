"""任务计划的展示模型与参数校验（与界面无关）。

界面根据 ``任务参数表`` 自动生成表单；保存时调用 ``应用参数`` 做类型
转换与范围校验，校验失败抛 ``ValueError``，不会写坏配置。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from 任务流程.军队配置.兵种资料 import 可选兵种名称
from 数据库.任务数据库 import (
    任务计划定义,
    任务计划定义列表,
    任务计划定义映射,
    任务计划是否启用,
    机器人设置,
    规范化任务计划顺序,
)


def 生成任务计划(设置) -> list[dict[str, str]]:
    """根据现有机器人配置生成任务状态，供界面和测试共同使用。"""
    if 设置 is None:
        return []

    def 布尔字段(字段名: str, 默认值: bool = False) -> bool:
        return bool(getattr(设置, 字段名, 默认值))

    任务状态 = []
    for 定义 in 任务计划定义列表:
        值 = getattr(设置, 定义.开关字段, None)
        已启用 = bool(值 if 定义.类型 != "list" else (值 or []))
        说明 = 定义.说明
        if 定义.类型 == "list":
            说明 += "；目标：" + ("、".join(map(str, 值)) if 值 else "未设置目标")
        elif 定义.类型 == "string":
            说明 += "；目标：" + (str(值) if 值 else "未设置目标")
        任务状态.append({
            "名称": 定义.名称,
            "状态": "已启用" if 已启用 else "未启用",
            "说明": 说明,
        })
    return [
        {"名称": "启动游戏与登录检查", "状态": "固定步骤", "说明": "启动客户端并确认进入可操作的主界面"},
        {"名称": "收集已有资源", "状态": "固定步骤", "说明": "读取并收集可领取资源"},
        *任务状态,
        {"名称": "速刷资源", "状态": "已启用" if 布尔字段("是否快速刷资源") else "未启用", "说明": "下兵后快速结束战斗"},
        {"名称": "资源打满后的行为", "状态": getattr(设置, "资源打满后动作", "退出"), "说明": "资源达到目标后退出任务或保持待机"},
        {"名称": "升级完成弹窗确认", "状态": "已启用" if 布尔字段("是否自动确认升级完成") else "未启用", "说明": "仅在明确识别升级完成文字和确认按钮后自动确认"},
    ]


# ---------------------------------------------------------------- 参数表单
@dataclass(frozen=True)
class 参数字段:
    字段: str
    标签: str
    类型: str  # int | float | text | secret | list | choice | bool | multi（多选勾选框）
    选项: tuple[str, ...] = ()
    最小值: float | None = None
    最大值: float | None = None
    提示: str = ""

    def 当前值(self, 设置) -> Any:
        值 = getattr(设置, self.字段, None)
        if self.类型 == "multi":
            return [项 for 项 in (值 or []) if 项 in self.选项]
        if self.类型 == "list":
            return "、".join(map(str, 值 or []))
        return 值

    def 解析(self, 原始值: Any) -> Any:
        """把表单值转换为设置字段的类型；不合法时抛 ValueError。"""
        if self.类型 == "bool":
            return bool(原始值)
        if self.类型 == "multi":
            项列表 = [原始值] if isinstance(原始值, str) else list(原始值 or [])
            未知 = [str(项) for 项 in 项列表 if str(项) not in self.选项]
            if 未知:
                raise ValueError(f"{self.标签}包含未知选项：{'、'.join(未知)}")
            # 按选项表顺序保存，界面勾选顺序不影响结果。
            已选 = {str(项) for 项 in 项列表}
            return [项 for 项 in self.选项 if 项 in 已选]
        if self.类型 == "list":
            文本 = str(原始值 or "")
            for 分隔 in ("\n", ",", "，", ";", "；"):
                文本 = 文本.replace(分隔, "、")
            return [项.strip() for 项 in 文本.split("、") if 项.strip()]
        if self.类型 in ("int", "float"):
            文本 = str(原始值 if 原始值 is not None else "").strip().replace(",", "")
            if not 文本:
                raise ValueError(f"{self.标签}不能为空")
            try:
                数值 = int(文本) if self.类型 == "int" else float(文本)
            except ValueError:
                raise ValueError(f"{self.标签}必须是数字") from None
            if self.最小值 is not None and 数值 < self.最小值:
                raise ValueError(f"{self.标签}不能小于 {self._格式(self.最小值)}")
            if self.最大值 is not None and 数值 > self.最大值:
                raise ValueError(f"{self.标签}不能大于 {self._格式(self.最大值)}")
            return 数值
        if self.类型 == "choice":
            值 = str(原始值 or "").strip()
            if self.选项 and 值 and 值 not in self.选项:
                raise ValueError(f"{self.标签}不在可选范围内")
            return 值
        return str(原始值 or "").strip()

    @staticmethod
    def _格式(数值: float) -> str:
        return str(int(数值)) if float(数值).is_integer() else str(数值)


@dataclass(frozen=True)
class 参数页:
    标题: str
    说明: str
    字段: tuple[参数字段, ...] = ()
    提示: tuple[str, ...] = field(default=())


def _字段选项(字段名: str) -> tuple[str, ...]:
    元数据 = 机器人设置.__dataclass_fields__[字段名].metadata
    return tuple(str(项) for 项 in 元数据.get("选项", []))


def _检查间隔(字段名: str) -> 参数字段:
    return 参数字段(字段名, "检查间隔（小时）", "float", 最小值=0)


_资源参数 = (
    参数字段("欲进攻的最小资源", "最低目标资源", "int", 最小值=0),
    参数字段("战利品优先级", "战利品优先级", "choice", ("均衡", "金币", "圣水", "黑水")),
    参数字段(
        "黑油储存上限", "黑水仓容量", "int", 最小值=0,
        提示="填写游戏资源栏显示的最大储存量。",
    ),
    参数字段("欲进攻资源建筑靠近地图边缘最小比例", "资源边缘比例", "float", 最小值=0, 最大值=1),
    参数字段("漏下兵种检测格数", "漏兵复核兵种数", "int", 最小值=0),
)

任务参数表: dict[str, 参数页] = {
    "main_resource": 参数页(
        "主世界刷资源", 任务计划定义映射["main_resource"].说明, _资源参数,
        ("资源易窃取评分固定为 0~10，必须严格大于 5 才进攻；5 分及以下自动跳过。",),
    ),
    "night_resource": 参数页(
        "夜世界刷资源", 任务计划定义映射["night_resource"].说明, _资源参数,
    ),
    "wall": 参数页("刷墙", 任务计划定义映射["wall"].说明, (
        参数字段("刷墙起始金币", "起始金币", "int", 最小值=0),
        参数字段("刷墙起始圣水", "起始圣水", "int", 最小值=0),
    )),
    "building": 参数页("建议建筑升级", 任务计划定义映射["building"].说明),
    "hero": 参数页("英雄或建筑升级", 任务计划定义映射["hero"].说明, (
        参数字段("欲升级的英雄或建筑", "升级目标", "list", 提示="多个目标用顿号、逗号或换行分隔。"),
        _检查间隔("建筑升级检查间隔"),
    )),
    "pet": 参数页("战宠升级", 任务计划定义映射["pet"].说明, (
        参数字段("欲升级的战宠", "战宠", "choice", _字段选项("欲升级的战宠")),
        _检查间隔("战宠升级检查间隔"),
    )),
    "research": 参数页("兵种或法术研究", 任务计划定义映射["research"].说明, (
        参数字段("欲升级的兵种或法术", "研究目标", "choice", _字段选项("欲升级的兵种或法术")),
        _检查间隔("研究升级检查间隔"),
    )),
    "startup": 参数页("启动游戏", "开始任务时先确认游戏状态。", (
        参数字段("自动启动游戏", "游戏没开时自动启动部落冲突", "bool"),
    ), (
        "只通过 ADB 启动游戏，不会启动或关闭模拟器；游戏已在运行时直接接管，不会重启。",
    )),
    "combat_options": 参数页("进攻选项", "直接影响主世界和夜世界的进攻流程。", (
        参数字段("是否快速刷资源", "快速结束资源战斗（速刷）", "bool"),
        参数字段("下兵间隔毫秒", "下兵间隔（毫秒）", "int", 最小值=0, 最大值=5000),
        参数字段("是否启用高速下兵", "启用高速下兵", "bool"),
        参数字段("高速下兵方式", "高速下兵方式", "choice", ("快速连点", "短按压")),
        参数字段("是否自动配兵", "启用自动配兵玩法", "bool"),
        参数字段("自动配兵玩法", "自动配兵玩法", "choice", ("资源优先", "稳健三星", "快速速刷")),
        参数字段("是否采集进攻界面图像", "采集进攻界面图像", "bool"),
    ), (
        "高速下兵仅用于数量不少于 8 个的普通兵种；英雄、攻城器械和药水仍逐点确认。",
        "战斗结果统计强制启用（胜负、星数、摧毁率和战利品分析）。",
    )),
    "troop_selection": 参数页("兵种选择", "勾选要带的兵种：刷资源前自动配兵，战斗中按兵种职责下兵。", (
        参数字段("是否自动配置军队", "按勾选兵种自动配兵", "bool"),
        参数字段("配兵兵种", "兵种", "multi", 可选兵种名称),
    ), (
        "开启后，每次刷资源前进入「编辑军队」页，清空普通兵种并按推荐比例用勾选的兵种填满军营；法术、攻城器械和英雄不改动。",
        "战斗中按职责下兵：开墙→肉盾→防御型→资源→近战→空中→远程→支援（天使最后跟随地面部队）。鼠标停在兵种上可看职责。",
        "超级兵种需要先在游戏里激活；未激活或未解锁的兵种会跳过并写入日志。不会点击任何宝石按钮。",
    )),
    "resource_policy": 参数页("资源打满后的行为", "资源达到目标后退出任务或保持待机。", (
        参数字段("资源打满后动作", "打满后动作", "choice", ("退出", "待机")),
    ), ("退出：完成任务并停止线程；待机：保持连接和界面观察，不再继续进攻。",)),
    "upgrade_popup": 参数页("升级完成弹窗确认", "仅在明确识别完成文字和确认按钮后自动确认。", (
        参数字段("是否自动确认升级完成", "自动确认升级完成弹窗", "bool"),
    ), (
        "必须连续两次识别到升级/研究完成文字和底部确认按钮才会点击；"
        "战斗中、商店、宝石、立即完成或识别不清时只记录日志并保持不动。",
    )),
    "notification": 参数页("通知与状态上报", "通过企业微信机器人推送运行状态。", (
        参数字段("企业微信webhook", "企业微信 Webhook", "text"),
        参数字段("状态上报间隔分钟", "状态上报间隔（分钟）", "int", 最小值=0),
    )),
    "official_api": 参数页("官方账号数据", "通过部落冲突官方 API 读取英雄、研究和战宠等级。", (
        参数字段("官方API令牌", "官方 API Token", "secret"),
        参数字段("玩家标签", "玩家标签", "text", 提示="游戏内个人资料里的 #标签"),
        参数字段("官方数据同步间隔分钟", "同步间隔（分钟）", "int", 最小值=5, 最大值=1440),
    ), (
        "在 developer.clashofclans.com 创建 Key，IP 填本机公网 IP；公网 IP 变化后需重新创建。",
        "填写后，研究、战宠、英雄升级前会先查官方等级：目标已满级就跳过，不再打开面板点击。",
        "官方 API 不提供资源数量和正在进行的升级，这些仍由截图识别；读取失败时按原流程执行。",
    )),
}

# 不属于可勾选任务、但需要配置的全局选项，按显示顺序排列。
全局配置键 = ("startup", "combat_options", "troop_selection", "resource_policy", "upgrade_popup", "notification", "official_api")

服务器选项 = ("国际服", "调试服务器")


@dataclass(frozen=True)
class 任务行:
    键: str
    名称: str
    说明: str
    已启用: bool
    类型: str
    需要目标: bool  # list/string 任务已勾选但未设置目标


def 任务行列表(设置) -> list[任务行]:
    """按设置中的顺序返回可勾选任务。"""
    if 设置 is None:
        return []
    结果 = []
    for 键 in 规范化任务计划顺序(getattr(设置, "任务计划顺序", None)):
        定义: 任务计划定义 = 任务计划定义映射[键]
        已启用 = 任务计划是否启用(设置, 键)
        结果.append(任务行(
            键, 定义.名称, 定义.说明, 已启用, 定义.类型,
            需要目标=定义.类型 in ("list", "string") and not 已启用,
        ))
    return 结果


def 已启用任务名称(设置) -> list[str]:
    return [行.名称 for 行 in 任务行列表(设置) if 行.已启用]


def 移动任务(设置, 键: str, 方向: int) -> bool:
    """在任务计划顺序中上移(-1)/下移(+1)一项；越界返回 False。"""
    顺序 = 规范化任务计划顺序(getattr(设置, "任务计划顺序", None))
    if 键 not in 顺序:
        return False
    新索引 = 顺序.index(键) + 方向
    if not 0 <= 新索引 < len(顺序):
        return False
    顺序.remove(键)
    顺序.insert(新索引, 键)
    设置.任务计划顺序 = 顺序
    return True


def 设置任务开关(设置, 键: str, 启用: bool) -> None:
    """bool 任务直接写开关；list/string 任务关闭时清空目标。

    list/string 任务“开启”需要目标，由参数页填写；这里不会凭空造目标。
    """
    定义 = 任务计划定义映射[键]
    if 定义.类型 == "bool":
        setattr(设置, 定义.开关字段, bool(启用))
    elif not 启用:
        setattr(设置, 定义.开关字段, [] if 定义.类型 == "list" else "")


def 应用参数(设置, 页键: str, 表单值: Mapping[str, Any]) -> list[str]:
    """校验并写入一页参数。先全部解析，全部成功后才写入设置。"""
    页 = 任务参数表[页键]
    已解析: dict[str, Any] = {}
    for 字段 in 页.字段:
        if 字段.字段 in 表单值:
            已解析[字段.字段] = 字段.解析(表单值[字段.字段])
    for 名称, 值 in 已解析.items():
        setattr(设置, 名称, 值)
    return list(已解析)


def 所有参数字段() -> Iterable[参数字段]:
    已见 = set()
    for 页 in 任务参数表.values():
        for 字段 in 页.字段:
            if 字段.字段 not in 已见:
                已见.add(字段.字段)
                yield 字段
