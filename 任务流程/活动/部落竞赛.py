"""部落竞赛：自动接一个打鱼能完成的任务。

流程（全部识别参数在 ``资源/活动/部落竞赛.json``）：
确认主世界主页 → 底栏『活动』→ 活动列表里找到『部落竞赛』→『开启』→
确认竞赛面板 → 个人积分已满或已有进行中任务就关闭返回 → 逐张点开任务卡
读取详情（卡面本身没有文字）→ 按白名单选一项 → 再次确认详情和『开始』
按钮后点击 → 关闭面板回主页。

护栏：
- 识别不清不点：每次点击前都要有模板或 OCR 的正面证据；
- 详情区出现宝石图标或『立即/跳过/重置/购买』等文字的卡片一律不点；
- 冷却中的卡片不点；
- 入口找不到（活动已结束）直接返回，不等待；
- 每一步都有超时，整个流程还有总超时；
- 不领奖：竞赛结束/可以领奖/个人积分满时只写日志提醒，
  任何领奖按钮都不点。

调度（rc147）：进攻前调用 ``执行(进攻前=True)``，按“进攻计数”而不只是
30 分钟冷却决定何时开面板：刚接任务后打 1 场再看一次以测速，之后按
进度速率预测完成那一场再看；没有任务时每 2 场看一次。看到任务已完成就在
同一次面板里接新任务。时间冷却仍作为上限兜底。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from 任务流程.基础任务框架 import 基础任务
from 任务流程.活动.竞赛配兵策略 import 解析指定单位

资源相对路径 = Path("资源") / "活动" / "部落竞赛.json"
状态键 = "部落竞赛检查记录"

# OCR 对繁体界面常常混出繁简两种字形；统一转成简体后再匹配关键词，
# 资源文件里的关键词只需要写简体。只收录界面里实际出现的字。
_繁简表 = str.maketrans({
    "競": "竞", "賽": "赛", "築": "筑", "師": "师", "戰": "战", "鬥": "斗", "門": "门",
    "毀": "毁", "個": "个", "營": "营", "開": "开", "啟": "启", "奪": "夺", "幣": "币",
    "聖": "圣", "擊": "击", "勝": "胜", "對": "对", "進": "进", "時": "时", "餘": "余",
    "礦": "矿", "儲": "储", "鑽": "钻", "資": "资", "禦": "御", "農": "农", "連": "连",
    "獄": "狱", "鷹": "鹰", "費": "费", "寶": "宝", "購": "购", "買": "买", "過": "过",
    "卻": "却", "鐘": "钟", "務": "务", "棄": "弃", "積": "积", "獲": "获", "贏": "赢",
    "聯": "联", "誼": "谊", "襲": "袭", "隊": "队", "級": "级", "種": "种", "護": "护",
    "達": "达", "滿": "满", "獎": "奖", "勵": "励", "領": "领", "動": "动", "場": "场",
    "單": "单", "遊": "游", "戲": "戏", "闇": "暗", "靈": "灵", "龍": "龙", "術": "术",
    "廠": "厂", "壘": "垒", "從": "从", "圖": "图", "騎": "骑", "強": "强", "塊": "块",
    "顆": "颗", "總": "总", "計": "计", "員": "员", "間": "间", "與": "与", "將": "将",
    "冊": "册", "訊": "讯", "禮": "礼", "鎖": "锁", "內": "内", "倉": "仓", "庫": "库",
    "壞": "坏", "罐": "罐", "瓶": "瓶", "鍋": "锅", "蓋": "盖", "藥": "药", "車": "车",
    "鍵": "键", "畫": "画", "後": "后", "釋": "释", "還": "还", "這": "这", "幾": "几",
    "攻": "攻", "擁": "拥", "幫": "帮", "實": "实", "現": "现", "爾": "尔", "撲": "扑",
    "飛": "飞", "彈": "弹", "炸": "炸", "砲": "炮", "弓": "弓", "設": "设", "備": "备",
    "選": "选", "擇": "择", "邊": "边", "臺": "台", "檯": "台", "風": "风", "雲": "云",
    "陣": "阵", "簡": "简", "體": "体", "繼": "继", "續": "续", "確": "确", "認": "认",
    "灣": "湾", "專": "专", "區": "区", "價": "价", "頭": "头", "點": "点", "數": "数",
    "牆": "墙", "墻": "墙",
})


def 规范文本(文本: Any) -> str:
    """去空白、繁转简、转小写，用于关键词匹配。"""
    return re.sub(r"\s+", "", str(文本 or "")).translate(_繁简表).lower()


# ------------------------------------------------------------------ 资源加载
def 资源候选目录() -> list[Path]:
    """EXE 同级目录优先（方便不打包直接改资源），再回退 _internal / 源码根。"""
    候选: list[Path] = []

    def 加入(目录):
        if 目录:
            路径 = Path(目录).resolve()
            if 路径 not in 候选:
                候选.append(路径)

    if getattr(sys, "frozen", False):
        程序目录 = Path(sys.executable).resolve().parent
        加入(程序目录)
        加入(getattr(sys, "_MEIPASS", None))
        加入(程序目录 / "_internal")
    加入(Path(__file__).resolve().parents[2])
    return 候选


def 查找资源文件(相对路径: str | Path, 候选目录: Iterable[Path] | None = None) -> Path | None:
    for 目录 in (候选目录 if 候选目录 is not None else 资源候选目录()):
        路径 = Path(目录) / 相对路径
        if 路径.is_file():
            return 路径
    return None


def 加载配置(路径: str | Path | None = None) -> dict:
    """读取部落竞赛资源 JSON；找不到或格式错误时抛 ``FileNotFoundError``/``ValueError``。"""
    if 路径 is None:
        路径 = 查找资源文件(资源相对路径)
        if 路径 is None:
            raise FileNotFoundError(f"找不到 {资源相对路径}")
    路径 = Path(路径)
    with open(路径, encoding="utf-8") as 文件:
        配置 = json.load(文件)
    if not isinstance(配置, dict):
        raise ValueError("部落竞赛资源格式错误：顶层必须是对象")
    配置["_目录"] = str(路径.parent)
    return 配置


# ------------------------------------------------------------------ OCR 工具
@dataclass(frozen=True)
class 文字项:
    文本: str
    框: tuple[int, int, int, int]

    @property
    def 中心(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.框
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def 规范(self) -> str:
        return 规范文本(self.文本)


def 整理OCR结果(OCR返回) -> list[文字项]:
    结果 = OCR返回[0] if isinstance(OCR返回, tuple) else OCR返回
    项列表 = []
    for 项 in 结果 or []:
        try:
            框, 文本 = 项[0], 项[1]
            xs = [float(点[0]) for 点 in 框]
            ys = [float(点[1]) for 点 in 框]
        except (TypeError, IndexError, ValueError):
            continue
        项列表.append(文字项(str(文本), (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    return 项列表


def 在区域内(点: tuple[int, int], 区域) -> bool:
    x1, y1, x2, y2 = 区域
    return x1 <= 点[0] <= x2 and y1 <= 点[1] <= y2


def 区域文字(项列表: list[文字项], 区域) -> list[文字项]:
    return [项 for 项 in 项列表 if 在区域内(项.中心, 区域)]


def 拼接文本(项列表: Iterable[文字项]) -> str:
    return "".join(项.规范 for 项 in 项列表)


def 查找关键词(项列表: list[文字项], 关键词: Iterable[str], 区域=None) -> 文字项 | None:
    词表 = [规范文本(词) for 词 in 关键词 if 词]
    for 项 in 项列表:
        if 区域 is not None and not 在区域内(项.中心, 区域):
            continue
        if any(词 in 项.规范 for 词 in 词表):
            return 项
    return None


def 含禁点文字(文本: str, 配置: dict) -> str | None:
    文本 = 规范文本(文本)
    for 词 in 配置.get("OCR", {}).get("禁点关键词", []):
        if 规范文本(词) and 规范文本(词) in 文本:
            return 词
    return None


def 纠正OCR文本(文本: str, 配置: dict) -> str:
    """规范化后按配置替换常见 OCR 错字（建菜→建筑、多人避→多人对战…）。"""
    文本 = 规范文本(文本)
    for 错, 对 in (配置.get("OCR纠错") or {}).items():
        if 错:
            文本 = 文本.replace(规范文本(错), 规范文本(对))
    if any(词 in 文本 for 词 in ("暴力", "摧毁", "拆毁", "破坏", "推毁")):
        文本 = re.sub(
            r"([0-9一二三四五六七八九十百千万]+\s*[块境]|块)城(?!墙|市|堡)",
            r"\1城墙",
            文本,
        )
    return 文本


def 阵容单位(阵容签名: str | None) -> list[str]:
    """'弓箭手x2+雷龙x11+飞龙+攻城战车' → ['弓箭手', '雷龙', '飞龙', '攻城战车']。"""
    单位 = []
    for 段 in str(阵容签名 or "").split("+"):
        名 = re.sub(r"[x×]\d+$", "", 规范文本(段))
        if 名:
            单位.append(名)
    return 单位


def 兵种要求满足(文本: str, 配置: dict, 阵容签名: str | None) -> bool:
    """没有兵种要求返回 True；有要求时只有阵容里有同名单位才算满足。

    OCR 常把兵种名读错（亡x1、戈俞冰人、攻城车），读不出或对不上一律不接。
    """
    要求词 = [规范文本(词) for 词 in (配置.get("兵种要求") or {}).get("要求词", ["使用", "至少需"]) if 词]
    位置 = [文本.find(词) + len(词) for 词 in 要求词 if 词 in 文本]
    if not 位置:
        return True
    要求 = re.split(r"[x×\d。，,.]", 文本[max(位置):], maxsplit=1)[0]
    if len(要求) < 2:
        return False
    return any(单位 == 要求 or (len(单位) >= 2 and 要求.endswith(单位) and len(要求) - len(单位) <= 1)
               for 单位 in 阵容单位(阵容签名))


def 命中不接名单(文本: str, 配置: dict) -> str | None:
    """主人明确不接的任务类别（捐兵/捐法术/捐攻城机器等）；命中返回类别名。

    ``不接名单`` 在 ``资源/活动/部落竞赛.json`` 里按类别列关键词，比白名单更优先：
    即使 OCR 把详情读歪、碰巧凑上某个白名单关键词，也一律不接。
    """
    文本 = 纠正OCR文本(文本, 配置)
    if not 文本:
        return None
    for 类别, 词表 in (配置.get("不接名单") or {}).items():
        if not isinstance(词表, (list, tuple)):
            continue
        if any(规范文本(词) and 规范文本(词) in 文本 for 词 in 词表):
            return str(类别)
    return None


def _可用单位集合(可用单位) -> set[str]:
    if isinstance(可用单位, dict):
        return {
            str(名称)
            for 单位列表 in 可用单位.values()
            for 名称 in (单位列表 or ())
        }
    return {str(名称) for 名称 in (可用单位 or ())}


def 指定兵种跳过原因(文本: str, 配置: dict, 可用单位=None) -> str | None:
    """提供可审计的拒接原因；不支持、未解锁或没有预检结果时都停手。"""
    标准文本 = 纠正OCR文本(文本, 配置)
    要求词 = [规范文本(词) for 词 in (配置.get("兵种要求") or {}).get("要求词", ["使用", "至少需"]) if 词]
    if not any(词 in 标准文本 for 词 in 要求词):
        return None
    解析 = 解析指定单位(标准文本)
    if not 解析:
        return "指定兵种名称/数量无法可靠识别"
    名称, _ = 解析
    if 名称 not in _可用单位集合(可用单位):
        return f"指定单位{名称}未解锁或预检未确认"
    return None


def 动态任务跳过原因(文本: str, 配置: dict, 可用单位=None) -> str | None:
    指定原因 = 指定兵种跳过原因(文本, 配置, 可用单位)
    if 指定原因:
        return 指定原因
    标准文本 = 纠正OCR文本(文本, 配置)
    拆墙定义 = (配置.get("白名单") or {}).get("拆墙", {})
    组 = 拆墙定义.get("关键词组") or []
    if 组 and all(any(规范文本(词) in 标准文本 for 词 in 词组 if 词) for 词组 in 组):
        if "炸弹人" not in _可用单位集合(可用单位):
            return "炸弹人未解锁或编辑页未识别"
    return None


def 识别任务类型(
    文本: str,
    配置: dict,
    阵容签名: str | None = None,
    可用单位=None,
) -> str | None:
    """按白名单定义判断；指定单位只接受预检已解锁的支持单位。"""
    if 命中不接名单(文本, 配置):
        return None
    文本 = 纠正OCR文本(文本, 配置)
    if not 文本:
        return None
    if any(规范文本(词) in 文本 for 词 in 配置.get("全局排除词", []) if 词):
        return None
    要求词 = [规范文本(词) for 词 in (配置.get("兵种要求") or {}).get("要求词", ["使用", "至少需"]) if 词]
    有指定要求 = any(词 in 文本 for 词 in 要求词)
    if 有指定要求:
        if 指定兵种跳过原因(文本, 配置, 可用单位):
            return None
        指定定义 = (配置.get("白名单") or {}).get("指定兵种", {})
        指定关键词组 = 指定定义.get("关键词组") or []
        指定规则匹配 = bool(指定关键词组) and all(
            any(规范文本(词) in 文本 for 词 in 词组 if 词)
            for 词组 in 指定关键词组
        )
        if 指定规则匹配:
            return "指定兵种"
    elif not 兵种要求满足(文本, 配置, 阵容签名):
        return None
    for 名称, 定义 in (配置.get("白名单") or {}).items():
        if any(规范文本(词) in 文本 for 词 in 定义.get("排除词", []) if 词):
            continue
        组 = 定义.get("关键词组") or []
        if 组 and all(any(规范文本(词) in 文本 for 词 in 词组 if 词) for 词组 in 组):
            if 名称 == "拆墙" and "炸弹人" not in _可用单位集合(可用单位):
                return None
            return 名称
    return None


def 解析积分(项列表: Iterable[文字项]) -> int | None:
    """详情里积分是单独一行纯数字（50~1000，50 的倍数）。"""
    候选 = []
    for 项 in 项列表:
        数字 = re.sub(r"[\s,+]", "", 项.文本)
        if not 数字.isdigit():
            continue
        值 = int(数字)
        # 奖章图标常被识别成末尾多一个 0/8。
        if 值 > 1000 and 数字[-1] in "08":
            值 = int(数字[:-1])
        if 50 <= 值 <= 1000 and 值 % 50 == 0:
            候选.append(值)
    return max(候选) if 候选 else None


def 解析个人积分(文本: str) -> tuple[int, int] | None:
    匹配 = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", str(文本 or ""))
    if not 匹配:
        return None
    当前, 上限 = (int(值.replace(",", "")) for 值 in 匹配.groups())
    if 上限 <= 0:
        return None
    return 当前, 上限


def 识别卡片位置(项列表: Iterable[文字项], 配置: dict) -> list[tuple[int, int]]:
    """用卡片下方的积分数字定位当前画面里完整露出的任务卡中心。"""
    面板 = 配置.get("面板", {})
    x1, y1, x2, y2 = 面板.get("卡片区ROI", (0, 0, 800, 600))
    dx, dy = 面板.get("卡片相对积分", [-15, -50])
    最小中心y = int(面板.get("卡片中心最小y", 120))
    位置 = []
    for 项 in 项列表:
        if not (x1 <= 项.框[0] and 项.框[2] <= x2 and y1 <= 项.框[1] and 项.框[3] <= y2):
            continue
        if 解析积分([项]) is None:
            continue
        中心 = (项.中心[0] + int(dx), 项.框[1] + int(dy))
        if 中心[1] < 最小中心y:
            continue
        if all(abs(中心[0] - 已有[0]) > 30 or abs(中心[1] - 已有[1]) > 30 for 已有 in 位置):
            位置.append(中心)
    return sorted(位置, key=lambda 点: (round(点[1] / 80), 点[0]))


# ------------------------------------------------------------------ 选择
@dataclass
class 任务候选:
    页: int
    位置: tuple[int, int]
    类型: str | None
    积分: int | None
    文本: str = ""
    冷却: bool = False
    禁点原因: str | None = None
    开始点: tuple[int, int] | None = None
    详情超时: bool = False


def 选择任务(候选列表: Iterable[任务候选], 启用白名单: Iterable[str], 配置: dict) -> 任务候选 | None:
    """积分最高优先；同分选完成快的（层级小：掠夺 1 > 摧毁资源 2 > 拆建筑/墙 3 >
    防御/指定建筑 4 > 胜利拿星 5 > 摧毁率 6），再按白名单顺序。"""
    启用 = [名 for 名 in 启用白名单]
    白名单 = 配置.get("白名单") or {}
    可选 = [
        候选 for 候选 in 候选列表
        if 候选.类型 in 启用 and not 候选.冷却 and not 候选.禁点原因
    ]
    if not 可选:
        return None
    return min(可选, key=lambda 候选: (
        -(候选.积分 or 0),
        int(白名单.get(候选.类型, {}).get("层级", 9)),
        启用.index(候选.类型),
    ))


def 官方API判断满分(累计积分: int | None, 记录: dict | None, 上限: int, 现在: datetime) -> tuple[bool | None, dict]:
    """用官方成就 Games Champion 的增量估算本期个人积分。

    第一次在本月看到时记为基线；之后 增量 >= 上限 视为满分。
    返回 (是否满分或 None 表示无法判断, 新记录)。
    """
    记录 = dict(记录 or {})
    if 累计积分 is None or 上限 <= 0:
        return None, 记录
    期号 = 现在.strftime("%Y-%m")
    if 记录.get("期号") != 期号 or not isinstance(记录.get("基线"), int):
        记录 = {"期号": 期号, "基线": int(累计积分)}
        return None, 记录
    return int(累计积分) - int(记录["基线"]) >= 上限, 记录


# ------------------------------------------------------------------ 任务
class 部落竞赛超时(Exception):
    pass


class 部落竞赛任务(基础任务):
    """部落竞赛接任务。``执行`` 返回 False 只表示页面无法恢复到主世界。"""

    def __init__(self, 上下文, 配置: dict | None = None, 官方摘要=None,
                 时钟: Callable[[], float] = time.monotonic, 现在: Callable[[], datetime] = datetime.now,
                 回主世界: Callable[[], bool] | None = None):
        super().__init__(上下文)
        self._配置 = 配置
        # 任务计划里的 event 项传入：不在主世界主页时先调用它安全切回主世界
        # （复用引擎的 _进入并确认主世界，不在这里重写世界入口识别）。
        # 打鱼间隙（进攻前）调用时已在主页，不传。
        self._回主世界 = 回主世界
        self.官方摘要 = 官方摘要
        self._时钟 = 时钟
        self._现在 = 现在
        self._截止 = 0.0
        self._模板缓存: dict[str, Any] = {}
        self._扫描中止原因: str | None = None
        self._记录: dict | None = None
        self.结果 = ""
        # 本轮从面板读到的进度，写进状态供界面显示（不影响任何点击决策）。
        self._本轮个人积分: tuple[int, int] | None = None
        self._本轮选择: str = ""
        self._本轮任务文本: str = ""
        self._当前任务类型: str = ""
        self._当前任务文本: str = ""
        # 面板上进行中任务卡的文字（与 _读取当前任务卡文本 同口径），作为后续比对基准。
        self._当前任务卡文本: str = ""

    # ---------------------------------------------------------------- 基础
    @property
    def 配置(self) -> dict:
        if self._配置 is None:
            self._配置 = 加载配置()
        return self._配置

    def _心跳秒(self) -> float:
        """本条日志作为心跳的有效期：流程进行中覆盖到总超时 + 宽限。

        监控只看最后一条日志的过期时间。单次 OCR/截图/模板识别本身阻塞超过
        60 秒时，识别循环里的定期日志写不出来；所以让流程内每条日志的有效期
        直接覆盖到本流程总截止时间之后 ``心跳宽限秒``。真正死锁超过总超时 +
        宽限后不会再有新日志，监控照常按无心跳停掉线程。
        """
        剩余 = self._截止 - self._时钟()
        if 剩余 <= 0:
            return 60.0
        return max(60.0, 剩余 + self._超时设置("心跳宽限秒", 30))

    def _日志(self, 文本: str) -> None:
        内容 = f"部落竞赛：{文本}"
        try:
            self.上下文.置脚本状态(内容, self._心跳秒())
        except TypeError:
            # 兼容只接受一个参数的旧上下文
            self.上下文.置脚本状态(内容)

    def _超时设置(self, 键: str, 默认: float) -> float:
        try:
            return float(self.配置.get("超时", {}).get(键, 默认))
        except (TypeError, ValueError):
            return 默认

    def _检查总超时(self) -> None:
        if self._时钟() > self._截止:
            raise 部落竞赛超时("整个流程超过总超时")
        停止事件 = getattr(self.上下文, "停止事件", None)
        if 停止事件 is not None and 停止事件.is_set():
            raise 部落竞赛超时("收到停止请求")

    def _延时(self, 毫秒: int) -> None:
        """可中断延时；顺带检测延时期间被后台维护检查占住的时间并写日志。

        2026-11-26 19:44 实机：``脚本延时`` 的后台维护（升级完成弹窗整屏 OCR）
        在活动列表上同步跑了约 3 分钟，本流程一条日志都写不出来。流程期间已
        通过 ``_部落竞赛流程中`` 关掉这些后台检查；这里再兜底记录真实耗时，
        以后任何类似阻塞都能从日志看到，并由步骤超时立即收尾。
        """
        开始 = time.monotonic()
        self.上下文.脚本延时(int(毫秒))
        多出 = time.monotonic() - 开始 - int(毫秒) / 1000.0
        if 多出 >= self._超时设置("慢调用日志秒", 3):
            self._日志(f"延时{int(毫秒)}毫秒实际多用了{多出:.1f}秒（后台检查占用），按步骤超时继续判断")

    def _截图(self):
        try:
            return self.上下文.op.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
        except TypeError:
            return self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)

    # 同一进程里只允许一次未返回的 OCR：超时后被放弃的识别线程还在跑时，
    # 不再并发调用同一个 native 引擎。
    _OCR进行中: threading.Thread | None = None

    # 某一步要求更短的 OCR 限时（例如确认活动列表）时临时设置，用完复位。
    _OCR临时上限秒: float | None = None

    def _OCR(self, 图像, 区域=None) -> list[文字项]:
        """限时 OCR。

        2026-11-26 18:14 实机：竞赛排在第一项、本会话首次用 OCR 时，点开活动列表后
        第一次识别（含首次加载 OCR 模型）2 分钟以上没返回，期间一条日志都没有，
        步骤超时也轮不到判断。这里把识别放到后台线程：每 ``OCR进度日志秒`` 写一条
        进度日志（也是心跳），超过 ``OCR秒`` 仍未返回就抛 ``部落竞赛超时``，
        交给 执行() 走安全关闭回主页并按冷却重试，不再无声卡住。
        """
        旧线程 = 部落竞赛任务._OCR进行中
        if 旧线程 is not None and 旧线程.is_alive():
            raise 部落竞赛超时("上一次 OCR 仍未返回，本轮放弃识别")
        结果: dict[str, Any] = {}
        偏移 = (0, 0)
        if 区域 is not None and 图像 is not None and hasattr(图像, "shape"):
            # 只识别需要的小区域：活动列表这类文字很多的整屏 OCR 实机要 1~4 分钟。
            高, 宽 = 图像.shape[:2]
            x1, y1, x2, y2 = [int(值) for 值 in 区域]
            x1, y1 = max(0, min(宽, x1)), max(0, min(高, y1))
            x2, y2 = max(x1, min(宽, x2)), max(y1, min(高, y2))
            if x2 > x1 and y2 > y1:
                图像 = 图像[y1:y2, x1:x2].copy()
                偏移 = (x1, y1)
        self._OCR偏移 = 偏移

        def 识别():
            try:
                获取 = getattr(self.上下文, "获取OCR引擎", None)
                引擎 = 获取() if callable(获取) else self.ocr引擎
                结果["值"] = 引擎(图像)
            except Exception as 异常:  # 识别失败按“没有文字”处理
                结果["异常"] = 异常

        线程 = threading.Thread(target=识别, name="部落竞赛OCR", daemon=True)
        部落竞赛任务._OCR进行中 = 线程
        线程.start()
        上限 = self._超时设置("OCR秒", 60)
        if self._OCR临时上限秒 is not None:
            上限 = min(上限, float(self._OCR临时上限秒))
        间隔 = max(1.0, min(self._超时设置("OCR进度日志秒", 10), 上限))
        开始 = time.monotonic()
        while True:
            线程.join(timeout=min(间隔, max(0.05, 上限 - (time.monotonic() - 开始))))
            if not 线程.is_alive():
                break
            已过 = time.monotonic() - 开始
            if 已过 >= 上限:
                self._日志(f"OCR 识别超过{int(上限)}秒仍未返回，放弃本轮并关闭面板")
                raise 部落竞赛超时(f"OCR 识别超过{int(上限)}秒未返回")
            self._日志(f"OCR 识别中（已{int(已过)}秒；首次使用需要加载文字识别模型）")
        部落竞赛任务._OCR进行中 = None
        耗时 = time.monotonic() - 开始
        if 耗时 >= 5:
            self._日志(f"OCR 耗时{耗时:.1f}秒（区域={tuple(区域) if 区域 is not None else '整屏'}）")
        if "异常" in 结果:
            self._日志(f"OCR 失败：{结果['异常']}")
            return []
        try:
            项列表 = 整理OCR结果(结果.get("值"))
        except Exception as 异常:
            self._日志(f"OCR 结果解析失败：{异常}")
            return []
        if 偏移 == (0, 0):
            return 项列表
        dx, dy = 偏移
        return [文字项(项.文本, (项.框[0] + dx, 项.框[1] + dy, 项.框[2] + dx, 项.框[3] + dy)) for 项 in 项列表]

    def _读模板(self, 名称: str):
        if 名称 in self._模板缓存:
            return self._模板缓存[名称]
        import cv2
        import numpy as np
        定义 = self.配置.get("模板", {}).get(名称) or {}
        图像列表 = []
        for 相对 in 定义.get("路径", []):
            路径 = Path(self.配置.get("_目录", ".")) / 相对
            if not 路径.is_file():
                其它 = 查找资源文件(Path("资源") / "活动" / 相对)
                路径 = 其它 if 其它 is not None else 路径
            if 路径.is_file():
                图 = cv2.imdecode(np.fromfile(str(路径), dtype=np.uint8), cv2.IMREAD_COLOR)
                if 图 is not None:
                    图像列表.append(图)
        self._模板缓存[名称] = 图像列表
        return 图像列表

    def 缺少的模板(self) -> list[str]:
        return [名 for 名 in self.配置.get("必需模板", []) if not self._读模板(名)]

    def _模板阈值(self, 名称: str) -> float:
        定义 = self.配置.get("模板", {}).get(名称) or {}
        return float(定义.get("阈值", 0.85))

    def _模板最佳(self, 图像, 名称: str, 区域=None) -> tuple[float, tuple[int, int]] | None:
        """不看阈值，返回 (最佳分数, 模板中心)；图像无效/模板缺失/ROI 太小返回 None。"""
        import cv2
        定义 = self.配置.get("模板", {}).get(名称) or {}
        x1, y1, x2, y2 = [int(值) for 值 in (区域 or 定义.get("ROI") or (0, 0, 800, 600))]
        if 图像 is None or not hasattr(图像, "shape"):
            return None
        子图 = 图像[max(0, y1):y2, max(0, x1):x2]
        最佳 = None
        for 模板 in self._读模板(名称):
            th, tw = 模板.shape[:2]
            if 子图.shape[0] < th or 子图.shape[1] < tw:
                continue
            结果 = cv2.matchTemplate(子图, 模板, cv2.TM_CCOEFF_NORMED)
            _, 分数, _, 位置 = cv2.minMaxLoc(结果)
            if 最佳 is None or 分数 > 最佳[0]:
                最佳 = (float(分数), (max(0, x1) + 位置[0] + tw // 2, max(0, y1) + 位置[1] + th // 2))
        return 最佳

    def _匹配模板(self, 图像, 名称: str, 区域=None) -> tuple[int, int] | None:
        """返回模板中心（800x600 坐标）；未命中或模板缺失返回 None。"""
        最佳 = self._模板最佳(图像, 名称, 区域)
        if 最佳 is None or 最佳[0] < self._模板阈值(名称):
            return None
        return 最佳[1]

    def _记录活动按钮诊断(self, 图像) -> None:
        """底栏没找到活动按钮时写出模板最佳分数/位置并存当时画面，便于事后确认原因（阈值不变）。"""
        try:
            最佳 = self._模板最佳(图像, "活动按钮")
            阈值 = self._模板阈值("活动按钮")
            区域 = (self.配置.get("模板", {}).get("活动按钮") or {}).get("ROI")
            if 最佳 is None:
                self._日志(f"活动按钮模板无法计算最佳分数（图像或模板无效），阈值{阈值:.2f}，ROI{区域}")
            else:
                self._日志(
                    f"活动按钮模板最佳分数{最佳[0]:.3f}（阈值{阈值:.2f}），位置{最佳[1]}，ROI{区域}"
                )
        except Exception as 异常:
            self._日志(f"活动按钮模板诊断失败（不影响流程）：{异常}")
        self._保存入口现场("活动按钮未找到", 图像=图像)

    def _等待(self, 条件: Callable[[], Any], 说明: str, 步骤秒: float | None = None):
        """轮询直到条件返回真值；超过步骤超时返回 None。

        单次条件判断（截图/识别）本身超过 ``慢调用日志秒`` 也写一条日志，
        不再出现几分钟没有任何日志的情况。
        """
        开始 = self._时钟()
        步骤截止 = 开始 + (self._超时设置("步骤秒", 8) if 步骤秒 is None else float(步骤秒))
        间隔 = int(self._超时设置("轮询毫秒", 500))
        慢调用秒 = self._超时设置("慢调用日志秒", 3)
        上次心跳 = 开始
        while True:
            self._检查总超时()
            单次开始 = time.monotonic()
            结果 = 条件()
            单次耗时 = time.monotonic() - 单次开始
            if 单次耗时 >= 慢调用秒:
                self._日志(f"确认{说明}单次识别耗时{单次耗时:.1f}秒")
            if 结果:
                return 结果
            现在 = self._时钟()
            if 现在 >= 步骤截止:
                self._日志(f"等待{说明}超时（{int(现在 - 开始)}秒）")
                return None
            if 现在 - 上次心跳 >= 20:
                # 单次识别很慢时也要持续写日志，避免监控按『无心跳』停掉线程。
                self._日志(f"仍在等待{说明}（已{int(现在 - 开始)}秒）")
                上次心跳 = 现在
            self._延时(间隔)

    def _点击(self, 点: tuple[int, int], 说明: str) -> bool:
        self._检查总超时()
        self._日志(f"点击{说明} {点}")
        # 写日志（心跳/通知回调）期间可能刚好收到停止：发送点击前再查一次。
        self._检查总超时()
        结果 = self.上下文.点击(int(点[0]), int(点[1]), 是否精确点击=True)
        if 结果 is False:
            self._日志(f"点击{说明}被点击护栏拒绝")
            return False
        return True

    def _滑动(self, 坐标) -> None:
        self._检查总超时()
        x1, y1, x2, y2 = [int(值) for 值 in 坐标]
        self.上下文.滑动屏幕((x1, y1), (x2, y2))

    def _设置面板标记(self, 开启: bool) -> None:
        self.上下文._部落竞赛面板已确认 = bool(开启)

    def _设置流程标记(self, 开启: bool) -> None:
        try:
            self.上下文._部落竞赛流程中 = bool(开启)
        except AttributeError:
            pass

    def _点击已确认关闭X(self, 点: tuple[int, int], 说明: str) -> bool:
        """对已通过模板与邻近禁点复核的关闭 X 临时放行点击护栏。"""
        标记 = "_部落竞赛安全关闭X点击中"
        原标记 = getattr(self.上下文, 标记, False)
        setattr(self.上下文, 标记, True)
        try:
            return self._点击(点, 说明)
        finally:
            setattr(self.上下文, 标记, 原标记)

    def _是主世界主页(self) -> bool:
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return False
        try:
            结果 = 识别(强制=True)
        except Exception:
            return False
        if (
            getattr(结果, "页面", "") != "主世界主页"
            or getattr(结果, "世界", None) != "主世界"
        ):
            return False
        可信度 = getattr(结果, "可信度", None)
        if 可信度 is not None:
            try:
                if float(可信度) < 0.70:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    # ---------------------------------------------------------------- 冷却
    def _读状态(self) -> dict:
        try:
            状态 = self.数据库.获取最新完整状态(self.机器人标志).状态数据
            记录 = 状态.get(状态键)
            return dict(记录) if isinstance(记录, dict) else {}
        except Exception:
            return {}

    def _写状态(self, 记录: dict) -> None:
        try:
            self.数据库.更新状态(self.机器人标志, 状态键, 记录)
        except Exception as 异常:
            self._日志(f"保存检查记录失败：{异常}")

    def _冷却分钟(self, 结果: str) -> float:
        设置间隔 = float(getattr(self.上下文.设置, "部落竞赛检查间隔分钟", 30) or 30)
        配置值 = self.配置.get("冷却分钟", {}).get(结果)
        try:
            配置值 = float(配置值)
        except (TypeError, ValueError):
            return 设置间隔
        # 常规结果跟随用户设置的间隔；满分/入口不存在等长冷却用资源里的值。
        if 结果 in {"已接任务", "已有任务", "无可接任务"}:
            return 设置间隔
        return 配置值

    # ---------------------------------------------------------------- 入口
    def 执行(self, 进攻前: bool = False) -> bool:
        设置 = self.上下文.设置
        if not getattr(设置, "是否部落竞赛接任务", False):
            self._清除竞赛配兵("部落竞赛接任务设置已关闭")
            来源 = "打鱼间隙" if 进攻前 else "任务计划"
            self._日志(f"本轮跳过（{来源}）：设置里未开启“部落竞赛接任务”")
            return True
        记录 = self._读状态()
        self._本次进攻前 = bool(进攻前)
        if 进攻前:
            记录["进攻计数"] = int(记录.get("进攻计数", 0) or 0) + 1
        现在 = time.time()
        到检查时机 = self._已到检查时机(记录, 现在, 进攻前=进攻前)
        当前动态类型 = self._记录任务类型(记录)
        if not 到检查时机 and 当前动态类型 not in {"拆墙", "指定兵种"}:
            if 进攻前:
                self._写状态(记录)
            try:
                说明 = self._跳过说明(记录, 现在, 进攻前)
            except Exception:
                说明 = "本轮跳过：未到检查时机"
            self._日志(说明)
            return True
        self._日志(self._触发说明(记录, 现在, 进攻前))
        self._本轮个人积分 = None
        self._本轮选择 = ""
        self._本轮任务文本 = ""
        self._当前任务类型 = ""
        self._当前任务文本 = ""
        self._当前任务卡文本 = ""
        try:
            配置 = self.配置
        except (OSError, ValueError) as 异常:
            self._日志(f"资源文件不可用，跳过：{异常}")
            self._记录结果(记录, "资源缺失", 360)
            return True
        if not 配置.get("已校准", False):
            self._日志("识别资源尚未用实机截图校准，只记录不点击")
            self._记录结果(记录, "资源未校准", 360)
            return True
        缺少 = self.缺少的模板()
        if 缺少:
            self._日志(f"缺少模板 {'、'.join(缺少)}，跳过且不点击")
            self._记录结果(记录, "资源缺失", 360)
            return True

        满分 = self._官方API满分(记录)
        if 满分:
            self._日志("官方数据显示本期个人积分已满，不再接任务；请手动领奖")
            self._提醒一次(记录, "满分", "部落竞赛个人积分已满，请手动去领奖励。")
            self._记录结果(记录, "已满分", self._冷却分钟("已满分"))
            return True

        if self._回主世界 is not None and not self._是主世界主页():
            if not self._切回主世界():
                self._记录结果(记录, "非主世界", self._冷却分钟("非主世界"))
                # 切换流程判定页面不可恢复时交给引擎安全待命；否则让后续任务照常继续。
                return not bool(getattr(self.上下文, "页面恢复失败", False))

        if (到检查时机 and self._启用了动态任务()) or 当前动态类型 in {"拆墙", "指定兵种"}:
            self._准备动态配兵预检(记录, 当前动态类型)
            if bool(getattr(self.上下文, "页面恢复失败", False)):
                self._日志("竞赛配兵预检后页面恢复未确认，停止本轮点击")
                return False

        self._记录 = 记录
        # 流程期间关掉 脚本延时 里的后台维护检查（升级完成弹窗整屏 OCR 等）：
        # 活动列表/竞赛面板文字最多，那些同步 OCR 实机一次要几分钟且不写日志。
        self._设置流程标记(True)
        try:
            self._截止 = self._时钟() + self._超时设置("总流程秒", 180)
            try:
                结果 = self._流程()
            except 部落竞赛超时 as 异常:
                self._日志(f"{异常}，中止并关闭面板")
                结果 = "超时"
            except Exception as 异常:
                self._日志(f"流程异常：{异常}，中止并关闭面板")
                结果 = "页面异常"
            self.结果 = 结果
            if 结果 in {"已满分", "可领奖", "入口不存在"}:
                self._清除竞赛配兵("竞赛任务已结束")
            # 已经打开过活动列表/面板就必须关回主页；还在主页时 _回到主页 不会点击。
            if 结果 != "非主世界":
                self._截止 = max(self._截止, self._时钟() + self._超时设置("步骤秒", 8) * 3)
                if not self._回到主页():
                    self._日志("无法确认回到主世界主页，停止后续点击")
                    self.上下文.页面恢复失败 = True
                    self._记录结果(记录, 结果, self._冷却分钟(结果))
                    return False
        finally:
            self._设置面板标记(False)
            self._设置流程标记(False)
        if 结果 == "已满分":
            self._提醒一次(记录, "满分", "部落竞赛个人积分已满，请手动去领奖励。")
        if 结果 == "可领奖":
            self._提醒一次(记录, "领奖", "部落竞赛已结束、可以领奖了，请自己去选择并领取奖励（脚本不会点领奖）。")
        if 结果 == "入口不存在" and 记录.get("本期见过入口") == self._现在().strftime("%Y-%m"):
            self._提醒一次(记录, "结束", "部落竞赛入口已消失（活动可能已结束），记得手动领奖。")
        self._记录结果(记录, 结果, self._冷却分钟(结果))
        return True

    def _当前页面描述(self) -> str:
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return "页面未知"
        try:
            结果 = 识别(强制=True)
        except Exception:
            return "页面未知"
        页面 = getattr(结果, "页面", "") or "未知"
        世界 = getattr(结果, "世界", None) or "未知"
        return f"页面={页面}，世界={世界}"

    def _切回主世界(self) -> bool:
        """不在主世界主页时调用注入的世界切换；回到主页返回 True，失败写清原因。"""
        self._日志(f"当前不在主世界主页（{self._当前页面描述()}），先安全切回主世界再查看竞赛任务")
        原因 = ""
        try:
            成功 = bool(self._回主世界())
        except Exception as 异常:
            成功 = False
            原因 = f"切换异常：{异常}"
        if 成功 and self._是主世界主页():
            self._日志("已回到主世界主页，继续打开竞赛面板查看可接任务")
            return True
        if not 原因:
            原因 = "世界切换未成功" if not 成功 else f"切换后仍未确认主世界主页（{self._当前页面描述()}）"
        self._日志(
            f"无法回到主世界主页：{原因}；本轮不接任务，"
            f"约{int(self._冷却分钟('非主世界'))}分钟后重试"
        )
        return False

    @staticmethod
    def _时分(时间戳: float) -> str:
        try:
            return datetime.fromtimestamp(float(时间戳)).strftime("%H:%M")
        except (OverflowError, OSError, ValueError):
            return ""

    def _跳过说明(self, 记录: dict, 现在: float, 进攻前: bool = False) -> str:
        """未到检查时机时写给用户看的跳过原因：冷却剩余、上次结果、已接任务。"""
        原因 = []
        下次 = float(记录.get("下次检查时间", 0) or 0)
        if 下次 > 现在:
            剩余分 = max(1, math.ceil((下次 - 现在) / 60))
            时分 = self._时分(下次)
            原因.append(f"冷却中，还剩约{剩余分}分钟" + (f"（{时分} 后再查看）" if 时分 else ""))
        目标 = 记录.get("下次检查进攻计数")
        if 目标 is not None:
            try:
                还差 = int(目标) - self._已完成进攻计数(记录, 进攻前)
                if 还差 > 0:
                    原因.append(f"或再打完{还差}场后提前查看")
            except (TypeError, ValueError):
                pass
        上次 = 记录.get("结果")
        if 上次:
            时间 = float(记录.get("时间", 0) or 0)
            时分 = self._时分(时间) if 时间 > 0 else ""
            时间文本 = f"（{时分}）" if 时分 else ""
            原因.append(f"上次结果：{上次}{时间文本}")
        if 记录.get("当前任务"):
            原因.append(f"已接任务：{记录['当前任务']}")
        来源 = "打鱼间隙" if 进攻前 else "任务计划"
        return f"本轮跳过（{来源}）：" + ("；".join(原因) if 原因 else "未到检查时机")

    @staticmethod
    def _已完成进攻计数(记录: dict, 进攻前: bool) -> int:
        """已经打完的场次。进攻前调用时“进攻计数”已含即将开打的这一场，要减掉。

        2026-11-26 18:20 实机：接任务时计数 N、预定 N+1 场后复查；下一次进攻前
        计数刚加到 N+1 就被当成“已打 1 场”，一场没打（41 秒后）又开了竞赛面板。
        """
        计数 = int(记录.get("进攻计数", 0) or 0)
        return 计数 - 1 if 进攻前 else 计数

    def _已到检查时机(self, 记录: dict, 现在: float, 进攻前: bool = False) -> bool:
        if 现在 >= float(记录.get("下次检查时间", 0) or 0):
            return True
        目标场次 = 记录.get("下次检查进攻计数")
        if 目标场次 is None:
            return False
        try:
            return self._已完成进攻计数(记录, 进攻前) >= int(目标场次)
        except (TypeError, ValueError):
            return False

    def _触发说明(self, 记录: dict, 现在: float, 进攻前: bool) -> str:
        """开面板前写明是谁触发的、为什么现在查看。"""
        来源 = "主世界刷资源打鱼间隙（进攻前）" if 进攻前 else "任务计划 部落竞赛接任务"
        下次 = float(记录.get("下次检查时间", 0) or 0)
        if 下次 <= 0:
            原因 = "首次检查"
        elif 现在 >= 下次:
            原因 = "冷却已到期"
        else:
            原因 = f"已打满预定场次（已完成{self._已完成进攻计数(记录, 进攻前)}场，预定第{记录.get('下次检查进攻计数')}场后查看）"
        return f"开始检查竞赛任务（触发：{来源}；{原因}）"

    def _记录任务类型(self, 记录: dict) -> str:
        类型 = str(记录.get("当前任务类型", "") or "")
        if 类型:
            return 类型
        文本 = str(记录.get("当前任务文本", "") or 记录.get("当前任务", "") or "")
        if "指定兵种" in 文本:
            return "指定兵种"
        if any(词 in 文本 for 词 in ("拆墙", "城墙", "块墙", "段墙")):
            return "拆墙"
        return ""

    def _启用了动态任务(self) -> bool:
        启用 = set(map(str, getattr(self.上下文.设置, "部落竞赛任务白名单", None) or ()))
        return bool(启用 & {"拆墙", "指定兵种"})

    def _准备动态配兵预检(self, 记录: dict, 当前类型: str = "") -> None:
        """仅在本进程首次需要时，用编辑页只读确认支持单位是否已解锁。"""
        上下文 = self.上下文
        if getattr(上下文, "_部落竞赛配兵预检完成", False):
            return
        from 任务流程.活动.竞赛配兵策略 import 指定单位映射
        from 任务流程.军队配置.编辑军队 import 期望配置

        基准 = 期望配置(getattr(上下文, "设置", None))
        上下文._部落竞赛基准配兵配置 = 基准
        可用目标 = {"兵种": [], "攻城": []}
        启用 = set(map(str, getattr(上下文.设置, "部落竞赛任务白名单", None) or ()))
        if "拆墙" in 启用 or 当前类型 == "拆墙":
            可用目标["兵种"].append("炸弹人")
        if "指定兵种" in 启用 or 当前类型 == "指定兵种":
            任务文本 = str(记录.get("当前任务文本", "") or "")
            已解析 = 解析指定单位(任务文本, self.配置) if 任务文本 else None
            if 已解析:
                名称, 分区 = 已解析
                可用目标.setdefault(分区, []).append(名称)
            else:
                for 名称, 分区 in dict.fromkeys(指定单位映射.values()):
                    可用目标.setdefault(分区, []).append(名称)
        # 不再依赖“按设置自动配兵”作为恢复基准：真正换兵前会读取编辑页实际阵容快照，
        # 读不完整就不换兵；任务结束按快照精确恢复。
        try:
            from 任务流程.军队配置.编辑军队 import 编辑军队任务
            可用 = 编辑军队任务(上下文).检查可用单位(可用目标)
        except Exception as 异常:
            可用 = {}
            self._日志(f"动态竞赛单位预检异常，本轮拒接相关任务：{异常}")
        上下文._部落竞赛可用单位 = 可用
        上下文._部落竞赛配兵预检完成 = True
        已解锁 = _可用单位集合(可用)
        if "拆墙" in 启用 or 当前类型 == "拆墙":
            self._日志(
                "动态任务预检：炸弹人已确认解锁" if "炸弹人" in 已解锁
                else "动态任务预检：炸弹人未解锁或无法识别，拆墙卡不接"
            )
        if "指定兵种" in 启用 or 当前类型 == "指定兵种":
            self._日志(
                "动态任务预检：可接要求单位=" + ("、".join(sorted(已解锁)) or "无，相关任务不接")
            )
        if 当前类型 in {"拆墙", "指定兵种"}:
            self._同步竞赛配兵(当前类型, str(记录.get("当前任务文本", "") or 记录.get("当前任务", "")))

    def _同步竞赛配兵(self, 类型: str, 文本: str) -> bool:
        上下文 = self.上下文
        if 类型 not in {"拆墙", "指定兵种"}:
            self._清除竞赛配兵("当前任务不需要临时配兵")
            return True
        from 任务流程.活动.竞赛配兵策略 import 构建任务配兵, 解析指定单位

        任务键 = f"{类型}:{文本[:48]}"
        if getattr(上下文, "_竞赛配兵失败任务键", "") == 任务键:
            上下文._部落竞赛配兵配置覆盖 = None
            上下文._竞赛配兵关键单位 = {}
            上下文._竞赛配兵任务键 = ""
            上下文._部落竞赛配兵任务类型 = ""
            self._日志(f"当前任务{类型}的配兵切换之前失败，保持原配兵继续打鱼")
            return False

        基准 = getattr(上下文, "_部落竞赛基准配兵配置", None)
        可用 = getattr(上下文, "_部落竞赛可用单位", {}) or {}
        临时配置, 原因 = 构建任务配兵(类型, 文本, 基准, _可用单位集合(可用))
        if not 临时配置:
            self._清除竞赛配兵(原因 or "没有可用的安全方案")
            self._日志(f"当前{类型}任务不切换配兵：{原因 or '没有可用方案'}")
            return False
        单位 = {"兵种": [], "法术": [], "攻城": []}
        if 类型 == "拆墙":
            单位["兵种"].append("炸弹人")
        else:
            解析 = 解析指定单位(文本, self.配置)
            if 解析:
                名称, 分区 = 解析
                单位.setdefault(分区, []).append(名称)
        上下文._部落竞赛配兵配置覆盖 = 临时配置
        上下文._竞赛配兵关键单位 = 单位
        上下文._竞赛配兵任务键 = 任务键
        上下文._竞赛配兵任务文本 = 文本
        上下文._部落竞赛配兵任务类型 = 类型
        上下文._本次运行已配兵签名 = None
        self._日志(f"当前任务为{类型}，临时配兵方案已确认，要求实际部署：{', '.join(sum(单位.values(), []))}")
        return True

    def _清除竞赛配兵(self, 原因: str) -> None:
        上下文 = self.上下文
        if isinstance(getattr(上下文, "_部落竞赛配兵配置覆盖", None), dict):
            self._日志(f"{原因}，恢复原配兵")
            上下文._本次运行已配兵签名 = None
        上下文._部落竞赛配兵配置覆盖 = None
        上下文._竞赛配兵关键单位 = {}
        上下文._竞赛配兵任务键 = ""
        上下文._竞赛配兵任务文本 = ""
        上下文._部落竞赛配兵任务类型 = ""
        上下文._竞赛配兵失败任务键 = ""

    def _计划进攻复查(self, 记录: dict, 结果: str) -> int | None:
        """按结果和任务进度预测下一次开面板的进攻计数；None 表示只看时间冷却。"""
        规则 = self.配置.get("进攻复查", {}) if isinstance(self.配置, dict) else {}
        # 统一按“已打完的场次”计，和 _已到检查时机 的比较口径一致。
        计数 = self._已完成进攻计数(记录, bool(getattr(self, "_本次进攻前", False)))
        if self._记录任务类型(记录) in {"拆墙", "指定兵种"}:
            # 动态配兵必须在任务完成或变更后的下一次进攻前撤回/重算。
            return 计数 + 1
        if 结果 == "已接任务":
            记录["进度基线"] = {"进度": 0, "进攻计数": 计数}
            return 计数 + 1  # 打一场后回来看速率
        if 结果 == "无可接任务":
            记录.pop("进度基线", None)
            return 计数 + int(规则.get("无任务复查场次", 2))
        if 结果 != "已有任务":
            return None
        进度 = getattr(self, "_进度", None)
        if not 进度:
            return 计数 + int(规则.get("无进度复查场次", 2))
        当前, 目标 = 进度
        基线 = 记录.get("进度基线") or {}
        try:
            基线进度 = int(基线.get("进度"))
            基线计数 = int(基线.get("进攻计数"))
        except (TypeError, ValueError):
            基线进度 = 基线计数 = None
        if 基线进度 is None or 当前 < 基线进度 or 基线计数 > 计数:
            记录["进度基线"] = {"进度": 当前, "进攻计数": 计数}
            return 计数 + 1
        场次 = 计数 - 基线计数
        增量 = 当前 - 基线进度
        if 场次 <= 0 or 增量 <= 0:
            return 计数 + int(规则.get("无进度复查场次", 2))
        剩余场次 = math.ceil((目标 - 当前) * 场次 / 增量)
        return 计数 + max(1, min(int(规则.get("最多间隔场次", 10)), 剩余场次))

    def _记录结果(self, 记录: dict, 结果: str, 冷却分钟: float) -> None:
        现在 = time.time()
        if 结果 == "无可接任务":
            冷却分钟 = min(float(冷却分钟), float(self.配置.get("进攻复查", {}).get("无任务复查分钟", 10)))
        记录.update({
            "时间": 现在,
            "结果": 结果,
            "下次检查时间": 现在 + max(1.0, float(冷却分钟)) * 60,
            "下次检查进攻计数": self._计划进攻复查(记录, 结果),
        })
        if self._本轮个人积分:
            记录["个人积分"] = list(self._本轮个人积分)
            记录["个人积分时间"] = 现在
        if 结果 == "已接任务" and self._本轮选择:
            记录["当前任务"] = self._本轮选择
            记录["当前任务时间"] = 现在
            记录["当前任务类型"] = self._本轮选择.split("（", 1)[0]
            记录["当前任务文本"] = self._本轮任务文本
            if self._当前任务卡文本:
                记录["当前任务卡文本"] = self._当前任务卡文本
            else:
                记录.pop("当前任务卡文本", None)
            记录.pop("当前任务进度", None)
        elif 结果 == "已有任务":
            进度 = getattr(self, "_进度", None)
            if 进度:
                记录["当前任务进度"] = [int(进度[0]), int(进度[1])]
            if not 记录.get("当前任务"):
                # 手动接的或上次没记下名字：界面仍要知道有进行中的任务。
                记录["当前任务"] = "进行中的任务"
                记录["当前任务时间"] = 现在
            if self._当前任务类型:
                记录["当前任务类型"] = self._当前任务类型
            if self._当前任务文本:
                记录["当前任务文本"] = self._当前任务文本
            if self._当前任务卡文本:
                记录["当前任务卡文本"] = self._当前任务卡文本
        elif 结果 in {"已满分", "入口不存在", "无可接任务", "可领奖"}:
            # 面板上已没有进行中的任务（做完了/没任务/活动结束）：界面不能再显示旧任务。
            for 键 in ("当前任务", "当前任务时间", "当前任务进度", "当前任务类型", "当前任务文本", "当前任务卡文本"):
                记录.pop(键, None)
        if 结果 not in {"入口不存在", "非主世界", "资源缺失", "资源未校准"}:
            记录["本期见过入口"] = self._现在().strftime("%Y-%m")
        self._写状态(记录)
        self._日志(f"本次结果：{结果}，约{int(冷却分钟)}分钟后再检查")

    def _提醒一次(self, 记录: dict, 类别: str, 文本: str) -> None:
        键 = f"已提醒{类别}"
        期号 = self._现在().strftime("%Y-%m")
        if 记录.get(键) == 期号:
            return
        记录[键] = 期号
        self._日志(文本)

    def _官方API满分(self, 记录: dict) -> bool:
        摘要 = self.官方摘要
        累计 = getattr(摘要, "部落竞赛累计积分", None) if 摘要 is not None else None
        上限 = int(getattr(self.上下文.设置, "部落竞赛个人积分上限", 0) or 0)
        满分, 新API记录 = 官方API判断满分(累计, 记录.get("官方API"), 上限, self._现在())
        if 新API记录:
            记录["官方API"] = 新API记录
        return bool(满分)

    # ---------------------------------------------------------------- 主流程
    def _流程(self) -> str:
        if not self._是主世界主页():
            self._日志("当前不在主世界主页，本轮不操作")
            return "非主世界"
        重试上限 = max(1, int(self._超时设置("入口重试次数", 2)))
        for 尝试 in range(重试上限):
            结果 = self._打开竞赛面板()
            if isinstance(结果, dict):
                return self._处理面板(结果)
            if 结果 != "入口异常":
                return 结果
            # 入口异常（点开的不是活动列表/部落竞赛面板）：已安全关闭回到主页才重试。
            if not self._是主世界主页():
                return "入口异常"
            if 尝试 + 1 < 重试上限:
                self._日志(f"入口确认失败，已回到主页，第{尝试 + 2}次尝试打开部落竞赛")
        self._日志(f"连续 {重试上限} 次没能进入部落竞赛面板，放弃本轮，回主页继续打鱼")
        return "入口异常"

    def _打开竞赛面板(self):
        """主页 → 活动列表 → 部落竞赛面板。成功返回面板 dict，否则返回结果字符串。

        每一步都要正面确认：活动列表要有『活动』标题+列表关闭 X；点『开启』后
        要有『部落竞赛』标题 OCR + 面板标题模板 + 关闭 X。点开的是别的活动/
        别的面板时保存现场截图，只点已确认且附近没有宝石/购买等字样的红 X
        关闭，返回『入口异常』交给上层重试或放弃。
        """
        图像 = self._截图()
        活动按钮 = self._匹配模板(图像, "活动按钮")
        if 活动按钮 is None:
            if not self._是主世界主页():
                self._日志("未找到活动按钮且当前页面非高置信主世界主页，按非主世界跳过")
                return "非主世界"
            self._日志("底栏没有找到活动按钮，跳过")
            self._记录活动按钮诊断(图像)
            return "入口不存在"
        if not self._点击(活动按钮, "活动按钮"):
            return "护栏阻止"
        self._日志("活动按钮已点击，确认活动列表")
        列表开始 = time.monotonic()
        列表秒 = self._超时设置("活动列表秒", 6)
        try:
            已确认 = self._等待(self._活动列表已打开, "活动列表", 步骤秒=列表秒)
            未确认原因 = f"{列表秒:g}秒内未确认"
        except 部落竞赛超时 as 异常:
            # 标题小区域 OCR 超时/上一次 OCR 未返回：和步骤超时同样处理
            # （写原因、存现场、安全关 X、记冷却）。停止请求/总超时照常上抛。
            if "OCR" not in str(异常):
                raise
            已确认 = None
            未确认原因 = f"标题OCR异常（{异常}）"
        if not 已确认:
            self._日志(f"活动列表{未确认原因}（实际{time.monotonic() - 列表开始:.1f}秒），关闭后按冷却稍后重试")
            self._保存入口现场("活动列表未确认")
            if self._是主世界主页():
                self._日志("点击活动按钮后仍在主页，活动列表没有打开")
                return "入口异常"
            if not self._安全关闭异常面板("活动列表未确认"):
                return "面板未确认"
            return "入口异常"
        # 活动列表已确认：让通用点击护栏不要把它当成意外弹窗关掉。
        self._设置面板标记(True)
        开启点 = self._找部落竞赛开启()
        if 开启点 is None:
            if self._活动列表已打开() is None and not self._是主世界主页():
                self._日志("活动列表已失去确认且不在主世界主页，不判定活动结束")
                return "非主世界"
            self._日志("活动列表里没有部落竞赛（活动可能已结束）")
            return "入口不存在"
        if not self._点击(开启点, "部落竞赛开启"):
            return "护栏阻止"
        面板 = self._等待(self._识别竞赛面板, "部落竞赛面板")
        if not 面板:
            self._保存入口现场("部落竞赛面板未确认")
            self._日志("点『开启』后没有确认到部落竞赛面板（可能点开了别的活动），安全关闭后重试")
            if not self._安全关闭异常面板("部落竞赛面板未确认"):
                return "面板未确认"
            return "入口异常"
        return 面板

    def _安全关闭异常面板(self, 原因: str) -> bool:
        """关闭点错的活动/面板回到主世界主页；只点模板确认的红 X。

        X 附近 OCR 出现『立即/跳过/重置/宝石/购买/商店』等字样或附近匹配到
        宝石图标时不点；找不到 X 不盲点。最多关 3 层，回到主页返回 True。
        """
        for _ in range(3):
            if self._是主世界主页():
                return True
            try:
                self._检查总超时()
            except 部落竞赛超时:
                return False
            图像 = self._截图()
            关闭点 = self._匹配模板(图像, "关闭按钮") or self._匹配模板(图像, "活动列表关闭")
            if 关闭点 is None:
                self._日志(f"{原因}：没有找到可确认的关闭 X，不盲点")
                return self._等待(self._是主世界主页, "回到主页") is not None
            x, y = int(关闭点[0]), int(关闭点[1])
            禁点 = self._关闭X附近禁点(图像, (x, y))
            if 禁点:
                self._日志(f"{原因}：关闭 X 附近出现『{禁点}』，不点击")
                return False
            try:
                if not self._点击已确认关闭X((x, y), "关闭异常面板"):
                    return False
            except 部落竞赛超时:
                return False
            self._延时(800)
        return self._是主世界主页()

    def _卡片区(self, 扩展: int = 0) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.配置.get("面板", {}).get("卡片区ROI") or (0, 0, 800, 600)
        return (max(0, x1 - 扩展), max(0, y1 - 扩展), min(800, x2 + 扩展), min(600, y2 + 扩展))

    def _关闭X附近禁点(self, 图像, 点: tuple[int, int]) -> str | None:
        """红 X 附近出现宝石/购买/跳过/重置/立即等字样或宝石图标时返回原因。"""
        x, y = int(点[0]), int(点[1])
        附近 = (max(0, x - 160), max(0, y - 40), min(800, x + 60), y + 120)
        try:
            项列表 = self._OCR(图像, 附近)
        except 部落竞赛超时 as 异常:
            if "OCR" not in str(异常):
                raise
            # OCR 卡住时仍要能关掉已打开的列表/面板回主页；只剩宝石图标模板做复核。
            self._日志("OCR 不可用，关闭前只用宝石图标模板复核 X 附近")
            项列表 = []
        禁点 = 含禁点文字(拼接文本(区域文字(项列表, 附近)), self.配置)
        if 禁点 is None and self._匹配模板(图像, "宝石图标", 附近) is not None:
            禁点 = "宝石图标"
        return 禁点

    def _保存入口现场(self, 原因: str, 图像=None) -> None:
        """入口确认失败时把当前帧存到 数据集/待命现场，下次有证据可查；不抛异常、不删旧图。

        传入 ``图像`` 时保存判定用的那一帧，不再重新截图。
        """
        try:
            import cv2

            if 图像 is None:
                图像 = self._截图()
            if 图像 is None or not hasattr(图像, "shape"):
                return
            目录 = Path(getattr(self.上下文, "待命现场目录", None) or (Path("数据集") / "待命现场"))
            目录.mkdir(parents=True, exist_ok=True)
            上限 = int(self.配置.get("入口现场最多张数", 30))
            if sum(1 for _ in 目录.glob("clan_entry_*.png")) >= 上限:
                self._日志(f"入口现场截图已达上限{上限}张，本次不保存（不会删除旧图）")
                return
            时间戳 = self._现在().strftime("%Y%m%d_%H%M%S")
            路径 = 目录 / f"clan_entry_{时间戳}_{int(time.time() * 1000) % 1000:03d}_{原因}.png"
            成功, 数据 = cv2.imencode(".png", 图像)
            if 成功:
                路径.write_bytes(数据.tobytes())
                self._日志(f"{原因}：已保存现场截图 {路径}")
        except Exception as 异常:
            self._日志(f"保存入口现场截图失败（不影响流程）：{异常}")

    def _活动列表视觉确认(self) -> bool:
        """页面识别器的快速视觉特征（居中高亮活动列表+右侧绿色入口+右上红X）。"""
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return False
        try:
            结果 = 识别(强制=True)
        except Exception:
            return False
        if getattr(结果, "页面", "") != "活动弹窗":
            return False
        try:
            return float(getattr(结果, "可信度", 0) or 0) >= 0.90
        except (TypeError, ValueError):
            return False

    def _活动列表已打开(self):
        """确认活动列表：先用视觉特征+关闭 X 模板（不 OCR），不行再只 OCR 标题小区域。

        2026-11-26 实机：原来每次轮询都整屏 OCR 活动列表（文字最多的一页），
        单次确认 164~251 秒；面板/详情等其它步骤只要 1~4 秒。
        """
        图像 = self._截图()
        if self._匹配模板(图像, "活动列表关闭") is None:
            return None
        if self._活动列表视觉确认():
            return True
        列表 = self.配置.get("活动列表", {})
        标题区 = 列表.get("标题ROI") or (300, 25, 500, 65)
        # 标题小区域 OCR 也只给几秒：确认活动列表整体要在几秒内结束。
        self._OCR临时上限秒 = self._超时设置("活动列表OCR秒", 5)
        try:
            项列表 = self._OCR(图像, 标题区)
        finally:
            self._OCR临时上限秒 = None
        if 查找关键词(项列表, 列表.get("标题关键词", ["活动"]), 标题区) is None:
            return None
        return True

    def _找部落竞赛开启(self) -> tuple[int, int] | None:
        列表 = self.配置.get("活动列表", {})
        for 次数 in range(int(列表.get("最多滑动次数", 4)) + 1):
            self._检查总超时()
            图像 = self._截图()
            # 标题、『剩余时间』和禁点检查都只看列表区，不必整屏 OCR。
            项列表 = self._OCR(图像, 列表.get("列表ROI"))
            标题 = self._找竞赛标题(项列表, 列表)
            if 标题 is not None:
                # 『开启』两个字 OCR 读不出来：用模板在标题下方同一张活动卡
                # 的横带里找按钮；横带里的文字同时做禁点检查。
                _, dy1, _, dy2 = 列表.get("开启相对标题ROI", [0, -10, 0, 170])
                列表区 = 列表.get("列表ROI", (0, 0, 800, 600))
                下沿 = min(列表区[3], 标题.框[1] + dy2)
                # 不越过下一张活动卡的『剩余时间』标题栏，避免把别的活动的绿色按钮当成『开启』。
                下一卡 = [
                    项.框[1] for 项 in 区域文字(项列表, 列表区)
                    if "剩余时间" in 项.规范 and 项.框[1] > 标题.框[3] + 20
                ]
                if 下一卡:
                    下沿 = min(下沿, min(下一卡) - 5)
                区域 = (列表区[0], 标题.框[1] + dy1, 列表区[2], 下沿)
                卡片文本 = 拼接文本(区域文字(项列表, 区域))
                禁点 = 含禁点文字(卡片文本, self.配置)
                if 禁点:
                    self._日志(f"部落竞赛活动卡出现『{禁点}』，不点击")
                    return None
                模板点 = self._匹配模板(图像, "开启按钮", 区域)
                if 模板点 is not None:
                    return 模板点
                if 标题.框[1] + dy2 <= 列表区[3]:
                    self._日志("找到部落竞赛但开启按钮模板未确认，不点击")
                    return None
                # 按钮还在列表下沿外面，再滑一次。
            if 次数 < int(列表.get("最多滑动次数", 4)):
                self._滑动(列表.get("滑动", [400, 450, 400, 150]))
                self._延时(600)
        return None

    @staticmethod
    def _找竞赛标题(项列表: list[文字项], 列表: dict) -> 文字项 | None:
        """活动列表里的『部落竞赛』标题；OCR 常把『競』读错，用正则兜底。"""
        区域 = 列表.get("列表ROI")
        候选 = [项 for 项 in 项列表 if 区域 is None or 在区域内(项.中心, 区域)]
        关键词 = [规范文本(词) for 词 in 列表.get("竞赛关键词", ["部落竞赛"])]
        正则 = 列表.get("竞赛正则", "部落.赛")
        命中 = [
            项 for 项 in 候选
            if any(词 in 项.规范 for 词 in 关键词) or (正则 and re.search(正则, 项.规范))
        ]
        return min(命中, key=lambda 项: 项.框[1]) if 命中 else None

    def _识别竞赛面板(self):
        """先用面板标题/关闭 X 模板和标题小区域 OCR 确认，确认后才整帧 OCR 一次面板内容。

        内容 OCR 保留整帧：个人积分、进度、进行中、以及位置不固定的“已满分/可领奖”
        横幅都要从同一份文字里判断；每次开面板只做这一次（实机 1~4 秒），仍受 OCR 限时保护。
        """
        图像 = self._截图()
        面板 = self.配置.get("面板", {})
        if self._匹配模板(图像, "面板标题") is None:
            return None
        if self._匹配模板(图像, "关闭按钮") is None:
            return None
        标题区 = 面板.get("标题ROI")
        if 查找关键词(self._OCR(图像, 标题区), 面板.get("标题关键词", ["部落竞赛"]), 标题区) is None:
            return None
        return {"图像": 图像, "文字": self._OCR(图像)}

    def _处理面板(self, 面板: dict) -> str:
        配置 = self.配置
        项列表 = 面板["文字"]
        积分区 = 配置.get("面板", {}).get("个人积分ROI")
        个人 = 解析个人积分(拼接文本(区域文字(项列表, 积分区)) if 积分区 else "")
        if 个人:
            self._本轮个人积分 = (int(个人[0]), int(个人[1]))
            self._日志(f"个人积分 {个人[0]}/{个人[1]}")
            if 个人[0] >= 个人[1]:
                return "已满分"
        全文 = 拼接文本(项列表)
        if any(规范文本(词) in 全文 for 词 in 配置.get("OCR", {}).get("已满分关键词", [])):
            return "已满分"
        if any(规范文本(词) in 全文 for 词 in 配置.get("OCR", {}).get("可领奖关键词", []) if 词):
            self._日志("面板显示竞赛已结束/可以领奖；只提醒，不点任何领奖按钮")
            return "可领奖"
        if self._匹配模板(面板["图像"], "已满分") is not None:
            return "已满分"
        self._进度 = self._读取进度(项列表)
        if self._进度 and self._进度[0] >= self._进度[1]:
            self._日志(f"当前任务进度 {self._进度[0]}/{self._进度[1]} 已完成，立即挑选新任务")
        elif self._存在进行中任务(面板["图像"], 项列表):
            记录 = self._读状态()
            缓存类型 = self._记录任务类型(记录)
            缓存文本 = str(记录.get("当前任务文本", "") or "")
            缓存卡文本 = str(记录.get("当前任务卡文本", "") or "")
            当前文本 = self._读取当前任务卡文本(项列表)
            if not 当前文本:
                # 本轮读不到卡文本：恢复基准阵容，但不改记录，下轮读到后再比对。
                self._清除竞赛配兵("进行中任务卡文本无法确认")
                self._日志("进行中任务卡文本无法确认，不沿用缓存任务类型")
            elif not 缓存卡文本 or not self._任务卡文本匹配(当前文本, 缓存卡文本):
                # 与接任务时记下的卡文本对不上（或没有基准）：旧类型/详情文本一律作废，
                # 只按当前卡文本重新识别；识别不出受支持类型就记为“未知”，避免下轮旧类型回流。
                重新识别 = 识别任务类型(
                    当前文本, self.配置, self._阵容签名(),
                    getattr(self.上下文, "_部落竞赛可用单位", {}) or {},
                )
                新类型 = 重新识别 if 重新识别 in {"拆墙", "指定兵种"} else "未知"
                self._当前任务类型 = 新类型
                self._当前任务文本 = 当前文本
                self._当前任务卡文本 = 当前文本
                原因 = "进行中任务卡与缓存不一致" if 缓存卡文本 else "进行中任务卡没有比对基准"
                self._日志(f"{原因}，按当前卡文本重新识别为：{新类型}")
                if 新类型 in {"拆墙", "指定兵种"}:
                    self._同步竞赛配兵(新类型, 当前文本)
                else:
                    self._清除竞赛配兵(原因)
            else:
                self._当前任务类型 = 缓存类型
                self._当前任务文本 = 缓存文本
                self._当前任务卡文本 = 缓存卡文本
                if 缓存类型 in {"拆墙", "指定兵种"}:
                    self._同步竞赛配兵(缓存类型, 缓存文本 or 当前文本)
                else:
                    self._清除竞赛配兵("当前任务不是受支持的动态配兵任务")
            进度说明 = f"（进度 {self._进度[0]}/{self._进度[1]}）" if self._进度 else ""
            self._日志(f"已有进行中的任务{进度说明}，交给打鱼完成")
            return "已有任务"

        self._清除竞赛配兵("当前没有进行中的动态任务")

        启用 = [名 for 名 in (getattr(self.上下文.设置, "部落竞赛任务白名单", None) or [])]
        if not 启用:
            self._日志("白名单为空，不接任务")
            return "无可接任务"

        self._扫描中止原因 = None
        候选列表 = self._扫描任务卡()
        self._保存详情超时卡位(候选列表)
        if self._扫描中止原因 == "详情超时":
            # 连续多张卡点开后都等不到详情：画面/识别状态不可信，停手不再点任何卡，
            # 交给 执行() 走安全关闭回主页，按『详情超时』冷却后再来。
            self._日志("连续多张任务卡详情超时，本轮不再点击任务卡，关闭面板交给打鱼")
            return "详情超时"
        for 候选 in 候选列表:
            状态 = "冷却" if 候选.冷却 else (f"禁点({候选.禁点原因})" if 候选.禁点原因 else (候选.类型 or "不在白名单"))
            self._日志(f"任务卡 页{候选.页 + 1}{候选.位置}：{状态}，{候选.积分 or '?'}分；{候选.文本[:40]}")
        跳过位置: set[tuple[int, tuple[int, int]]] = set()
        失败原因: list[str] = []
        while True:
            self._检查总超时()
            可选候选 = [
                候选 for 候选 in 候选列表
                if (候选.页, tuple(候选.位置)) not in 跳过位置
            ]
            最佳 = 选择任务(可选候选, 启用, 配置)
            if 最佳 is None:
                if not 失败原因:
                    if self._扫描中止原因 == "扫描未完成":
                        self._日志("时间预算内未扫完任务卡且已读卡片中没有可接任务，关闭面板交给打鱼")
                        return "扫描未完成"
                    self._日志("没有符合白名单的可接任务")
                    return "无可接任务"
                if "复核不一致" in 失败原因 and "护栏阻止" not in 失败原因:
                    return "复核不一致"
                if "护栏阻止" in 失败原因:
                    return "护栏阻止"
                if "详情超时" in 失败原因 and "超时" not in 失败原因:
                    return "详情超时"
                return "超时"
            self._日志(f"选择 {最佳.类型}（{最佳.积分 or '?'}分）")
            结果 = self._开始任务(最佳)
            if 结果 == "已接任务":
                self._本轮选择 = f"{最佳.类型}（{最佳.积分 or '?'}分）"
                self._本轮任务文本 = 最佳.文本
                self._当前任务类型 = 最佳.类型 or ""
                self._当前任务文本 = 最佳.文本
                self._当前任务卡文本 = self._读取已接任务卡文本()
                if 最佳.类型 in {"拆墙", "指定兵种"}:
                    self._同步竞赛配兵(最佳.类型, 最佳.文本)
                else:
                    self._清除竞赛配兵("新任务不需要临时配兵")
                return "已接任务"
            if 结果 == "超时":
                # 已点击『开始』但确认超时：禁止再盲点其他卡片，直接停手
                return "超时"
            if 结果 == "详情超时":
                # 复核时点开选中卡却等不到详情：面板状态不可信，不再顺延去点其他卡
                self._日志(f"选中卡 {最佳.类型}（{最佳.积分 or '?'}分）复核时详情超时，停手不再点击其他卡")
                return "详情超时"
            跳过位置.add((最佳.页, tuple(最佳.位置)))
            失败原因.append(结果)
            self._日志(f"候选 {最佳.类型}（{最佳.积分 or '?'}分）尝试结果={结果}，跳过并顺延次优候选")

    def _阵容签名(self) -> str:
        """最近一场进攻识别到的兵栏签名；还没打过仗时为空，指定兵种任务一律不接。"""
        return str(getattr(self.上下文, "本场阵容签名", "") or "")

    def _读取进度(self, 项列表: list[文字项]) -> tuple[int, int] | None:
        """卡片区里的 a/b 就是进行中任务的进度（个人积分和主页建筑工人计数都在卡片区外）。"""
        卡片区 = self.配置.get("面板", {}).get("卡片区ROI")
        候选 = []
        for 项 in (区域文字(项列表, 卡片区) if 卡片区 else []):
            匹配 = re.fullmatch(r"(\d{1,5})/(\d{1,5})", 项.规范)
            if not 匹配:
                continue
            当前, 目标 = int(匹配.group(1)), int(匹配.group(2))
            if 目标 >= 1 and 当前 <= 目标:
                候选.append((项.中心[1], 项.中心[0], 当前, 目标))
        if not 候选:
            return None
        _, _, 当前, 目标 = min(候选)
        return 当前, 目标

    def _读取当前任务卡文本(self, 项列表: list[文字项]) -> str | None:
        """用进度定位进行中卡；卡面无文案时只读打开该卡的详情，不猜缓存任务。"""
        卡片区 = self.配置.get("面板", {}).get("卡片区ROI")
        if not 卡片区:
            return None
        进度项 = []
        for 项 in 区域文字(项列表, 卡片区):
            匹配 = re.fullmatch(r"(\d{1,5})/(\d{1,5})", 项.规范)
            if not 匹配:
                continue
            当前, 目标 = int(匹配.group(1)), int(匹配.group(2))
            if 目标 >= 1 and 当前 <= 目标:
                进度项.append(项)
        if not 进度项:
            return None
        活动进度 = min(进度项, key=lambda 项: (项.中心[1], 项.中心[0]))
        页面 = self.配置.get("面板", {}).get("页") or []
        卡心 = [tuple(map(int, 点)) for 点 in (页面[0].get("卡片", []) if 页面 else [])]
        if not 卡心:
            return None
        进度x, 进度y = 活动进度.中心
        卡心x, 卡心y = min(
            卡心,
            key=lambda 点: abs(点[0] - 进度x) + abs(点[1] - 进度y),
        )
        卡位 = (卡心x, 卡心y)

        # 进行中卡的弹窗可能仍开着（开始后按钮变成“放弃”）。优先从弹窗读目标，
        # 读完安全收起，避免把详情内容当成卡面文字或把它留给后续流程。
        当前详情 = self._提取进行中任务详情文本(项列表)
        if 当前详情:
            try:
                self._关闭详情()
            except Exception as 异常:
                self._清除竞赛配兵("进行中任务详情无法安全收起")
                self._日志(f"进行中任务详情收起失败，不沿用缓存任务类型：{异常}")
                return None
            return 当前详情

        半宽 = int(self.配置.get("面板", {}).get("卡片文本半宽", 55))
        半高 = int(self.配置.get("面板", {}).get("卡片文本半高", 70))
        卡内文字 = []
        for 项 in 区域文字(项列表, 卡片区):
            if 项 is 活动进度 or re.fullmatch(r"\d{1,5}/\d{1,5}", 项.规范):
                continue
            if 解析积分([项]) is not None:
                continue
            x, y = 项.中心
            if abs(x - 卡心x) <= 半宽 and abs(y - 卡心y) <= 半高:
                卡内文字.append(项)
        文本 = 拼接文本(sorted(卡内文字, key=lambda 项: (项.中心[1], 项.中心[0])))
        if 文本:
            return 文本

        # 进行中任务卡面通常只显示图标和 a/b 进度，不显示目标句。点击该卡只打开详情，
        # 绝不点击“放弃”；详情文字必须读到且与缓存同口径比对后才允许沿用动态配兵。
        return self._读取当前任务卡详情文本(卡位)

    def _提取进行中任务详情文本(self, 项列表: list[文字项]) -> str | None:
        """从已打开的进行中任务详情里提取稳定目标文字，去掉积分、进度和倒计时。"""
        卡片区 = self._卡片区(扩展=60)
        放弃词 = self.配置.get("OCR", {}).get("已接确认关键词", ["放弃"])
        操作项 = 查找关键词(项列表, 放弃词, 卡片区)
        if 操作项 is None:
            # 现场 OCR 有时只识出红色按钮文字的首字“放”；仅接受单字项，避免命中目标句。
            操作项 = next(
                (项 for 项 in 区域文字(项列表, 卡片区) if 项.规范 in {"放", "弃"}),
                None,
            )
        if 操作项 is None:
            return None
        dx1, dy1, dx2, dy2 = self.配置.get("面板", {}).get("详情相对开始文字", [-165, -180, 85, 50])
        区域 = (
            操作项.框[0] + int(dx1), 操作项.框[1] + int(dy1),
            操作项.框[2] + int(dx2), 操作项.框[3] + int(dy2),
        )
        区域项 = 区域文字(项列表, 区域)
        目标项 = []
        for 项 in 区域项:
            if 项 is 操作项 or re.fullmatch(r"\d{1,5}/\d{1,5}", 项.规范):
                continue
            if 解析积分([项]) is not None:
                continue
            if re.fullmatch(r"\d*(?:天|日|小时|小時|时|分钟|分鐘|秒)", 项.规范):
                continue
            目标项.append(项)
        文本 = 拼接文本(sorted(目标项, key=lambda 项: (项.中心[1], 项.中心[0])))
        return 文本 or None

    def _识别当前任务详情(self) -> str | None:
        图像 = self._截图()
        项列表 = self._OCR(图像, self._卡片区(扩展=60))
        return self._提取进行中任务详情文本(项列表)

    def _读取当前任务卡详情文本(self, 卡位: tuple[int, int]) -> str | None:
        已打开 = False
        读取结果 = None
        关闭失败 = False
        try:
            if not self._点击(卡位, "进行中任务卡详情"):
                return None
            已打开 = True
            结果 = self._等待(self._识别当前任务详情, "进行中任务详情")
            读取结果 = str(结果 or "").strip() or None
        except 部落竞赛超时:
            self._清除竞赛配兵("进行中任务详情读取超时")
            raise
        except Exception as 异常:
            self._日志(f"打开或读取进行中任务详情失败，不沿用缓存任务类型：{异常}")
        finally:
            if 已打开:
                try:
                    self._关闭详情()
                except Exception as 异常:
                    关闭失败 = True
                    self._清除竞赛配兵("进行中任务详情无法安全收起")
                    self._日志(f"进行中任务详情收起失败：{异常}")
        return None if 关闭失败 else 读取结果

    def _读取已接任务卡文本(self) -> str:
        """接任务后立即按面板卡片口径记一份卡文本，作为进行中任务的比对基准。

        卡面没有目标文字时，通过进行中卡的“放弃”详情读取同一份稳定目标文本；
        读不到就返回空串，后续仍按保守规则恢复基准阵容。
        """
        try:
            for 次 in range(2):
                图像 = self._截图()
                卡片区 = self.配置.get("面板", {}).get("卡片区ROI")
                # 只 OCR 卡片区（与 _任务已开始 同口径），面板整帧 OCR 每次开面板只做一次。
                项列表 = self._OCR(图像, 卡片区)
                卡文 = self._读取当前任务卡文本(项列表)
                if 卡文:
                    return 卡文
                放弃词 = self.配置.get("OCR", {}).get("已接确认关键词", ["放弃"])
                if 查找关键词(项列表, 放弃词, 卡片区):
                    if 次 == 0:
                        self._关闭详情()
                        continue
                    return ""
                return ""
        except Exception as 异常:
            self._日志(f"接任务后读取任务卡文本失败：{异常}")
        return ""

    def _任务卡文本匹配(self, 当前文本: str, 缓存文本: str) -> bool:
        当前 = 规范文本(纠正OCR文本(当前文本, self.配置))
        缓存 = 规范文本(纠正OCR文本(缓存文本, self.配置))
        return bool(当前 and 缓存 and 当前 == 缓存)

    def _存在进行中任务(self, 图像, 项列表: list[文字项]) -> bool:
        卡片区 = self.配置.get("面板", {}).get("卡片区ROI")
        文本 = 拼接文本(区域文字(项列表, 卡片区) if 卡片区 else 项列表)
        if any(规范文本(词) in 文本 for 词 in self.配置.get("OCR", {}).get("进行中关键词", []) if 词):
            return True
        if self._卡片已变灰(图像):
            return True
        return self._匹配模板(图像, "进行中") is not None

    def _卡片已变灰(self, 图像) -> bool:
        """接了任务后其余卡片全部变成灰色；用第一页卡片图标的饱和度判断。"""
        规则 = self.配置.get("面板", {}).get("进行中灰卡") or {}
        页列表 = self.配置.get("面板", {}).get("页") or []
        if not 规则 or not 页列表 or 图像 is None or not hasattr(图像, "shape"):
            return False
        try:
            import cv2
            hsv = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
        except Exception:
            return False
        dx1, dy1, dx2, dy2 = 规则.get("采样相对卡心", [-30, -45, 30, 5])
        阈值 = float(规则.get("饱和度阈值", 35))
        灰卡 = 总数 = 0
        for x, y in 页列表[0].get("卡片", []):
            块 = hsv[max(0, y + dy1):y + dy2, max(0, x + dx1):x + dx2, 1]
            if 块.size == 0:
                continue
            总数 += 1
            灰卡 += float(块.mean()) < 阈值
        return 总数 > 0 and 灰卡 >= int(规则.get("最少灰卡数", 5))

    def _单卡已变灰(self, 图像, 位置: tuple[int, int]) -> bool:
        """点开卡片前检测该卡片中心是否呈低饱和灰态（冷却/进行中锁定），避免白等 8 秒超时。"""
        规则 = self.配置.get("面板", {}).get("进行中灰卡") or {}
        if not 规则 or 图像 is None or not hasattr(图像, "shape"):
            return False
        try:
            import cv2
            import numpy as np

            高, 宽 = 图像.shape[:2]
            dx1, dy1, dx2, dy2 = 规则.get("采样相对卡心", [-30, -45, 30, 5])
            x, y = int(位置[0]), int(位置[1])
            y1 = max(0, y + int(dy1))
            y2 = min(高, y + int(dy2))
            x1 = max(0, x + int(dx1))
            x2 = min(宽, x + int(dx2))
            块 = 图像[y1:y2, x1:x2]
            if 块.size == 0 or getattr(块, "ndim", 0) != 3:
                return False
            hsv = cv2.cvtColor(块, cv2.COLOR_BGR2HSV)
            平均饱和度 = float(np.mean(hsv[:, :, 1]))
            平均亮度 = float(np.mean(hsv[:, :, 2]))
            阈值 = float(规则.get("饱和度阈值", 35))
            # 排除全黑测试占位图，仅对可见灰色卡片跳过
            return 平均饱和度 < 阈值 and 平均亮度 >= 40.0
        except Exception:
            return False

    def _卡片区指纹(self, 图像):
        """提取卡片区灰度缩略图，用于翻页后画面是否实际滚动的去重比较。"""
        if 图像 is None or not hasattr(图像, "shape") or getattr(图像, "ndim", 0) < 2:
            return None
        try:
            import cv2
            import numpy as np

            x1, y1, x2, y2 = self.配置.get("面板", {}).get("卡片区ROI", (250, 90, 720, 470))
            高, 宽 = 图像.shape[:2]
            区域 = 图像[max(0, int(y1)):min(高, int(y2)), max(0, int(x1)):min(宽, int(x2))]
            if 区域.size == 0:
                return None
            灰度 = cv2.cvtColor(区域, cv2.COLOR_BGR2GRAY) if getattr(区域, "ndim", 0) == 3 else 区域
            if float(np.std(灰度)) < 1.0:
                return None
            return cv2.resize(灰度, (96, 72), interpolation=cv2.INTER_AREA)
        except Exception:
            return None

    @staticmethod
    def _卡片区无变化(上页指纹, 本页指纹) -> bool:
        if 上页指纹 is None or 本页指纹 is None:
            return False
        try:
            import cv2
            return float(cv2.absdiff(上页指纹, 本页指纹).mean()) < 3.0
        except Exception:
            return False

    def _切换到页(self, 当前页: int, 目标页: int) -> int:
        页列表 = self.配置.get("面板", {}).get("页", [])
        if 目标页 == 当前页:
            return 当前页
        if 目标页 < 当前页:
            回滑 = self.配置.get("面板", {}).get("回到第一页滑动")
            if 回滑:
                for _ in range(max(1, 当前页 - 目标页)):
                    self._滑动(回滑)
                    self._延时(600)
            当前页 = 0
        for 页号 in range(当前页 + 1, 目标页 + 1):
            滑动 = 页列表[页号].get("滑动")
            if 滑动:
                self._滑动(滑动)
                self._延时(600)
        self._当前页 = 目标页
        return 目标页

    def _读取详情(self, 页: int, 位置: tuple[int, int]) -> 任务候选:
        """点开一张卡，返回详情识别结果；不点击任何按钮。"""
        候选 = 任务候选(页=页, 位置=tuple(位置), 类型=None, 积分=None)
        if not self._点击(位置, "任务卡"):
            候选.禁点原因 = "点击护栏"
            return 候选
        详情 = self._等待(lambda: self._识别详情(), "任务详情")
        if not 详情:
            # 没有开始按钮：可能是冷却中的卡或识别不清，都不接。
            图像 = self._截图()
            卡片区 = self._卡片区()
            文本 = 拼接文本(区域文字(self._OCR(图像, 卡片区), 卡片区))
            候选.冷却 = True
            候选.详情超时 = True
            候选.文本 = 文本
            禁点 = 含禁点文字(文本, self.配置)
            if 禁点:
                候选.禁点原因 = 禁点
            return 候选
        候选.文本 = 详情["文本"]
        候选.积分 = 详情["积分"]
        候选.开始点 = 详情["开始点"]
        候选.禁点原因 = 详情["禁点"]
        候选.冷却 = 详情["冷却"]
        不接 = 命中不接名单(详情["文本"], self.配置)
        if 不接 and not 候选.禁点原因:
            候选.禁点原因 = f"不接名单:{不接}"
        可用单位 = getattr(self.上下文, "_部落竞赛可用单位", {}) or {}
        候选.类型 = 识别任务类型(详情["文本"], self.配置, self._阵容签名(), 可用单位)
        if 候选.类型 is None and not 候选.禁点原因:
            候选.禁点原因 = 动态任务跳过原因(详情["文本"], self.配置, 可用单位)
        return 候选

    def _识别详情(self):
        图像 = self._截图()
        卡片区 = self._卡片区()
        # 详情框相对『开始』最多下探约 50 像素，OCR 区域在卡片区外多留一圈。
        项列表 = self._OCR(图像, self._卡片区(扩展=60))
        开始 = 查找关键词(项列表, self.配置.get("OCR", {}).get("开始关键词", ["开始"]), 卡片区)
        if 开始 is None:
            return None
        dx1, dy1, dx2, dy2 = self.配置.get("面板", {}).get("详情相对开始文字", [-165, -180, 85, 50])
        区域 = (开始.框[0] + dx1, 开始.框[1] + dy1, 开始.框[2] + dx2, 开始.框[3] + dy2)
        区域项 = [项 for 项 in 区域文字(项列表, 区域) if 项 is not 开始]
        文本 = 拼接文本(区域项)
        禁点 = 含禁点文字(文本 + 开始.规范, self.配置)
        if 禁点 is None and self._匹配模板(图像, "宝石图标", 区域) is not None:
            禁点 = "宝石图标"
        冷却 = any(规范文本(词) in 文本 for 词 in self.配置.get("OCR", {}).get("冷却关键词", []) if 词)
        模板点 = self._匹配模板(图像, "开始按钮", 区域)
        开始点 = None
        if 模板点 is not None and abs(模板点[0] - 开始.中心[0]) <= 45 and abs(模板点[1] - 开始.中心[1]) <= 30:
            开始点 = 模板点
        return {
            "文本": 文本,
            "积分": 解析积分(区域项),
            "开始点": 开始点,
            "禁点": 禁点,
            "冷却": 冷却,
        }

    def _关闭详情(self) -> None:
        空白点 = self.配置.get("面板", {}).get("空白点")
        if 空白点:
            self._点击(tuple(空白点), "空白处关闭详情")
            self._延时(400)

    def _扫描任务卡(self) -> list[任务候选]:
        """逐页找出任务卡并点开读详情。

        任务卡的数量和顺序每次都会变（接任务后进行中的卡会挪到左上角，
        卡数也可能是 13 张），所以卡片位置按卡下方的积分数字现找；
        找不到积分数字时才退回资源里写死的位置。同一任务在相邻两页都
        露出来时只读一次；灰卡直接跳过，翻页无位移则提前结束。
        """
        页列表 = self.配置.get("面板", {}).get("页", [])
        候选列表: list[任务候选] = []
        已读: set[tuple[str, int | None]] = set()
        当前页 = 0
        上页指纹 = None
        连续超时 = 0
        超时上限 = max(1, int(self._超时设置("连续详情超时上限", 3)))
        # 预留不超过总超时的四分之一，避免很短的总超时（测试/手动调小）一开扫就放弃。
        预留秒 = min(self._超时设置("选择预留秒", 90), self._超时设置("总流程秒", 180) / 4)
        已跳过卡位 = self._今日详情超时卡位()
        for 页号, 页 in enumerate(页列表):
            self._检查总超时()
            if self._扫描预算不足(预留秒):
                self._扫描中止原因 = "扫描未完成"
                break
            当前页 = self._切换到页(当前页, 页号)
            页面图像 = self._截图()
            本页指纹 = self._卡片区指纹(页面图像)
            if 页号 > 0 and self._卡片区无变化(上页指纹, 本页指纹):
                self._日志(f"翻页到第{页号 + 1}页后卡片区无明显变化，已滑到底提前结束")
                break
            if 本页指纹 is not None:
                上页指纹 = 本页指纹
            位置列表 = 识别卡片位置(self._OCR(页面图像, self._卡片区()), self.配置) or [
                tuple(位置) for 位置 in 页.get("卡片", [])
            ]
            for 位置 in 位置列表:
                卡片坐标 = tuple(位置)
                if self._扫描预算不足(预留秒):
                    # 留够『复核+开始+确认+关面板』的时间：用已读到的卡先挑，
                    # 不再把整个总超时耗在扫卡上（rc154 实机 12 张卡扫 7 分钟没挑过一次）。
                    self._日志(f"扫描任务卡剩余时间不足 {int(预留秒)} 秒，停止扫描，用已读到的 {len(候选列表)} 张卡挑选")
                    self._扫描中止原因 = "扫描未完成"
                    break
                if self._卡位已跳过(已跳过卡位, 页号, 卡片坐标):
                    self._日志(f"跳过今日详情超时过的卡 页{页号 + 1}{卡片坐标}")
                    候选列表.append(
                        任务候选(页=页号, 位置=卡片坐标, 类型=None, 积分=None, 冷却=True)
                    )
                    continue
                if self._单卡已变灰(页面图像, 卡片坐标):
                    self._日志(f"跳过灰卡/冷却卡 页{页号 + 1}{卡片坐标}")
                    候选列表.append(
                        任务候选(页=页号, 位置=卡片坐标, 类型=None, 积分=None, 冷却=True)
                    )
                    continue
                候选 = self._读取详情(页号, 卡片坐标)
                self._关闭详情()
                if 候选.详情超时:
                    连续超时 += 1
                    候选列表.append(候选)
                    if 连续超时 >= 超时上限:
                        self._日志(f"连续 {连续超时} 张任务卡详情超时，停止扫描")
                        self._扫描中止原因 = "详情超时"
                        break
                    continue
                连续超时 = 0
                键 = (候选.文本, 候选.积分)
                if 候选.文本 and 键 in 已读:
                    continue
                已读.add(键)
                候选列表.append(候选)
            if self._扫描中止原因:
                break
        self._当前页 = 当前页
        return 候选列表

    def _扫描预算不足(self, 预留秒: float) -> bool:
        return self._截止 - self._时钟() < float(预留秒)

    def _今日详情超时卡位(self) -> list[tuple[int, int, int]]:
        记录 = (getattr(self, "_记录", None) or {}).get("详情超时卡") or {}
        if not isinstance(记录, dict) or 记录.get("日期") != self._现在().strftime("%Y-%m-%d"):
            return []
        卡位 = []
        for 项 in 记录.get("卡位") or []:
            try:
                页, x, y = (int(值) for 值 in 项)
            except (TypeError, ValueError):
                continue
            卡位.append((页, x, y))
        return 卡位

    @staticmethod
    def _卡位已跳过(卡位列表, 页: int, 位置: tuple[int, int]) -> bool:
        return any(
            页 == 已页 and abs(int(位置[0]) - x) <= 30 and abs(int(位置[1]) - y) <= 30
            for 已页, x, y in 卡位列表
        )

    def _保存详情超时卡位(self, 候选列表: list[任务候选]) -> None:
        """详情超时的卡位记到当天：今天之后的检查直接跳过，不再每次白等。"""
        记录 = getattr(self, "_记录", None)
        if 记录 is None:
            return
        新卡位 = [(候选.页, int(候选.位置[0]), int(候选.位置[1])) for 候选 in 候选列表 if 候选.详情超时]
        if not 新卡位:
            return
        卡位 = self._今日详情超时卡位()
        for 页, x, y in 新卡位:
            if not self._卡位已跳过(卡位, 页, (x, y)):
                卡位.append((页, x, y))
        记录["详情超时卡"] = {
            "日期": self._现在().strftime("%Y-%m-%d"),
            "卡位": [list(项) for 项 in 卡位],
        }

    def _开始任务(self, 目标: 任务候选) -> str:
        当前页 = getattr(self, "_当前页", 0)
        self._切换到页(当前页, 目标.页)
        if not self._点击(目标.位置, "选中的任务卡"):
            return "护栏阻止"
        详情 = self._等待(lambda: self._识别详情(), "选中任务详情")
        if not 详情:
            self._关闭详情()
            return "详情超时"
        类型 = 识别任务类型(
            详情["文本"], self.配置, self._阵容签名(),
            getattr(self.上下文, "_部落竞赛可用单位", {}) or {},
        )
        if 类型 != 目标.类型:
            原文摘要 = str(详情.get("文本", "") or "")[:40]
            self._日志(
                f"复核任务类型不一致（{类型} ≠ {目标.类型}），复核原文：{原文摘要}；不点开始"
            )
            self._关闭详情()
            return "复核不一致"
        if 详情["禁点"]:
            self._日志(f"复核发现『{详情['禁点']}』，不点开始")
            self._关闭详情()
            return "护栏阻止"
        if 详情["冷却"] or 详情["开始点"] is None:
            self._日志("开始按钮未通过模板+文字双重确认，不点击")
            self._关闭详情()
            return "护栏阻止"
        if not self._点击(详情["开始点"], "开始"):
            return "护栏阻止"
        # 开始后同一位置的按钮会变成红色『放弃/放棄』，但实机更常见的是
        # 详情弹窗直接收起、接到的卡挪到左上角显示 0/N 进度、其余卡变灰。
        # 三种证据任一出现都算已接；只用来确认，绝不点击『放弃』。
        if self._等待(self._任务已开始, "任务开始确认"):
            self._日志(f"已接任务：{目标.类型}（{目标.积分 or '?'}分）{目标.文本[:40]}")
            return "已接任务"
        # 最后再收起详情看一次卡片网格：开始已生效但弹窗还挡着时不要误报超时。
        self._关闭详情()
        if self._任务已开始(允许弹窗=False):
            self._日志(f"已接任务（收起详情后确认）：{目标.类型}（{目标.积分 or '?'}分）{目标.文本[:40]}")
            return "已接任务"
        return "超时"

    def _任务已开始(self, 允许弹窗: bool = True):
        """开始后确认任务已接：放弃按钮 / 0/N 进度 / 其余卡片全部变灰。"""
        图像 = self._截图()
        卡片区 = self.配置.get("面板", {}).get("卡片区ROI")
        项列表 = self._OCR(图像, 卡片区)
        放弃词 = self.配置.get("OCR", {}).get("已接确认关键词", ["放弃"])
        if 查找关键词(项列表, 放弃词, 卡片区):
            return True
        开始词 = self.配置.get("OCR", {}).get("开始关键词", ["开始"])
        if 查找关键词(项列表, 开始词, 卡片区):
            return False  # 详情弹窗仍显示『开始』：还没生效
        区域项 = 区域文字(项列表, 卡片区) if 卡片区 else 项列表
        # 进度分数 0/N（刚接的任务）；页码 1/2 不算。
        if any(re.fullmatch(r"0\s*/\s*\d{1,4}", 项.规范) for 项 in 区域项):
            return True
        return self._卡片已变灰(图像)

    # ---------------------------------------------------------------- 关闭
    def _回到主页(self) -> bool:
        try:
            return self._关闭到主页()
        except 部落竞赛超时:
            return self._是主世界主页()

    def _关闭到主页(self) -> bool:
        for _ in range(4):
            if self._是主世界主页():
                return True
            try:
                self._检查总超时()
            except 部落竞赛超时:
                return False
            图像 = self._截图()
            关闭点 = self._匹配模板(图像, "关闭按钮") or self._匹配模板(图像, "活动列表关闭")
            if 关闭点 is None:
                # 详情弹窗挡住了 X 之外没有别的情况；先点空白处，再找 X。
                标题区 = self.配置.get("面板", {}).get("标题ROI")
                项列表 = self._OCR(图像, 标题区)
                if 查找关键词(项列表, self.配置.get("面板", {}).get("标题关键词", ["部落竞赛"]),
                         标题区) is not None:
                    self._关闭详情()
                    continue
                self._日志("没有找到可确认的关闭按钮，不盲点")
                return self._等待(self._是主世界主页, "回到主页") is not None
            禁点 = self._关闭X附近禁点(图像, 关闭点)
            if 禁点:
                self._日志(f"关闭 X 附近出现『{禁点}』，不点击")
                return False
            try:
                self._点击已确认关闭X(关闭点, "关闭")
            except 部落竞赛超时:
                return False
            self._延时(800)
        return self._是主世界主页()
