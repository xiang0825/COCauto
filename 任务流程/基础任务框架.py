

import queue
import random
import threading
import time
import gc
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Tuple, Any, Optional

import cv2
import numpy as np

from 工具包.工具函数 import 生成贝塞尔轨迹
from 数据库.任务数据库 import 任务数据库, 机器人设置
from 核心.ADB屏幕 import ADB屏幕

from 核心.键盘操作 import 键盘控制器
from 核心.鼠标操作 import 鼠标控制器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 模块.检测.OCR识别器 import 安全OCR引擎
from 模块.检测.YOLO检测器 import 线程安全YOLO检测器

@dataclass
class 任务上下文:
    机器人标志: str
    数据库: 任务数据库
    消息队列: queue.Queue
    继续事件: threading.Event
    停止事件: threading.Event
    op: ADB屏幕
    雷电模拟器: object
    键盘:键盘控制器
    鼠标:鼠标控制器
    置脚本状态:Callable
    企业微信通知器: Optional[Any] = None  # 新增：企业微信通知器实例
    上次上报时间: float = 0.0  # 新增：上次上报的时间戳
    上报间隔秒: int = 0  # 新增：上报间隔（秒）
    上次检查上报时间: float = 0.0  # 新增：上次检查上报的时间戳（避免频繁检查）
    任务计划等待秒: float = 0.0  # 当前轮任务请求的下一次检查等待时间

    def 请求任务计划等待(self, 秒数: float, 原因: str = "") -> None:
        """请求任务计划在本轮结束后延迟再次检查。

        升级、研究等任务失败后本来已经有小时级冷却，但旧调度器仍每 5 秒
        重复进入任务并截图，既刷日志又增加 OCR/ADB 压力。等待由调度器统一
        执行，仍使用 ``脚本延时``，因此暂停和停止请求可以立即生效。
        """
        try:
            等待 = max(0.0, float(秒数))
        except (TypeError, ValueError):
            return
        # 防止错误配置造成无限长等待；用户仍可停止机器人，且下一轮最多一小时
        # 后会重新确认页面和任务状态。
        等待 = min(等待, 3600.0)
        当前等待 = getattr(self, "任务计划等待秒", 0.0)
        try:
            当前等待 = max(0.0, float(当前等待))
        except (TypeError, ValueError):
            当前等待 = 0.0
        self.任务计划等待秒 = max(当前等待, 等待)
        if 原因:
            self._任务计划等待原因 = str(原因)
    def 获取模板识别器(self):
        """每个机器人运行上下文只保留一个模板识别器引用。"""
        识别器 = getattr(self, "_共享模板识别器", None)
        if 识别器 is None:
            识别器 = 模板匹配引擎()
            self._共享模板识别器 = 识别器
        return 识别器

    def 获取OCR引擎(self):
        """延迟创建并复用 OCR 引擎，避免任务循环重复触碰 native 模型。"""
        引擎 = getattr(self, "_共享OCR引擎", None)
        if 引擎 is None:
            引擎 = 安全OCR引擎()
            self._共享OCR引擎 = 引擎
        return 引擎

    def 获取YOLO检测器(self):
        """延迟创建并复用默认 YOLO 检测器。"""
        检测器 = getattr(self, "_共享YOLO检测器", None)
        if 检测器 is None:
            检测器 = 线程安全YOLO检测器()
            self._共享YOLO检测器 = 检测器
        return 检测器

    def 释放识别模型(self) -> None:
        """机器人停止时释放 ONNX/OpenCV native 对象，避免反复运行逐渐涨内存。"""
        OCR = getattr(self, "_共享OCR引擎", None)
        释放OCR = getattr(OCR, "释放模型", None)
        if callable(释放OCR):
            try:
                释放OCR()
            except Exception:
                pass
        YOLO = getattr(self, "_共享YOLO检测器", None)
        释放YOLO = getattr(YOLO, "释放模型", None)
        if callable(释放YOLO):
            try:
                释放YOLO()
            except Exception:
                pass
        # 清除本次运行持有的截图引用；模板缓存本身有固定上限。
        self._点击识别截图 = None
        self._最近点击页面结果 = None
        self._战斗结束截图 = None
        self._战斗开始兵栏画面 = None
        self._共享OCR引擎 = None
        self._共享YOLO检测器 = None
        gc.collect()

    @staticmethod
    def 是否内存异常(异常: Exception | str) -> bool:
        文本 = str(异常 or "").lower()
        return any(
            关键词 in 文本
            for 关键词 in (
                "bad allocation", "outofmemory", "out of memory",
                "insufficient memory", "memoryerror", "low virtual memory",
                "主机内存保护", "资源耗尽",
            )
        )

    def 触发内存保护(self, 来源: str, 异常: Exception | str) -> None:
        """内存故障后只释放本进程资源并停止输入，绝不重启游戏。"""
        if getattr(self, "_内存保护已触发", False):
            return
        self._内存保护已触发 = True
        self.释放识别模型()
        self.页面恢复失败 = True
        try:
            self.停止事件.set()
        except Exception:
            pass
        self.置脚本状态(
            f"[资源保护] {来源}检测到内存异常：{异常}；"
            "已释放OCR/YOLO与截图缓存，停止所有后续截图和点击；"
            "不关闭CoC、不关闭模拟器、不重启ADB"
        )

    @property
    def 设置(self) -> 机器人设置:
        配置 = self.数据库.获取机器人设置(self.机器人标志)
        return 配置

    # def 置脚本状态(self, 日志内容:str, 超时的时间:float=60):
    #     print(f"[机器人消息] {self.机器人标志} {time.strftime('%Y年%m月%d日 %H:%M:%S')}: {日志内容}")
    #     self.数据库.记录日志(self.机器人标志, 日志内容, time.time() + 超时的时间)

    def 记录正常(self, 文本: str, 超时的时间: float = 60):
        self.置脚本状态(文本, 超时的时间)

    def 记录警告(self, 文本: str, 超时的时间: float = 60):
        try:
            self.置脚本状态(文本, 超时的时间, 级别="警告")
        except TypeError:
            # 兼容旧签名
            self.置脚本状态("[警告] " + 文本, 超时的时间)

    def 记录错误(self, 文本: str, 超时的时间: float = 60):
        try:
            self.置脚本状态(文本, 超时的时间, 级别="错误")
        except TypeError:
            self.置脚本状态("[错误] " + 文本, 超时的时间)

    def 游戏内拉远视距(self, 次数: int = 5) -> bool:
        """只对已确认在前台的 CoC 执行游戏内缩放，不触碰模拟器桌面。"""
        设备 = getattr(getattr(self, "op", None), "设备", None)
        操作 = getattr(设备, "游戏内拉远视距", None)
        if callable(操作):
            return bool(操作(次数=次数))
        self.置脚本状态("当前连接不支持安全的游戏内拉远视距，跳过缩放按键")
        return False

    def _识别中央游戏提示(self, 屏幕图像) -> dict[str, Any] | None:
        """识别遮挡主世界的教程/活动对话气泡，并返回安全点击点。

        这类对话会把主世界资源栏和入口留在背景中，导致模板识别误以为
        已经可以继续操作。不能只靠 ESC：当前 CoC 测试服的对话气泡对
        Android BACK 不响应，必须点击气泡正文推进。这里仅接受中央、
        下半屏的 OCR 文字和教程/提示关键词，绝不把顶部资源栏、商店或
        地图建筑文字当作可点击目标。
        """
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None
        try:
            高, 宽 = 屏幕图像.shape[:2]
            if 高 < 120 or 宽 < 240:
                return None
            左 = int(宽 * 0.12)
            上 = int(高 * 0.24)
            右 = int(宽 * 0.88)
            下 = int(高 * 0.92)
            区域 = 屏幕图像[上:下, 左:右]
            OCR返回 = self.获取OCR引擎()(区域)
            OCR结果 = OCR返回[0] if isinstance(OCR返回, tuple) else OCR返回
            OCR结果 = list(OCR结果 or [])
            # 部分测试服弹层的绿色“继续”按钮文字在整块中央区域中会
            # 被 RapidOCR 漏掉，但在按钮底部窄区可以识别。补做一次小
            # 区域 OCR，并把框坐标换回中央区域坐标；普通主页底部的
            # “攻击/商店”不含提示关键词，不会形成点击候选。
            # 底部窄区是补充证据，不能在每个普通延时周期都再次启动
            # OCR/ONNX；两秒最多补查一次，保持长期运行的 CPU/内存开销可控。
            当前单调时间 = time.monotonic()
            if 当前单调时间 - float(
                getattr(self, "_中央提示按钮OCR时间", 0.0)
            ) >= 2.0:
                self._中央提示按钮OCR时间 = 当前单调时间
                按钮左 = int(宽 * 0.25)
                按钮上 = int(高 * 0.72)
                按钮右 = int(宽 * 0.75)
                按钮下 = int(高 * 0.98)
                按钮OCR返回 = self.获取OCR引擎()(
                    屏幕图像[按钮上:按钮下, 按钮左:按钮右]
                )
                按钮OCR结果 = list((
                    按钮OCR返回[0]
                    if isinstance(按钮OCR返回, tuple)
                    else 按钮OCR返回
                ) or [])
                for 识别项 in 按钮OCR结果:
                    if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
                        continue
                    try:
                        原框 = 识别项[0]
                        偏移框 = [
                            [
                                float(点[0]) + 按钮左 - 左,
                                float(点[1]) + 按钮上 - 上,
                            ]
                            for 点 in 原框
                        ]
                        OCR结果.append((偏移框, 识别项[1], *识别项[2:]))
                    except (TypeError, ValueError, IndexError):
                        continue
        except Exception as 异常:
            if self.是否内存异常(异常):
                self.触发内存保护("中央提示OCR", 异常)
            return None

        提示关键词 = (
            "首领", "就是你", "新晋", "欢迎", "恭喜", "冠军", "奖励",
            "记得", "领取", "村长", "解锁", "能力", "護盾", "护盾",
            "魔法護盾", "魔法护盾", "繼續", "继续", "继續", "继绩",
            "繼績", "reward", "welcome",
            "congrat", "leader", "chief",
        )
        命中 = []
        for 识别项 in OCR结果:
            if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
                continue
            文本 = self._规范升级弹窗OCR文本(识别项[1])
            if not 文本 or not any(关键词.lower() in 文本 for 关键词 in 提示关键词):
                continue
            框 = self._解析升级弹窗OCR框(识别项)
            if 框 is None:
                continue
            x1, y1, x2, y2 = 框
            中心x = (x1 + x2) / 2 + 左
            中心y = (y1 + y2) / 2 + 上
            # 只接受中央对话正文；顶部资源栏、右下商店和普通建筑
            # 标签都不在这个区域内。
            if not (
                宽 * 0.18 <= 中心x <= 宽 * 0.82
                and 高 * 0.48 <= 中心y <= 高 * 0.88
            ):
                continue
            命中.append((x1, y1, x2, y2, 中心x, 中心y, 文本))

        if not 命中:
            return None
        def 是继续按钮文本(文本内容: str) -> bool:
            return any(
                关键词 in 文本内容
                for 关键词 in ("繼續", "继续", "继續", "继绩", "繼績")
            )

        # 测试服偶尔只识别到能力说明正文，漏掉绿色按钮上的“继续”。
        # 正文只能作为“确实存在中央提示”的证据，不能作为点击点；
        # 此时在同一帧下方寻找宽阔的绿色按钮几何，避免点击说明文字。
        绿色按钮中心 = None
        try:
            hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)
            绿色 = cv2.inRange(
                hsv,
                np.array([35, 45, 55], dtype=np.uint8),
                np.array([95, 255, 255], dtype=np.uint8),
            )
            高度, 宽度 = 屏幕图像.shape[:2]
            绿色[: int(高度 * 0.68), :] = 0
            绿色[:, : int(宽度 * 0.18)] = 0
            绿色[:, int(宽度 * 0.82) :] = 0
            绿色 = cv2.morphologyEx(
                绿色, cv2.MORPH_CLOSE, np.ones((5, 9), dtype=np.uint8)
            )
            轮廓, _ = cv2.findContours(
                绿色, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            候选按钮 = []
            for 轮廓项 in 轮廓:
                x, y, w, h = cv2.boundingRect(轮廓项)
                面积 = w * h
                if (
                    w >= 宽度 * 0.12
                    and h >= 高度 * 0.06
                    and h <= 高度 * 0.20
                    and 2.0 <= w / max(h, 1) <= 6.5
                    and y + h / 2 >= 高度 * 0.76
                    and 面积 >= 宽度 * 高度 * 0.006
                ):
                    候选按钮.append((面积, x + w / 2, y + h / 2))
            if 候选按钮:
                _, 按钮x, 按钮y = max(候选按钮)
                绿色按钮中心 = (
                    int(round(按钮x * 800 / 宽度)),
                    int(round(按钮y * 600 / 高度)),
                )
        except (cv2.error, TypeError, ValueError):
            绿色按钮中心 = None

        明确继续 = [项 for 项 in 命中 if 是继续按钮文本(项[6])]
        def 是中央底部安全按钮(点击点) -> bool:
            """教程/能力提示的继续按钮必须位于画面中央。"""
            try:
                点击x, 点击y = 点击点
                # 主世界左下区域包含世界切换飞艇、攻击入口和其它常驻
                # HUD。教程正文关键词一旦被地图 OCR 误命中，旧版绿色
                # 几何回退会把这些控件当成“继续”，实际把主世界切到
                # 夜世界。真正的能力/教程继续按钮在中央下方安全带内。
                return (
                    800 * 0.32 <= float(点击x) <= 800 * 0.68
                    and 600 * 0.72 <= float(点击y) <= 600 * 0.90
                )
            except (TypeError, ValueError):
                return False

        if not 明确继续 and 绿色按钮中心 is not None:
            # 只有在提示正文已经命中关键词、且底部绿色按钮同帧存在时，
            # 才允许用几何按钮中心代替漏掉的按钮 OCR。
            if not 是中央底部安全按钮(绿色按钮中心):
                return None
            _, _, _, _, _, _, 文本 = max(
                命中,
                key=lambda 项: (项[2] - 项[0]) * (项[3] - 项[1]),
            )
            return {"文本": 文本, "点击点": 绿色按钮中心}

        # 能力说明页的正文框比底部绿色“继续”按钮更大。优先选择
        # 明确的继续文字，并要求它位于下方按钮区域。没有按钮文字或
        # 绿色按钮几何时安全停止，不回退到说明正文点击。
        if not 明确继续:
            return None
        _, _, _, _, 中心x, 中心y, 文本 = max(
            明确继续,
            key=lambda 项: (
                1 if 项[5] >= 高 * 0.70 else 0,
                (项[2] - 项[0]) * (项[3] - 项[1]),
            ),
        )
        点击点 = (
            int(round(中心x * 800 / 宽)),
            int(round(中心y * 600 / 高)),
        )
        if not 是中央底部安全按钮(点击点):
            return None
        return {
            "文本": 文本,
            "点击点": 点击点,
        }

    def 清理中央游戏提示(self, 屏幕图像=None) -> bool:
        """点击一页已确认的中央提示，返回是否确实处理了提示。"""
        if bool(getattr(self, "_战斗中", False)):
            return False
        if 屏幕图像 is None:
            try:
                屏幕图像 = self.op.获取屏幕图像cv(
                    0, 0, 800, 600, 强制刷新=True
                )
            except TypeError:
                屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
        候选 = self._识别中央游戏提示(屏幕图像)
        if not 候选:
            return False
        x, y = 候选["点击点"]
        self.置脚本状态(
            f"检测到中央教程/活动提示：{候选['文本']}；"
            f"点击对话气泡{ x},{ y}推进，不进入商店或宝石页面"
        )
        if not self.点击已确认安全按钮(x, y, 延时=220):
            self.页面恢复失败 = True
            self.置脚本状态("中央教程/活动提示点击失败，禁止继续操作")
            return False
        # 清除点击前缓存，下一页必须重新抓取同一 CoC display 的画面。
        self._点击识别截图 = None
        self._点击识别截图时间 = 0.0
        return True

    @staticmethod
    def _规范升级弹窗OCR文本(文本: Any) -> str:
        """把升级弹窗 OCR 文本压缩成便于安全匹配的形式。"""
        return str(文本 or "").strip().lower().replace(" ", "").replace("\n", "")

    @classmethod
    def _OCR确认英雄升级详情(cls, OCR结果) -> bool:
        """确认当前详情卡属于英雄，而不是普通建筑升级卡。

        英雄详情页同样会露出“取消/立即完成”和右上角红色 X。若只看
        这些通用结构，主页点击护栏会把英雄详情当成普通建筑详情关闭，
        使英雄任务永远拿不到升级页。这里要求英雄名称（或英雄殿堂）
        与升级详情结构同时出现，才把页面交回英雄任务处理。
        """
        文本 = "".join(
            cls._规范升级弹窗OCR文本(项[1])
            for 项 in (OCR结果 or [])
            if isinstance(项, (list, tuple)) and len(项) > 1
        )
        if not 文本:
            return False
        # 国际服测试服可能返回繁体或少量简繁混合 OCR。
        for 原字, 新字 in {
            "蠻": "蛮", "靈": "灵", "飛": "飞", "戰": "战",
            "護": "护", "龍": "龙", "級": "级", "餘": "余",
            "將": "将", "傷": "伤", "類": "类", "擊": "击",
            "間": "间", "動": "动", "時": "时", "確": "确",
            "進": "进", "行": "行", "築": "筑",
        }.items():
            文本 = 文本.replace(原字, 新字)
        英雄名称 = (
            "野蛮人之王", "弓箭女皇", "亡灵王子", "大守护者",
            "飞盾战神", "飞龙公爵",
        )
        有英雄名称 = any(名称 in 文本 for 名称 in 英雄名称)
        有英雄殿堂 = "英雄殿堂" in 文本
        有基础升级结构 = any(词 in 文本 for 词 in (
            "升级", "升至", "正在将", "正在进行升级",
        )) and any(词 in 文本 for 词 in (
            "取消", "立即完成", "剩余时间", "升级时间", "通行证",
            "加速建筑", "加速建筑工人",
        ))
        # 测试服/国际服部分版本会把野蛮人之王 OCR 成“巨人”，且
        # 确认页不显示“取消/立即完成”。英雄详情仍稳定包含生命值、
        # 每秒伤害、移动速度和所需空间等单位属性；与“升至+升级时间”
        # 同时出现时足以区别普通建筑详情，允许世界拖动护栏安全关 X。
        有英雄属性结构 = (
            any(词 in 文本 for 词 in ("生命值", "每秒伤害值", "移动速度"))
            and any(词 in 文本 for 词 in ("所需空间", "攻击偏好", "伤害类型"))
        )
        有确认升级结构 = (
            "升至" in 文本
            and any(词 in 文本 for 词 in ("确认", "升级时间", "通行证"))
        )
        有升级结构 = 有基础升级结构 or 有确认升级结构
        return (有英雄名称 or 有英雄殿堂 or 有英雄属性结构) and 有升级结构

    def _当前画面是英雄升级详情(self, 屏幕图像) -> bool:
        """用同一帧 OCR 判断是否应交给英雄任务继续处理。"""
        try:
            OCR返回 = self.获取OCR引擎()(屏幕图像)
            OCR结果 = OCR返回[0] if isinstance(OCR返回, tuple) else OCR返回
            return self._OCR确认英雄升级详情(OCR结果)
        except Exception:
            # 护栏 OCR 失败时不能授权任何点击，交给原有普通护栏继续
            # 按“未知/不可确认”处理。
            return False

    @staticmethod
    def _解析升级弹窗OCR框(识别项) -> tuple[float, float, float, float] | None:
        """兼容 RapidOCR 四点框和测试中常用的矩形框格式。"""
        if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
            return None
        框 = 识别项[0]
        try:
            if len(框) == 4 and all(
                isinstance(点, (list, tuple)) and len(点) >= 2 for 点 in 框
            ):
                xs = [float(点[0]) for 点 in 框]
                ys = [float(点[1]) for 点 in 框]
                return min(xs), min(ys), max(xs), max(ys)
            if len(框) == 4 and all(isinstance(值, (int, float)) for 值 in 框):
                x1, y1, x2, y2 = (float(值) for 值 in 框)
                return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        except (TypeError, ValueError, IndexError):
            return None
        return None

    def _识别升级完成弹窗(self, 屏幕图像) -> dict[str, Any] | None:
        """只返回经过文字和位置双重确认的升级完成弹窗候选。

        这里故意不使用“确定”按钮模板单独做触发条件。CoC 的胜利、
        登录、商店和购买页面都可能有相同按钮，必须先看到明确的升级/能力
        完成文字，才能把底部按钮交给自动确认流程。
        """
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None
        try:
            高, 宽 = 屏幕图像.shape[:2]
            左, 上 = 80, 45
            右, 下 = min(int(宽), 780), min(int(高), 590)
            if 右 <= 左 or 下 <= 上:
                return None
            区域 = 屏幕图像[上:下, 左:右]
            OCR返回 = self.获取OCR引擎()(区域)
            OCR结果 = OCR返回[0] if isinstance(OCR返回, tuple) else OCR返回
            OCR结果 = OCR结果 or []
        except Exception as 异常:
            if self.是否内存异常(异常):
                self.触发内存保护("升级完成弹窗OCR", 异常)
            else:
                上次错误 = float(getattr(self, "_升级完成弹窗错误时间", 0.0))
                当前时间 = time.monotonic()
                if 当前时间 - 上次错误 >= 5.0:
                    self.置脚本状态(f"升级完成弹窗识别暂时失败：{异常}")
                    self._升级完成弹窗错误时间 = 当前时间
            return None

        规范项 = []
        for 识别项 in OCR结果:
            if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
                continue
            文本 = self._规范升级弹窗OCR文本(识别项[1])
            if not 文本:
                continue
            框 = self._解析升级弹窗OCR框(识别项)
            if 框 is None:
                continue
            x1, y1, x2, y2 = 框
            规范项.append((文本, (x1 + 左, y1 + 上, x2 + 左, y2 + 上)))

        if not 规范项:
            return None
        全部文本 = "".join(文本 for 文本, _ in 规范项)
        # “立即完成/使用宝石/商店”优先级最高，哪怕 OCR 同时误识别出
        # “升级完成”，也绝不能自动点击。
        危险词 = (
            "宝石", "商店", "购买", "补充", "使用宝石", "花费宝石",
            "立即完成", "立即升级", "gems", "shop", "buy", "finishnow",
        )
        if any(词 in 全部文本 for 词 in 危险词):
            return None

        完成词 = (
            "升级完成", "升级完毕", "研究完成", "研究完毕", "建筑完成",
            "建筑升级完成", "英雄升级完成", "战宠升级完成", "能力已解锁",
            "解锁能力", "能力升级完成", "upgradecomplete", "upgradecompleted",
            "researchcomplete", "buildingcomplete", "abilityunlocked",
            "给予能力", "授予能力", "获得能力", "giveability",
        )
        命中完成词 = next((词 for 词 in 完成词 if 词 in 全部文本), None)
        if not 命中完成词:
            return None

        确认词 = ("确认", "确定", "继续", "confirm", "ok")
        候选按钮 = []
        for 文本, (x1, y1, x2, y2) in 规范项:
            if not any(词 in 文本 for 词 in 确认词):
                continue
            中心x = (x1 + x2) / 2
            中心y = (y1 + y2) / 2
            # 只接受中央弹窗下方的按钮，屏蔽资源栏、地图和右上角控件。
            if 250 <= 中心x <= 760 and 385 <= 中心y <= 570:
                候选按钮.append((中心y, 中心x, int(round(中心x)), int(round(中心y)), 文本))
        if not 候选按钮:
            return None

        _, _, 按钮x, 按钮y, 按钮文本 = max(候选按钮)
        return {
            "完成词": 命中完成词,
            "确认文本": 按钮文本,
            "确认点": (按钮x, 按钮y),
            "摘要": f"{命中完成词}+{按钮文本}",
        }

    def 自动确认升级完成弹窗(self) -> bool:
        """低频检查并安全确认升级完成弹窗，返回本次是否点击。

        默认关闭，用户在“任务计划 -> 升级完成弹窗确认”中开启后才运行。
        同一弹窗必须连续两次识别成功才会点击，避免过渡帧或 OCR 偶发误报。
        """
        if getattr(self, "_升级完成弹窗检查中", False):
            return False
        try:
            if not bool(getattr(self.设置, "是否自动确认升级完成", False)):
                return False
        except Exception:
            return False
        if (
            getattr(self, "_内存保护已触发", False)
            or bool(getattr(self, "_战斗中", False))
        ):
            return False

        当前时间 = time.monotonic()
        上次检查 = float(getattr(self, "_升级完成弹窗检查时间", 0.0))
        # 升级完成弹窗会持续显示，不需要高频 OCR。5 秒一帧可以明显
        # 降低 RapidOCR native session 和 ADB screencap 的长期提交内存，
        # 同时保留两帧确认，避免误点。
        # 任务计划进入小时级冷却时，页面已经在本轮末尾确认过，
        # 不需要每 5 秒启动一次 ADB screencap/OCR。仍保留低频检查，
        # 这样升级完成弹窗不会被永久漏掉，同时显著降低长期运行压力。
        检查间隔 = self._升级完成弹窗检查间隔()
        if 当前时间 - 上次检查 < 检查间隔:
            return False
        self._升级完成弹窗检查时间 = 当前时间
        self._升级完成弹窗检查中 = True
        try:
            # 先执行现有宝石/商店护栏。它只会在明确危险模板命中时发送
            # 一次安全 ESC；命中后本次升级确认检查立即结束，绝不抢点。
            if self.检查宝石商店危险页面():
                self._升级完成弹窗候选 = None
                return False
            页面结果 = getattr(self, "_最近点击页面结果", None)
            if 页面结果 is not None and 页面结果.页面 in {"战斗中", "战斗结算", "战斗过渡"}:
                return False

            # 宝石护栏刚刚已经拿过一张画面；这里复用短缓存，避免一次
            # 检查连续启动两次 screencap，尤其避免长期运行时拖高模拟器。
            屏幕图像 = self._获取点击识别截图(强制=False)
            候选 = self._识别升级完成弹窗(屏幕图像)
            if not 候选:
                self._升级完成弹窗候选 = None
                return False

            确认点 = 候选["确认点"]
            指纹 = (候选["完成词"], 候选["确认文本"], round(确认点[0] / 8), round(确认点[1] / 8))
            上次候选 = getattr(self, "_升级完成弹窗候选", None)
            if not isinstance(上次候选, tuple) or len(上次候选) != 2:
                self._升级完成弹窗候选 = (指纹, 当前时间)
                self.置脚本状态(f"升级完成弹窗待二次确认：{候选['摘要']}")
                return False
            旧指纹, 旧时间 = 上次候选
            if 旧指纹 != 指纹 or 当前时间 - float(旧时间) > 4.0:
                self._升级完成弹窗候选 = (指纹, 当前时间)
                self.置脚本状态(f"升级完成弹窗识别已更新，等待稳定确认：{候选['摘要']}")
                return False

            self._升级完成弹窗点击中 = True
            try:
                点击成功 = self.点击已确认安全按钮(
                    确认点[0], 确认点[1], 延时=180
                )
            finally:
                self._升级完成弹窗点击中 = False
            if 点击成功:
                self._升级完成弹窗候选 = None
                self.置脚本状态(
                    f"升级完成弹窗已确认：{候选['摘要']}，点击{确认点[0]},{确认点[1]}"
                )
                return True
            self.置脚本状态("升级完成弹窗确认按钮输入被拒绝，保持当前画面不重复点击")
            self._升级完成弹窗候选 = None
            return False
        finally:
            self._升级完成弹窗检查中 = False

    def _升级完成弹窗检查间隔(self) -> float:
        """返回升级完成弹窗的维护检查间隔（秒）。"""
        return 30.0 if bool(getattr(self, "_任务计划长时间等待", False)) else 5.0

    def 处理战斗星级奖励弹窗(self, 强制=True) -> bool:
        """安全确认夜世界战斗后的“胜利之星奖励”弹窗。

        该弹窗底下仍保留主页资源栏，若直接按主页识别结果继续任务，
        下一轮攻击按钮会被弹窗遮挡。只有页面识别器同时确认蓝紫面板和
        中央绿色确定按钮时才允许精确点击；识别不到时保持阻断，不发送
        ESC、不进入商店，也不点击任何宝石入口。
        """
        if getattr(self, "_内存保护已触发", False) or bool(getattr(self, "_战斗中", False)):
            return False
        try:
            识别器 = self._获取点击页面识别器()
            屏幕图像 = self._获取点击识别截图(强制=bool(强制))
            页面结果 = 识别器.识别(屏幕图像, 战斗中=False)
            if getattr(页面结果, "页面", "") != "战斗星级奖励":
                if str(getattr(页面结果, "页面", "")).endswith("主页"):
                    self._战斗结束已确认 = False
                return False
            确认点 = 识别器.定位战斗星级奖励确定按钮(屏幕图像)
            if 确认点 is None:
                self.置脚本状态("已识别星级奖励弹窗但未确认按钮位置，阻止后续输入")
                return True
            点击成功 = self.点击已确认安全按钮(
                确认点[0], 确认点[1], 延时=300
            )
            if not 点击成功:
                self.置脚本状态("星级奖励确认按钮输入被拒绝，保持当前画面")
                return True
            self._战斗结束已确认 = False
            self._点击识别截图 = None
            self._点击识别截图时间 = 0.0
            self.置脚本状态(
                f"已确认夜世界星级奖励弹窗，安全点击确定：{确认点[0]},{确认点[1]}"
            )
            return True
        except Exception as 异常:
            self.置脚本状态(f"星级奖励弹窗处理失败，阻止后续输入：{异常}")
            return True

    @staticmethod
    def _检测升级详情弹窗关闭点(屏幕图像) -> tuple[int, int] | None:
        """只检测升级详情弹窗右上角的红色关闭按钮。

        CoC 的“正在升级/立即完成”面板没有稳定的文字模板，而且不同
        版本的标题会在简体、繁体和活动名称之间变化。宝石按钮绝不能
        作为恢复目标，所以这里不做 OCR 点击，也不返回底部绿色按钮；
        只有同时满足中央灰色标题栏、右上角红色方形按钮和尺寸约束时，
        才返回一个可安全关闭的参考坐标。
        """
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None
        try:
            高, 宽 = 屏幕图像.shape[:2]
            if 高 < 120 or 宽 < 240 or len(屏幕图像.shape) < 3:
                return None
            hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)

            # 升级详情弹窗的标题栏位于中央上方，颜色偏灰且饱和度低；
            # 这一步用于排除主世界右侧其它红色控件。
            标题栏 = hsv[
                int(高 * 0.035):int(高 * 0.14),
                int(宽 * 0.08):int(宽 * 0.82),
            ]
            if 标题栏.size == 0:
                return None
            低饱和明亮像素 = cv2.inRange(
                标题栏,
                (0, 0, 55),
                (180, 105, 235),
            )
            标题栏支持度 = cv2.countNonZero(低饱和明亮像素) / float(
                标题栏.shape[0] * 标题栏.shape[1]
            )
            if 标题栏支持度 < 0.60:
                return None

            色相 = hsv[:, :, 0]
            红色遮罩 = (
                ((色相 <= 15) | (色相 >= 165))
                & (hsv[:, :, 1] >= 100)
                & (hsv[:, :, 2] >= 100)
            ).astype("uint8")
            # 只看中央弹窗预期的右上角，排除最右侧主世界控件。
            x起点, x终点 = int(宽 * 0.80), int(宽 * 0.95)
            y终点 = int(高 * 0.20)
            区域 = 红色遮罩[:y终点, x起点:x终点]
            if 区域.size == 0:
                return None
            区域 = cv2.morphologyEx(
                区域,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            )
            _, _, 统计, 重心 = cv2.connectedComponentsWithStats(区域, 8)
            候选 = []
            for 序号 in range(1, len(统计)):
                x, y, 方宽, 方高, 面积 = [int(值) for 值 in 统计[序号]]
                全局x = x + x起点
                全局y = y
                中心x, 中心y = [float(值) for 值 in 重心[序号]]
                中心x += x起点
                if not (
                    宽 * 0.83 <= 中心x <= 宽 * 0.925
                    and 高 * 0.025 <= 中心y <= 高 * 0.16
                    and 宽 * 0.025 <= 方宽 <= 宽 * 0.085
                    and 高 * 0.045 <= 方高 <= 高 * 0.14
                    and 面积 >= 方宽 * 方高 * 0.25
                    and 方宽 / max(1, 方高) <= 1.8
                ):
                    continue
                候选.append((面积, 全局x, 全局y, 方宽, 方高, 中心x, 中心y))
            if not 候选:
                return None

            # 主世界活动弹窗的右上角 X 可能同时落在同一几何范围内，
            # 且通常比升级详情 X 更靠右。升级详情的 X 在实际 CoC 布局
            # 约占宽度 0.83；有多个候选时优先这个内侧候选，避免把活动
            # 弹窗的 X 当成升级面板关闭点。单个候选仍保留宽屏兼容范围，
            # 以免固定分辨率测试或主题布局被误拒绝。
            内侧候选 = [项 for 项 in 候选 if 项[5] <= 宽 * 0.86]
            _, _, _, _, _, 中心x, 中心y = max(
                内侧候选 or 候选,
                key=lambda 项: 项[0],
            )
            # 上层所有输入都使用 800×600 参考画布；这里统一换算，
            # 因而 1280×720、1920×1080 等截图仍能点击同一视觉位置。
            return (
                int(round(中心x * 800 / 宽)),
                int(round(中心y * 600 / 高)),
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    @staticmethod
    def _检测主世界活动弹窗关闭点(屏幕图像) -> tuple[int, int] | None:
        """识别覆盖主世界的活动/奖励弹窗右上角红色 X。

        CoC 会在主世界上方弹出赛季、活动或奖励面板。资源栏和家乡入口
        仍然露在弹窗后面，单靠主页锚点会误以为页面可操作。这里仅接受
        右上区域内带白色 X 的红色方形按钮，并要求同时存在大面积中央面板；
        主世界常驻红色徽标没有白色 X 或面板证据，不会触发。
        """
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None
        try:
            高, 宽 = 屏幕图像.shape[:2]
            if 高 < 300 or 宽 < 500 or len(屏幕图像.shape) < 3:
                return None
            hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)
            色相 = hsv[:, :, 0]
            红色 = (
                ((色相 <= 15) | (色相 >= 165))
                & (hsv[:, :, 1] >= 115)
                & (hsv[:, :, 2] >= 120)
            ).astype(np.uint8)
            x起点, x终点 = int(宽 * 0.78), int(宽 * 0.98)
            y终点 = int(高 * 0.24)
            区域 = 红色[:y终点, x起点:x终点]
            if 区域.size == 0:
                return None
            区域 = cv2.morphologyEx(
                区域,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
            )
            _, _, 统计, 重心 = cv2.connectedComponentsWithStats(区域, 8)
            灰度 = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2GRAY)
            候选 = []
            for 序号 in range(1, len(统计)):
                x, y, 方宽, 方高, 面积 = [int(值) for 值 in 统计[序号]]
                中心x, 中心y = [float(值) for 值 in 重心[序号]]
                中心x += x起点
                if not (
                    # 高分辨率/右锚定活动面板的关闭 X 可能贴近屏幕右边缘；
                    # 旧上限 0.96 会把 1280×720 实机的中心 x=1229 排除，
                    # 随后世界切换入口会被活动面板遮挡。
                    宽 * 0.82 <= 中心x <= 宽 * 0.98
                    and 高 * 0.025 <= 中心y <= 高 * 0.20
                    and 宽 * 0.025 <= 方宽 <= 宽 * 0.10
                    and 高 * 0.035 <= 方高 <= 高 * 0.16
                    and 面积 >= 方宽 * 方高 * 0.22
                    and 0.55 <= 方宽 / max(1, 方高) <= 1.8
                ):
                    continue
                左 = max(0, x + x起点)
                上 = max(0, y)
                右 = min(宽, 左 + 方宽)
                下 = min(高, 上 + 方高)
                if 右 <= 左 or 下 <= 上:
                    continue
                灰色块 = 灰度[上:下, 左:右]
                饱和度 = hsv[上:下, 左:右, 1]
                亮白 = (饱和度 < 100) & (灰色块 > 180)
                if int(np.count_nonzero(亮白)) < max(8, int(方宽 * 方高 * 0.015)):
                    continue
                面板区域 = 灰度[
                    int(高 * 0.08):int(高 * 0.88),
                    int(宽 * 0.08):int(宽 * 0.90),
                ]
                if 面板区域.size == 0:
                    continue
                中央亮度 = float(np.mean(面板区域))
                边缘亮度 = float(np.mean(np.concatenate((
                    灰度[:max(1, int(高 * 0.08))].ravel(),
                    灰度[int(高 * 0.92):].ravel(),
                ))))
                # 不同活动主题的面板与主世界对比度可能很低；只用作
                # 辅助证据，红色 X 和白色交叉线仍是必要条件。
                if abs(中央亮度 - 边缘亮度) < 5.0:
                    continue
                候选.append((面积, 中心x, 中心y))
            if not 候选:
                return None
            _, 中心x, 中心y = max(候选, key=lambda 项: 项[0])
            return (
                int(round(中心x * 800 / 宽)),
                int(round(中心y * 600 / 高)),
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def _检测主世界建筑详情关闭点(self, 屏幕图像) -> tuple[int, int] | None:
        """识别主世界选中建筑详情面板的安全关闭点。

        实机测试服会在主世界中央保留“取消/立即完成/加速建筑”等建筑
        详情面板。主页攻击按钮仍然可见，但点击会被面板吞掉；这个面板
        不能用 ESC 关闭，因为根页面误发 ESC 可能回到模拟器桌面。只有
        OCR 同时确认详情按钮结构，并在右上角找到红色关闭控件时，才返
        回关闭点；绝不使用底部“立即完成”或宝石坐标。
        """
        if 屏幕图像 is None or not hasattr(屏幕图像, "shape"):
            return None
        try:
            高, 宽 = 屏幕图像.shape[:2]
            if 高 < 300 or 宽 < 500 or len(屏幕图像.shape) < 3:
                return None
            OCR返回 = self.获取OCR引擎()(屏幕图像)
            OCR结果 = OCR返回[0] if isinstance(OCR返回, tuple) else OCR返回
            文本 = "".join(
                self._规范升级弹窗OCR文本(项[1])
                for 项 in (OCR结果 or [])
                if isinstance(项, (list, tuple)) and len(项) > 1
            )
            有取消 = "取消" in 文本
            有立即完成 = any(词 in 文本 for 词 in (
                "立即完成", "立即完成", "加速建筑", "加速建筑工人",
            ))
            if not (有取消 and 有立即完成):
                return None

            hsv = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2HSV)
            色相 = hsv[:, :, 0]
            红色遮罩 = (
                ((色相 <= 15) | (色相 >= 165))
                & (hsv[:, :, 1] >= 70)
                & (hsv[:, :, 2] >= 60)
            ).astype("uint8")
            x起点, x终点 = int(宽 * 0.90), int(宽 * 0.995)
            y终点 = int(高 * 0.20)
            区域 = 红色遮罩[:y终点, x起点:x终点]
            if 区域.size == 0:
                return None
            区域 = cv2.morphologyEx(
                区域,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            )
            _, _, 统计, 重心 = cv2.connectedComponentsWithStats(区域, 8)
            候选 = []
            for 序号 in range(1, len(统计)):
                x, y, 方宽, 方高, 面积 = [int(值) for 值 in 统计[序号]]
                中心x, 中心y = [float(值) for 值 in 重心[序号]]
                中心x += x起点
                if not (
                    宽 * 0.90 <= 中心x <= 宽 * 0.995
                    and 高 * 0.025 <= 中心y <= 高 * 0.20
                    and 4 <= 方宽 <= 宽 * 0.10
                    and 4 <= 方高 <= 高 * 0.12
                    and 面积 >= 8
                ):
                    continue
                候选.append((面积, 中心x, 中心y))
            if not 候选:
                return None
            _, 中心x, 中心y = max(候选, key=lambda 项: 项[0])
            return (
                int(round(中心x * 800 / 宽)),
                int(round(中心y * 600 / 高)),
            )
        except (AttributeError, TypeError, ValueError, cv2.error):
            return None

    def 清理主世界活动弹窗(self, 屏幕图像=None) -> bool:
        """关闭已确认的主世界活动弹窗；识别不清时绝不点击。"""
        if bool(getattr(self, "_战斗中", False)):
            return False
        try:
            if 屏幕图像 is None:
                try:
                    屏幕图像 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)

            # 活动/建筑面板的几何 X 可能在夜世界或其它页面中出现相似
            # 形状。先用轻量页面识别确认上下文；夜世界、战斗、结算和
            # 未知页一律不把右上角 X 当作“主世界活动弹窗”来点，避免
            # 启动阶段在夜世界反复点击错误坐标而卡死登录检测。
            try:
                页面结果 = self._获取点击页面识别器().识别(
                    屏幕图像,
                    战斗中=False,
                )
                if (
                    getattr(页面结果, "页面", "") != "主世界主页"
                    or getattr(页面结果, "世界", "") != "主世界"
                ):
                    return False
            except Exception:
                # 页面识别器不可用时继续使用下面的专用 OCR/几何复核；
                # 不能因为诊断器异常直接发送关闭点击。
                return False

            # 英雄详情页会同时露出主页 HUD、普通升级结构和红色 X。
            # 它必须留给英雄升级任务处理，不能被主世界通用清理器关掉。
            if self._当前画面是英雄升级详情(屏幕图像):
                self.置脚本状态(
                    "检测到英雄升级详情，交由英雄任务继续处理；"
                    "主世界护栏不关闭、不点击立即完成或宝石"
                )
                return False
            关闭点 = self._检测主世界活动弹窗关闭点(屏幕图像)
            关闭说明 = "主世界活动/奖励弹窗"
            if 关闭点 is None:
                关闭点 = self._检测主世界建筑详情关闭点(屏幕图像)
                关闭说明 = "主世界建筑详情面板"
            if 关闭点 is None:
                return False

            # 英雄详情的 X 关闭后，测试服会短暂保留英雄殿堂列表。该
            # 列表仍露出主世界 HUD，并且右上角可能有一个与面板 X 相似
            # 的红色控件；不能沿用普通活动/建筑面板坐标，否则会点到
            # HUD 或让殿堂列表继续覆盖后续任务。先用同一帧 OCR 确认
            # 英雄殿堂，再点击已经验证过的顶部英雄入口（逻辑坐标
            # 356,33）关闭，禁止 ESC/BACK 和底部立即完成/宝石按钮。
            def 识别英雄殿堂文字(图像):
                if 图像 is None or not hasattr(图像, "shape"):
                    return ""
                高, 宽 = 图像.shape[:2]
                左 = int(宽 * 250 / 800)
                上 = int(高 * 55 / 600)
                右 = int(宽 * 710 / 800)
                下 = int(高 * 590 / 600)
                裁剪 = 图像[上:下, 左:右]
                if 裁剪.size == 0:
                    return ""
                OCR返回 = self.获取OCR引擎()(裁剪)
                OCR结果 = OCR返回[0] if isinstance(OCR返回, tuple) else OCR返回
                return "".join(
                    self._规范升级弹窗OCR文本(项[1])
                    for 项 in (OCR结果 or [])
                    if isinstance(项, (list, tuple)) and len(项) > 1
                )

            try:
                英雄文本 = 识别英雄殿堂文字(屏幕图像)
            except Exception:
                英雄文本 = ""
            # 底层英雄建筑详情卡也会显示“英雄殿堂[等级]”，但没有
            # “建议升级/可使用”列表段；必须命中列表特征才允许再次点
            # 顶部入口，避免把详情卡误判成殿堂列表而反复点击入口。
            英雄殿堂仍在 = (
                "英雄殿堂" in 英雄文本
                and ("建议升级" in 英雄文本 or "可使用" in 英雄文本)
            )
            if 英雄殿堂仍在:
                self.置脚本状态(
                    "检测到英雄殿堂列表，改用顶部英雄入口安全关闭；"
                    "禁止点击右上角相似控件、立即完成和宝石"
                )
                if not self.点击已确认安全按钮(356, 33, 延时=700):
                    self.页面恢复失败 = True
                    self.置脚本状态(
                        "英雄殿堂顶部入口关闭输入未通过安全复核，禁止继续点击"
                    )
                    return False
                清理缓存 = getattr(self.op, "清理截图缓存", None)
                if callable(清理缓存):
                    清理缓存()
                for _ in range(6):
                    self.脚本延时(250)
                    try:
                        try:
                            新画面 = self.op.获取屏幕图像cv(
                                0, 0, 800, 600, 强制刷新=True
                            )
                        except TypeError:
                            新画面 = self.op.获取屏幕图像cv(0, 0, 800, 600)
                        新文本 = 识别英雄殿堂文字(新画面)
                        新殿堂仍在 = (
                            "英雄殿堂" in 新文本
                            and ("建议升级" in 新文本 or "可使用" in 新文本)
                        )
                        if not 新殿堂仍在:
                            self.置脚本状态(
                                "英雄殿堂列表已通过顶部入口安全关闭"
                            )
                            return True
                    except Exception as 异常:
                        self.置脚本状态(
                            f"英雄殿堂关闭后复核失败，继续等待新画面：{异常}"
                        )
                self.页面恢复失败 = True
                self.置脚本状态(
                    "英雄殿堂顶部入口重试后仍未关闭，禁止后续点击"
                )
                return False
            self.置脚本状态(
                f"检测到{关闭说明}，安全关闭右上角X：{关闭点[0]},{关闭点[1]}"
            )
            if not self.点击已确认安全按钮(
                关闭点[0], 关闭点[1], 延时=260
            ):
                self.页面恢复失败 = True
                self.置脚本状态("活动弹窗关闭输入未通过安全复核，禁止继续点击")
                return False
            清理缓存 = getattr(self.op, "清理截图缓存", None)
            if callable(清理缓存):
                清理缓存()
            return True
        except Exception as 异常:
            self.页面恢复失败 = True
            self.置脚本状态(f"活动弹窗关闭失败，禁止继续点击：{异常}")
            return False

    def 清理选择卡片弹窗(self, 屏幕图像=None) -> bool:
        """关闭已确认的选择卡片弹窗，并确认回到主世界或断线恢复页。

        测试服的超级部队选择卡片会覆盖主世界 HUD，不能复用普通
        活动弹窗清理器：后者要求当前页已经是主世界。这里先由页面
        识别器确认“中央红色卡片 + 右上角白色 X”，只点击该 X，禁止
        点击卡片、购买、确认或任何宝石入口。
        """
        if bool(getattr(self, "_战斗中", False)):
            return False
        if getattr(self, "_内存保护已触发", False):
            return False
        try:
            if 屏幕图像 is None:
                try:
                    屏幕图像 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
            识别器 = self._获取点击页面识别器()
            页面结果 = 识别器.识别(屏幕图像, 战斗中=False)
            if getattr(页面结果, "页面", "") != "选择卡片弹窗":
                return False
            关闭点 = 识别器.定位选择卡片弹窗关闭按钮(屏幕图像)
            if 关闭点 is None:
                self.页面恢复失败 = True
                self.置脚本状态(
                    "已识别选择卡片弹窗但未确认安全关闭X，禁止继续点击"
                )
                return False
            self.置脚本状态(
                f"检测到选择卡片弹窗，安全关闭右上角X：{关闭点[0]},{关闭点[1]}；"
                "禁止点击卡片、商店和宝石"
            )
            if not self.点击已确认安全按钮(
                关闭点[0], 关闭点[1], 延时=260
            ):
                self.页面恢复失败 = True
                self.置脚本状态(
                    "选择卡片弹窗关闭输入未通过安全复核，禁止继续点击"
                )
                return False
            清理缓存 = getattr(self.op, "清理截图缓存", None)
            if callable(清理缓存):
                清理缓存()
            for _ in range(8):
                self.脚本延时(220)
                try:
                    try:
                        新画面 = self.op.获取屏幕图像cv(
                            0, 0, 800, 600, 强制刷新=True
                        )
                    except TypeError:
                        新画面 = self.op.获取屏幕图像cv(0, 0, 800, 600)
                    新结果 = 识别器.识别(新画面, 战斗中=False)
                    if getattr(新结果, "页面", "") == "断线弹窗":
                        # 关闭测试服卡片后可能先出现连接中断提示；卡片
                        # 已经安全关闭，此时交给登录流程的断线恢复器，
                        # 不再把断线页误判为“卡片关闭失败”。
                        self._点击识别截图 = None
                        self._点击识别截图时间 = 0.0
                        self.置脚本状态(
                            "选择卡片弹窗已关闭，但画面出现断线弹窗；"
                            "交给登录恢复流程处理"
                        )
                        return True
                    if (
                        getattr(新结果, "页面", "") == "主世界主页"
                        and getattr(新结果, "世界", "") == "主世界"
                        and float(getattr(新结果, "可信度", 0.0)) >= 0.50
                    ):
                        self._点击识别截图 = None
                        self._点击识别截图时间 = 0.0
                        self.置脚本状态(
                            "选择卡片弹窗已安全关闭，已确认回到主世界"
                        )
                        return True
                    if getattr(新结果, "页面", "") == "选择卡片弹窗":
                        continue
                except Exception as 异常:
                    self.置脚本状态(
                        f"选择卡片弹窗关闭后复核失败，继续等待新画面：{异常}"
                    )
            self.页面恢复失败 = True
            self.置脚本状态(
                "选择卡片弹窗关闭后未确认回到主世界，禁止后续点击"
            )
            return False
        except Exception as 异常:
            self.页面恢复失败 = True
            self.置脚本状态(f"选择卡片弹窗清理失败，禁止继续点击：{异常}")
            return False

    def 关闭军队配置页(self, 屏幕图像=None) -> bool:
        """关闭已确认的军队配置页，并连续确认已经回到主世界。

        军队配置页本身没有主世界主页锚点，但右上角的红色 ``X`` 与
        活动弹窗相同。不能直接复用 ``清理主世界活动弹窗``，因为它会
        先要求页面已经是主世界主页，导致启动时手动打开军队页时永远
        安全停住。调用方必须先通过军队配置页攻击按钮和中央面板确认；
        本方法只允许点击已确认的右上角 X，绝不发送 ESC/BACK，也不触
        碰底部攻击、强化、商店或宝石按钮。
        """
        if bool(getattr(self, "_战斗中", False)):
            return False
        try:
            if 屏幕图像 is None:
                try:
                    屏幕图像 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)

            # 由进攻入口的同一套视觉规则确认中央军队面板与右下攻击
            # 按钮，防止把普通页面右上角的红色控件当成关闭目标。
            from 任务流程.主世界打鱼.打开进攻页面 import 打开进攻页面任务
            检测器 = 打开进攻页面任务.__new__(打开进攻页面任务)
            if 检测器._检测攻击按钮(屏幕图像) is None:
                return False
            关闭点 = self._检测主世界活动弹窗关闭点(屏幕图像)
            if 关闭点 is None:
                return False
            self.置脚本状态(
                f"已确认军队配置页，安全点击右上角关闭X：{关闭点[0]},{关闭点[1]}"
            )
            if not self.点击已确认安全按钮(
                关闭点[0], 关闭点[1], 延时=320
            ):
                self.页面恢复失败 = True
                self.置脚本状态("军队配置页关闭输入未通过安全复核，禁止继续点击")
                return False
            清理缓存 = getattr(self.op, "清理截图缓存", None)
            if callable(清理缓存):
                清理缓存()

            # 关闭后只接受连续的主世界主页证据；过渡帧、未知页和夜世界
            # 均不能算关闭成功，也不再发送第二个盲点。
            for _ in range(6):
                try:
                    新画面 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    新画面 = self.op.获取屏幕图像cv(0, 0, 800, 600)
                结果 = self._获取点击页面识别器().识别(
                    新画面,
                    战斗中=False,
                )
                if (
                    getattr(结果, "页面", "") == "主世界主页"
                    and getattr(结果, "世界", "") == "主世界"
                    and float(getattr(结果, "可信度", 0.0) or 0.0) >= 0.50
                ):
                    self.置脚本状态(
                        f"军队配置页已关闭，连续确认回到主世界（{结果.摘要()}）"
                    )
                    return True
                self.脚本延时(250)
            self.页面恢复失败 = True
            self.置脚本状态("军队配置页已点击关闭但未确认回到主世界，禁止继续点击")
            return False
        except Exception as 异常:
            self.页面恢复失败 = True
            self.置脚本状态(f"军队配置页安全关闭失败，禁止继续点击：{异常}")
            return False

    @staticmethod
    def _OCR确认升级详情页(OCR结果) -> bool:
        """确认升级详情页标题，兼容升级中和待确认两种文案。

        国际服测试版本的升级中面板常显示“正在将…升至84级”，而不是
        “正在进行升级”。这两类页面都只允许关闭右上角 X，绝不能把底部
        的“立即完成”或宝石数量当成恢复按钮。把文字判断独立出来，便于
        用固定 OCR 回归样本覆盖简体、繁体和进行中页面。
        """
        OCR文本 = "".join(
            str(项[1]) for 项 in OCR结果 or []
            if isinstance(项, (list, tuple)) and len(项) > 1
        ).replace(" ", "").replace("\n", "")
        if not OCR文本:
            return False
        有升级中标题 = any(标题 in OCR文本 for 标题 in (
            "正在进行升级", "正在進行升級", "正在进行升級", "正在進行升级",
            "正在将", "正在將",
        ))
        # “正在将…升至…级”是当前实机测试服的升级中标题；标题中同时
        # 出现“立即完成/剩余时间”时，即使英雄名称 OCR 有误也仍可安全
        # 认定为升级详情页，因为后续只会点击几何确认过的右上角 X。
        有升级中结构 = (
            "升至" in OCR文本
            and any(词 in OCR文本 for 词 in ("立即完成", "剩余时间", "剩餘時間", "级", "級"))
        )
        有升级确认标题 = (
            "升至" in OCR文本
            and ("?" in OCR文本 or "？" in OCR文本)
        )
        return 有升级中标题 or 有升级中结构 or 有升级确认标题

    def 关闭升级详情弹窗(self, 屏幕图像=None) -> bool:
        """安全关闭升级详情弹窗；绝不点击宝石或立即完成。

        返回 True 只表示已经点过关闭按钮并重新确认主世界主页。没有
        检测到该弹窗时返回 False 且不改变页面状态；检测到但关闭后无法
        确认主页时设置 ``页面恢复失败``，调用方必须停止后续输入。
        """
        if bool(getattr(self, "_战斗中", False)):
            return False
        try:
            if 屏幕图像 is None:
                try:
                    屏幕图像 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
            关闭点 = self._检测升级详情弹窗关闭点(屏幕图像)
            # 英雄详情与普通建筑详情共用右上角 X，但英雄页必须由英雄任务
            # 的专用收尾逻辑关闭；否则在选择英雄后会被这里提前关闭。
            if self._当前画面是英雄升级详情(屏幕图像):
                self.置脚本状态(
                    "当前为英雄升级详情，保留页面交给英雄任务；"
                    "通用升级护栏不关闭"
                )
                return False
        except Exception as 异常:
            self.置脚本状态(f"升级详情弹窗预检失败，未发送输入：{异常}")
            self.页面恢复失败 = True
            return False

        if 关闭点 is None:
            return False

        def 有升级详情标题(图像) -> bool:
            try:
                OCR结果, _ = self.获取OCR引擎()(图像)
            except Exception as 异常:
                self.置脚本状态(f"升级详情标题复核失败，未发送关闭点击：{异常}")
                return False
            return self._OCR确认升级详情页(OCR结果)

        # 几何红色 X 只能作为候选，不能单独授权点击：主世界活动/奖励
        # 弹窗也可能有相似的灰色标题栏。确认页只允许点右上角 X 取消，
        # 绝不点击底部绿色确认/宝石按钮。
        if not 有升级详情标题(屏幕图像):
            return False

        self.置脚本状态(
            f"检测到升级详情弹窗，安全点击右上角关闭{关闭点[0]},{关闭点[1]}；"
            "禁止点击立即完成、宝石和商店"
        )
        if not self.点击已确认安全按钮(关闭点[0], 关闭点[1], 延时=220):
            self.页面恢复失败 = True
            self.置脚本状态("升级详情弹窗关闭按钮输入失败，禁止继续点击")
            return False

        # 清掉弹窗之前的页面缓存，强制用新帧确认，不把未知/旧画面
        # 当成主页继续打开进攻页。
        self._点击识别截图 = None
        self._点击识别截图时间 = 0.0
        截止时间 = time.monotonic() + 2.5
        while time.monotonic() < 截止时间:
            try:
                try:
                    新画面 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    新画面 = self.op.获取屏幕图像cv(0, 0, 800, 600)
                # 确认页的 X 可能只关闭一层，随后露出“正在进行升级”
                # 面板。每一层都必须重新拿到升级标题证据，再只点右上角
                # X；不能看到背景主页特征就提前返回。
                剩余关闭点 = self._检测升级详情弹窗关闭点(新画面)
                if 剩余关闭点 is not None and 有升级详情标题(新画面):
                    if not self.点击已确认安全按钮(
                        剩余关闭点[0], 剩余关闭点[1], 延时=220
                    ):
                        self.页面恢复失败 = True
                        self.置脚本状态("升级详情第二层关闭输入失败，禁止继续点击")
                        return False
                    self.置脚本状态(
                        f"检测到升级详情仍有一层面板，继续安全关闭X："
                        f"{剩余关闭点[0]},{剩余关闭点[1]}"
                    )
                    self._点击识别截图 = None
                    self._点击识别截图时间 = 0.0
                    continue
                # 几何候选但没有升级标题时，可能只是主世界活动/奖励
                # X；它不能阻止已经确认的主世界返回结果，也不能被本
                # 方法点击。
                if 剩余关闭点 is not None:
                    剩余关闭点 = None
                结果 = self._获取点击页面识别器().识别(
                    新画面,
                    战斗中=False,
                )
                self._最近点击页面结果 = 结果
                if 结果.页面 == "主世界主页" and 剩余关闭点 is None:
                    self.页面恢复失败 = False
                    self.置脚本状态(
                        f"升级详情弹窗已关闭，已确认回到主世界主页（{结果.摘要()}）"
                    )
                    return True
            except Exception as 异常:
                self.置脚本状态(f"升级详情弹窗关闭后的主页复核失败：{异常}")
            self.脚本延时(180)

        self.页面恢复失败 = True
        self.置脚本状态(
            "升级详情弹窗已尝试关闭，但未确认主世界主页；"
            "保留当前画面并禁止后续点击"
        )
        return False

    def 关闭意外英雄升级详情弹窗(self, 屏幕图像=None) -> bool:
        """关闭地图拖动误触打开的英雄详情，只允许点击右上角 X。

        世界入口搜索本身只应拖动地图，但实机复测发现一条穿过基地中央
        的拖动轨迹会打开野蛮人之王详情。该页面底部有绿色资源确认按钮，
        不能让世界切换流程继续拖动或把它当普通主页处理。这里把“英雄
        详情标题 + 详情右上角 X + 关闭后主页复核”做成独立安全通道，
        不触碰绿色确认、宝石、商店或返回键。
        """
        self._意外英雄详情已检测 = False
        if bool(getattr(self, "_战斗中", False)):
            return False
        try:
            if 屏幕图像 is None:
                try:
                    屏幕图像 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
            # 先用廉价的右上角 X 几何候选过滤普通地图帧，避免世界入口
            # 每次边缘拖动都启动一次 OCR。只有存在详情 X 时才做标题识别。
            关闭点 = self._检测升级详情弹窗关闭点(屏幕图像)
            if 关闭点 is None:
                return False
            try:
                页面结果 = self.识别点击画面(强制=True)
            except Exception:
                页面结果 = None
            是英雄详情 = self._当前画面是英雄升级详情(屏幕图像)
            if not 是英雄详情:
                # 详情标题 OCR 失败时也不能继续拖动：同一位置的红 X
                # 可能属于评分/奖励/其它多按钮面板，必须保留画面等待
                # 专用流程或人工确认，绝不穿透面板。
                if getattr(页面结果, "页面", "") == "多按钮弹窗":
                    self._意外英雄详情已检测 = True
                    self.页面恢复失败 = True
                    self.置脚本状态(
                        "地图拖动后检测到未确认的多按钮弹窗，OCR未确认英雄详情；"
                        "禁止继续拖动或点击面板"
                    )
                return False
            self._意外英雄详情已检测 = True
        except Exception as 异常:
            self.页面恢复失败 = True
            self.置脚本状态(f"拖动后英雄详情预检失败，禁止继续搜索：{异常}")
            return False

        if 关闭点 is None:
            self.页面恢复失败 = True
            self.置脚本状态(
                "拖动后确认处于英雄升级详情，但未确认右上角关闭X；"
                "禁止继续拖动，禁止点击绿色确认和宝石"
            )
            return False

        self.置脚本状态(
            f"地图拖动误触英雄升级详情，安全点击右上角关闭X{关闭点[0]},{关闭点[1]}；"
            "禁止点击绿色确认、宝石和商店"
        )
        if not self.点击已确认安全按钮(关闭点[0], 关闭点[1], 延时=250):
            self.页面恢复失败 = True
            self.置脚本状态("英雄详情关闭X点击失败，禁止继续世界入口搜索")
            return False

        self._点击识别截图 = None
        self._点击识别截图时间 = 0.0
        截止时间 = time.monotonic() + 2.5
        while time.monotonic() < 截止时间:
            try:
                try:
                    新画面 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    新画面 = self.op.获取屏幕图像cv(0, 0, 800, 600)
                if self._当前画面是英雄升级详情(新画面):
                    self.脚本延时(180)
                    continue
                结果 = self.识别点击画面(强制=True)
                self._最近点击页面结果 = 结果
                if getattr(结果, "页面", "") in {"主世界主页", "夜世界主页"}:
                    self.页面恢复失败 = False
                    self.置脚本状态(
                        f"英雄详情已安全关闭，已确认回到主页（{结果.摘要()}）"
                    )
                    return True
            except Exception as 异常:
                self.置脚本状态(f"英雄详情关闭后的主页复核失败：{异常}")
            self.脚本延时(180)

        self.页面恢复失败 = True
        self.置脚本状态(
            "英雄详情已尝试关闭但未确认回到主页，保留当前画面并停止世界入口搜索"
        )
        return False

    def 安全返回键(self, 说明: str = "", *, 已确认可关闭面板: bool = False) -> bool:
        """受限地发送 Android BACK，默认拒绝。

        Android 的 BACK 在 CoC 根页面会直接把游戏退回模拟器启动器。过去的
        ``世界切换超时`` / ``主页校验`` 把“页面未知”当成可恢复状态，因此
        会在识别抖动时触发这个危险动作。现在只有调用方已经用专用模板确认
        了一个可关闭的游戏内面板时才允许一次 BACK；战斗、结算、未知页面一律
        不发送，保留画面并停止后续点击。
        """
        if not 已确认可关闭面板:
            self.置脚本状态(
                f"安全返回键已拒绝{('（' + 说明 + '）') if 说明 else ''}："
                "未确认可关闭面板；页面未知时禁止用ESC/返回键恢复"
            )
            self.页面恢复失败 = True
            return False

        if bool(getattr(self, "_战斗中", False)):
            self.置脚本状态(
                f"安全返回键已拒绝{('（' + 说明 + '）') if 说明 else ''}："
                "战斗期间禁止发送ESC/返回键，保留当前战斗画面"
            )
            self.页面恢复失败 = True
            return False

        # 调用方曾经确认过面板，不代表面板现在仍然存在。面板可能已经
        # 被点击关闭，或识别结果正好跨越转场；此时 Android BACK 会把
        # CoC 退回模拟器启动器。发送前对已知危险页面做最后一次复核。
        页面识别函数 = getattr(self, "识别点击画面", None)
        if callable(页面识别函数):
            try:
                页面结果 = 页面识别函数(强制=True)
                当前页面 = str(getattr(页面结果, "页面", "") or "")
                禁止返回页面 = {
                    "主世界主页",
                    "夜世界主页",
                    "战斗中",
                    "战斗过渡",
                    "战斗结算",
                    "战斗奖励选择",
                    "断线弹窗",
                    "系统维护",
                    "登录页",
                    "模拟器桌面",
                }
                if 当前页面 in 禁止返回页面:
                    self.置脚本状态(
                        f"安全返回键已拒绝{('（' + 说明 + '）') if 说明 else ''}："
                        f"发送前确认当前页面为{当前页面}，禁止退出游戏或破坏战斗状态"
                    )
                    self.页面恢复失败 = True
                    return False
            except Exception as 异常:
                self.置脚本状态(
                    f"安全返回键已拒绝{('（' + 说明 + '）') if 说明 else ''}："
                    f"发送前页面复核失败：{异常}"
                )
                self.页面恢复失败 = True
                return False
        设备 = getattr(getattr(self, "op", None), "设备", None)
        获取前台包名 = getattr(设备, "获取当前前台包名", None)
        if callable(获取前台包名):
            try:
                当前包名 = 获取前台包名()
                目标包名 = str(getattr(self.设置, "部落冲突包名", "") or "")
                if not 当前包名 or not 目标包名 or 当前包名 != 目标包名:
                    self.置脚本状态(
                        f"安全返回键已拒绝{('（' + 说明 + '）') if 说明 else ''}："
                        f"CoC不在前台（当前={当前包名 or '未知'}，目标={目标包名 or '未知'}）"
                    )
                    self.页面恢复失败 = True
                    return False
            except Exception as 异常:
                self.置脚本状态(
                    f"安全返回键已拒绝{('（' + 说明 + '）') if 说明 else ''}："
                    f"无法确认CoC前台状态：{异常}"
                )
                self.页面恢复失败 = True
                return False

        按键 = getattr(getattr(self, "键盘", None), "按字符按压", None)
        if not callable(按键):
            self.置脚本状态("安全返回键已拒绝：缺少键盘控制器")
            self.页面恢复失败 = True
            return False
        return 按键("esc") is not False

    def _获取点击页面识别器(self):
        """懒加载轻量页面识别器，避免启动时初始化额外模型。"""
        识别器 = getattr(self, "_点击页面识别器", None)
        if 识别器 is None:
            from 模块.检测.页面识别器 import 页面识别器
            识别器 = 页面识别器(self.获取模板识别器())
            self._点击页面识别器 = 识别器
        return 识别器

    def _获取点击识别截图(self, 强制: bool = False):
        """按场景复用页面护栏截图，避免高频输入反复 ``screencap``。

        战斗中没有商店或宝石购买入口，页面护栏的职责是确认仍在战斗、
        及时发现结算页。因此 0.75 秒一帧已足够；这能避免下兵时把 ADB
        transport、OpenCV 和模拟器渲染线程同时压满。主世界仍保留较短
        缓存，以便点击建筑后立即发现资源不足/宝石确认页。
        """
        当前时间 = time.monotonic()
        上次时间 = float(getattr(self, "_点击识别截图时间", 0.0))
        上次截图 = getattr(self, "_点击识别截图", None)
        战斗中 = bool(getattr(self, "_战斗中", False))
        缓存窗口秒 = 0.75 if 战斗中 else 0.20
        # 强制仅用于主世界点击后的确认。战斗中的“强制”不应绕过底层
        # ADB 截图节流，否则一次连点会产生一张新全屏图。
        if (
            not 强制
            and 上次截图 is not None
            and 当前时间 - 上次时间 <= 缓存窗口秒
        ):
            return 上次截图
        屏幕图像 = self.op.获取屏幕图像cv(
            0,
            0,
            800,
            600,
            强制刷新=bool(强制 and not 战斗中),
        )
        self._点击识别截图 = 屏幕图像
        self._点击识别截图时间 = 当前时间
        return 屏幕图像

    def 识别点击画面(self, 强制: bool = False):
        """点击前/后执行一次轻量页面识别，只记录状态，不发送输入。"""
        try:
            屏幕图像 = self._获取点击识别截图(强制=强制)
            结果 = self._获取点击页面识别器().识别(
                屏幕图像,
                战斗中=bool(getattr(self, "_战斗中", False)),
            )
            # 夜世界红色等级徽章是有用的备用特征，但实机主世界在
            # 动画/地图纹理经过左上角时曾出现过“只有红徽章命中”的
            # 单帧误判。点击护栏不能把这种单帧结果当成已经切换世界：
            # 一旦本上下文刚确认过主世界，红徽章单独命中就先返回未知，
            # 让调用方等待下一帧，而不是继续发送主世界或夜世界入口点击。
            页面 = str(getattr(结果, "页面", "") or "")
            依据 = tuple(getattr(结果, "依据", ()) or ())
            上次主页世界 = getattr(self, "_最近确认主页世界", None)
            if (
                页面 == "夜世界主页"
                and 上次主页世界 == "主世界"
                and 依据
                and all("夜世界红色等级徽章" in str(项) for 项 in 依据)
            ):
                结果 = replace(
                    结果,
                    页面="未知",
                    世界=None,
                    可信度=0.0,
                    依据=("夜世界红色等级徽章单帧命中，等待连续确认",),
                )
            elif 页面 == "主世界主页":
                self._最近确认主页世界 = "主世界"
            elif 页面 == "夜世界主页":
                self._最近确认主页世界 = "夜世界"
            self._最近点击页面结果 = 结果
            现在 = time.monotonic()
            日志键 = (结果.页面, 结果.世界, 结果.依据)
            if (
                日志键 != getattr(self, "_上次点击页面日志键", None)
                or 现在 - float(getattr(self, "_上次点击页面日志时间", 0.0)) >= 1.0
            ):
                self.置脚本状态(f"点击护栏画面识别：{结果.摘要()}")
                self._上次点击页面日志键 = 日志键
                self._上次点击页面日志时间 = 现在
            return 结果
        except Exception as 异常:
            # 识别器故障不能把输入线程打死；危险页面仍由宝石保护的
            # 独立识别负责拦截，下一次点击会重新尝试页面识别。
            上次错误时间 = float(getattr(self, "_点击页面识别错误时间", 0.0))
            现在 = time.monotonic()
            if 现在 - 上次错误时间 >= 2.0:
                self.置脚本状态(f"点击护栏画面识别暂时失败：{异常}")
                self._点击页面识别错误时间 = 现在
            if self.是否内存异常(异常):
                self.触发内存保护("点击护栏", 异常)
            return None

    def _系统维护页阻断输入(self, 页面结果) -> bool:
        """维护页出现时阻断所有普通/战斗输入并安全停止。"""
        if getattr(页面结果, "页面", "") != "系统维护":
            return False
        self.页面恢复失败 = True
        if not getattr(self, "_系统维护页已记录", False):
            self.置脚本状态(
                "点击护栏检测到官方系统维护页面，禁止继续输入；保留CoC前台并安全停止"
            )
            self._系统维护页已记录 = True
        try:
            self.停止事件.set()
        except Exception:
            pass
        return True

    def 输入前安全检查(self) -> bool:
        """供原始鼠标路径使用；返回 True 表示必须阻断本次输入。"""
        if getattr(self, "_内存保护已触发", False):
            return True
        if self.检查宝石商店危险页面():
            return True
        结果 = getattr(self, "_最近点击页面结果", None)
        if 结果 is None:
            结果 = self.识别点击画面()
        # 官方 Google Play 评分提示会在战斗回营后覆盖主世界。它不是
        # 宝石/商店页，旧护栏会把它当成未知主世界并把下一次任务点击
        # 送到弹窗按钮。只有轻量页面识别结果为“未知”时才启动低频 OCR，
        # 避免把每一次普通输入都变成一次完整 OCR 推理。只允许自动点击
        # “稍后/稍後”，不点击“评论”或“不再显示”，且完成后阻断当前输入。
        if (
            结果 is not None
            and 结果.页面 == "多按钮弹窗"
            and getattr(self, "_研究面板已确认", False)
        ):
            # 研究目标页本身包含左右大卡片，通用页面识别会把它归为
            # “多按钮弹窗”。只有研究流程已经确认过标题和目标结构时，
            # 才允许该流程继续点目标/确认；关闭研究面板后会清除标记。
            return False
        if 结果 is not None and 结果.页面 == "选择卡片弹窗":
            self.清理选择卡片弹窗(getattr(self, "_点击识别截图", None))
            # 无论关闭是否成功，都阻断原始输入；失败时由清理器设置
            # 页面恢复失败，防止任何任务穿透弹窗误点卡片或宝石。
            return True
        if 结果 is not None and 结果.页面 == "升级详情弹窗":
            当前帧 = getattr(self, "_点击识别截图", None)
            已关闭 = self.关闭升级详情弹窗(当前帧)
            if not 已关闭 and not getattr(self, "页面恢复失败", False):
                self.置脚本状态(
                    "已识别升级详情弹窗但未完成安全关闭，阻断当前输入；"
                    "禁止点击立即完成、宝石或商店"
                )
            # 升级详情即使已安全关闭，也必须阻断触发本次检查的原始
            # 点击，下一次输入必须重新抓取主页画面。
            return True
        if 结果 is not None and 结果.页面 == "多按钮弹窗":
            self.清理官方评分弹窗()
            # OCR未确认文字或关闭失败时同样阻断，禁止穿透弹窗点击。
            return True
        if (
            结果 is not None
            and 结果.页面 == "未知"
            and self.清理官方评分弹窗()
        ):
            return True
        if self._系统维护页阻断输入(结果):
            return True
        if 结果 is not None and 结果.页面 == "战斗星级奖励":
            self.处理战斗星级奖励弹窗(强制=True)
            return True
        if 结果 is not None and 结果.页面 == "断线弹窗":
            self.页面恢复失败 = True
            if not getattr(self, "_断线弹窗已记录", False):
                self.置脚本状态(
                    "检测到 CoC 连接中断弹窗，禁止继续点击；"
                    "保留游戏前台，等待登录恢复流程或人工重新登入"
                )
                self._断线弹窗已记录 = True
            if getattr(self, "_战斗中", False):
                try:
                    self.停止事件.set()
                except Exception:
                    pass
            return True
        # 升级详情面板会把主世界入口遮住，但不一定命中宝石/商店模板。
        # 只有在轻量页面识别已经判为未知时才运行这个几何预检，避免
        # 给战斗和普通主世界点击增加一张额外截图；检测到后只关闭红色
        # X，并阻断当前点击，等待下一次调用重新确认页面。
        if (
            not getattr(self, "_战斗中", False)
            and 结果 is not None
            and 结果.页面 == "未知"
        ):
            if self.关闭升级详情弹窗():
                return True
            if getattr(self, "页面恢复失败", False):
                return True
        # 主世界/夜世界 HUD 可能仍露在升级详情面板后方，轻量页面识别
        # 因此会返回“主页”。只在当前缓存帧出现中央标题栏+右上角红色
        # X 的几何候选时，复用同一个安全关闭器做 OCR 复核；普通主页
        # 没有该候选，不会额外执行 OCR，也不会影响战斗输入路径。
        if (
            not getattr(self, "_战斗中", False)
            and not getattr(self, "_城墙升级确认中", False)
            and not getattr(self, "_城墙升级资源点击中", False)
            and 结果 is not None
            and 结果.页面 in {"主世界主页", "夜世界主页"}
        ):
            # 活动/奖励面板会保留底层资源栏，轻量识别因此可能仍返回
            # “主页”。先做纯几何的红色 X + 中央面板预检；只有命中候选
            # 才调用安全关闭器，避免普通主页每次输入都触发 OCR。
            当前帧 = getattr(self, "_点击识别截图", None)
            try:
                活动关闭点 = (
                    当前帧 is not None
                    and self._检测主世界活动弹窗关闭点(当前帧)
                )
            except Exception:
                活动关闭点 = None
            if 活动关闭点:
                if self.清理主世界活动弹窗(当前帧):
                    return True
                if getattr(self, "页面恢复失败", False):
                    return True
        # 主世界/夜世界 HUD 可能仍露在升级详情面板后方，轻量页面识别
        # 因此会返回“主页”。只在当前缓存帧出现中央标题栏+右上角红色
        # X 的几何候选时，复用同一个安全关闭器做 OCR 复核；普通主页
        # 没有该候选，不会额外执行 OCR，也不会影响战斗输入路径。
        if (
            not getattr(self, "_战斗中", False)
            and not getattr(self, "_城墙升级确认中", False)
            and not getattr(self, "_城墙升级资源点击中", False)
            and 结果 is not None
            and 结果.页面 in {"主世界主页", "夜世界主页"}
        ):
            try:
                有升级面板候选 = (
                    当前帧 is not None
                    and self._检测升级详情弹窗关闭点(当前帧) is not None
                )
            except Exception:
                有升级面板候选 = False
            if 有升级面板候选:
                if self.关闭升级详情弹窗(当前帧):
                    return True
                if getattr(self, "页面恢复失败", False):
                    return True
        # 结果页出现后，禁止战斗线程继续点击兵栏/法术栏；这里不发送
        # ESC，避免把正常结算页误退出，回营任务负责后续处理。
        if (
            getattr(self, "_战斗中", False)
            and 结果 is not None
            and 结果.页面 == "战斗结算"
        ):
            self._战斗结束已确认 = True
            if not getattr(self, "_结算点击已拦截日志", False):
                self.置脚本状态("点击护栏：已识别战斗结算页，阻止继续下兵")
                self._结算点击已拦截日志 = True
            return True
        return False

    @staticmethod
    def _定位官方评分弹窗稍后按钮(OCR结果) -> tuple[int, int] | None:
        """从官方评分弹窗 OCR 中定位安全的“稍后/稍後”按钮。"""
        项目 = [
            项 for 项 in (OCR结果 or [])
            if isinstance(项, (list, tuple)) and len(项) > 1
        ]
        全部文本 = "".join(
            str(项[1]).replace(" ", "").replace("\n", "")
            for 项 in 项目
        )
        # OCR 会把《部落冲突》中的“冲/衝”以及“评分/評分”截断或误读。
        # 评分弹窗仍要求“部落 + GooglePlay + 稍后/稍後”三项组合证据，
        # 不依赖完整标题，避免原图分辨率下因少一个“评”字而漏掉弹窗。
        if "部落" not in 全部文本 or "GooglePlay" not in 全部文本:
            return None
        for 项 in 项目:
            文本 = str(项[1]).replace(" ", "").replace("\n", "")
            if "稍后" not in 文本 and "稍後" not in 文本:
                continue
            try:
                框 = [
                    (float(点[0]), float(点[1]))
                    for 点 in 项[0]
                ]
                if len(框) < 2:
                    continue
                x = int(round(sum(点[0] for 点 in 框) / len(框)))
                y = int(round(sum(点[1] for 点 in 框) / len(框)))
                # 评分按钮位于弹窗下半部；这是安全范围校验，不是固定
                # 点击坐标，实际输入使用 OCR 框中心并通过安全点击入口。
                if y >= 300:
                    return x, y
            except (TypeError, ValueError, IndexError):
                continue
        return None

    def 清理官方评分弹窗(self, 屏幕图像=None) -> bool:
        """安全关闭官方评分提示，只允许点击“稍后/稍後”。"""
        if bool(getattr(self, "_战斗中", False)):
            return False
        if getattr(self, "_内存保护已触发", False):
            return False
        try:
            # 评分提示只会在回营/主页低频出现；限制 OCR 频率，避免把
            # 资源/城墙任务的每一次普通点击变成一次完整 OCR 推理。
            当前时间 = time.monotonic()
            上次检查 = float(getattr(self, "_评分弹窗上次检查时间", 0.0))
            if 当前时间 - 上次检查 < 2.0 and 屏幕图像 is None:
                return False
            self._评分弹窗上次检查时间 = 当前时间
            if 屏幕图像 is None:
                try:
                    屏幕图像 = self.op.获取屏幕图像cv(
                        0, 0, 800, 600, 强制刷新=True
                    )
                except TypeError:
                    屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
            OCR结果, _ = self.获取OCR引擎()(屏幕图像)
            坐标 = self._定位官方评分弹窗稍后按钮(OCR结果)
            if 坐标 is None:
                return False
            self.置脚本状态(
                f"检测到官方评分提示，安全点击稍后/稍後：{坐标[0]},{坐标[1]}；"
                "禁止点击评论和不再显示"
            )
            if not self.点击已确认安全按钮(坐标[0], 坐标[1], 延时=350):
                self.置脚本状态("官方评分提示稍后按钮输入被拒绝，保持当前画面")
                return False
            self._点击识别截图 = None
            self._点击识别截图时间 = 0.0
            return True
        except Exception as 异常:
            if self.是否内存异常(异常):
                self.触发内存保护("官方评分提示", 异常)
            return False

    def 检查宝石商店危险页面(self, 强制: bool = False) -> bool:
        """识别宝石/商店弹窗，ESC 退出后恢复任务，不允许点宝石。

        宝石图标在主世界右上角本来就会常驻，因此只在中部弹窗区域
        (y=80..520)匹配，并且只接受中央弹窗范围内的命中，避免把正常
        资源栏或地图上的绿色物体误判成危险页面。四个模板来自
        img/宝石*.bmp；它们是图像拦截信号，不是可点击目标。
        """
        # 城墙升级确认页右下角带有资源图标，可能与旧版宝石模板发生
        # 相似匹配。该标志只在“升级标题 + 资源费用”双重确认后、仅包围
        # 一次已计算好的确认按钮点击，不能让宝石护栏把合法资源升级点
        # 误拦截并发送 ESC。
        if getattr(self, "_城墙升级确认中", False):
            return False
        if getattr(self, "_宝石保护已触发", False):
            return True

        # 战斗画面没有商店/宝石购买入口。仍然做一次轻量页面识别，让
        # 每次输入都能知道自己是否还在战斗；但不运行宝石模板的重检查，
        # 避免高频下兵时增加 ADB/CPU 压力或误发 ESC 中断战斗。
        if getattr(self, "_战斗中", False):
            结果 = self.识别点击画面(强制=强制)
            # 战斗中无法取到新画面时，不能继续盲目下兵：这会不断创建
            # ADB 客户端并扩大 transport 卡死。保留战斗，不再发送输入。
            if 结果 is None:
                if not getattr(self, "_战斗护栏失败已记录", False):
                    self.置脚本状态("战斗护栏无法确认当前画面，阻止后续下兵并等待任务安全停止")
                    self._战斗护栏失败已记录 = True
                return True
            if self._系统维护页阻断输入(结果):
                return True
            if 结果.页面 == "断线弹窗":
                self.页面恢复失败 = True
                self.置脚本状态(
                    "战斗中检测到 CoC 连接中断弹窗，停止后续输入并保留当前画面"
                )
                try:
                    self.停止事件.set()
                except Exception:
                    pass
                return True
            if 结果.页面 == "战斗结算":
                self._战斗结束已确认 = True
                if not getattr(self, "_结算点击已拦截日志", False):
                    self.置脚本状态("点击护栏：已识别战斗结算页，阻止继续下兵")
                    self._结算点击已拦截日志 = True
                return True
            if 结果.页面 == "战斗奖励选择":
                # 结算横幅先出现、回营按钮后出现时，页面识别器会在
                # 过渡动画里看到“奖励选择”特征。MuMu 的实际渲染可能
                # 持续数秒；过早把它当成用户必须处理的奖励页，会让
                # 战斗任务停在结算动画，下一轮无法回营。这里延长复核
                # 窗口，只接受“战斗结算/仍在战斗”两种明确结果，绝不
                # 点击奖励卡片，也不发送 ESC。
                复核结果 = None
                try:
                    延时函数 = getattr(self, "脚本延时", None)
                    for 复核序号 in range(10):
                        if callable(延时函数):
                            延时函数(800 if 复核序号 == 0 else 500)
                        self._点击识别截图 = None
                        self._点击识别截图时间 = 0.0
                        复核结果 = self.识别点击画面()
                        复核页面 = getattr(复核结果, "页面", "") if 复核结果 else ""
                        if 复核页面 != "战斗奖励选择":
                            break
                except Exception:
                    复核结果 = None
                if 复核结果 is not None and 复核结果.页面 == "战斗结算":
                    self._战斗结束已确认 = True
                    self._战斗奖励弹窗已确认 = False
                    self.置脚本状态("奖励页过渡复核为战斗结算，交给回营流程")
                    return True
                if 复核结果 is not None and 复核结果.页面 == "战斗中":
                    self._战斗奖励弹窗已确认 = False
                    self.置脚本状态("奖励页特征复核为战斗中，判定为过渡误报，继续下兵")
                    return False
                # 奖励卡片覆盖在战场上，不能把普通地图点击继续发出去；
                # 奖励内容来自测试服/活动版本，当前没有安全的自动选择规则。
                # 这里只阻断当前输入并交给进攻/回营状态机继续观察；不要
                # 立刻设置停止事件，因为真实结算动画可能还没有渲染出“回营”。
                self._战斗奖励弹窗已确认 = True
                if not getattr(self, "_战斗奖励弹窗已记录", False):
                    self.置脚本状态(
                        "检测到战斗奖励选择弹窗，已禁止下兵和法术输入；"
                        "不选择奖励、不发送ESC，等待结算页或回营按钮继续渲染"
                    )
                    self._战斗奖励弹窗已记录 = True
                return True
            if 结果.页面 != "战斗中":
                if not getattr(self, "_战斗过渡已阻止日志", False):
                    self.置脚本状态(
                        f"战斗护栏尚未确认战斗画面（当前={结果.页面}），阻止下兵输入"
                    )
                    self._战斗过渡已阻止日志 = True
                return True
            self._战斗过渡已阻止日志 = False
            return False

        当前时间 = time.monotonic()
        try:
            # 这张截图同时供页面识别和下方危险区域识别，普通点击前
            # 的鼠标回调会命中 160ms 缓存，不会再次 screencap。
            屏幕图像 = self._获取点击识别截图(强制=强制)
            页面结果 = self.识别点击画面()
            if self._系统维护页阻断输入(页面结果):
                return True
        except Exception as 异常:
            if self.是否内存异常(异常):
                self.触发内存保护("点击护栏截图", 异常)
            self.置脚本状态(f"点击护栏截图失败，阻止本次输入：{异常}")
            return True

        上次检查 = float(getattr(self, "_宝石保护上次检查时间", 0.0))
        if not 强制 and 当前时间 - 上次检查 < 0.75:
            return False
        self._宝石保护上次检查时间 = 当前时间

        try:
            高, 宽 = 屏幕图像.shape[:2]
            # 直接裁剪中央弹窗可能出现的区域；原实现先在 800×440
            # 大区域里找图再过滤坐标，既慢又让右上角常驻宝石参与匹配。
            区域左, 区域上 = 180, 130
            区域右, 区域下 = min(宽, 620), min(高, 450)
            危险区域 = 屏幕图像[区域上:区域下, 区域左:区域右]
            识图引擎 = self.获取模板识别器()
            中央命中列表 = []
            for 模板 in ("宝石.bmp", "宝石1.bmp"):
                命中, 坐标 = self._多尺度匹配宝石图标(
                    识图引擎,
                    危险区域,
                    模板,
                    比例列表=(0.80, 1.00),
                )
                绝对坐标 = (
                    int(坐标[0]) + 区域左,
                    int(坐标[1]) + 区域上,
                )
                if 命中:
                    中央命中列表.append((模板, 绝对坐标))
            # 备用外观只做一次等比匹配；常见危险弹窗已由前两张图
            # 覆盖，避免每次正常点击都执行全部模板的多尺度扫描。
            for 模板 in ("宝石2.bmp", "宝石3.bmp"):
                命中, 坐标 = self._多尺度匹配宝石图标(
                    识图引擎,
                    危险区域,
                    模板,
                    比例列表=(1.00,),
                )
                if 命中:
                    中央命中列表.append(
                        (
                            模板,
                            (int(坐标[0]) + 区域左, int(坐标[1]) + 区域上),
                        )
                    )

            # 这些资源图是很小的局部绿色图案，单张在地图、结算卡片
            # 或普通弹窗背景上也可能高相似。只有两张以上模板在同一
            # 个中央区域共同命中，才升级为危险页并发送 ESC。
            for 参考模板, 参考坐标 in 中央命中列表:
                同区域命中 = [
                    项 for 项 in 中央命中列表
                    if abs(项[1][0] - 参考坐标[0]) <= 28
                    and abs(项[1][1] - 参考坐标[1]) <= 28
                ]
                if len(同区域命中) >= 2:
                    命中模板 = "、".join(项[0] for 项 in 同区域命中)
                    命中坐标 = 参考坐标
                    break
            else:
                return False

            if not 命中模板 or 命中坐标 is None:
                return False

            self._宝石保护已触发 = True
            self.置脚本状态(
                f"[安全拦截] 识别到中央宝石/商店危险页面（{命中模板}，"
                f"位置{命中坐标[0]},{命中坐标[1]}），"
                "禁止点击宝石、购买、补充或进入商店"
            )
            已回主页面 = self._宝石保护发送ESC并确认主页面()
            if 已回主页面:
                self._宝石保护已触发 = False
                self.页面恢复失败 = False
                self.置脚本状态(
                    "[安全拦截] 已退出危险页面并确认回到主世界主页；"
                    "取消本次点击，继续后续任务"
                )
            else:
                # 无法确认主页时保持保护锁，但不设置停止事件；上层会
                # 看到页面恢复失败并停止后续点击，不会卡死在 SystemExit。
                self.页面恢复失败 = True
                self.置脚本状态(
                    "[安全拦截] ESC后未确认主世界主页，禁止后续点击，等待人工检查"
                )
            return True
        except SystemExit:
            raise
        except Exception as 异常:
            # 单次截图/模板读取失败时不把正常操作误判成危险页面；下一次
            # 点击会按节流窗口再次检查。真正命中模板时仍然是强制拦截。
            self.置脚本状态(f"[安全拦截] 宝石页面识别暂时失败：{异常}")
            return False

    @staticmethod
    def _多尺度匹配宝石图标(
        识图引擎,
        图像,
        模板路径,
        比例列表=(0.80, 1.00, 1.20),
    ):
        """兼容窗口缩放后的宝石图标，返回图标中心坐标。"""
        模板 = 识图引擎._安全加载模板(模板路径)
        if 模板 is None:
            return False, (0, 0)
        最佳分数 = -1.0
        最佳坐标 = (0, 0)
        for 比例 in 比例列表:
            if 比例 == 1.00:
                缩放模板 = 模板
            else:
                缩放模板 = cv2.resize(
                    模板,
                    None,
                    fx=比例,
                    fy=比例,
                    interpolation=cv2.INTER_AREA if 比例 < 1 else cv2.INTER_CUBIC,
                )
            if (
                缩放模板.size == 0
                or 缩放模板.shape[0] > 图像.shape[0]
                or 缩放模板.shape[1] > 图像.shape[1]
            ):
                continue
            _, 分数, _, 左上 = cv2.minMaxLoc(
                cv2.matchTemplate(图像, 缩放模板, cv2.TM_CCOEFF_NORMED)
            )
            if 分数 > 最佳分数:
                最佳分数 = 分数
                最佳坐标 = (
                    左上[0] + 缩放模板.shape[1] // 2,
                    左上[1] + 缩放模板.shape[0] // 2,
                )
        return 最佳分数 >= 0.86, 最佳坐标

    def _宝石保护发送ESC并确认主页面(self) -> bool:
        """只用 ESC 退出危险页，并用主城入口和资源栏确认恢复成功。"""
        预设确认器 = getattr(self, "_宝石保护确认主页面", None)
        按字符按压 = getattr(getattr(self, "键盘", None), "按字符按压", None)
        if not callable(按字符按压):
            self.置脚本状态("[安全拦截] 缺少键盘控制器，未执行任何点击")
            return False

        if callable(预设确认器):
            # 测试和上层可注入确认器；生产环境走真实截图模板匹配。
            # 一次只关闭最上层危险面板；若仍未回到主页，保持锁定并
            # 交给上层下一次安全检查，绝不能连续多次 BACK 退出游戏。
            安全返回键 = getattr(self, "安全返回键", None)
            if not callable(安全返回键) or not 安全返回键(
                "宝石保护预设确认", 已确认可关闭面板=True
            ):
                return False
            self.置脚本状态("[安全拦截] 已发送1次ESC退出危险页面，不执行第二选择")
            return bool(预设确认器())

        识图引擎 = self.获取模板识别器()
        # 危险页只允许一次 BACK。第一次通常足以关闭确认框；如果
        # 模板/截图暂时不稳定，保持保护锁并停止后续点击，避免第二次
        # BACK 在已经回到游戏根页面时把 CoC 退到启动器。
        序号 = 1
        安全返回键 = getattr(self, "安全返回键", None)
        if callable(安全返回键):
            if not 安全返回键(f"宝石保护第{序号}次", 已确认可关闭面板=True):
                return False
        else:
            self.置脚本状态("[安全拦截] 缺少安全返回键入口，未发送ESC")
            return False
        self.脚本延时(180)
        try:
            屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
            有家乡进攻按钮, _, _ = 识图引擎.执行匹配(
                屏幕图像,
                "家乡进攻图标.bmp|家乡进攻图标1.bmp|家乡进攻图标2.bmp|家乡进攻图标3.bmp",
                相似度阈值=0.88,
            )
            有主世界资源栏, _, _ = 识图引擎.执行匹配(
                屏幕图像,
                "主世界圣水图标.bmp",
                相似度阈值=0.88,
            )
            if 有家乡进攻按钮 and 有主世界资源栏:
                self.置脚本状态(f"[安全拦截] 第{序号}次ESC后确认主世界主页")
                return True
        except Exception as 异常:
            self.置脚本状态(f"[安全拦截] 第{序号}次主页确认失败：{异常}")
        return False

    def 发送死亡通知(self, 原因: str):
        """通知监控中心：本线程即将死亡

        设置停止事件，让线程在下一个延时点退出。
        同时发送消息给监控中心，告知线程已死亡，等待监控中心重启。

        告知监控中心已经死了，麻烦收尸并复活我

        参数:
            原因: 死亡原因描述
        """
        self.置脚本状态(f"线程即将死亡，原因：{原因}")

        # 通知监控中心（仅作通知，监控中心会等待线程自然结束后重启）
        self.消息队列.put({
            "类型": "死亡通知",
            "机器人标志": self.机器人标志,
            "原因": 原因
        })

        # 立即设置停止事件，让线程在下一个延时点退出
        self.停止事件.set()

    def 发送企业微信通知(self, 状态文本: str, 包含截图: bool = True):
        """发送企业微信状态通知（任务代码可随时调用）

        参数：
            状态文本: 要发送的文字内容
            包含截图: 是否附带当前屏幕截图
        """
        if self.企业微信通知器 is None:
            return  # 未配置 webhook，静默跳过

        try:
            截图 = None
            if 包含截图:
                截图 = self.op.获取屏幕图像cv(0, 0, 800, 600)

            self.企业微信通知器.发送状态消息(
                机器人标志=self.机器人标志,
                状态文本=状态文本,
                截图=截图
            )
        except Exception as e:
            self.记录警告(f"企业微信通知发送失败: {e}")

    def 处理异常(self, 任务名: str, 异常: Exception, 是否重启游戏=True, 是否重启机器人=True):
        """统一异常处理入口

        参数:
            任务名: 触发异常的任务类名
            异常: 捕获到的异常对象
            是否重启游戏: 是否尝试将游戏应用置于前台（受安全锁约束）
            是否重启机器人: 是否发送死亡通知，让监控中心重启机器人线程
        """
        异常文本 = str(异常)
        是否资源保护 = self.是否内存异常(异常)
        if 是否资源保护:
            # 主机/模拟器提交额度不足时，不能再为了异常通知抓一张图；
            # 否则“保护已触发”会被二次截图包装成连续 ADB 错误。
            self.置脚本状态(
                f"任务[{任务名}] 已因资源保护停止：{异常}；"
                "当前不是普通ADB断线，不再截图、OCR或自动重连"
            )
        else:
            self.置脚本状态(f"任务[{任务名}] 异常：{异常}")
        是否战斗中 = bool(getattr(self, "_战斗中", False))
        # 异常时不能把 Android 前台从当前画面切走。尤其是战斗中、ADB
        # 截图断连和页面超时，自动打开应用可能打断战斗，甚至把模拟器
        # 切到启动器/其他应用；这些情况统一安全停止，等待人工确认。
        安全锁标记 = (
            "ADB", "device", "截图", "超时", "无心跳", "未找到主世界入口",
            "未找到下一个按钮", "战斗", "不在前台",
        )
        禁止自动恢复 = 是否战斗中 or any(标记 in 异常文本 for 标记 in 安全锁标记)

        if 是否资源保护:
            是否重启游戏 = False
            是否重启机器人 = False
            self.置脚本状态(
                "资源保护安全锁：保留当前游戏和模拟器，不启动、切换或关闭任何应用；"
                "请先释放模拟器内存后再手动启动任务"
            )
        elif 是否重启游戏 and 禁止自动恢复:
            是否重启游戏 = False
            self.置脚本状态(
                "异常恢复安全锁：保留当前游戏页面，不启动、切换或关闭任何应用；"
                "请确认模拟器画面后手动继续"
            )

        # 发送异常通知
        try:
            异常信息 = 异常文本[:100]  # 限制长度
            操作描述 = "重启游戏" if 是否重启游戏 else ("重启机器人" if 是否重启机器人 else "继续执行")
            self.发送企业微信通知(
                f"⚠️ 任务异常\n任务: {任务名}\n异常: {异常信息}\n操作: {操作描述}",
                # 资源保护时明确禁止二次截图；普通异常仍保留原有通知截图。
                包含截图=not 是否资源保护
            )
        except Exception as e:
            # 通知发送失败不应影响异常处理流程
            print(f"发送异常通知失败: {e}")

        if 是否重启游戏:
            # 不强制结束游戏进程，避免识别/截图错误造成游戏循环重启。
            包名 = self.数据库.获取机器人设置(self.机器人标志).部落冲突包名
            self.置脚本状态("尝试恢复游戏前台（不结束游戏进程）")
            try:
                self.雷电模拟器.打开应用(包名)
            except Exception as 恢复异常:
                self.记录警告(f"未能恢复游戏前台：{恢复异常}")

        if 是否重启机器人:
            self.发送死亡通知(f"任务[{任务名}] 异常：{异常}")

    def 脚本延时(self, 毫秒数):
        """脚本延时方法 - 可中断、可暂停、支持定时任务的智能延时

        这是整个机器人框架的核心延时方法，不仅仅是简单的 time.sleep()，
        它承担了多个关键职责：

        职责1：精确延时
            - 以1毫秒为单位进行延时
            - 适用于模拟人类操作的随机延时

        职责2：响应停止事件（可中断）
            - 每毫秒检查停止事件，确保能快速响应停止请求
            - 收到停止事件时立即清理资源并抛出 SystemExit

        职责3：响应暂停事件（可暂停）
            - 检测到暂停时阻塞等待，直到收到继续信号
            - 不占用 CPU，线程会进入等待状态

        职责4：定时任务管理（定时上报）
            - 每秒检查一次是否需要发送状态上报
            - 基于实际时间间隔，不受短延时影响
            - 即使频繁调用短延时（如5ms），也最多每秒检查一次

        参数:
            毫秒数: 延时的毫秒数

        异常:
            SystemExit: 收到停止事件时抛出，用于终止任务线程

        使用示例:
            上下文.脚本延时(500)  # 延时500毫秒
            上下文.脚本延时(random.randint(400, 600))  # 随机延时，模拟人类

        注意事项:
            - 不要使用 time.sleep()，始终使用此方法
            - 延时期间可以被停止事件中断
            - 延时期间可以被暂停事件暂停
        """

        try:
            总秒数 = max(0.0, int(毫秒数 or 0) / 1000.0)
        except (TypeError, ValueError):
            总秒数 = 0.0
        if 总秒数 <= 0:
            return

        # 旧实现每毫秒执行一次 Python 循环。战斗等待、页面等待和待机
        # 累积起来会变成每个机器人每秒约 1000 次唤醒，多个机器人或
        # Tk/ONNX 同时运行时会明显抬高 CPU。使用 Event.wait 休眠，仍
        # 保留停止/暂停的及时响应，并把唤醒频率限制在每秒最多 5 次。
        截止时间 = time.monotonic() + 总秒数
        while True:
            if self.停止事件.is_set():
                self.置脚本状态("收到停止事件")
                raise SystemExit(f"收到退出请求,主动退出线程,机器人{self.机器人标志}已关闭")

            if not self.继续事件.is_set():
                # 暂停时也用有界等待，这样停止事件仍能快速唤醒线程。
                self.继续事件.wait(timeout=0.25)
                continue

            当前单调时间 = time.monotonic()
            if 当前单调时间 >= 截止时间:
                break

            # 升级完成弹窗只做低频、双帧确认，不参与战斗输入路径。这样
            # 可在主世界等待期间自动处理确认，同时不会给下兵循环增加 OCR。
            if 当前单调时间 - float(getattr(self, "_升级完成弹窗调度时间", 0.0)) >= 0.5:
                self._升级完成弹窗调度时间 = 当前单调时间
                try:
                    self.自动确认升级完成弹窗()
                except SystemExit:
                    raise
                except Exception as 异常:
                    上次错误 = float(getattr(self, "_升级完成弹窗调度错误时间", 0.0))
                    if 当前单调时间 - 上次错误 >= 5.0:
                        self.置脚本状态(f"升级完成弹窗处理暂时失败：{异常}")
                        self._升级完成弹窗调度错误时间 = 当前单调时间

            # CoC 可能在任务执行期间异步弹出能力/教程说明层（例如“魔法
            # 护盾”）。它会保留主世界 HUD，不能等到下一次任务入口才处理，
            # 否则后续坐标点击会被弹层吞掉。只在非战斗状态低频检查，并且
            # 仍由清理中央提示的 OCR + 下半屏范围共同确认，绝不点击商店、
            # 宝石或普通建筑。清理函数内部的短延时会再次进入本方法，但
            # 调度时间戳会阻止递归重复 OCR。
            if (
                not getattr(self, "_战斗中", False)
                and 当前单调时间
                - float(getattr(self, "_中央提示调度时间", 0.0))
                >= 0.75
            ):
                self._中央提示调度时间 = 当前单调时间
                try:
                    # 延时调度发生在任务自己的下一次截图之前。若断线、
                    # 结算或其它遮罩正好盖住主页，直接 OCR 会看到底层
                    # “魔法护盾/继续”文字并把点击送到不可见位置。生产
                    # 上下文都有 ADB 屏幕对象，因此先做一次轻量页级复核；
                    # 只有明确是主世界/夜世界主页才允许处理中央提示。
                    # 缺少 op 的单元测试/旧适配器保留原有调用兼容。
                    设备屏幕 = getattr(self, "op", None)
                    允许处理中央提示 = 设备屏幕 is None
                    if 设备屏幕 is not None:
                        try:
                            from 模块.检测.页面识别器 import 页面识别器

                            复核画面 = 设备屏幕.获取屏幕图像cv(
                                0, 0, 800, 600, 强制刷新=True
                            )
                            复核结果 = 页面识别器(
                                self.获取模板识别器()
                            ).识别(复核画面, 战斗中=False)
                            允许处理中央提示 = getattr(
                                复核结果, "页面", ""
                            ) in {"主世界主页", "夜世界主页"}
                        except Exception:
                            # 页级复核失败时不猜测，不向未知画面发送输入。
                            允许处理中央提示 = False
                    if 允许处理中央提示:
                        self.清理中央游戏提示(
                            复核画面 if 设备屏幕 is not None else None
                        )
                except SystemExit:
                    raise
                except Exception as 异常:
                    上次错误 = float(getattr(self, "_中央提示调度错误时间", 0.0))
                    if 当前单调时间 - 上次错误 >= 5.0:
                        self.置脚本状态(f"中央能力/教程提示处理暂时失败：{异常}")
                        self._中央提示调度错误时间 = 当前单调时间

            # 回营后可能先显示覆盖主页的夜世界星级奖励确认框。低频
            # 视觉检查只在战斗结束链路仍未清理时运行，避免长期待机时
            # 每个机器人持续做全屏 OCR/模板操作。
            if 当前单调时间 - float(getattr(self, "_星级奖励调度时间", 0.0)) >= 0.75:
                self._星级奖励调度时间 = 当前单调时间
                if (
                    not getattr(self, "_战斗中", False)
                    and (
                        bool(getattr(self, "_战斗结束已确认", False))
                        or getattr(getattr(self, "_最近点击页面结果", None), "页面", "")
                        in {"战斗结算", "战斗星级奖励"}
                    )
                ):
                    try:
                        self.处理战斗星级奖励弹窗(强制=True)
                    except SystemExit:
                        raise
                    except Exception as 异常:
                        self.置脚本状态(f"星级奖励弹窗检查暂时失败：{异常}")

            # 每1秒检查一次定时上报（基于实际时间，而不是循环次数）。
            if self.企业微信通知器 and self.上报间隔秒 > 0:
                当前时间 = time.time()
                if 当前时间 - self.上次检查上报时间 >= 1.0:
                    self.上次检查上报时间 = 当前时间
                    if 当前时间 - self.上次上报时间 >= self.上报间隔秒:
                        try:
                            from datetime import datetime
                            self.发送企业微信通知(
                                f"📊 状态上报\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                                包含截图=True
                            )
                            self.上次上报时间 = 当前时间
                        except Exception as e:
                            print(f"定时上报失败: {e}")

            # 等待停止事件；收到事件后下一轮统一记录并退出。
            等待秒数 = min(0.25, max(0.0, 截止时间 - time.monotonic()))
            if 等待秒数 > 0:
                self.停止事件.wait(timeout=等待秒数)

    def 点击(self,x,y,延时=None,是否精确点击=False):
        # 所有任务共用这一入口；危险页面一旦被识别，ESC 并确认主页，
        # 取消当前点击，但允许上层任务继续走任务计划。
        if self.检查宝石商店危险页面():
            return False

        # 战斗结算页可能刚好出现在两次下兵之间。识别到结算后只阻止
        # 输入，不发送 ESC，让专门的回营流程读取结果并返回主页。
        页面结果 = getattr(self, "_最近点击页面结果", None)
        if (
            getattr(self, "_战斗中", False)
            and 页面结果 is not None
            and 页面结果.页面 == "战斗结算"
        ):
            self._战斗结束已确认 = True
            if not getattr(self, "_结算点击已拦截日志", False):
                self.置脚本状态("点击护栏：已识别战斗结算页，阻止继续下兵")
                self._结算点击已拦截日志 = True
            return False

        # 延时默认值
        if 延时 is None:
            延时 = random.randint(400, 600)

        # 精确点击控制
        随机半径 = 0 if 是否精确点击 else 6

        # 加随机偏移
        x = random.randint(x - 随机半径, x + 随机半径)
        y = random.randint(y - 随机半径, y + 随机半径)

        if self.鼠标 is None:
            raise RuntimeError("鼠标控制器未初始化")

        self.鼠标.移动到(x, y)
        点击成功 = self.鼠标.左键点击()
        if 点击成功 is False:
            self.置脚本状态(f"点击护栏：输入适配器拒绝点击({x},{y})")
            return False
        self.脚本延时(延时)

        # 升级、收集等主世界点击可能刚好打开资源不足/宝石确认页，必须
        # 用新帧二次确认。战斗则没有这类入口；逐次强制截图会让大量下兵
        # 反复启动 ADB screencap，长期运行时会拖垮模拟器。战斗只每 0.75
        # 秒复核一次画面，仍可及时阻止结算页后的继续下兵。
        战斗中 = bool(getattr(self, "_战斗中", False))
        点击后检查时间 = float(getattr(self, "_战斗点击后检查时间", 0.0))
        需要战斗复核 = (not 战斗中) or (time.monotonic() - 点击后检查时间 >= 0.75)
        if 需要战斗复核 and self.检查宝石商店危险页面(强制=not 战斗中):
            return False
        if 战斗中 and 需要战斗复核:
            self._战斗点击后检查时间 = time.monotonic()
        页面结果 = getattr(self, "_最近点击页面结果", None)
        if (
            getattr(self, "_战斗中", False)
            and 页面结果 is not None
            and 页面结果.页面 == "战斗结算"
        ):
            self._战斗结束已确认 = True
            self.置脚本状态("点击后识别到战斗结算页，后续停止下兵")
        return True

    def 点击已确认安全按钮(self, x, y, 延时=100):
        """点击已经由专用模板/弹窗识别确认的非购买按钮。

        登录重载、登录提示确认等按钮属于恢复流程，不能再次经过
        宝石保护模板匹配：旧测试服的宝石小图模板会误命中弹窗背景，
        让恢复按钮永远点不下去。调用方必须先完成专用视觉确认，且
        这里固定精确点击，不接受随机偏移，也不允许用于普通任务。
        """
        if self.鼠标 is None:
            self.置脚本状态("恢复按钮点击失败：鼠标控制器未初始化")
            return False
        原安全回调 = getattr(self.鼠标, "_安全点击检查回调", None)
        try:
            # 鼠标底层也有同一保护回调；临时绕过只为已确认的恢复按钮，
            # 防止同一张弹窗被保护层重复判定而无法恢复。
            if hasattr(self.鼠标, "_安全点击检查回调"):
                self.鼠标._安全点击检查回调 = None
            self.鼠标.移动到(int(x), int(y))
            结果 = self.鼠标.左键点击()
            self.脚本延时(max(0, int(延时 or 0)))
            return bool(结果)
        finally:
            if hasattr(self.鼠标, "_安全点击检查回调"):
                self.鼠标._安全点击检查回调 = 原安全回调

    def 滑动屏幕(self, 起点坐标, 终点坐标):
        """使用贝塞尔曲线模拟人类滑动操作"""
        起点x, 起点y = 起点坐标
        终点x, 终点y = 终点坐标

        # 随机偏移增强人类行为模拟
        起点x += random.randint(-5, 5)
        起点y += random.randint(-5, 5)
        终点x += random.randint(-5, 5)
        终点y += random.randint(-5, 5)

        # 控制点随机生成在起点和终点附近
        控制点1 = (
            起点x + (终点x - 起点x) * 0.3 + random.randint(-30, 30),
            起点y + (终点y - 起点y) * 0.3 + random.randint(-30, 30),
        )
        控制点2 = (
            起点x + (终点x - 起点x) * 0.6 + random.randint(-30, 30),
            起点y + (终点y - 起点y) * 0.6 + random.randint(-30, 30),
        )

        路径点 = 生成贝塞尔轨迹((起点x, 起点y), 控制点1, 控制点2, (终点x, 终点y), 步数=random.randint(25, 40))

        self.鼠标.移动到(路径点[0][0], 路径点[0][1])
        self.鼠标.左键按下()

        for 当前点 in 路径点[1:]:
            self.鼠标.移动到(当前点[0], 当前点[1])
            self.脚本延时(random.randint(5, 15))  # 模拟人类微小不规律移动

        self.鼠标.左键抬起()
        self.脚本延时(random.randint(500, 1000))


from abc import ABC, abstractmethod


class 基础任务(ABC):
    """游戏任务基类 - 统一的任务基类，自动初始化常用工具"""

    # 类属性：元数据（由装饰器或子类设置）
    元数据: Any = None

    def __init__(self, 上下文: '任务上下文'):
        self.上下文 = 上下文
        # 自动初始化常用工具
        获取模板识别器 = getattr(上下文, "获取模板识别器", None)
        获取OCR引擎 = getattr(上下文, "获取OCR引擎", None)
        获取YOLO检测器 = getattr(上下文, "获取YOLO检测器", None)
        self.模板识别 = (
            获取模板识别器() if callable(获取模板识别器) else 模板匹配引擎()
        )
        self.ocr引擎 = (
            获取OCR引擎() if callable(获取OCR引擎) else 安全OCR引擎()
        )
        self.检测器 = (
            获取YOLO检测器() if callable(获取YOLO检测器) else 线程安全YOLO检测器()
        )
        # 便捷属性
        self.数据库 = 上下文.数据库
        self.机器人标志 = 上下文.机器人标志


    @abstractmethod
    def 执行(self) -> bool:
        """
        执行任务主逻辑
        返回True继续下一个任务，返回False终止流程
        """
        pass

    def 异常处理(self, 异常: Exception, 是否重启游戏=True, 是否重启机器人=True):
        """统一异常处理 - 委托给上下文处理"""
        self.上下文.处理异常(self.__class__.__name__, 异常, 是否重启游戏, 是否重启机器人)

    def 是否出现图片(self, 模板路径: str, 区域: Tuple[int, int, int, int] = (0, 0, 800, 600), 相似度阈值=0.9) -> Tuple[
        bool, Tuple[int, int]]:
        """
        当前机器人操作的模拟器是否出现指定图片，并返回坐标。

        参数:
            模板路径: 模板图路径（可为多个路径用 | 分隔）
            区域: 指定识别区域，格式为 (x1, y1, x2, y2)

        返回:
            是否匹配, (x, y) 坐标
        """
        x1, y1, x2, y2 = 区域
        屏幕图像 = self.上下文.op.获取屏幕图像cv(x1, y1, x2, y2)
        是否匹配, (x, y), _ = self.模板识别.执行匹配(屏幕图像, 模板路径, 相似度阈值)

        # 注意坐标需要加上区域偏移量
        if 是否匹配:
            return True, (x + x1, y + y1)
        else:
            return False, (x + x1, y + y1)

    # 兼容旧方法名
    已出现图片 = 是否出现图片

    def 执行OCR识别(self, 区域: Tuple[int, int, int, int] = (0, 0, 800, 600)) -> list:
        """执行屏幕OCR识别"""
        try:
            x1, y1, x2, y2 = 区域
            屏幕图像 = self.上下文.op.获取屏幕图像cv(x1, y1, x2, y2)
            # 少数旧任务/测试构造会绕过 __init__（例如从残留升级面板
            # 恢复任务时直接复用任务对象），这时不能因为缺少实例属性就
            # 让主页护栏反复报 AttributeError。优先复用上下文共享引擎，
            # 并把它补回任务实例，避免每一帧重新加载 native OCR 模型。
            OCR引擎 = getattr(self, "ocr引擎", None)
            if OCR引擎 is None:
                获取OCR引擎 = getattr(self.上下文, "获取OCR引擎", None)
                if callable(获取OCR引擎):
                    OCR引擎 = 获取OCR引擎()
                else:
                    OCR引擎 = 安全OCR引擎()
                self.ocr引擎 = OCR引擎
            OCR返回 = OCR引擎(屏幕图像)
            if isinstance(OCR返回, tuple):
                ocr结果 = OCR返回[0]
            else:
                ocr结果 = OCR返回
            return ocr结果 if ocr结果 is not None else []
        except Exception as e:
            if self.上下文.是否内存异常(e):
                self.上下文.触发内存保护("OCR", e)
            self.上下文.置脚本状态(f"OCR识别失败: {str(e)}")
            return []
