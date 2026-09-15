import random
import time
import math
import re

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文, 基础任务
from 任务流程.更新主世界账号资源状态 import 更新家乡资源状态任务
from 模块.检测.OCR识别器 import 安全OCR引擎
from 模块.检测.YOLO检测器 import 线程安全YOLO检测器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 数据库.任务数据库 import 任务数据库, 机器人设置


class 资源不足错误(Exception):
    def __init__(self, 错误信息):
        super().__init__(错误信息)
        self.错误信息 = 错误信息

    def __str__(self):
        return f"发生了：{self.错误信息}"

class 城墙升级任务(基础任务):
    """自动检测并升级城墙"""

    # 任务坐标统一使用 800×600 逻辑画布；ADB 屏幕适配器会负责映射到实际分辨率。
    墙体搜索区域 = (70, 55, 730, 540)
    墙体搜索每轮最大候选数 = 24
    墙体搜索最大轮数 = 5
    墙体搜索超时秒 = 120
    墙体点击后等待毫秒 = 420
    墙体关键词 = ("城墙", "城牆", "围墙", "围牆", "wall", "walls")
    墙体满级关键词 = ("已满级", "已滿級", "满级", "滿級", "最高等级", "最高等級", "maxed", "maxlevel")

    @property
    def 设置(self) -> 机器人设置:
        配置 = self.数据库.获取机器人设置(self.机器人标志)
        return 配置

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文
            # 这些字段由主任务线程读取，用于在资源不足时自动切换到刷资源。
            上下文.刷墙需要资源 = False
            上下文.刷墙墙体记录 = []
            # 初始化配置
            if not self.检查功能开启(上下文):
                return True

            # 不再用“刷墙起始金币/圣水”挡住扫描。起始值只能决定任务优先级，
            # 不能替代对当前墙段实际升级费用的判断；否则资源不足时永远不会
            # 进入墙体面板，也就无法自动转去刷资源。
            for _ in range(300):
                if 上下文.停止事件.is_set():
                    break
                if not self.刷一次墙():
                    if getattr(上下文, "刷墙需要资源", False):
                        return True
                    上下文.置脚本状态("本次刷墙未完成升级，结束本轮墙体扫描")
                    break

            return True
        except 资源不足错误 as e:
            self.上下文.置脚本状态(e.__str__())
            return False
        except Exception as e:

            self.异常处理(e)
            return False

    def 刷一次墙(self):
        上下文 = self.上下文

        上下文.置脚本状态("开始刷一块墙：扫描主世界可见墙段")
        self.进入城墙界面(上下文)
        try:
            # 先刷新右上角实际资源，避免 DB 中的战前快照让“资源不足”
            # 被误判为可升级，或反过来跳过真正可升级的墙段。
            更新家乡资源状态任务(上下文).执行()
        except Exception as 异常:
            上下文.置脚本状态(f"刷墙前资源刷新失败，使用最近资源快照：{异常}")
        开始找墙时间 = time.monotonic()
        已尝试点 = []
        本次墙体记录 = []
        当前金币, 当前圣水 = self.获取当前墙体资源(上下文)

        # 旧实现只 OCR “城墙”文字，但文字只有在点击墙段后才会出现，
        # 因此永远没有第一步。现在先用边缘/颜色生成墙段候选，再用
        # 点击后的“城墙”文字和升级面板双重确认，候选失败就换点。
        for 轮次 in range(self.墙体搜索最大轮数):
            if time.monotonic() - 开始找墙时间 >= self.墙体搜索超时秒:
                break

            屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            候选点列表 = self.生成城墙候选点(屏幕图像)
            候选点列表 = [
                点 for 点 in 候选点列表
                if not any((点[0] - 旧点[0]) ** 2 + (点[1] - 旧点[1]) ** 2 < 14 ** 2
                           for 旧点 in 已尝试点)
            ]
            上下文.置脚本状态(
                f"第{轮次 + 1}轮识别到{len(候选点列表)}个墙段候选点"
            )

            for 候选序号, (x, y) in enumerate(候选点列表, 1):
                if time.monotonic() - 开始找墙时间 >= self.墙体搜索超时秒:
                    break
                已尝试点.append((x, y))
                上下文.置脚本状态(
                    f"尝试选择墙段 {x},{y}（第{候选序号}个候选）"
                )
                上下文.点击(x, y, 延时=180, 是否精确点击=True)
                上下文.脚本延时(self.墙体点击后等待毫秒)
                ocr结果 = self.执行OCR识别(上下文)
                墙体项 = next(
                    (项 for 项 in (ocr结果 or [])
                     if len(项) >= 2 and self.文本是否城墙(项[1])),
                    None,
                )
                if 墙体项 is None:
                    continue

                墙体状态 = self.解析城墙状态(ocr结果, 当前金币, 当前圣水)
                墙体记录 = {
                    "坐标": [int(x), int(y)],
                    "等级": 墙体状态["等级"],
                    "状态": 墙体状态["状态"],
                    "金币费用": 墙体状态["金币费用"],
                    "圣水费用": 墙体状态["圣水费用"],
                }
                本次墙体记录.append(墙体记录)
                上下文.置脚本状态(
                    f"墙体候选位置{x},{y}：等级={墙体记录['等级'] or '未知'}，"
                    f"状态={墙体记录['状态']}"
                )

            if 本次墙体记录:
                self.记录墙体扫描状态(上下文, 本次墙体记录)
                if self.执行最低等级墙(上下文, 本次墙体记录):
                    上下文.脚本延时(900)
                    return True
                if getattr(上下文, "刷墙需要资源", False):
                    return False

            if 轮次 + 1 < self.墙体搜索最大轮数:
                self.滑动屏幕(上下文, random.randint(0, 5))
                上下文.置脚本状态("当前区域未确认可升级墙段，平移村庄继续搜索")

        if not getattr(上下文, "刷墙需要资源", False):
            上下文.置脚本状态("未找到可升级城墙：已扫描可见墙段和多个村庄区域")
        return False


    def 检查功能开启(self, 上下文) -> bool:
        """检查是否开启刷墙功能"""

        是否开启 = 上下文.数据库.获取机器人设置(上下文.机器人标志).开启刷墙
        if not 是否开启:
            上下文.置脚本状态("刷墙功能已关闭（请在任务计划勾选“刷墙”，配置会自动保存）")
            return False
        else:
            return True


    def 已够资源升级(self)-> bool:
        上下文=self.上下文
        更新家乡资源状态任务(上下文).执行()
        当前金币 = 上下文.数据库.获取最新完整状态(上下文.机器人标志).状态数据["家乡资源"]["金币"]
        当前圣水 = 上下文.数据库.获取最新完整状态(上下文.机器人标志).状态数据["家乡资源"]["圣水"]
        刷墙起始金币= 上下文.数据库.获取机器人设置(上下文.机器人标志).刷墙起始金币
        刷墙起始圣水= 上下文.数据库.获取机器人设置(上下文.机器人标志).刷墙起始圣水

        if 当前金币>刷墙起始金币:
            上下文.置脚本状态("金币满足用户设定的条件,开始刷墙")
            return True
        elif 当前圣水>刷墙起始圣水:
            上下文.置脚本状态("圣水满足用户设定的条件,开始刷墙")
            return True
        else:
            上下文.置脚本状态(f"未到达刷墙要求,设定的条件为金币超过{刷墙起始圣水},或圣水超过{刷墙起始圣水}")
            return False

    def 进入城墙界面(self, 上下文):
        """准备在主世界直接扫描墙段。

        旧版点击 (353, 13) 假定存在“城墙列表”入口，但当前版本该位置
        不是稳定入口，点击后也不会产生可供 OCR 的墙体列表。任务计划在
        进入本任务前已经调用到主世界，因此这里仅等待画面稳定，不再误点
        顶部 UI；找不到墙时由主流程负责平移和重试。
        """
        上下文.置脚本状态("主世界画面已稳定，准备识别墙段")
        上下文.脚本延时(800)



    def 执行OCR识别(self, 上下文) -> list:
        """执行屏幕OCR识别"""

        try:
            # 选中墙后标题/升级面板可能出现在底部或右侧，不能再限制在
            # 219,57,595,398；使用完整逻辑画布，OCR 坐标天然为绝对坐标。
            屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            # 使用OCR引擎识别
            ocr结果, _ = self.ocr引擎(屏幕图像)
            return ocr结果 or []
        except Exception as e:
            上下文.置脚本状态(f"OCR识别失败: {str(e)}")
            return []

    @classmethod
    def 文本是否城墙(cls, 文本) -> bool:
        """兼容简体/繁体和国际服英文 OCR 结果。"""
        文本 = str(文本 or "").replace(" ", "").lower()
        return any(关键词 in 文本 for 关键词 in cls.墙体关键词)

    @staticmethod
    def _规范OCR文本(文本) -> str:
        return str(文本 or "").replace(" ", "").replace("级", "級").lower()

    def 解析城墙等级(self, ocr结果) -> int | None:
        """从选中墙体的标题提取等级，例如“城墙（16级-）”。"""
        for 识别项 in ocr结果 or []:
            if len(识别项) < 2 or not self.文本是否城墙(识别项[1]):
                continue
            文本 = self._规范OCR文本(识别项[1])
            匹配 = re.search(
                r"(?:城墙|城牆|围墙|围牆|walls?)\D{0,14}"
                r"(\d{1,2})\s*(?:級|lvl|level)",
                文本,
                re.IGNORECASE,
            )
            if 匹配:
                try:
                    return int(匹配.group(1))
                except (TypeError, ValueError):
                    pass
        return None

    def 解析城墙状态(self, ocr结果, 当前金币=None, 当前圣水=None) -> dict:
        """判断墙段是可升级、满级、资源不足还是需要再次确认。

        只有 OCR 同时提供升级入口或费用证据时才会判定为可操作，避免把
        选中面板上的普通按钮当作升级按钮。
        """
        文本列表 = [
            self._规范OCR文本(项[1])
            for 项 in (ocr结果 or [])
            if len(项) >= 2
        ]
        合并文本 = " ".join(文本列表)
        等级 = self.解析城墙等级(ocr结果)
        金币费用, 圣水费用 = self.解析城墙升级费用(ocr结果)
        已满级 = any(
            self._规范OCR文本(关键词) in 合并文本
            for 关键词 in self.墙体满级关键词
        )
        有升级入口 = any(
            "升级" in 文本 or "升級" in 文本 or "upgrade" in 文本
            for 文本 in 文本列表
        )

        if 已满级:
            状态 = "已满级"
        else:
            可用资源结果 = []
            if 金币费用 is not None and 当前金币 is not None:
                可用资源结果.append(int(当前金币) >= 金币费用)
            if 圣水费用 is not None and 当前圣水 is not None:
                可用资源结果.append(int(当前圣水) >= 圣水费用)

            if 可用资源结果 and any(可用资源结果) and 有升级入口:
                状态 = "可升级"
            elif 可用资源结果 and not any(可用资源结果):
                状态 = "资源不足"
            elif 有升级入口:
                # 费用 OCR 可能短暂丢失；保留入口证据，交给执行阶段的
                # 图标匹配和二次 OCR 再确认。
                状态 = "可升级"
            else:
                状态 = "待确认"

        return {
            "等级": 等级,
            "状态": 状态,
            "金币费用": 金币费用,
            "圣水费用": 圣水费用,
        }

    @staticmethod
    def 选择最低等级墙段(墙体记录) -> list[dict]:
        """返回未满级墙段，最低等级优先；未知等级放在最后。

        资源不足的低等级墙不能被更高等级墙越过，调用方会据此转入刷资源。
        """
        return sorted(
            [记录 for 记录 in (墙体记录 or []) if 记录.get("状态") != "已满级"],
            key=lambda 记录: (
                记录.get("等级") is None,
                记录.get("等级") if 记录.get("等级") is not None else 10_000,
                记录.get("坐标", [10_000, 10_000]),
            ),
        )

    def 获取当前墙体资源(self, 上下文) -> tuple[int | None, int | None]:
        try:
            状态 = 上下文.数据库.获取最新完整状态(上下文.机器人标志)
            资源 = (状态.状态数据 or {}).get("家乡资源", {})
            return (
                int(资源.get("金币", 0) or 0),
                int(资源.get("圣水", 0) or 0),
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return None, None

    def 记录墙体扫描状态(self, 上下文, 墙体记录):
        上下文.刷墙墙体记录 = list(墙体记录)
        try:
            上下文.数据库.更新状态(
                上下文.机器人标志,
                "城墙识别",
                {"墙体": 墙体记录, "说明": "本轮可见墙段的位置、等级和升级状态"},
            )
        except Exception:
            # 状态记录失败不应阻断实际升级。
            pass

    def 执行最低等级墙(self, 上下文, 墙体记录) -> bool:
        """重新选中最低等级墙段，二次确认后只点击一次升级入口。"""
        当前金币, 当前圣水 = self.获取当前墙体资源(上下文)
        候选记录 = self.选择最低等级墙段(墙体记录)
        if not 候选记录:
            return False

        for 记录 in 候选记录:
            x, y = 记录["坐标"]
            if 记录.get("状态") == "资源不足":
                上下文.置脚本状态(
                    f"最低等级墙段{x},{y}（{记录.get('等级') or '未知'}级）资源不足，准备刷资源"
                )
                上下文.刷墙需要资源 = True
                return False
            if 记录.get("状态") != "可升级":
                上下文.置脚本状态(f"墙段{x},{y}状态为{记录.get('状态') or '未知'}，切换下一个候选墙段")
                continue
            上下文.置脚本状态(
                f"选择最低等级墙段{x},{y}（{记录.get('等级') or '未知'}级），二次确认升级"
            )
            上下文.点击(x, y, 延时=180, 是否精确点击=True)
            上下文.脚本延时(self.墙体点击后等待毫秒)
            最新OCR = self.执行OCR识别(上下文)
            最新状态 = self.解析城墙状态(最新OCR, 当前金币, 当前圣水)
            if 最新状态["状态"] == "已满级":
                上下文.置脚本状态(f"墙段{x},{y}已满级，切换下一个最低等级墙段")
                continue
            if 最新状态["状态"] == "资源不足":
                上下文.置脚本状态(f"墙段{x},{y}资源不足，准备自动刷资源")
                上下文.刷墙需要资源 = True
                return False
            if 最新状态["状态"] != "可升级":
                上下文.置脚本状态(f"墙段{x},{y}未确认升级入口，切换下一个候选墙段")
                continue

            成功 = self.执行升级(
                上下文,
                x - 10,
                y - 10,
                x + 10,
                y + 10,
                已选中=True,
                OCR结果=最新OCR,
            )
            if 成功:
                try:
                    上下文.数据库.更新状态(
                        上下文.机器人标志,
                        "城墙升级记录",
                        {"坐标": [x, y], "升级前等级": 最新状态["等级"], "状态": "已点击升级"},
                    )
                except Exception:
                    pass
                return True

        return False

    @staticmethod
    def 解析OCR坐标(坐标点列表, 偏移=(0, 0)) -> tuple[int, int, int, int]:
        """把 OCR 四边形坐标转成稳定的绝对包围框。"""
        if not 坐标点列表 or len(坐标点列表) < 2:
            raise ValueError("OCR 坐标为空")
        所有x = [int(点[0]) for 点 in 坐标点列表]
        所有y = [int(点[1]) for 点 in 坐标点列表]
        偏移x, 偏移y = int(偏移[0]), int(偏移[1])
        左上x = max(0, min(800, min(所有x) + 偏移x))
        左上y = max(0, min(600, min(所有y) + 偏移y))
        右下x = max(左上x + 1, min(800, max(所有x) + 偏移x))
        右下y = max(左上y + 1, min(600, max(所有y) + 偏移y))
        return 左上x, 左上y, 右下x, 右下y

    def 生成城墙候选点(self, 屏幕图像: np.ndarray) -> list[tuple[int, int]]:
        """从村庄画面提取墙段候选点。

        城墙在不同等级下颜色会变化，因此不依赖单一模板；使用金色/灰色
        边缘和等距去重生成候选，真正是否为墙由点击后的 OCR 再确认。
        """
        if not isinstance(屏幕图像, np.ndarray) or 屏幕图像.ndim != 3:
            return []
        高度, 宽度 = 屏幕图像.shape[:2]
        if 高度 < 80 or 宽度 < 120:
            return []

        区域左, 区域上, 区域右, 区域下 = self.墙体搜索区域
        区域右 = min(区域右, 宽度)
        区域下 = min(区域下, 高度)
        if 区域右 <= 区域左 or 区域下 <= 区域上:
            return []
        裁剪 = 屏幕图像[区域上:区域下, 区域左:区域右]
        hsv图像 = cv2.cvtColor(裁剪, cv2.COLOR_BGR2HSV)

        # 兼容常见灰黑墙体和金色墙顶；只用于排序，不直接判定墙。
        金色掩码 = cv2.inRange(
            hsv图像,
            np.array([8, 75, 75], dtype=np.uint8),
            np.array([40, 255, 255], dtype=np.uint8),
        )
        灰色掩码 = cv2.inRange(
            hsv图像,
            np.array([0, 0, 28], dtype=np.uint8),
            np.array([179, 145, 205], dtype=np.uint8),
        )
        灰度 = cv2.cvtColor(裁剪, cv2.COLOR_BGR2GRAY)
        边缘 = cv2.Canny(灰度, 60, 170)
        线性掩码 = cv2.bitwise_or(边缘, 金色掩码)
        线性掩码 = cv2.morphologyEx(
            线性掩码,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        线段列表 = cv2.HoughLinesP(
            线性掩码,
            1,
            np.pi / 180,
            threshold=14,
            minLineLength=16,
            maxLineGap=5,
        )
        候选评分 = []
        if 线段列表 is not None:
            for 线段 in 线段列表[:, 0]:
                x1, y1, x2, y2 = [int(值) for 值 in 线段]
                长度 = math.hypot(x2 - x1, y2 - y1)
                角度 = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
                # 等距视角下的墙线通常是斜线；过滤水平文字和竖直 UI。
                if 长度 < 16 or not (18 <= 角度 <= 72 or 108 <= 角度 <= 162):
                    continue
                for 比例 in (0.30, 0.50, 0.70):
                    x = round(x1 + (x2 - x1) * 比例) + 区域左
                    y = round(y1 + (y2 - y1) * 比例) + 区域上
                    半径 = 6
                    局部金色 = 金色掩码[
                        max(0, y - 区域上 - 半径):min(区域下 - 区域上, y - 区域上 + 半径 + 1),
                        max(0, x - 区域左 - 半径):min(区域右 - 区域左, x - 区域左 + 半径 + 1),
                    ]
                    局部灰色 = 灰色掩码[
                        max(0, y - 区域上 - 半径):min(区域下 - 区域上, y - 区域上 + 半径 + 1),
                        max(0, x - 区域左 - 半径):min(区域右 - 区域左, x - 区域左 + 半径 + 1),
                    ]
                    金色比例 = float(np.count_nonzero(局部金色)) / max(1, 局部金色.size)
                    灰色比例 = float(np.count_nonzero(局部灰色)) / max(1, 局部灰色.size)
                    评分 = 长度 * 0.45 + 金色比例 * 80 + 灰色比例 * 22
                    候选评分.append((评分, x, y))

        候选评分.sort(reverse=True)
        结果 = []
        for _, x, y in 候选评分:
            if not (区域左 <= x < 区域右 and 区域上 <= y < 区域下):
                continue
            if any((x - 旧x) ** 2 + (y - 旧y) ** 2 < 16 ** 2 for 旧x, 旧y in 结果):
                continue
            结果.append((x, y))
            if len(结果) >= self.墙体搜索每轮最大候选数:
                break

        # 低画质/缩放状态下 Hough 可能没有稳定直线，改用角点作为保底；
        # 这些点仍然必须经过点击后的“城墙” OCR 确认，不会直接升级。
        if not 结果:
            角点列表 = cv2.goodFeaturesToTrack(
                灰度,
                maxCorners=self.墙体搜索每轮最大候选数 * 2,
                qualityLevel=0.02,
                minDistance=18,
                blockSize=5,
            )
            if 角点列表 is not None:
                for 角点 in 角点列表:
                    x = int(round(float(角点[0][0]))) + 区域左
                    y = int(round(float(角点[0][1]))) + 区域上
                    if 区域左 <= x < 区域右 and 区域上 <= y < 区域下:
                        结果.append((x, y))
                    if len(结果) >= self.墙体搜索每轮最大候选数:
                        break

        return 结果

    def 处理已选中的城墙(self, 上下文, ocr结果, 目标点: tuple[int, int]) -> bool:
        """点击候选点后确认标题确实是城墙，再读取升级面板。"""
        墙体项 = next(
            (项 for 项 in (ocr结果 or [])
             if len(项) >= 2 and self.文本是否城墙(项[1])),
            None,
        )
        if 墙体项 is None:
            return False
        上下文.置脚本状态(
            f"已确认城墙候选点{目标点[0]},{目标点[1]}，读取升级资源按钮"
        )
        x, y = int(目标点[0]), int(目标点[1])
        return self.执行升级(
            上下文,
            x - 10,
            y - 10,
            x + 10,
            y + 10,
            已选中=True,
            OCR结果=ocr结果,
        )

    @staticmethod
    def OCR文本数字(文本) -> int | None:
        """读取升级费用；兼容 OCR 把 5/0 识别成 S/o 的情况。"""
        文本 = str(文本 or "").replace(" ", "").replace(",", "")
        if not 文本:
            return None
        # RapidOCR 在当前测试服截图中偶尔把“5,000,000”读成
        # “000000S”，把首位 5 放到了末尾；先还原这个特例再做字符替换。
        if (
            len(文本) >= 5
            and 文本[-1:] in {"s", "S"}
            and 文本[:-1].isdigit()
            and set(文本[:-1]) == {"0"}
        ):
            文本 = 文本[-1:] + 文本[:-1]
        文本 = 文本.translate(str.maketrans({"o": "0", "O": "0", "s": "5", "S": "5"}))
        数字 = re.sub(r"[^0-9]", "", 文本)
        if not 数字:
            return None
        try:
            数值 = int(数字)
        except ValueError:
            return None
        return 数值 if 10_000 <= 数值 <= 100_000_000 else None

    def 解析城墙升级费用(self, ocr结果) -> tuple[int | None, int | None]:
        """按升级按钮的左右位置读取金币/圣水费用。"""
        金币费用 = None
        圣水费用 = None
        for 识别项 in ocr结果 or []:
            if len(识别项) < 2:
                continue
            try:
                x1, y1, x2, y2 = self.解析OCR坐标(识别项[0])
            except Exception:
                continue
            if y1 < 430 or y2 > 485:
                continue
            数值 = self.OCR文本数字(识别项[1])
            if 数值 is None:
                continue
            if x2 <= 485:
                金币费用 = 数值
            elif x1 >= 485:
                圣水费用 = 数值
        return 金币费用, 圣水费用

    def 定位城墙升级确认按钮(self, ocr结果) -> tuple[int, int] | None:
        """从确认框 OCR 定位“确认”，只接受底部操作区的按钮。"""
        for 识别项 in ocr结果 or []:
            if len(识别项) < 2:
                continue
            文本 = self._规范OCR文本(识别项[1])
            if "确认" not in 文本 and "confirm" not in 文本:
                continue
            try:
                x1, y1, x2, y2 = self.解析OCR坐标(识别项[0])
            except Exception:
                continue
            if 430 <= y1 <= 540 and x2 > 500:
                return ((x1 + x2) // 2, (y1 + y2) // 2)
        return None

    def 确认城墙升级提交(self, 上下文) -> bool:
        """处理资源按钮之后出现的升级确认框，并验证确认框已消失。"""
        确认OCR = self.执行OCR识别(上下文)
        合并文本 = " ".join(
            self._规范OCR文本(项[1])
            for 项 in (确认OCR or [])
            if len(项) >= 2
        )
        有升级确认框 = (
            "将城墙升至" in 合并文本
            or "将城牆升至" in 合并文本
            or "upgrade" in 合并文本 and "wall" in 合并文本
        )
        确认点 = self.定位城墙升级确认按钮(确认OCR)
        if not 有升级确认框 and 确认点 is None:
            # 某些版本会把资源按钮直接视为确认动作。
            上下文.置脚本状态("未出现城墙二次确认框，升级入口已提交")
            return True
        if 确认点 is None:
            上下文.置脚本状态("已出现城墙升级确认框，但未定位到确认按钮")
            return False

        上下文.置脚本状态(f"定位城墙升级确认按钮{确认点[0]},{确认点[1]}，提交升级")
        上下文.点击(
            确认点[0],
            确认点[1],
            延时=650,
            是否精确点击=True,
        )
        for _ in range(3):
            上下文.脚本延时(300)
            验证OCR = self.执行OCR识别(上下文)
            验证文本 = " ".join(
                self._规范OCR文本(项[1])
                for 项 in (验证OCR or [])
                if len(项) >= 2
            )
            if "将城墙升至" not in 验证文本 and "将城牆升至" not in 验证文本:
                上下文.置脚本状态("城墙升级确认已提交")
                return True
        上下文.置脚本状态("城墙升级确认框仍在，未确认升级提交")
        return False

    def 处理OCR结果(self, 上下文, ocr结果) -> bool:
        """解析OCR结果并处理,并尝试升级城墙,返回false则升级失败"""
        for 识别项 in ocr结果:
            if len(识别项) < 2:
                continue
            文本内容 = 识别项[1]
            if not self.文本是否城墙(文本内容):
                continue

            # 获取坐标信息
            try:
                # 当前执行OCR识别返回的是完整画布坐标；同时保留该方法
                # 对外的兼容性，避免再把右下角硬编码到 595。
                左上x, 左上y, 右下x, 右下y = self.解析OCR坐标(识别项[0])
            except Exception as e:
                上下文.置脚本状态(f"坐标解析失败: {str(e)}")
                continue



            # 检查升级能力
            if not self.检查升级条件(上下文, 左上x, 左上y, 右下x, 右下y):
                return False

            # 执行升级操作
            return self.执行升级(上下文, 左上x, 左上y, 右下x, 右下y)

        return False

    @staticmethod
    def 是否包含指定颜色_HSV(图像: np.ndarray, 目标RGB: tuple,
                             色差H=10, 色差S=100, 色差V=100,
                             最少像素数=1000, 是否可视化=False) -> bool:

        "H (色相),S (饱和度),V (亮度)表示这三者的偏移的容忍程度"

        # 将图像转换为 HSV
        hsv图像 = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)

        # RGB → HSV（先转 BGR 再转 HSV）
        目标色_BGR = np.uint8([[list(reversed(目标RGB))]])  # RGB -> BGR
        目标色_HSV = cv2.cvtColor(目标色_BGR, cv2.COLOR_BGR2HSV)[0][0]
        h, s, v = map(int, 目标色_HSV)  # ⚠️ 转成 int 防止溢出

        # 定义 HSV 范围上下限
        下限 = np.array([max(0, h - 色差H), max(0, s - 色差S), max(0, v - 色差V)])
        上限 = np.array([min(179, h + 色差H), min(255, s + 色差S), min(255, v + 色差V)])

        # 掩码提取
        掩码 = cv2.inRange(hsv图像, 下限, 上限)
        匹配像素数 = cv2.countNonZero(掩码)

        #print(f"目标HSV: {目标色_HSV}  匹配像素数: {匹配像素数}")

        if 是否可视化:
            cv2.imshow("原图", 图像)
            cv2.imshow("匹配掩码", 掩码)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        return 匹配像素数 >= 最少像素数

    def 检查升级条件(self, 上下文, x1, y1, x2, y2) -> bool:
        """检查资源是否足够"""
        try:
            # 颜色块检测（模拟FindColorBlock）
            区域图像 = 上下文.op.获取屏幕图像cv(x1, y1, x2, y2)

            是否有红色调偏粉色块=self.是否包含指定颜色_HSV(
                区域图像, (250, 135, 124),
                色差H=10, 色差S=10, 色差V=10,
                最少像素数=150
            )
            if 是否有红色调偏粉色块:  # 根据实际情况调整阈值
                上下文.置脚本状态("资源不足无法升级")
                raise 资源不足错误("资源不足,退出刷墙功能")
                #return False
            return True
        except 资源不足错误 as e:
            raise#捕获后再次抛出
        except Exception as e:
            上下文.置脚本状态(f"资源检查失败: {str(e)}")
            return False

    def 执行升级(
            self,
            上下文,
            x1,
            y1,
            x2,
            y2,
            已选中: bool = False,
            OCR结果=None,
    ) -> bool:
        """执行升级操作"""
        try:
            if not 已选中:
                # 旧的建议列表流程传入的是目标框，需要先点击选中。
                中心x = (x1 + x2) // 2 + random.randint(-5, 5)
                中心y = (y1 + y2) // 2 + random.randint(-5, 5)
                上下文.点击(中心x, 中心y, 延时=1500)
            else:
                # 直接扫描墙段时目标已经被点击；再次点击可能会关闭面板或
                # 进入“选择一列”，所以只等待升级面板稳定。
                上下文.置脚本状态("城墙面板已打开，不重复点击墙段")
                上下文.脚本延时(350)

            # # 选择升级资源
            # 当前金币 = 上下文.数据库.获取最新资源(上下文.机器人标志).get("金币", 0)
            # 当前圣水 = 上下文.数据库.获取最新资源(上下文.机器人标志).get("圣水", 0)


            当前金币=上下文.数据库.获取最新完整状态(上下文.机器人标志).状态数据["家乡资源"]["金币"]
            当前圣水=上下文.数据库.获取最新完整状态(上下文.机器人标志).状态数据["家乡资源"]["圣水"]
            金币费用, 圣水费用 = self.解析城墙升级费用(OCR结果)
            区域图像=上下文.op.获取屏幕图像cv(276,440,626,468)
            #区域图像=上下文.op.获取屏幕图像cv(133,428,677,491)

            金币图片 = "升级建筑的金币小图标.bmp|升级建筑的金币小图标1.bmp" if self.设置.是否刷主世界 else "升级建筑的金币小图标夜.bmp|升级建筑的金币小图标1夜.bmp"
            圣水图片 = "升级建筑的圣水小图标.bmp|升级建筑的圣水小图标1.bmp" if self.设置.是否刷主世界 else "升级建筑的圣水小图标夜.bmp|升级建筑的圣水小图标1夜.bmp"
            有金币图标,(金币x,金币y),金币调试图=self.模板识别.执行匹配(区域图像,金币图片,0.9)
            有圣水图标, (圣水x, 圣水y), _ = self.模板识别.执行匹配(区域图像, 圣水图片,0.9)
            金币x=276+金币x-27
            金币y=440+金币y+30

            圣水x=276+圣水x-27
            圣水y=440+圣水y+30


            # 屏幕图像=上下文.op.获取屏幕图像cv(0,0,800,600)
            # cv2.rectangle(屏幕图像, (圣水x, 圣水y), (圣水x+10, 圣水y+10), (0, 255, 0), 2)
            # cv2.imshow("a",屏幕图像)
            # cv2.waitKey(0)
            # cv2.destroyAllWindows()




            if 当前圣水 > 当前金币 and 有圣水图标:
                if 圣水费用 is not None and 当前圣水 < 圣水费用:
                    上下文.置脚本状态(f"圣水不足：当前{当前圣水}，城墙升级需要{圣水费用}")
                    return False
                上下文.置脚本状态("使用圣水升级")
                上下文.点击(圣水x, 圣水y, 延时=1000)
            elif 有金币图标:
                if 金币费用 is not None and 当前金币 < 金币费用:
                    上下文.置脚本状态(f"金币不足：当前{当前金币}，城墙升级需要{金币费用}")
                    return False
                上下文.置脚本状态("使用金币升级")
                上下文.点击(金币x, 金币y, 延时=1000)
            else:
                raise RuntimeError("无法定位升级按钮")
            上下文.置脚本状态("城墙升级资源入口已点击，检查二次确认框")
            return self.确认城墙升级提交(上下文)
        except Exception as e:
            上下文.置脚本状态(f"升级操作失败: {str(e)}")
            return False

    def 滑动屏幕(self, 上下文, 随机半径):
        """模拟滑动操作"""
        x = 399 if self.设置.是否刷主世界 else 450
        start_x = x + 随机半径
        start_y = 116 + 随机半径

        上下文.鼠标.移动到(start_x, start_y)
        上下文.鼠标.左键按下()

        for _ in range(10):
            dy = random.randint(7, 12)
            上下文.鼠标.移动相对位置(0,random.randint(7,12))
            #上下文.鼠标.移动到(start_x, start_y + dy)
            上下文.脚本延时(5)
        上下文.鼠标.左键抬起()

        上下文.脚本延时(random.randint(1000, 1500))
