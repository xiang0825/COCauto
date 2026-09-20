

import queue
import random
import threading
import time
import gc
from collections.abc import Callable
from dataclasses import dataclass
from typing import Tuple, Any, Optional

import cv2

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

    def 输入前安全检查(self) -> bool:
        """供原始鼠标路径使用；返回 True 表示必须阻断本次输入。"""
        if getattr(self, "_内存保护已触发", False):
            return True
        if self.检查宝石商店危险页面():
            return True
        结果 = getattr(self, "_最近点击页面结果", None)
        if 结果 is None:
            结果 = self.识别点击画面()
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

    def 检查宝石商店危险页面(self, 强制: bool = False) -> bool:
        """识别宝石/商店弹窗，ESC 退出后恢复任务，不允许点宝石。

        宝石图标在主世界右上角本来就会常驻，因此只在中部弹窗区域
        (y=80..520)匹配，并且只接受中央弹窗范围内的命中，避免把正常
        资源栏或地图上的绿色物体误判成危险页面。四个模板来自
        img/宝石*.bmp；它们是图像拦截信号，不是可点击目标。
        """
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
            return False

        当前时间 = time.monotonic()
        try:
            # 这张截图同时供页面识别和下方危险区域识别，普通点击前
            # 的鼠标回调会命中 160ms 缓存，不会再次 screencap。
            屏幕图像 = self._获取点击识别截图(强制=强制)
            self.识别点击画面()
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
            "未找到下一个按钮", "战斗",
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
            ocr结果, _ = self.ocr引擎(屏幕图像)
            return ocr结果 if ocr结果 is not None else []
        except Exception as e:
            if self.上下文.是否内存异常(e):
                self.上下文.触发内存保护("OCR", e)
            self.上下文.置脚本状态(f"OCR识别失败: {str(e)}")
            return []
