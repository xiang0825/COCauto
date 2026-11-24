"""部落冲突官方 API（developer.clashofclans.com）账号数据同步。

只用标准库，不引入新依赖。机器人用它在升级任务前确认目标是否已经满级，
避免对已满级的研究、战宠或英雄反复打开面板点击。

官方 API 只提供等级、奖杯等账号数据，不提供资源数量和正在进行的升级，
这些仍由截图识别负责。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

默认基础地址 = "https://api.clashofclans.com/v1"

# API 英文名 -> 机器人设置里使用的游戏内中文名（与设置选项保持一致）。
英雄名称 = {
    "Barbarian King": "野蛮人之王",
    "Archer Queen": "弓箭女皇",
    "Grand Warden": "大守护者",
    "Royal Champion": "飞盾战神",
    "Minion Prince": "亡灵王子",
    "Dragon Duke": "飞龙公爵",
}

研究名称 = {
    # 圣水兵种
    "Barbarian": "野蛮人", "Archer": "弓箭手", "Goblin": "哥布林", "Giant": "巨人",
    "Wall Breaker": "炸弹人", "Balloon": "气球兵", "Wizard": "法师", "Healer": "天使",
    "Dragon": "飞龙", "P.E.K.K.A": "皮卡超人", "Baby Dragon": "飞龙宝宝",
    "Miner": "掘地矿工", "Electro Dragon": "雷电飞龙", "Yeti": "大雪怪",
    "Dragon Rider": "龙骑士", "Electro Titan": "雷霆泰坦", "Root Rider": "根蔓骑士",
    "Thrower": "巨矛投手", "Meteor Golem": "陨石戈仑",
    # 黑油兵种
    "Minion": "亡灵", "Hog Rider": "野猪骑士", "Valkyrie": "瓦基丽武神",
    "Golem": "戈仑石人", "Witch": "女巫", "Lava Hound": "熔岩猎犬",
    "Bowler": "巨石投手", "Ice Golem": "戈仑冰人", "Headhunter": "英雄猎手",
    "Apprentice Warden": "守护者学徒", "Druid": "德鲁伊", "Furnace": "烈焰熔炉",
    # 攻城器械
    "Wall Wrecker": "攻城战车", "Battle Blimp": "攻城飞艇", "Stone Slammer": "攻城气球",
    "Siege Barracks": "攻城训练营", "Log Launcher": "攻城滚木车",
    "Flame Flinger": "攻城烈焰车", "Battle Drill": "攻城钻机",
    "Troop Launcher": "部队发射器",
    # 法术
    "Lightning Spell": "雷电法术", "Healing Spell": "疗伤法术", "Rage Spell": "狂暴法术",
    "Jump Spell": "弹跳法术", "Freeze Spell": "冰冻法术", "Clone Spell": "镜像法术",
    "Invisibility Spell": "隐形法术", "Recall Spell": "回溯法术",
    "Revive Spell": "复苏法术", "Totem Spell": "图腾法术",
    "Poison Spell": "伤害药水法术", "Earthquake Spell": "地震法术",
    "Haste Spell": "急速法术", "Skeleton Spell": "骷髅法术", "Bat Spell": "蝙蝠法术",
    "Overgrowth Spell": "疯狂蔓生法术", "Ice Block Spell": "冰障法术",
}

战宠名称 = {
    "L.A.S.S.I": "莱希", "Electro Owl": "闪枭", "Mighty Yak": "大耗", "Unicorn": "独角",
    "Frosty": "冰牙", "Diggy": "地兽", "Poison Lizard": "猛蜥", "Phoenix": "凤凰",
    "Spirit Fox": "灵狐", "Angry Jelly": "愤怒水母", "Sneezy": "阿啾",
}

错误提示 = {
    400: "参数错误，请检查玩家标签",
    403: "Token 无效或本机公网 IP 不在 Token 白名单（IP 变化后需重新创建 Key）",
    404: "找不到该玩家标签",
    429: "请求过于频繁被限流",
    503: "官方服务器维护中",
}


class 官方API错误(Exception):
    def __init__(self, 状态码: int, 原因: str):
        self.状态码 = 状态码
        提示 = 错误提示.get(状态码, "网络异常，请检查网络或代理")
        super().__init__(f"HTTP {状态码} {原因}：{提示}" if 状态码 else f"{原因}：{提示}")


def 规范化标签(标签: str) -> str:
    文本 = str(标签 or "").strip().upper().replace("O", "0")
    if 文本 and not 文本.startswith("#"):
        文本 = "#" + 文本
    return 文本


def 获取玩家(令牌: str, 标签: str, 基础地址: str = 默认基础地址,
          超时秒: float = 10.0, 重试次数: int = 2) -> dict:
    """读取玩家完整资料；失败抛 ``官方API错误``。"""
    令牌 = str(令牌 or "").strip()
    if not 令牌.isascii() or any(字符.isspace() for 字符 in 令牌):
        # HTTP 头只能是 ASCII；粘贴时混入全角字符、空格或换行会直接抛编码异常。
        raise 官方API错误(0, "Token 含有非法字符（全角字符、空格或换行），请重新复制粘贴")
    地址 = f"{基础地址.rstrip('/')}/players/{urllib.parse.quote(规范化标签(标签), safe='')}"
    请求 = urllib.request.Request(地址, headers={
        "Authorization": f"Bearer {令牌.strip()}",
        "Accept": "application/json",
        "User-Agent": "coc-robot",
    })
    for 次数 in range(重试次数 + 1):
        try:
            with urllib.request.urlopen(请求, timeout=超时秒) as 响应:
                return json.loads(响应.read().decode("utf-8"))
        except urllib.error.HTTPError as 异常:
            try:
                原因 = json.loads(异常.read().decode("utf-8")).get("reason", 异常.reason)
            except Exception:
                原因 = 异常.reason
            if 异常.code in (429, 500, 502, 503, 504) and 次数 < 重试次数:
                time.sleep(2 ** 次数)
                continue
            raise 官方API错误(异常.code, str(原因)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as 异常:
            if 次数 < 重试次数:
                time.sleep(2 ** 次数)
                continue
            raise 官方API错误(0, str(getattr(异常, "reason", 异常))) from None
    raise 官方API错误(0, "未知错误")


@dataclass
class 账号摘要:
    """按机器人中文名索引的等级信息：名称 -> (当前等级, 满级)。"""
    标签: str = ""
    名字: str = ""
    大本营: int = 0
    英雄: dict[str, tuple[int, int]] = field(default_factory=dict)
    研究: dict[str, tuple[int, int]] = field(default_factory=dict)
    战宠: dict[str, tuple[int, int]] = field(default_factory=dict)
    已激活超级兵种: list[str] = field(default_factory=list)
    # 成就 “Games Champion” 的累计值 = 历次部落竞赛个人积分之和；
    # None 表示官方数据里没有这项成就。
    部落竞赛累计积分: int | None = None
    同步时间: float = 0.0

    def 是否满级(self, 类别: str, 名称: str) -> bool | None:
        """已知且满级 True，已知未满 False，官方数据里找不到返回 None。"""
        表 = {"英雄": self.英雄, "研究": self.研究, "战宠": self.战宠}.get(类别, {})
        if 名称 not in 表:
            return None
        等级, 满级 = 表[名称]
        return 满级 > 0 and 等级 >= 满级

    def 未满级(self, 类别: str) -> list[str]:
        表 = {"英雄": self.英雄, "研究": self.研究, "战宠": self.战宠}.get(类别, {})
        return [名 for 名, (等级, 满级) in 表.items() if 等级 < 满级]

    def 转为字典(self) -> dict:
        return {
            "标签": self.标签, "名字": self.名字, "大本营": self.大本营,
            "英雄": {k: list(v) for k, v in self.英雄.items()},
            "研究": {k: list(v) for k, v in self.研究.items()},
            "战宠": {k: list(v) for k, v in self.战宠.items()},
            "已激活超级兵种": self.已激活超级兵种,
            "部落竞赛累计积分": self.部落竞赛累计积分, "同步时间": self.同步时间,
        }

    def 日志文本(self) -> str:
        英雄 = "、".join(f"{名}{等}/{满}" for 名, (等, 满) in self.英雄.items())
        未满研究 = self.未满级("研究")
        未满战宠 = self.未满级("战宠")
        return (
            f"官方数据：{self.名字}（{self.标签}）大本营{self.大本营}；英雄 {英雄 or '无'}；"
            f"未满级研究 {len(未满研究)} 项"
            + (f"（{'、'.join(未满研究[:8])}{'…' if len(未满研究) > 8 else ''}）" if 未满研究 else "")
            + f"；未满级战宠 {len(未满战宠)} 只"
            + (f"；已激活超级兵种：{'、'.join(self.已激活超级兵种)}" if self.已激活超级兵种 else "")
        )


def 整理账号摘要(玩家: dict) -> 账号摘要:
    摘要 = 账号摘要(
        标签=玩家.get("tag", ""), 名字=玩家.get("name", ""),
        大本营=int(玩家.get("townHallLevel") or 0), 同步时间=time.time(),
    )
    for 项 in 玩家.get("heroes", []):
        if 项.get("village") == "home" and 项.get("name") in 英雄名称:
            摘要.英雄[英雄名称[项["name"]]] = (int(项.get("level", 0)), int(项.get("maxLevel", 0)))
    for 项 in 玩家.get("troops", []) + 玩家.get("spells", []):
        if 项.get("village") != "home":
            continue
        名 = 项.get("name")
        等级 = (int(项.get("level", 0)), int(项.get("maxLevel", 0)))
        if 名 in 研究名称:
            摘要.研究[研究名称[名]] = 等级
        elif 名 in 战宠名称:
            摘要.战宠[战宠名称[名]] = 等级
        if 项.get("superTroopIsActive"):
            摘要.已激活超级兵种.append(名)
    for 项 in 玩家.get("achievements", []) or []:
        if 项.get("name") == "Games Champion":
            try:
                摘要.部落竞赛累计积分 = int(项.get("value") or 0)
            except (TypeError, ValueError):
                摘要.部落竞赛累计积分 = None
            break
    return 摘要


def 同步账号(令牌: str, 标签: str, 基础地址: str = 默认基础地址) -> 账号摘要:
    return 整理账号摘要(获取玩家(令牌, 标签, 基础地址))
