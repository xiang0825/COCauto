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
    # 每个候选点都做一次完整 OCR 会触发模拟器整屏截图和 ONNX 推理，
    # 24 个点在当前设备上超过 CoC 的空闲断线窗口。先快速筛选面板变化，
    # 再对疑似选中目标做 OCR，单轮限制在安全时长内。
    墙体搜索每轮最大候选数 = 12
    墙体搜索最大轮数 = 5
    墙体搜索超时秒 = 75
    墙体点击后等待毫秒 = 350
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
            # 资源确认后若出现建筑工人宝石提示，本轮必须安全终止，不能
            # 继续把同一批墙体记录当成可重试候选再次点击。
            上下文.刷墙安全中止 = False
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
            self._标记资源不足并返回主世界(self.上下文, str(e))
            return False
        except Exception as e:

            self.异常处理(e)
            return False

    def 刷一次墙(self):
        上下文 = self.上下文

        上下文.置脚本状态("开始刷一块墙：扫描主世界可见墙段")
        if self.进入城墙界面(上下文) is False:
            上下文.页面恢复失败 = True
            上下文.置脚本状态("准备刷墙时未确认主世界画面，停止墙体扫描")
            return False
        try:
            # 先刷新右上角实际资源。资源 OCR 失败时数据库会保留上一份
            # 已确认快照，但那份快照可能已经过期；刷墙绝不能拿旧余额
            # 去点击资源升级卡，否则游戏会弹出“购买缺少资源？”并暴露
            # 宝石入口。这里必须 fail-closed：本轮只安全结束，下一轮
            # 重新确认资源后再扫描墙体。
            资源刷新成功 = bool(更新家乡资源状态任务(上下文).执行())
        except Exception as 异常:
            资源刷新成功 = False
            上下文.置脚本状态(f"刷墙前资源刷新失败，禁止使用旧资源快照：{异常}")
        if not 资源刷新成功 or getattr(上下文, "_最近资源识别成功", None) is False:
            上下文.置脚本状态(
                "刷墙前资源 OCR 未确认，禁止读取旧余额、点击升级入口或使用宝石"
            )
            return False
        开始找墙时间 = time.monotonic()
        已尝试点 = []
        本次墙体记录 = []
        当前金币, 当前圣水 = self.获取当前墙体资源(上下文)
        if 当前金币 is None or 当前圣水 is None:
            上下文.置脚本状态(
                "城墙本轮未确认金币/圣水余额，不判定资源不足，不点击升级或宝石入口；稍后重试"
            )
            return False

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

            当前基准画面 = 屏幕图像
            for 候选序号, (x, y) in enumerate(候选点列表, 1):
                if time.monotonic() - 开始找墙时间 >= self.墙体搜索超时秒:
                    break
                已尝试点.append((x, y))
                上下文.置脚本状态(
                    f"尝试选择墙段 {x},{y}（第{候选序号}个候选）"
                )
                if 上下文.点击(x, y, 延时=180, 是否精确点击=True) is False:
                    上下文.置脚本状态(
                        f"墙段{x},{y}选择点击未被安全输入层接受，停止本轮扫描"
                    )
                    return False
                上下文.脚本延时(self.墙体点击后等待毫秒)
                点击前画面 = 当前基准画面
                点击后画面 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)

                # 断线弹窗是可恢复状态：只点击“重新载入游戏”，不关闭
                # 应用、不进入商店，然后交回登录检测重新确认主页。
                需要重载, (重载x, 重载y), _ = self.模板识别.执行匹配(
                    点击后画面,
                    "重新载入游戏.bmp|连接中断.bmp",
                    相似度阈值=0.85,
                )
                if not 需要重载:
                    需要重载, (重载x, 重载y) = self._检测断线弹窗(点击后画面)
                if 需要重载:
                    上下文.置脚本状态(
                        "刷墙扫描发现游戏断线弹窗，仅点击重新载入并恢复主页；不关闭游戏"
                    )
                    if not self._安全重载断线弹窗(上下文, 重载x, 重载y):
                        return False
                    上下文.脚本延时(5000)
                    try:
                        from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务
                        检测游戏登录状态任务(上下文).执行(首次登录=False)
                    except Exception as 异常:
                        上下文.置脚本状态(f"断线恢复后的主页检测失败：{异常}")
                    return False

                # 候选点来自视觉推断，不能假定每个候选仍在主世界地图内。
                # 实机已复现误点飞艇入口后切到夜世界；若继续做城墙 OCR，
                # 后续坐标会被当成夜世界墙体并继续发送错误点击。
                if not self._候选点击后确认主世界(上下文):
                    return False

                # 没有看到选择面板时跳过昂贵 OCR；点击前后仍各只截一次
                # 图，保证真正的墙面板出现时不会漏掉。
                if not self._选择面板明显变化(点击前画面, 点击后画面):
                    当前基准画面 = 点击后画面
                    continue

                当前基准画面 = 点击后画面

                ocr结果 = self.执行OCR识别(上下文, 屏幕图像=点击后画面)
                墙体项 = next(
                    (项 for 项 in (ocr结果 or [])
                     if len(项) >= 2 and self.文本是否城墙(项[1])),
                    None,
                )
                if 墙体项 is None:
                    # 边缘/Hough 候选也可能落在英雄或普通建筑上。它们
                    # 不会触发升级，但会留下选中面板；若直接继续下一点，
                    # 下一次点击可能发生在错误面板上，停止时还会把面板
                    # 留在屏幕。只用安全地图空白点取消，再重新取基准图。
                    if not self._安全关闭非城墙选中面板(上下文):
                        return False
                    当前基准画面 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
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
                # 当前墙体面板会保留在屏幕底部；若直接点击下一个候选点，
                # CoC 可能仍返回旧面板，OCR 就会把旧墙体重复记录到新坐标。
                # 先用地图空白点关闭已确认面板，再重新取基准画面，保证
                # 每个坐标都对应一次真实的新选择。
                if not self._安全关闭已确认面板(上下文):
                    return False
                当前基准画面 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)

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

    def _安全重载断线弹窗(self, 上下文, x: int, y: int) -> bool:
        """断线恢复按钮被输入层拒绝时立即停止，禁止在未知页面继续流程。"""
        try:
            if 上下文.点击已确认安全按钮(x, y, 延时=180) is False:
                上下文.置脚本状态(
                    "刷墙断线恢复按钮输入被拒绝，停止墙体扫描"
                )
                上下文.页面恢复失败 = True
                return False
            return True
        except Exception as 异常:
            上下文.置脚本状态(f"刷墙断线恢复按钮点击失败：{异常}，停止墙体扫描")
            上下文.页面恢复失败 = True
            return False

    def _安全关闭非城墙选中面板(self, 上下文) -> bool:
        """非城墙候选只取消选中，不发送 ESC/BACK，也不触碰商店。"""
        return self._安全关闭已确认面板(
            上下文,
            日志内容="候选点未确认城墙，已安全取消选中面板",
            错误前缀="非城墙候选",
        )

    def _安全关闭已确认面板(
        self,
        上下文,
        日志内容="已确认墙体面板已安全关闭，准备尝试下一个候选",
        错误前缀="已选中面板",
    ) -> bool:
        """只用地图空白点关闭选择面板，不发送 ESC/BACK。"""
        点击 = getattr(上下文, "点击", None)
        if not callable(点击):
            上下文.置脚本状态(f"{错误前缀}未找到安全地图点击入口，停止继续扫描")
            上下文.页面恢复失败 = True
            return False
        try:
            结果 = 点击(90, 80, 延时=220, 是否精确点击=True)
            if 结果 is False:
                上下文.置脚本状态(
                    f"{错误前缀}的安全取消点击未被输入层接受，停止继续扫描"
                )
                上下文.页面恢复失败 = True
                return False
            上下文.脚本延时(180)
            上下文.置脚本状态(日志内容)
            return True
        except Exception as 异常:
            上下文.置脚本状态(f"取消{错误前缀}失败：{异常}，停止继续扫描")
            上下文.页面恢复失败 = True
            return False

    def _候选点击后确认主世界(self, 上下文) -> bool:
        """确认候选点击没有把刷墙流程带到夜世界或其它页面。"""
        识别函数 = getattr(上下文, "识别点击画面", None)
        if not callable(识别函数):
            # 旧测试替身没有页面识别器时保持兼容；正式运行上下文一定
            # 提供该接口，真实设备因此始终走下面的页面护栏。
            return True
        try:
            try:
                结果 = 识别函数(强制=True)
            except TypeError:
                结果 = 识别函数()
        except Exception as 异常:
            上下文.置脚本状态(f"墙段点击后的主世界复核失败：{异常}，停止继续扫描")
            上下文.页面恢复失败 = True
            return False

        页面 = str(getattr(结果, "页面", "") or "")
        世界 = str(getattr(结果, "世界", "") or "")
        可信度 = float(getattr(结果, "可信度", 0.0) or 0.0)
        if 页面 == "主世界主页" and 世界 == "主世界" and 可信度 >= 0.60:
            return True

        if 页面 == "夜世界主页" or 世界 == "夜世界":
            上下文.置脚本状态(
                "墙段候选点击后误入夜世界，停止城墙OCR并尝试切回主世界"
            )
            try:
                from 任务流程.世界跳转.到主世界任务 import 到主世界任务
                if 到主世界任务(上下文).执行():
                    上下文.置脚本状态("刷墙误入夜世界后已切回主世界，结束本轮扫描")
                    return False
            except Exception as 异常:
                上下文.置脚本状态(f"误入夜世界后的主世界恢复失败：{异常}")
            上下文.页面恢复失败 = True
            return False

        上下文.置脚本状态(
            f"墙段点击后未确认主世界（页面={页面 or '未知'}，世界={世界 or '未知'}，"
            f"置信度={可信度:.2f}），停止继续扫描"
        )
        上下文.页面恢复失败 = True
        return False


    def 检查功能开启(self, 上下文) -> bool:
        """检查是否开启刷墙功能"""

        是否开启 = 上下文.数据库.获取机器人设置(上下文.机器人标志).开启刷墙
        if not 是否开启:
            上下文.置脚本状态("刷墙功能已关闭（请在任务计划勾选“刷墙”，配置会自动保存）")
            return False
        else:
            return True

    def _标记资源不足并返回主世界(self, 上下文, 原因: str = "") -> None:
        """资源不足时执行唯一允许的转场：关闭墙体面板并切换刷资源。

        这里故意不点击任何资源、宝石、商店或立即完成入口。即使主世界
        刷资源任务没有在任务计划中勾选，主任务线程也会根据这个标志直接
        启动一次主世界刷资源流程。
        """
        上下文.刷墙需要资源 = True
        if 原因:
            上下文.置脚本状态(f"{原因}；禁止使用宝石，禁止进入商店")
        else:
            上下文.置脚本状态("城墙升级资源不足；禁止使用宝石，禁止进入商店")

        # 选中的城墙面板会遮挡主世界操作区。这里绝不发送 Android BACK/ESC：
        # 实机测试表明该版本墙体选择面板收到 BACK 会弹出“确认退出游戏”，
        # 而不是关闭墙体面板。改用地图左上方经过输入护栏的空白点关闭面板，
        # 再强制复核必须回到主世界，失败就停止而不继续点击。
        键盘 = getattr(上下文, "键盘", None)
        按字符按压 = getattr(键盘, "按字符按压", None)
        点击 = getattr(上下文, "点击", None)
        if not callable(点击):
            上下文.置脚本状态(
                "未找到安全地图点击入口，禁止发送ESC，保持当前画面"
            )
            return
        try:
            结果 = 点击(90, 80, 延时=350, 是否精确点击=True)
            if 结果 is False:
                上下文.置脚本状态(
                    "关闭城墙面板的安全地图点击未被输入层接受，禁止启动刷资源"
                )
                上下文.页面恢复失败 = True
                return
        except Exception as 异常:
            上下文.置脚本状态(f"关闭城墙面板的安全地图点击失败：{异常}")
            上下文.页面恢复失败 = True
            return
        复核函数 = getattr(上下文, "识别点击画面", None)
        if callable(复核函数):
            try:
                复核结果 = 复核函数(强制=True)
                if 复核结果 is not None and 复核结果.页面 != "主世界主页":
                    上下文.置脚本状态(
                        f"关闭城墙面板后未确认主世界（当前={复核结果.页面}），"
                        "停止后续点击"
                    )
                    上下文.页面恢复失败 = True
                    return
            except Exception as 异常:
                上下文.置脚本状态(f"关闭城墙面板后的主页复核失败：{异常}")
                上下文.页面恢复失败 = True
                return
        上下文.置脚本状态("已用安全地图点击退出城墙面板，准备启动主世界刷资源任务")

    @staticmethod
    def 选择可安全使用的升级资源(
            当前金币: int | None,
            当前圣水: int | None,
            金币费用: int | None,
            圣水费用: int | None,
            有金币按钮: bool,
            有圣水按钮: bool,
    ) -> str | None:
        """只返回已确认余额足够的资源类型，余额不足时返回 None。

        资源费用或余额无法确认时也不返回可点击项，确保不会把资源入口
        误点成宝石购买/立即完成入口。
        """
        可用资源 = []
        if (
            有金币按钮
            and 金币费用 is not None
            and 当前金币 is not None
            and int(当前金币) >= int(金币费用)
        ):
            可用资源.append(("金币", int(当前金币)))
        if (
            有圣水按钮
            and 圣水费用 is not None
            and 当前圣水 is not None
            and int(当前圣水) >= int(圣水费用)
        ):
            可用资源.append(("圣水", int(当前圣水)))
        if not 可用资源:
            return None
        return max(可用资源, key=lambda 项目: 项目[1])[0]


    def 已够资源升级(self)-> bool:
        上下文=self.上下文
        更新成功 = 更新家乡资源状态任务(上下文).执行()
        当前金币, 当前圣水 = self.获取当前墙体资源(上下文)
        if not 更新成功 and (当前金币 is None or 当前圣水 is None):
            上下文.置脚本状态(
                "刷墙前资源 OCR 未确认，暂停刷墙；不把未知余额当作 0，也不使用宝石"
            )
            return False
        if 当前金币 is None or 当前圣水 is None:
            上下文.置脚本状态("刷墙前缺少完整资源状态，暂停刷墙且不点击任何资源入口")
            return False
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
        return True



    @staticmethod
    def _检测断线弹窗(屏幕图像: np.ndarray) -> tuple[bool, tuple[int, int]]:
        """模板失效时识别测试服断线弹窗，并返回文字按钮的点击中心。

        不能只看绿色按钮：战斗结算页底部也有绿色“回营”按钮，
        会导致把正常结算页误判为断线。这里先找中央近似均匀的深色
        弹窗主体，再确认标题、正文和左对齐操作文字三段白色文字。
        """
        if not isinstance(屏幕图像, np.ndarray) or 屏幕图像.ndim != 3:
            return False, (0, 0)
        高度, 宽度 = 屏幕图像.shape[:2]
        if 高度 < 300 or 宽度 < 400:
            return False, (0, 0)
        参考点 = 屏幕图像[高度 // 2, 宽度 // 2].astype(np.int16)
        差异 = np.max(
            np.abs(屏幕图像.astype(np.int16) - 参考点), axis=2
        )
        区域左, 区域上 = int(宽度 * 0.08), int(高度 * 0.16)
        区域右, 区域下 = int(宽度 * 0.92), int(高度 * 0.86)
        近似面板 = (差异[区域上:区域下, 区域左:区域右] <= 3).astype(np.uint8) * 255
        近似面板 = cv2.morphologyEx(
            近似面板, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8)
        )
        轮廓列表, _ = cv2.findContours(
            近似面板, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        灰度 = cv2.cvtColor(屏幕图像, cv2.COLOR_BGR2GRAY)
        for 轮廓 in sorted(轮廓列表, key=cv2.contourArea, reverse=True):
            x, y, w, h = cv2.boundingRect(轮廓)
            x += 区域左
            y += 区域上
            面积 = cv2.contourArea(轮廓)
            if not (
                面积 >= 宽度 * 高度 * 0.15
                and 宽度 * 0.42 <= w <= 宽度 * 0.75
                and 高度 * 0.25 <= h <= 高度 * 0.55
                and 宽度 * 0.14 <= x <= 宽度 * 0.30
                and 高度 * 0.22 <= y <= 高度 * 0.45
            ):
                continue
            面板灰度 = 灰度[y:y + h, x:x + w]
            if 面板灰度.size == 0:
                continue
            def 亮像素(上比例, 下比例, 左比例=0.04, 右比例=0.92):
                上边 = max(0, min(h - 1, int(h * 上比例)))
                下边 = max(上边 + 1, min(h, int(h * 下比例)))
                左边 = max(0, min(w - 1, int(w * 左比例)))
                右边 = max(左边 + 1, min(w, int(w * 右比例)))
                return 面板灰度[上边:下边, 左边:右边] > 120

            标题像素 = 亮像素(0.10, 0.35)
            正文像素 = 亮像素(0.35, 0.72)
            操作像素 = 亮像素(0.72, 0.95, 0.04, 0.58)
            if (
                int(np.count_nonzero(标题像素)) < 180
                or int(np.count_nonzero(正文像素)) < 120
                or int(np.count_nonzero(操作像素)) < 120
            ):
                continue
            操作y1, 操作y2 = int(h * 0.72), int(h * 0.95)
            操作x1, 操作x2 = int(w * 0.04), int(w * 0.58)
            ys, xs = np.where(面板灰度[操作y1:操作y2, 操作x1:操作x2] > 120)
            if len(xs) == 0:
                continue
            return True, (
                x + 操作x1 + int((xs.min() + xs.max()) / 2),
                y + 操作y1 + int((ys.min() + ys.max()) / 2),
            )
        return False, (0, 0)

    @staticmethod
    def _选择面板明显变化(点击前画面: np.ndarray, 点击后画面: np.ndarray) -> bool:
        """只比较底部升级面板区，快速判断是否值得调用 OCR。"""
        if (
            not isinstance(点击前画面, np.ndarray)
            or not isinstance(点击后画面, np.ndarray)
            or 点击前画面.shape != 点击后画面.shape
            or 点击前画面.ndim != 3
        ):
            return True
        高度 = 点击后画面.shape[0]
        上边 = max(0, min(高度 - 1, round(高度 * 0.64)))
        前景 = 点击前画面[上边:]
        后景 = 点击后画面[上边:]
        if 前景.size == 0:
            return True
        差异 = cv2.absdiff(前景, 后景)
        变化比例 = float(np.mean(np.max(差异, axis=2) > 22))
        平均变化 = float(np.mean(差异))
        return 变化比例 >= 0.02 or 平均变化 >= 5.0

    def 执行OCR识别(self, 上下文, 屏幕图像=None) -> list:
        """执行屏幕OCR识别"""

        try:
            # 选中墙后标题/升级面板可能出现在底部或右侧，不能再限制在
            # 219,57,595,398；使用完整逻辑画布，OCR 坐标天然为绝对坐标。
            if 屏幕图像 is None:
                屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
            # 城墙标题、费用和确认按钮都位于面板区域。每个候选墙段
            # 都会触发一次 OCR，长期把整张 800×600 画面送入 ONNX 会
            # 放大内存峰值，曾出现 bad allocation/进程无日志退出。限定
            # 到面板区域，同时把 OCR 坐标恢复成 800×600 绝对坐标，
            # 不改变既有解析逻辑。确认页标题贴近顶部，不能从 y=40
            # 开始裁剪，否则“將城升至…”会被漏掉并误判为已提交。
            偏移x, 偏移y = 0, 0
            待识别图像 = 屏幕图像
            if (
                isinstance(屏幕图像, np.ndarray)
                and 屏幕图像.ndim == 3
                and 屏幕图像.shape[0] >= 550
                and 屏幕图像.shape[1] >= 790
            ):
                偏移x, 偏移y = 120, 0
                待识别图像 = np.ascontiguousarray(
                    屏幕图像[偏移y:550, 偏移x:790]
                )
            上下文.置脚本状态(
                f"城墙OCR开始：区域={偏移x},{偏移y},{偏移x + 待识别图像.shape[1]},"
                f"{偏移y + 待识别图像.shape[0]}"
            )
            ocr结果, _ = self.ocr引擎(待识别图像)
            ocr结果 = ocr结果 or []
            if 偏移x or 偏移y:
                恢复结果 = []
                for 识别项 in ocr结果:
                    if len(识别项) < 2:
                        continue
                    修复项 = list(识别项)
                    try:
                        修复项[0] = [
                            [float(点[0]) + 偏移x, float(点[1]) + 偏移y]
                            for 点 in 识别项[0]
                        ]
                    except (TypeError, ValueError, IndexError):
                        continue
                    恢复结果.append(修复项)
                ocr结果 = 恢复结果
            上下文.置脚本状态(f"城墙OCR完成：识别到{len(ocr结果)}项")
            return ocr结果
        except Exception as e:
            判断内存异常 = getattr(上下文, "是否内存异常", None)
            触发内存保护 = getattr(上下文, "触发内存保护", None)
            if callable(判断内存异常) and 判断内存异常(e) and callable(触发内存保护):
                触发内存保护("城墙OCR", e)
            上下文.置脚本状态(f"OCR识别失败: {str(e)}")
            return []

    @classmethod
    def 文本是否城墙(cls, 文本) -> bool:
        """兼容简体/繁体、英文及实机 OCR 漏字的城墙标题。

        国际服实机中 RapidOCR 偶尔会把 ``城墙（16级）`` 识别成
        ``城（16级）``。只放宽这种“单独的城字 + 等级”完整标题，
        不接受任意包含“城”的建筑名称，避免把部落城堡等误当成墙。
        """
        文本 = str(文本 or "").replace(" ", "").replace("級", "级").lower()
        if any(关键词 in 文本 for 关键词 in cls.墙体关键词):
            return True
        return bool(re.fullmatch(r"城[（(]?\d{1,2}级[）)]?[-—]?", 文本))

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
                r"(?:城墙|城牆|围墙|围牆|walls?|城)\D{0,14}"
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
        # 主世界资源/建造区域也可能被 OCR 识别为“建造和升级”。
        # 没有“城墙（等级）”标题时，不能把这类文字当成已打开的墙体面板。
        有城墙等级标题 = 等级 is not None
        已满级 = any(
            self._规范OCR文本(关键词) in 合并文本
            for 关键词 in self.墙体满级关键词
        )
        有升级入口 = any(
            "升级" in 文本 or "升級" in 文本 or "upgrade" in 文本
            for 文本 in 文本列表
        )

        if 已满级 and 有城墙等级标题:
            状态 = "已满级"
        else:
            可用资源结果 = []
            if 金币费用 is not None and 当前金币 is not None:
                可用资源结果.append(int(当前金币) >= 金币费用)
            if 圣水费用 is not None and 当前圣水 is not None:
                可用资源结果.append(int(当前圣水) >= 圣水费用)

            if 有城墙等级标题 and 可用资源结果 and any(可用资源结果) and 有升级入口:
                状态 = "可升级"
            elif 可用资源结果 and not any(可用资源结果):
                状态 = "资源不足"
            elif 有城墙等级标题 and 有升级入口:
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
            资源 = (状态.状态数据 or {}).get("家乡资源")
            if not isinstance(资源, dict):
                return None, None
            if any(字段 not in 资源 for 字段 in ("金币", "圣水")):
                return None, None
            return (
                int(资源["金币"] or 0),
                int(资源["圣水"] or 0),
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
                self._标记资源不足并返回主世界(
                    上下文,
                    f"最低等级墙段{x},{y}（{记录.get('等级') or '未知'}级）资源不足",
                )
                return False
            if 记录.get("状态") != "可升级":
                上下文.置脚本状态(f"墙段{x},{y}状态为{记录.get('状态') or '未知'}，切换下一个候选墙段")
                continue
            上下文.置脚本状态(
                f"选择最低等级墙段{x},{y}（{记录.get('等级') or '未知'}级），二次确认升级"
            )
            if 上下文.点击(x, y, 延时=180, 是否精确点击=True) is False:
                上下文.置脚本状态(
                    f"最低等级墙段{x},{y}二次选择点击未被安全输入层接受"
                )
                return False
            if not self._候选点击后确认主世界(上下文):
                return False
            最新OCR = []
            最新状态 = {"状态": "待确认"}
            # 点击墙段后面板有短暂动画；只重新读取画面，不重复点击墙段。
            # 这样既能等到真实面板出现，也能避免把主世界 OCR 误判成升级面板。
            for 面板重试次数 in range(3):
                上下文.脚本延时(
                    self.墙体点击后等待毫秒 if 面板重试次数 == 0 else 300
                )
                最新OCR = self.执行OCR识别(上下文)
                最新状态 = self.解析城墙状态(最新OCR, 当前金币, 当前圣水)
                if 最新状态["状态"] in {"已满级", "资源不足", "可升级"}:
                    break
                if 面板重试次数 < 2:
                    上下文.置脚本状态(
                        f"墙段{x},{y}面板未稳定，第{面板重试次数 + 1}次重试OCR"
                    )
            if 最新状态["状态"] == "已满级":
                上下文.置脚本状态(f"墙段{x},{y}已满级，切换下一个最低等级墙段")
                continue
            if 最新状态["状态"] == "资源不足":
                self._标记资源不足并返回主世界(
                    上下文,
                    f"墙段{x},{y}资源不足",
                )
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
            if getattr(上下文, "刷墙安全中止", False):
                上下文.置脚本状态(
                    "城墙升级触发宝石安全中止，本轮不再重试墙段，避免重复点击"
                )
                return False
            if getattr(上下文, "页面恢复失败", False):
                上下文.置脚本状态(
                    "城墙升级后的页面未恢复，本轮不再继续点击墙段"
                )
                return False

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
            # 绿色草地在 HSV 中也接近 40°；收窄色相并提高饱和度，
            # 避免整片地图被当作“金色墙顶”。
            np.array([8, 90, 80], dtype=np.uint8),
            np.array([35, 255, 255], dtype=np.uint8),
        )
        灰色掩码 = cv2.inRange(
            hsv图像,
            np.array([0, 0, 28], dtype=np.uint8),
            np.array([179, 145, 205], dtype=np.uint8),
        )
        # 高等级城墙在国际服常见蓝紫色/青色外沿，不能只靠旧的
        # 金色/灰色掩码，否则 Hough 会更偏向建筑和资源图标的边缘。
        蓝紫色掩码 = cv2.inRange(
            hsv图像,
            np.array([88, 55, 42], dtype=np.uint8),
            np.array([179, 255, 235], dtype=np.uint8),
        )
        灰度 = cv2.cvtColor(裁剪, cv2.COLOR_BGR2GRAY)
        边缘 = cv2.Canny(灰度, 60, 170)
        线性掩码 = cv2.bitwise_or(边缘, 金色掩码)
        线性掩码 = cv2.bitwise_or(
            线性掩码,
            cv2.Canny(蓝紫色掩码, 40, 120),
        )
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
        # 蓝紫墙沿在建筑遮挡下通常只有短而断续的边缘；单独用较低
        # 阈值再跑一次颜色边缘 Hough，随后仍统一按距离去重和 OCR
        # 确认，避免把短墙段直接丢在综合线段阈值之外。
        彩色线段列表 = cv2.HoughLinesP(
            cv2.Canny(蓝紫色掩码, 40, 120),
            1,
            np.pi / 180,
            threshold=8,
            minLineLength=18,
            maxLineGap=8,
        )
        if 彩色线段列表 is not None:
            if 线段列表 is None:
                线段列表 = 彩色线段列表
            else:
                线段列表 = np.concatenate((线段列表, 彩色线段列表), axis=0)
        候选评分 = []
        if 线段列表 is not None:
            for 线段 in 线段列表[:, 0]:
                x1, y1, x2, y2 = [int(值) for 值 in 线段]
                长度 = math.hypot(x2 - x1, y2 - y1)
                角度 = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
                # 等距视角下的墙线通常是斜线；过滤水平文字和竖直 UI。
                if 长度 < 16 or not (18 <= 角度 <= 72 or 108 <= 角度 <= 162):
                    continue
                # 墙段经常被建筑或树木遮住，线段两端附近比中点更容易
                # 落在可点击的墙块上；增加采样位置，但仍由后续 OCR
                # 确认，不能直接把边缘当成墙。
                for 比例 in (0.20, 0.35, 0.50, 0.65, 0.80):
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
                    局部蓝紫色 = 蓝紫色掩码[
                        max(0, y - 区域上 - 半径):min(区域下 - 区域上, y - 区域上 + 半径 + 1),
                        max(0, x - 区域左 - 半径):min(区域右 - 区域左, x - 区域左 + 半径 + 1),
                    ]
                    金色比例 = float(np.count_nonzero(局部金色)) / max(1, 局部金色.size)
                    灰色比例 = float(np.count_nonzero(局部灰色)) / max(1, 局部灰色.size)
                    蓝紫色比例 = float(np.count_nonzero(局部蓝紫色)) / max(1, 局部蓝紫色.size)
                    # 降低长度权重，避免长建筑边缘长期霸占前 12 个点；
                    # 墙顶的颜色/纹理证据优先，同时保留足够长的线段。
                    评分 = (
                        长度 * 0.32
                        + 金色比例 * 100
                        + 灰色比例 * 30
                        # 当前国际服高等级城墙的蓝紫外沿是最有区分度的
                        # 证据，权重高于建筑长度和泛金色装饰。
                        + 蓝紫色比例 * 180
                    )
                    候选评分.append((评分, x, y))

        候选评分.sort(reverse=True)
        结果 = []
        # 仅按分数取前 12 个点时，候选可能全部集中在一个建筑边缘，
        # 导致真实墙段所在区域完全没有机会被点击。第一遍按 3×3
        # 空间网格取每格最佳点，第二遍再按分数补齐，特意保留 3 个
        # 名额给同一网格内相邻的墙段，既控制 OCR 次数，又避免真实墙
        # 与建筑边缘落在同一格时被唯一候选遮掉；最终仍必须经过城墙
        # OCR 安全确认。
        网格列数, 网格行数 = 3, 3
        已覆盖网格 = set()
        区域宽度 = max(1, 区域右 - 区域左)
        区域高度 = max(1, 区域下 - 区域上)

        def 添加候选(x, y, 网格键=None):
            if not (区域左 <= x < 区域右 and 区域上 <= y < 区域下):
                return False
            if any((x - 旧x) ** 2 + (y - 旧y) ** 2 < 16 ** 2 for 旧x, 旧y in 结果):
                return False
            结果.append((x, y))
            if 网格键 is not None:
                已覆盖网格.add(网格键)
            return True

        for _, x, y in 候选评分:
            网格x = min(
                网格列数 - 1,
                max(0, int((x - 区域左) * 网格列数 / 区域宽度)),
            )
            网格y = min(
                网格行数 - 1,
                max(0, int((y - 区域上) * 网格行数 / 区域高度)),
            )
            网格键 = (网格x, 网格y)
            if 网格键 in 已覆盖网格:
                continue
            if 添加候选(x, y, 网格键) and len(结果) >= self.墙体搜索每轮最大候选数:
                break

        if len(结果) < self.墙体搜索每轮最大候选数:
            for _, x, y in 候选评分:
                if 添加候选(x, y) and len(结果) >= self.墙体搜索每轮最大候选数:
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
            # 实机 800×600 城墙面板的费用文字上沿通常在 420～428；
            # 旧的 430 下限会漏掉真实的 10,000,000/5,000,000 费用，
            # 随后错误地进入“费用未知”分支并触发危险的 ESC 恢复。
            if y1 < 395 or y2 > 500:
                continue
            数值 = self.OCR文本数字(识别项[1])
            if 数值 is None:
                continue
            if x2 <= 485:
                金币费用 = 数值
            elif x1 >= 485:
                圣水费用 = 数值
        return 金币费用, 圣水费用

    @staticmethod
    def 获取城墙升级资源模板() -> tuple[str, str]:
        """返回主世界城墙面板的资源按钮模板。

        城墙升级只发生在主世界。这里不能根据“是否刷主世界”选择模板，
        因为该开关只控制主世界刷资源任务；用户可以关闭刷资源而单独开启刷墙。
        旧逻辑在这种配置下会误用夜世界模板，导致两个按钮都匹配失败。
        """
        return (
            "升级建筑的金币小图标.bmp|升级建筑的金币小图标1.bmp",
            "升级建筑的圣水小图标.bmp|升级建筑的圣水小图标1.bmp",
        )

    def 识别城墙升级资源按钮(self, 上下文, OCR结果=None) -> dict:
        """在主世界城墙面板中定位金币/圣水升级入口。

        首选历史上最稳定的按钮区域；如果游戏 UI 因窗口缩放或版本差异
        发生轻微偏移，再使用扩大的兼容区域。返回的点击点是升级按钮中心
        附近的安全位置，而不是资源小图标本身。
        """
        金币图片, 圣水图片 = self.获取城墙升级资源模板()
        搜索区域列表 = (
            (276, 440, 626, 468),
            (250, 425, 650, 525),
            (133, 428, 677, 491),
        )

        for 区域左, 区域上, 区域右, 区域下 in 搜索区域列表:
            区域图像 = 上下文.op.获取屏幕图像cv(
                区域左, 区域上, 区域右, 区域下
            )
            if 区域图像 is None or getattr(区域图像, "size", 0) == 0:
                continue

            有金币图标, (金币x, 金币y), _ = self.模板识别.执行匹配(
                区域图像, 金币图片, 0.9
            )
            有圣水图标, (圣水x, 圣水y), _ = self.模板识别.执行匹配(
                区域图像, 圣水图片, 0.9
            )
            if not 有金币图标 and not 有圣水图标:
                continue

            # 模板返回的是小图标中心；按钮可点击中心在其左下方。
            金币点击点 = (
                区域左 + 金币x - 27,
                区域上 + 金币y + 30,
            ) if 有金币图标 else (0, 0)
            圣水点击点 = (
                区域左 + 圣水x - 27,
                区域上 + 圣水y + 30,
            ) if 有圣水图标 else (0, 0)
            上下文.置脚本状态(
                "城墙升级入口匹配（主世界模板）："
                f"金币={'成功' if 有金币图标 else '失败'}，"
                f"圣水={'成功' if 有圣水图标 else '失败'}，"
                f"搜索区域={区域左},{区域上},{区域右},{区域下}"
            )
            return {
                "金币": 有金币图标,
                "金币点击点": 金币点击点,
                "圣水": 有圣水图标,
                "圣水点击点": 圣水点击点,
            }

        # 当前测试服的升级卡片会把资源图标放大并叠加半透明背景，旧的
        # 小图标模板在实机上最高只有约 0.7 匹配度，导致明明能看到两张
        # “5000000 + 升级”卡片却报告“无法定位升级按钮”。优先使用本次
        # 已经完成的面板 OCR，按“升级”文字和费用文字所在卡片反推出
        # 点击中心；坐标只允许落在两张资源升级卡片的中下部，绝不会
        # 触及“商店”或“宝石”入口。
        if OCR结果 is None:
            OCR结果 = self.执行OCR识别(上下文)

        def 规范升级文字(文本) -> str:
            return (
                self._规范OCR文本(文本)
                .replace("极", "级")
                .replace("極", "級")
            )

        OCR金币点击点 = None
        OCR圣水点击点 = None
        OCR金币费用框 = None
        OCR圣水费用框 = None
        # 当前 MuMu 画面中左侧费用框可能横跨旧的 x=485 分界线
        # （例如 457..515），不能用“右边界 <= 485”判断卡片归属。
        # 两张升级卡片的实际中线约为 528；按文字框中心分栏，兼容
        # 1280x720 映射到 800x600 后的轻微横向偏移。
        卡片分栏中线 = 528
        for 识别项 in OCR结果 or []:
            if len(识别项) < 2:
                continue
            try:
                x1, y1, x2, y2 = self.解析OCR坐标(识别项[0])
            except (TypeError, ValueError, IndexError):
                continue
            文本 = 规范升级文字(识别项[1])
            中心x = (x1 + x2) // 2
            if y1 >= 470 and "升" in 文本 and (
                "级" in 文本 or "級" in 文本
            ):
                if 390 <= 中心x < 卡片分栏中线 and OCR金币点击点 is None:
                    OCR金币点击点 = (中心x, min(520, max(460, (y1 + y2) // 2)))
                elif 卡片分栏中线 <= 中心x <= 650 and OCR圣水点击点 is None:
                    OCR圣水点击点 = (中心x, min(520, max(460, (y1 + y2) // 2)))
                continue

            数值 = self.OCR文本数字(识别项[1])
            if 数值 is None or not (400 <= y1 <= 470):
                continue
            if 中心x < 卡片分栏中线 and OCR金币费用框 is None:
                OCR金币费用框 = (x1, y1, x2, y2)
            elif 卡片分栏中线 <= 中心x and OCR圣水费用框 is None:
                OCR圣水费用框 = (x1, y1, x2, y2)

        if OCR金币点击点 is None and OCR金币费用框 is not None:
            x1, y1, x2, y2 = OCR金币费用框
            OCR金币点击点 = (
                (x1 + x2) // 2,
                min(520, max(460, y2 + 38)),
            )
        if OCR圣水点击点 is None and OCR圣水费用框 is not None:
            x1, y1, x2, y2 = OCR圣水费用框
            OCR圣水点击点 = (
                (x1 + x2) // 2,
                min(520, max(460, y2 + 38)),
            )

        if OCR金币点击点 is not None or OCR圣水点击点 is not None:
            上下文.置脚本状态(
                "城墙升级入口匹配（OCR兼容回退）："
                f"金币={'成功' if OCR金币点击点 is not None else '失败'}，"
                f"圣水={'成功' if OCR圣水点击点 is not None else '失败'}"
            )
            return {
                "金币": OCR金币点击点 is not None,
                "金币点击点": OCR金币点击点 or (0, 0),
                "圣水": OCR圣水点击点 is not None,
                "圣水点击点": OCR圣水点击点 or (0, 0),
            }

        OCR摘要列表 = []
        for 项 in (OCR结果 or []):
            if len(项) < 2:
                continue
            try:
                左, 上, _, _ = self.解析OCR坐标(项[0])
            except (TypeError, ValueError, IndexError):
                continue
            OCR摘要列表.append(f"{str(项[1])[:24]}@{左},{上}")
        OCR摘要 = "；".join(OCR摘要列表)[:700]
        上下文.置脚本状态(
            "城墙升级入口匹配失败：已尝试主世界资源按钮模板和兼容区域"
            + (f"；OCR摘要={OCR摘要}" if OCR摘要 else "；OCR摘要为空")
        )
        return {
            "金币": False,
            "金币点击点": (0, 0),
            "圣水": False,
            "圣水点击点": (0, 0),
        }

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

    @classmethod
    def _建筑工人不可用(cls, ocr结果) -> bool:
        """识别“升级时间无/建筑工人忙”，避免点击后弹出宝石提示。"""
        for 识别项 in ocr结果 or []:
            if len(识别项) < 2:
                continue
            文本 = cls._规范OCR文本(识别项[1])
            if any(片段 in 文本 for 片段 in ("升级时间", "升級时间", "升级時間", "升級時間")) and any(
                词 in 文本 for 词 in ("无", "無", "none", "n/a", "不可用")
            ):
                return True
            if ("建筑工人" in 文本 or "建築工人" in 文本) and any(
                词 in 文本 for 词 in ("忙", "占用", "不可用", "busy")
            ):
                return True
        return False

    def 定位城墙升级确认资源按钮(self, ocr结果) -> tuple[int, int] | None:
        """OCR 漏识别“确认”时，按右下角资源费用反推确认按钮中心。

        测试服字体下“确认”经常被识别成无关汉字，但确认框标题和
        5,000,000 资源费用仍然稳定可见。只接受右下角、底部的资源数字，
        不会把顶部资源栏或宝石数量当成确认按钮。
        """
        for 识别项 in ocr结果 or []:
            if len(识别项) < 2:
                continue
            try:
                x1, y1, x2, y2 = self.解析OCR坐标(识别项[0])
            except Exception:
                continue
            if x1 < 480 or y1 < 500 or y2 > 570:
                continue
            if self.OCR文本数字(识别项[1]) is None:
                continue
            # 费用数字位于绿色确认按钮的下半部，点击其上方按钮主体。
            return ((x1 + x2) // 2, max(480, y1 - 18))
        return None

    @staticmethod
    def _规范城墙升级确认标题(文本) -> str:
        """兼容测试服中文字体把“墙/升/至”识别成近形字。"""
        return (
            str(文本 or "")
            .replace(" ", "")
            .replace("瘤", "墙")
            .replace("牆", "墙")
            .replace("將", "将")
            .replace("確認", "确认")
            .replace("確", "确")
            .replace("開", "升")
            .replace("开", "升")
            .replace("級", "级")
            # 当前国际服测试画面偶尔把标题“將城牆升至”漏识别为
            # “將城升至”。只有在确认标题短语中补回“墙”，不影响
            # 普通建筑/资源文字。
            .replace("将城升至", "将城墙升至")
            .replace("将城升到", "将城墙升到")
            .replace("城升至", "墙升至")
            .replace("城升到", "墙升到")
            .lower()
        )

    def 确认城墙升级提交(self, 上下文) -> bool:
        """处理资源按钮之后出现的升级确认框，并验证确认框已消失。"""
        上下文.置脚本状态("城墙升级确认OCR开始")
        确认OCR = self.执行OCR识别(上下文)
        if not 确认OCR:
            # OCR 没有返回结果时不能把“未知”当成已提交，否则确认框
            # 会留在屏幕上，下一轮可能把普通坐标误当成升级入口。
            上下文.置脚本状态("城墙升级确认OCR无结果，保留确认框并结束本轮")
            return False
        if self._建筑工人不可用(确认OCR):
            上下文.置脚本状态(
                "确认页识别到建筑工人全部忙碌，禁止点击确认和使用宝石"
            )
            上下文.刷墙安全中止 = True
            关闭详情 = getattr(上下文, "关闭升级详情弹窗", None)
            if callable(关闭详情):
                try:
                    关闭详情()
                except Exception as 异常:
                    上下文.置脚本状态(f"忙碌建筑工人确认页安全关闭失败：{异常}")
            return False
        合并文本 = " ".join(
            self._规范城墙升级确认标题(项[1])
            for 项 in (确认OCR or [])
            if len(项) >= 2
        )
        有升级确认框 = (
            "将城墙升至" in 合并文本
            or "将墙升至" in 合并文本
            or "城墙升至" in 合并文本
            or "upgrade" in 合并文本 and "wall" in 合并文本
        )
        确认点 = self.定位城墙升级确认按钮(确认OCR)
        if 有升级确认框 and 确认点 is None:
            确认点 = self.定位城墙升级确认资源按钮(确认OCR)
        if not 有升级确认框 and 确认点 is None:
            # 资源入口点击后即使 OCR 没有识别到标题，也不能把未知画面
            # 当作“已经提交”。实机测试服曾把真实标题识别成“將城升至”，
            # 旧分支会因此误报成功并把确认框留在屏幕上。宁可保留当前
            # 面板等待下一轮复核，也绝不放行后续任务或触发宝石路径。
            上下文.置脚本状态(
                "城墙升级确认页证据不足，未确认二次确认框或已提交；"
                "保留当前画面并停止本轮"
            )
            return False
        if 确认点 is None:
            上下文.置脚本状态("已出现城墙升级确认框，但未定位到确认按钮")
            return False

        上下文.置脚本状态(f"定位城墙升级确认按钮{确认点[0]},{确认点[1]}，提交升级")
        上下文._城墙升级确认中 = True
        try:
            点击成功 = 上下文.点击(
                确认点[0],
                确认点[1],
                延时=650,
                是否精确点击=True,
            )
            if 点击成功 is False:
                上下文.置脚本状态(
                    "城墙升级确认按钮未被安全输入层接受，未确认升级提交"
                )
                return False
            上下文.置脚本状态("城墙升级确认按钮已点击，开始验证确认框消失")
            无确认页证据次数 = 0
            for _ in range(3):
                上下文.脚本延时(300)
                验证OCR = self.执行OCR识别(上下文)
                验证文本 = " ".join(
                    self._规范城墙升级确认标题(项[1])
                    for 项 in (验证OCR or [])
                    if len(项) >= 2
                )
                # 建筑工人/宝石提示会覆盖确认页，但底下的“将城墙升至…”
                # 仍然可被 OCR 读到。因此危险文字必须优先于确认标题判断，
                # 否则会把上层宝石提示误当作“确认框还在”而一直卡住。
                if any(
                    词 in 验证文本
                    for 词 in (
                        "宝石", "寶石", "使用宝石", "使用寶石",
                        "立即完成", "商店", "shop",
                    )
                ):
                    检查危险页 = getattr(上下文, "检查宝石商店危险页面", None)
                    if callable(检查危险页):
                        # 通用护栏默认会跳过城墙确认阶段，以避免把资源
                        # 图标误报为宝石。此处已有 OCR 明确危险文字，临时
                        # 解除该标志，只允许护栏执行安全 ESC，不允许点击。
                        try:
                            上下文._城墙升级确认中 = False
                            检查危险页(强制=True)
                        except Exception as 异常:
                            上下文.置脚本状态(f"宝石提示安全退出失败，保留当前画面：{异常}")
                        finally:
                            上下文._城墙升级确认中 = True
                    上下文.置脚本状态(
                        "确认后出现建筑工人宝石提示，已禁止使用宝石；"
                        "本次升级未提交，停止复核并交给下一轮任务"
                    )
                    上下文.刷墙安全中止 = True
                    return False
                确认框仍在 = (
                    "将城墙升至" in 验证文本
                    or "将墙升至" in 验证文本
                    or "城墙升至" in 验证文本
                    or ("upgrade" in 验证文本 and "wall" in 验证文本)
                    # 标题偶发漏字时，底部“升级时间 + 费用”仍是确认页
                    # 的结构证据；不能只因标题一帧漏识别就触发宝石护栏。
                    or ("升级时间" in 验证文本 and self.OCR文本数字(验证文本) is not None)
                )
                if 确认框仍在:
                    无确认页证据次数 = 0
                    continue

                无确认页证据次数 += 1
                if 无确认页证据次数 < 2:
                    continue
                识别页面 = getattr(上下文, "识别点击画面", None)
                页面结果 = 识别页面(强制=True) if callable(识别页面) else None
                if 页面结果 is None or getattr(页面结果, "页面", "") == "主世界主页":
                    上下文.置脚本状态("城墙升级确认已提交")
                    return True
            上下文.置脚本状态("城墙升级确认框仍在，未确认升级提交")
            return False
        finally:
            上下文._城墙升级确认中 = False

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
                self._标记资源不足并返回主世界(
                    上下文,
                    "识别到城墙升级资源不足",
                )
                return False
            return True
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
                if 上下文.点击(中心x, 中心y, 延时=1500) is False:
                    上下文.置脚本状态("城墙升级入口点击未被安全输入层接受")
                    return False
            else:
                # 直接扫描墙段时目标已经被点击；再次点击可能会关闭面板或
                # 进入“选择一列”，所以只等待升级面板稳定。
                上下文.置脚本状态("城墙面板已打开，不重复点击墙段")
                上下文.脚本延时(350)

            # # 选择升级资源
            # 当前金币 = 上下文.数据库.获取最新资源(上下文.机器人标志).get("金币", 0)
            # 当前圣水 = 上下文.数据库.获取最新资源(上下文.机器人标志).get("圣水", 0)


            当前金币, 当前圣水 = self.获取当前墙体资源(上下文)
            if 当前金币 is None or 当前圣水 is None:
                上下文.置脚本状态(
                    "资源余额未确认，禁止点击城墙升级入口、宝石入口或商店入口"
                )
                return False
            金币费用, 圣水费用 = self.解析城墙升级费用(OCR结果)
            按钮识别 = self.识别城墙升级资源按钮(上下文, OCR结果=OCR结果)
            # OCR 结果可能来自点击后的上一帧；按钮未定位时刷新最多两次。
            # 刷新期间不发送任何点击，失败则安全退出，绝不回退到宝石/商店。
            for 按钮重试次数 in range(2):
                if 按钮识别["金币"] or 按钮识别["圣水"]:
                    break
                上下文.置脚本状态(
                    f"城墙升级入口未稳定，第{按钮重试次数 + 1}次刷新面板OCR"
                )
                上下文.脚本延时(300)
                新OCR = self.执行OCR识别(上下文)
                if 新OCR:
                    OCR结果 = 新OCR
                按钮识别 = self.识别城墙升级资源按钮(
                    上下文, OCR结果=OCR结果
                )
            有金币图标 = 按钮识别["金币"]
            有圣水图标 = 按钮识别["圣水"]
            金币x, 金币y = 按钮识别["金币点击点"]
            圣水x, 圣水y = 按钮识别["圣水点击点"]

            if not 有金币图标 and not 有圣水图标:
                raise RuntimeError("无法定位主世界城墙升级按钮")

            # 测试服在建筑工人全部占用时仍会显示资源升级卡片；点击
            # 卡片不会开始升级，而是弹出“额外支付宝石”的提示。这个
            # 分支必须在发送资源按钮点击前拦截，不能等弹窗出现后再
            # 退出。面板关闭后交给下一轮重试，不使用宝石、不进商店。
            if self._建筑工人不可用(OCR结果):
                上下文.置脚本状态(
                    "识别到建筑工人不可用，跳过城墙升级入口；禁止使用宝石"
                )
                self._安全关闭非城墙选中面板(上下文)
                return False

            安全资源 = self.选择可安全使用的升级资源(
                当前金币,
                当前圣水,
                金币费用,
                圣水费用,
                有金币图标,
                有圣水图标,
            )
            if 安全资源 is None:
                self._标记资源不足并返回主世界(
                    上下文,
                    "没有确认到足够的城墙升级资源或升级费用",
                )
                return False

            # 此处已经通过资源余额、费用和按钮 OCR 三重确认，属于城墙面板
            # 内唯一允许的资源按钮输入。主页 HUD 可能仍露在面板后方，通用
            # 升级面板护栏会把它识别成“主页+升级详情”，因此仅在这一枚
            # 已验证按钮的点击期间放行，点击完成后立即恢复通用拦截。
            上下文._城墙升级资源点击中 = True
            try:
                if 安全资源 == "圣水":
                    上下文.置脚本状态("使用圣水升级")
                    点击成功 = 上下文.点击(圣水x, 圣水y, 延时=1000)
                else:
                    上下文.置脚本状态("使用金币升级")
                    点击成功 = 上下文.点击(金币x, 金币y, 延时=1000)
            finally:
                上下文._城墙升级资源点击中 = False
            if 点击成功 is False:
                上下文.置脚本状态(
                    "城墙升级资源入口点击未被安全输入层接受，未确认升级提交"
                )
                return False
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
