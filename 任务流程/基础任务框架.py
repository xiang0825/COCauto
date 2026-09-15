

import queue
import random
import threading
import time
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

    def 检查宝石商店危险页面(self, 强制: bool = False) -> bool:
        """识别宝石/商店弹窗，ESC 退出后恢复任务，不允许点宝石。

        宝石图标在主世界右上角本来就会常驻，因此只在中部弹窗区域
        (y=80..520)匹配，并且只接受中央弹窗范围内的命中，避免把正常
        资源栏或地图上的绿色物体误判成危险页面。四个模板来自
        img/宝石*.bmp；它们是图像拦截信号，不是可点击目标。
        """
        if getattr(self, "_宝石保护已触发", False):
            return True

        # 战斗画面没有商店/宝石购买入口。战场建筑、资源图标和特效可能
        # 与宝石模板局部相似；战斗中继续做全屏模板匹配还会额外增加
        # ADB screencap 压力，并可能误发 ESC 中断战斗。战斗结束后由
        # 回营流程和下一次主城主页校验重新启用完整保护。
        if getattr(self, "_战斗中", False):
            return False

        当前时间 = time.monotonic()
        上次检查 = float(getattr(self, "_宝石保护上次检查时间", 0.0))
        if not 强制 and 当前时间 - 上次检查 < 0.75:
            return False
        self._宝石保护上次检查时间 = 当前时间

        try:
            屏幕图像 = self.op.获取屏幕图像cv(0, 0, 800, 600)
            高, 宽 = 屏幕图像.shape[:2]
            上 = max(0, min(高, 80))
            右 = min(宽, 800)
            下 = min(高, 520)
            危险区域 = 屏幕图像[上:下, 0:右]
            识图引擎 = 模板匹配引擎()
            命中模板 = None
            命中坐标 = None
            for 模板 in ("宝石.bmp", "宝石1.bmp", "宝石2.bmp", "宝石3.bmp"):
                命中, 坐标 = self._多尺度匹配宝石图标(
                    识图引擎,
                    危险区域,
                    模板,
                )
                绝对坐标 = (int(坐标[0]), int(坐标[1]) + 上)
                # 网络截图中的危险弹窗位于画面中央；把上方资源栏和
                # 地图边缘排除，避免进游戏后立即误触发安全保护。
                if 命中 and 180 <= 绝对坐标[0] <= 620 and 130 <= 绝对坐标[1] <= 450:
                    命中模板 = 模板
                    命中坐标 = 绝对坐标
                    break
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
    def _多尺度匹配宝石图标(识图引擎, 图像, 模板路径):
        """兼容窗口缩放后的宝石图标，返回图标中心坐标。"""
        模板 = 识图引擎._安全加载模板(模板路径)
        if 模板 is None:
            return False, (0, 0)
        最佳分数 = -1.0
        最佳坐标 = (0, 0)
        # 覆盖常见 70%~130% 窗口缩放；中央弹窗约束在调用方处理。
        for 比例 in (0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30):
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
            for 序号 in range(3):
                按字符按压("esc")
                if 序号 < 2:
                    self.脚本延时(180)
            self.置脚本状态("[安全拦截] 已连续发送3次ESC退出危险页面，不执行第二选择")
            return bool(预设确认器())

        识图引擎 = 模板匹配引擎()
        for 序号 in range(3):
            按字符按压("esc")
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
                    self.置脚本状态(f"[安全拦截] 第{序号 + 1}次ESC后确认主世界主页")
                    return True
            except Exception as 异常:
                self.置脚本状态(f"[安全拦截] 第{序号 + 1}次主页确认失败：{异常}")
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
            是否重启游戏: 是否关闭并重新打开游戏应用
            是否重启机器人: 是否发送死亡通知，让监控中心重启机器人线程
        """
        self.置脚本状态(f"任务[{任务名}] 异常：{异常}")

        # 发送异常通知
        try:
            异常信息 = str(异常)[:100]  # 限制长度
            操作描述 = "重启游戏" if 是否重启游戏 else ("重启机器人" if 是否重启机器人 else "继续执行")
            self.发送企业微信通知(
                f"⚠️ 任务异常\n任务: {任务名}\n异常: {异常信息}\n操作: {操作描述}",
                包含截图=True
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

        for i in range(毫秒数):
            time.sleep(0.001)

            # 每1秒检查一次定时上报（基于实际时间，而不是循环次数）
            # 这样即使频繁调用短延时，也不会过度检查
            if self.企业微信通知器 and self.上报间隔秒 > 0:
                当前时间 = time.time()
                # 距离上次检查超过1秒才再次检查
                if 当前时间 - self.上次检查上报时间 >= 1.0:
                    self.上次检查上报时间 = 当前时间
                    # 检查是否到了上报时间
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

            if not self.继续事件.is_set():
                self.继续事件.wait()

            if self.停止事件.is_set():
                self.置脚本状态("收到停止事件")
                raise SystemExit(f"收到退出请求,主动退出线程,机器人{self.机器人标志}已关闭")

    def 点击(self,x,y,延时=None,是否精确点击=False):
        # 所有任务共用这一入口；危险页面一旦被识别，ESC 并确认主页，
        # 取消当前点击，但允许上层任务继续走任务计划。
        if self.检查宝石商店危险页面():
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
        self.鼠标.左键点击()
        self.脚本延时(延时)

        # 点击可能刚好打开资源不足/宝石确认页；点击后的第二次检查只
        # 在节流窗口允许时执行，战斗连点不会每次额外截一张图。
        # 点击后必须强制检查，不能被前置检查的节流窗口跳过；升级页的
        # 宝石/商店弹窗就是在这次点击后才出现的。
        if self.检查宝石商店危险页面(强制=True):
            return False
        return True

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
        self.模板识别 = 模板匹配引擎()
        self.ocr引擎 = 安全OCR引擎()
        self.检测器 = 线程安全YOLO检测器()
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
            self.上下文.置脚本状态(f"OCR识别失败: {str(e)}")
            return []
