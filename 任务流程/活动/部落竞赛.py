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
- 不领奖，只在日志/通知里提醒。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from 任务流程.基础任务框架 import 基础任务

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


def 识别任务类型(文本: str, 配置: dict) -> str | None:
    """按白名单定义判断任务类型；全局排除词命中时返回 None。"""
    文本 = 规范文本(文本)
    if not 文本:
        return None
    if any(规范文本(词) in 文本 for 词 in 配置.get("全局排除词", []) if 词):
        return None
    for 名称, 定义 in (配置.get("白名单") or {}).items():
        if any(规范文本(词) in 文本 for 词 in 定义.get("排除词", []) if 词):
            continue
        组 = 定义.get("关键词组") or []
        if 组 and all(any(规范文本(词) in 文本 for 词 in 词组 if 词) for 词组 in 组):
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


def 选择任务(候选列表: Iterable[任务候选], 启用白名单: Iterable[str], 配置: dict) -> 任务候选 | None:
    """先按白名单层级（1=核心打鱼类，2=可选），同层选积分最高，再按白名单顺序。"""
    启用 = [名 for 名 in 启用白名单]
    白名单 = 配置.get("白名单") or {}
    可选 = [
        候选 for 候选 in 候选列表
        if 候选.类型 in 启用 and not 候选.冷却 and not 候选.禁点原因
    ]
    if not 可选:
        return None
    return min(可选, key=lambda 候选: (
        int(白名单.get(候选.类型, {}).get("层级", 9)),
        -(候选.积分 or 0),
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
                 时钟: Callable[[], float] = time.monotonic, 现在: Callable[[], datetime] = datetime.now):
        super().__init__(上下文)
        self._配置 = 配置
        self.官方摘要 = 官方摘要
        self._时钟 = 时钟
        self._现在 = 现在
        self._截止 = 0.0
        self._模板缓存: dict[str, Any] = {}
        self.结果 = ""

    # ---------------------------------------------------------------- 基础
    @property
    def 配置(self) -> dict:
        if self._配置 is None:
            self._配置 = 加载配置()
        return self._配置

    def _日志(self, 文本: str) -> None:
        self.上下文.置脚本状态(f"部落竞赛：{文本}")

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
        self.上下文.脚本延时(int(毫秒))

    def _截图(self):
        try:
            return self.上下文.op.获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
        except TypeError:
            return self.上下文.op.获取屏幕图像cv(0, 0, 800, 600)

    def _OCR(self, 图像) -> list[文字项]:
        try:
            获取 = getattr(self.上下文, "获取OCR引擎", None)
            引擎 = 获取() if callable(获取) else self.ocr引擎
            return 整理OCR结果(引擎(图像))
        except Exception as 异常:
            self._日志(f"OCR 失败：{异常}")
            return []

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

    def _匹配模板(self, 图像, 名称: str, 区域=None) -> tuple[int, int] | None:
        """返回模板中心（800x600 坐标）；未命中或模板缺失返回 None。"""
        import cv2
        定义 = self.配置.get("模板", {}).get(名称) or {}
        x1, y1, x2, y2 = [int(值) for 值 in (区域 or 定义.get("ROI") or (0, 0, 800, 600))]
        阈值 = float(定义.get("阈值", 0.85))
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
            if 分数 >= 阈值 and (最佳 is None or 分数 > 最佳[0]):
                最佳 = (分数, (max(0, x1) + 位置[0] + tw // 2, max(0, y1) + 位置[1] + th // 2))
        return 最佳[1] if 最佳 else None

    def _等待(self, 条件: Callable[[], Any], 说明: str):
        """轮询直到条件返回真值；超过步骤超时返回 None。"""
        步骤截止 = self._时钟() + self._超时设置("步骤秒", 8)
        间隔 = int(self._超时设置("轮询毫秒", 500))
        while True:
            self._检查总超时()
            结果 = 条件()
            if 结果:
                return 结果
            if self._时钟() >= 步骤截止:
                self._日志(f"等待{说明}超时")
                return None
            self._延时(间隔)

    def _点击(self, 点: tuple[int, int], 说明: str) -> bool:
        self._检查总超时()
        self._日志(f"点击{说明} {点}")
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

    def _是主世界主页(self) -> bool:
        识别 = getattr(self.上下文, "识别点击画面", None)
        if not callable(识别):
            return False
        try:
            结果 = 识别(强制=True)
        except Exception:
            return False
        return (
            getattr(结果, "页面", "") == "主世界主页"
            and getattr(结果, "世界", "主世界") == "主世界"
        )

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
    def 执行(self) -> bool:
        设置 = self.上下文.设置
        if not getattr(设置, "是否部落竞赛接任务", False):
            return True
        记录 = self._读状态()
        现在 = time.time()
        下次 = float(记录.get("下次检查时间", 0) or 0)
        if 现在 < 下次:
            return True
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
        if 结果 == "已满分":
            self._提醒一次(记录, "满分", "部落竞赛个人积分已满，请手动去领奖励。")
        if 结果 == "入口不存在" and 记录.get("本期见过入口") == self._现在().strftime("%Y-%m"):
            self._提醒一次(记录, "结束", "部落竞赛入口已消失（活动可能已结束），记得手动领奖。")
        self._记录结果(记录, 结果, self._冷却分钟(结果))
        return True

    def _记录结果(self, 记录: dict, 结果: str, 冷却分钟: float) -> None:
        现在 = time.time()
        记录.update({
            "时间": 现在,
            "结果": 结果,
            "下次检查时间": 现在 + max(1.0, float(冷却分钟)) * 60,
        })
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
        通知 = getattr(self.上下文, "发送企业微信通知", None)
        if callable(通知):
            try:
                通知(文本, 包含截图=False)
            except Exception:
                pass

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
        图像 = self._截图()
        活动按钮 = self._匹配模板(图像, "活动按钮")
        if 活动按钮 is None:
            self._日志("底栏没有找到活动按钮，跳过")
            return "入口不存在"
        if not self._点击(活动按钮, "活动按钮"):
            return "护栏阻止"
        if not self._等待(self._活动列表已打开, "活动列表"):
            return "面板未确认"
        # 活动列表已确认：让通用点击护栏不要把它当成意外弹窗关掉。
        self._设置面板标记(True)
        开启点 = self._找部落竞赛开启()
        if 开启点 is None:
            self._日志("活动列表里没有部落竞赛（活动可能已结束）")
            return "入口不存在"
        if not self._点击(开启点, "部落竞赛开启"):
            return "护栏阻止"
        面板 = self._等待(self._识别竞赛面板, "部落竞赛面板")
        if not 面板:
            return "面板未确认"
        return self._处理面板(面板)

    def _活动列表已打开(self):
        图像 = self._截图()
        列表 = self.配置.get("活动列表", {})
        项列表 = self._OCR(图像)
        if 查找关键词(项列表, 列表.get("标题关键词", ["活动"]), 列表.get("标题ROI")) is None:
            return None
        if self._匹配模板(图像, "活动列表关闭") is None:
            return None
        return 项列表

    def _找部落竞赛开启(self) -> tuple[int, int] | None:
        列表 = self.配置.get("活动列表", {})
        for 次数 in range(int(列表.get("最多滑动次数", 4)) + 1):
            self._检查总超时()
            图像 = self._截图()
            项列表 = self._OCR(图像)
            标题 = self._找竞赛标题(项列表, 列表)
            if 标题 is not None:
                # 『开启』两个字 OCR 读不出来：用模板在标题下方同一张活动卡
                # 的横带里找按钮；横带里的文字同时做禁点检查。
                _, dy1, _, dy2 = 列表.get("开启相对标题ROI", [0, -10, 0, 170])
                列表区 = 列表.get("列表ROI", (0, 0, 800, 600))
                区域 = (列表区[0], 标题.框[1] + dy1, 列表区[2], min(列表区[3], 标题.框[1] + dy2))
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
        图像 = self._截图()
        面板 = self.配置.get("面板", {})
        项列表 = self._OCR(图像)
        if 查找关键词(项列表, 面板.get("标题关键词", ["部落竞赛"]), 面板.get("标题ROI")) is None:
            return None
        if self._匹配模板(图像, "面板标题") is None:
            return None
        if self._匹配模板(图像, "关闭按钮") is None:
            return None
        return {"图像": 图像, "文字": 项列表}

    def _处理面板(self, 面板: dict) -> str:
        配置 = self.配置
        项列表 = 面板["文字"]
        积分区 = 配置.get("面板", {}).get("个人积分ROI")
        个人 = 解析个人积分(拼接文本(区域文字(项列表, 积分区)) if 积分区 else "")
        if 个人:
            self._日志(f"个人积分 {个人[0]}/{个人[1]}")
            if 个人[0] >= 个人[1]:
                return "已满分"
        全文 = 拼接文本(项列表)
        if any(规范文本(词) in 全文 for 词 in 配置.get("OCR", {}).get("已满分关键词", [])):
            return "已满分"
        if self._匹配模板(面板["图像"], "已满分") is not None:
            return "已满分"
        if self._存在进行中任务(面板["图像"], 项列表):
            self._日志("已有进行中的任务，交给打鱼完成")
            return "已有任务"

        启用 = [名 for 名 in (getattr(self.上下文.设置, "部落竞赛任务白名单", None) or [])]
        if not 启用:
            self._日志("白名单为空，不接任务")
            return "无可接任务"

        候选列表 = self._扫描任务卡()
        for 候选 in 候选列表:
            状态 = "冷却" if 候选.冷却 else (f"禁点({候选.禁点原因})" if 候选.禁点原因 else (候选.类型 or "不在白名单"))
            self._日志(f"任务卡 页{候选.页 + 1}{候选.位置}：{状态}，{候选.积分 or '?'}分；{候选.文本[:40]}")
        最佳 = 选择任务(候选列表, 启用, 配置)
        if 最佳 is None:
            self._日志("没有符合白名单的可接任务")
            return "无可接任务"
        self._日志(f"选择 {最佳.类型}（{最佳.积分 or '?'}分）")
        return self._开始任务(最佳)

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

    def _切换到页(self, 当前页: int, 目标页: int) -> int:
        页列表 = self.配置.get("面板", {}).get("页", [])
        if 目标页 == 当前页:
            return 当前页
        if 目标页 < 当前页:
            回滑 = self.配置.get("面板", {}).get("回到第一页滑动")
            if 回滑:
                self._滑动(回滑)
                self._延时(600)
            当前页 = 0
        for 页号 in range(当前页 + 1, 目标页 + 1):
            滑动 = 页列表[页号].get("滑动")
            if 滑动:
                self._滑动(滑动)
                self._延时(600)
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
            文本 = 拼接文本(区域文字(self._OCR(图像), self.配置.get("面板", {}).get("卡片区ROI", (0, 0, 800, 600))))
            候选.冷却 = True
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
        候选.类型 = 识别任务类型(详情["文本"], self.配置)
        return 候选

    def _识别详情(self):
        图像 = self._截图()
        项列表 = self._OCR(图像)
        卡片区 = self.配置.get("面板", {}).get("卡片区ROI", (0, 0, 800, 600))
        开始 = 查找关键词(项列表, self.配置.get("OCR", {}).get("开始关键词", ["开始"]), 卡片区)
        if 开始 is None:
            return None
        dx1, dy1, dx2, dy2 = self.配置.get("面板", {}).get("详情相对开始文字", [-165, -180, 60, 50])
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
        页列表 = self.配置.get("面板", {}).get("页", [])
        候选列表: list[任务候选] = []
        当前页 = 0
        for 页号, 页 in enumerate(页列表):
            当前页 = self._切换到页(当前页, 页号)
            for 位置 in 页.get("卡片", []):
                候选列表.append(self._读取详情(页号, tuple(位置)))
                self._关闭详情()
        self._当前页 = 当前页
        return 候选列表

    def _开始任务(self, 目标: 任务候选) -> str:
        当前页 = getattr(self, "_当前页", 0)
        self._切换到页(当前页, 目标.页)
        if not self._点击(目标.位置, "选中的任务卡"):
            return "护栏阻止"
        详情 = self._等待(lambda: self._识别详情(), "选中任务详情")
        if not 详情:
            return "超时"
        类型 = 识别任务类型(详情["文本"], self.配置)
        if 类型 != 目标.类型:
            self._日志(f"复核任务类型不一致（{类型} ≠ {目标.类型}），不点开始")
            return "护栏阻止"
        if 详情["禁点"]:
            self._日志(f"复核发现『{详情['禁点']}』，不点开始")
            return "护栏阻止"
        if 详情["冷却"] or 详情["开始点"] is None:
            self._日志("开始按钮未通过模板+文字双重确认，不点击")
            return "护栏阻止"
        if not self._点击(详情["开始点"], "开始"):
            return "护栏阻止"
        # 开始后同一位置的按钮会变成红色『放弃』：只用它确认，绝不点击它。
        放弃词 = self.配置.get("OCR", {}).get("已接确认关键词", ["放弃"])
        卡片区 = self.配置.get("面板", {}).get("卡片区ROI")
        if self._等待(lambda: 查找关键词(self._OCR(self._截图()), 放弃词, 卡片区), "任务开始确认"):
            self._日志(f"已接任务：{目标.类型}（{目标.积分 or '?'}分）{目标.文本[:40]}")
            return "已接任务"
        return "超时"

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
                项列表 = self._OCR(图像)
                if 查找关键词(项列表, self.配置.get("面板", {}).get("标题关键词", ["部落竞赛"]),
                         self.配置.get("面板", {}).get("标题ROI")) is not None:
                    self._关闭详情()
                    continue
                self._日志("没有找到可确认的关闭按钮，不盲点")
                return self._等待(self._是主世界主页, "回到主页") is not None
            try:
                self._点击(关闭点, "关闭")
            except 部落竞赛超时:
                return False
            self._延时(800)
        return self._是主世界主页()
