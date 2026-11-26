import argparse
import sys
import threading
import queue
import time
from dataclasses import replace
from time import sleep


def _配置稳定的控制台输出():
    """让 Windows 控制台不会因中文日志导致机器人线程崩溃。

    MuMu/CoC 的任务线程会把中文状态打印到 stdout。某些启动方式（尤其
    双击 EXE、旧版 cmd 或被重定向到文件时）会把 stdout 标成 cp1252，
    这时普通 print 会抛出 UnicodeEncodeError，连带结束任务线程。这里
    只调整 Python 文本流的编码和容错，不改变 ADB 或游戏操作。
    """
    for 流 in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        if 流 is None or not hasattr(流, "reconfigure"):
            continue
        try:
            流.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 无控制台/已关闭的重定向流不应阻止程序启动。
            pass


_配置稳定的控制台输出()

from 数据库.任务数据库 import 任务数据库, 机器人设置
from 模块.ADB设备操作类 import ADB设备操作类
from 线程.自动化机器人 import 自动化机器人


class 自动重启策略:
    """非人工停止后的自动重启节流：冷却、连续失败计数、放弃。

    纯状态机，不做 I/O，方便单测；监控中心负责截图复核和真正启动。
    监控线程、复核线程和界面线程都会调用，所有状态读写都在锁内。
    """

    冷却秒 = 600.0
    # 自动重启后稳定运行满这么久才清零失败计数；必须大于冷却秒，
    # 否则“每 10 分钟停一次”会被当成稳定而无限重启。
    稳定清零秒 = 3600.0
    最大连续失败 = 3
    人工或终止原因 = frozenset({"", "未启动", "控制台关闭", "手动终止", "界面停止按钮", "任务自然完成"})

    def __init__(self, 时钟=time.monotonic):
        self._时钟 = 时钟
        self._状态: dict[str, dict] = {}
        self._锁 = threading.RLock()

    def _取(self, 标志: str) -> dict:
        return self._状态.setdefault(标志, {
            "停止线程": None, "停止时间": 0.0, "上次重启": None,
            "上次尝试": None, "连续失败": 0, "已放弃": False, "复核中": False,
        })

    @classmethod
    def 原因可自动重启(cls, 原因: str) -> bool:
        原因 = str(原因 or "").strip()
        if 原因 in cls.人工或终止原因:
            return False
        # 内存保护：重启只会再次压垮主机，必须人工处理。
        return "内存" not in 原因

    def 记录人工操作(self, 标志: str) -> None:
        """人工开始/停止后清零：人工永远优先，失败计数从头算。"""
        with self._锁:
            self._状态.pop(标志, None)

    def 判定(self, 标志: str, 线程标识, 原因: str, 已暂停: bool) -> str:
        """返回 'ignore' | 'wait' | 'give_up' | 'check'。

        线程标识：已停止的主线程对象 id，用来区分“同一次停止”和“新的停止”。
        """
        with self._锁:
            return self._判定(标志, 线程标识, 原因, 已暂停)

    def _判定(self, 标志: str, 线程标识, 原因: str, 已暂停: bool) -> str:
        状态 = self._取(标志)
        现在 = self._时钟()
        if 状态["停止线程"] != 线程标识:
            # 新的一次停止。重启后不到稳定清零时间又停了，算这次重启失败。
            状态["停止线程"] = 线程标识
            状态["停止时间"] = 现在
            if 状态["上次重启"] is not None and 现在 - 状态["上次重启"] < self.稳定清零秒:
                状态["连续失败"] += 1
            elif 状态["上次重启"] is not None:
                状态["连续失败"] = 0
            状态["上次重启"] = None
        if not self.原因可自动重启(原因):
            if 原因 not in ("", "未启动"):
                self.记录人工操作(标志)
            return "ignore"
        if 已暂停 or 状态["复核中"]:
            return "ignore"
        if 状态["已放弃"]:
            return "ignore"
        if 状态["连续失败"] >= self.最大连续失败:
            状态["已放弃"] = True
            return "give_up"
        起点 = 状态["上次尝试"] if 状态["上次尝试"] is not None else 状态["停止时间"]
        if 现在 - 起点 < self.冷却秒:
            return "wait"
        状态["复核中"] = True
        状态["上次尝试"] = 现在
        return "check"

    def 复核结果(self, 标志: str, 已重启: bool, 人工介入: bool = False) -> None:
        """复核线程结束时调用。人工介入不计失败，只解除“复核中”。"""
        with self._锁:
            状态 = self._状态.get(标志)
            if 状态 is None:
                # 复核期间人工操作已清空状态：这次复核作废，不重建、不计数。
                return
            状态["复核中"] = False
            if 人工介入:
                return
            if 已重启:
                状态["上次重启"] = self._时钟()
            else:
                状态["连续失败"] += 1

    def 连续失败(self, 标志: str) -> int:
        with self._锁:
            状态 = self._状态.get(标志)
            return int(状态["连续失败"]) if 状态 else 0


# ==== 监控中心 ====
class 机器人监控中心:
    """增强型监控服务"""

    # 关窗时等待所有机器人主线程退出的总时长上限（秒）。
    关闭等待主线程秒 = 5.0

    def __init__(self,日志队列=None):
        self.机器人池 = {}
        # UI 停顿或窗口缩放时，日志不能无限堆积到内存；数据库仍保留
        # 日志历史，队列只承担实时显示职责。
        self.日志队列 = 日志队列 or queue.Queue(maxsize=2000)
        # 监控消息只是短暂的内部通知，设置上限避免异常线程持续产生日志时
        # 把消息无限堆进内存；详细历史仍由机器人自己的数据库保存。
        self.全局消息队列 = queue.Queue(maxsize=500)
        self.数据库 = 任务数据库()
        self.运行标志 = True#用于控制监控线程退出的标志
        self.自动重启 = 自动重启策略()

        # 启动监控线程,监控每一个机器人的行为
        self.监控线程 = threading.Thread(
            target=self._监控循环,
            name="机器人监控线程",
            daemon=True
        )
        self.监控线程.start()



    def 创建机器人(self,机器人标志: str, 初始设置: 机器人设置 = None):

        if 机器人标志 in self.机器人池:
            raise ValueError(f"机器人标志[{机器人标志}],已存在")
        else:
            机器人实例 = 自动化机器人(机器人标志, self.全局消息队列, self.数据库,self.日志队列)

        if 初始设置:
            self.数据库.保存机器人设置(机器人标志, 初始设置)

        self.机器人池[机器人标志] = 机器人实例

    def 创建并启动机器人(self, 机器人标志: str, 初始设置: 机器人设置 = None):
        """创建机器人并启动"""
        self.创建机器人(机器人标志,初始设置)
        self.启动机器人(机器人标志)

    def 启动机器人(self, 机器人标志: str):
        """通过统一护栏启动机器人，禁止同一 ADB 设备被并行占用。"""
        if 机器人标志 not in self.机器人池:
            raise ValueError(f"机器人标志[{机器人标志}]不存在")
        self._检查设备是否已被其它机器人占用(机器人标志)
        self.机器人池[机器人标志].启动()
        # 人工启动（界面/F1）把自动重启的失败计数清零。
        策略 = getattr(self, "自动重启", None)
        if 策略 is not None:
            策略.记录人工操作(机器人标志)

    def _检查设备是否已被其它机器人占用(self, 机器人标志: str) -> None:
        """启动前阻止多个机器人同时控制同一模拟器。"""
        当前设置 = self.数据库.获取机器人设置(机器人标志)
        当前序列号 = str(
            getattr(当前设置, "ADB设备序列号", "") or ""
        ).strip()
        if not 当前序列号:
            return

        for 其它标志, 其它机器人 in self.机器人池.items():
            if 其它标志 == 机器人标志:
                continue
            停止事件 = getattr(其它机器人, "停止事件", None)
            # 没有停止事件的旧/测试替身按“占用中”处理，保持 fail-closed。
            if 停止事件 is None or not 停止事件.is_set():
                其它设置 = self.数据库.获取机器人设置(其它标志)
                其它序列号 = str(
                    getattr(其它设置, "ADB设备序列号", "") or ""
                ).strip()
                if 其它序列号 and 其它序列号 == 当前序列号:
                    raise RuntimeError(
                        f"ADB 设备 {当前序列号} 已被机器人[{其它标志}]占用，"
                        f"禁止同时启动机器人[{机器人标志}]"
                    )

    def 关闭(self):
        """关闭监控中心，确保桌面程序退出时不留下后台进程。"""
        self.运行标志 = False
        机器人列表 = list(self.机器人池.values())
        for 机器人 in 机器人列表:
            try:
                机器人.停止("控制台关闭", 等待=False)
            except Exception:
                pass
        # 先等主线程收尾（写完最后几条日志），调用方随后才轮转/清空日志。
        截止 = time.monotonic() + self.关闭等待主线程秒
        for 机器人 in 机器人列表:
            主线程 = getattr(机器人, "主线程", None)
            if 主线程 is None or 主线程 is threading.current_thread():
                continue
            try:
                if 主线程.is_alive():
                    主线程.join(timeout=max(0.0, 截止 - time.monotonic()))
            except Exception:
                pass
        if hasattr(self, "监控线程") and self.监控线程.is_alive():
            # 监控循环最多每秒检查一次；短等待即可释放数据库和互斥锁。
            self.监控线程.join(timeout=2)

    def _监控循环(self):
        """持续监控所有机器人的状态"""
        while self.运行标志:
            # 检查任务状态
            for 用户标识, 线程 in list(self.机器人池.items()):
                # print("监控中")
                超时状态, 原因 = 线程.检查超时()
                if  超时状态:

                    self._加入全局消息队列(f"机器人{用户标识} "+原因)
                    留证 = getattr(线程, "保存异常现场", None)
                    if callable(留证):
                        留证("心跳超时", 原因)
                    线程.停止("无心跳")
                    # 无心跳时画面可能正处于战斗、结算或 ADB 断连的中间态。
                    # 这里绝不把任意应用拉到前台，也不立即重建线程；只有
                    # 冷却后只读确认回到主世界主页，才由自动重启策略重启。
                    self._加入全局消息队列(
                        f"机器人{用户标识} 已安全停止；不切换、重启或关闭任何 Android 应用，"
                        "确认回到主世界主页后才会自动重启。"
                    )

                try:
                    self._检查自动重启(用户标识, 线程)
                except Exception as 异常:
                    print(f"[监控中心] 自动重启检查失败：{异常}")

                # 处理消息
            self._处理消息()
            self._检查每日通知()
            time.sleep(1)

    def _检查每日通知(self) -> None:
        """到点发每日完成汇总（调度器自身 30 秒节流、每天只发一次）。"""
        try:
            调度器 = getattr(self, "_每日通知调度器", None)
            if 调度器 is None:
                from 应用.每日通知 import 每日通知调度器

                调度器 = 每日通知调度器(self.数据库, lambda: list(self.机器人池.keys()))
                self._每日通知调度器 = 调度器
            调度器.检查()
        except Exception as 异常:
            print(f"[监控中心] 每日通知检查失败：{异常}")

    def _检查自动重启(self, 标志: str, 机器人) -> None:
        停止事件 = getattr(机器人, "停止事件", None)
        if 停止事件 is None or not 停止事件.is_set() or not self.运行标志:
            return
        主线程 = getattr(机器人, "主线程", None)
        if 主线程 is None or 主线程.is_alive():
            return
        try:
            允许 = bool(getattr(self.数据库.获取机器人设置(标志), "非人工停止后自动重启", True))
        except Exception:
            允许 = False
        if not 允许:
            return
        继续事件 = getattr(机器人, "继续事件", None)
        已暂停 = 继续事件 is not None and not 继续事件.is_set()
        原因 = str(getattr(机器人, "停止原因", "") or "")
        动作 = self.自动重启.判定(标志, id(主线程), 原因, 已暂停)
        if 动作 == "give_up":
            文本 = (
                f"非人工停止后自动重启已连续失败 {self.自动重启.最大连续失败} 次，"
                f"不再自动重启；最后停止原因：{原因}"
            )
            self._记录机器人日志(机器人, 文本)
            self._桌面通知(标志, "自动重启已放弃", 文本)
        elif 动作 == "check":
            threading.Thread(
                target=self._复核并自动重启, args=(标志, 机器人, 原因, 主线程),
                name=f"自动重启复核-{标志}", daemon=True,
            ).start()

    def _复核并自动重启(self, 标志: str, 机器人, 原因: str, 原线程) -> None:
        已重启 = False
        人工介入 = False
        try:
            确认, 说明 = 机器人.只读确认主世界主页()
            # 复核期间人工点了开始/停止/暂停：人工优先，放弃这次自动重启。
            继续事件 = getattr(机器人, "继续事件", None)
            人工介入 = (
                getattr(机器人, "主线程", None) is not 原线程
                or str(getattr(机器人, "停止原因", "") or "") != 原因
                or (继续事件 is not None and not 继续事件.is_set())
                or not self.运行标志
            )
            if 人工介入:
                return
            if not 确认:
                self._记录机器人日志(
                    机器人,
                    f"自动重启前只读复核未确认主世界主页（{说明}），"
                    f"10 分钟后再试（已失败 {self.自动重启.连续失败(标志) + 1} 次）",
                )
                return
            self._记录机器人日志(机器人, f"非人工停止（{原因}）后已确认主世界主页（{说明}），自动重启任务计划")
            self._检查设备是否已被其它机器人占用(标志)
            机器人.启动()
            已重启 = True
        except Exception as 异常:
            self._记录机器人日志(机器人, f"自动重启失败：{异常}")
        finally:
            self.自动重启.复核结果(标志, 已重启, 人工介入=人工介入)

    @staticmethod
    def _记录机器人日志(机器人, 文本: str) -> None:
        try:
            机器人.记录日志(文本, 300, "警告")
        except Exception:
            print(f"[监控中心] {文本}")

    def _桌面通知(self, 标志: str, 标题: str, 正文: str) -> None:
        try:
            from 工具包.桌面通知 import 机器人桌面通知

            机器人桌面通知(self.数据库.获取机器人设置(标志), 标志, "自动重启", 标题, 正文, 级别="错误")
        except Exception:
            pass

    def _处理消息(self):
        """处理来自各个机器人的消息"""
        while True:
            try:
                消息 = self.全局消息队列.get_nowait()
            except queue.Empty:
                break
            if isinstance(消息, dict) and 消息.get("类型") == "死亡通知":
                self.处理死亡通知(消息["机器人标志"], 消息.get("原因", ""))
            else:
                print(f"[监控中心消息] {time.ctime()}: {消息}")
            self.全局消息队列.task_done()

    def _加入全局消息队列(self, 消息) -> None:
        """队列满时丢弃最旧通知，保证监控线程不被消息阻塞。"""
        try:
            self.全局消息队列.put_nowait(消息)
        except queue.Full:
            try:
                self.全局消息队列.get_nowait()
                self.全局消息队列.task_done()
            except queue.Empty:
                pass
            try:
                self.全局消息队列.put_nowait(消息)
            except queue.Full:
                pass

    def 处理死亡通知(self, 机器人标志: str, 死亡原因: str):
        """处理机器人发起的死亡通知

        注意：机器人线程会自己设置停止事件并退出；连接、超时和战斗
        中异常只安全停止，不把 Android 前台切走或自动重启游戏。
        """
        self._加入全局消息队列(f"机器人 {机器人标志} 报告死亡，原因：{死亡原因}")
        from 核心.异常 import 文本命中安全锁

        if 文本命中安全锁(死亡原因):
            self._加入全局消息队列(
                f"机器人 {机器人标志} 因连接、超时或战斗安全锁停止；已禁止自动重启以避免切换游戏页面。"
                "修复连接或确认页面后请从界面手动启动。"
            )
            return
        # 未分类异常也不能自动重建机器人。未知错误时页面、ADB 前台和
        # 游戏状态都没有得到确认；自动重启会把一次异常放大成重复点击、
        # 反复切前台，甚至触发 CoC 的退出/断线流程。保留原实例和现场，
        # 由用户确认模拟器画面后从 UI 手动继续。
        self._加入全局消息队列(
            f"机器人 {机器人标志} 因未分类任务异常安全停止；已禁止自动重启，"
            "请确认模拟器页面和 ADB 状态后从界面手动启动。"
        )


def 停止所有活跃机器人(监控系统, 超时秒: float = 10.0) -> list[str]:
    """停止并限时等待所有活跃机器人主线程退出，返回仍未退出的标志列表。"""
    监控系统.运行标志 = False
    超时未退出 = []
    for 标志, 机器人实例 in list(监控系统.机器人池.items()):
        主线程 = getattr(机器人实例, "主线程", None)
        if 主线程 is not None and 主线程.is_alive():
            try:
                机器人实例.停止("手动终止", 等待=False)
            except TypeError:
                机器人实例.停止("手动终止")
            if 主线程.is_alive():
                主线程.join(timeout=超时秒)
            if 主线程.is_alive():
                超时未退出.append(标志)
    return 超时未退出


# ==== 使用示例 ====
if __name__ == "__main__":
    # ==== 命令行解析 ====
    parser = argparse.ArgumentParser(description="不打开界面，直接按已保存的任务计划开始运行")

    parser.add_argument(
        "--机器人",
        action="append",
        nargs="+",  # 每个机器人是一组参数
        required=False,
        help="""机器人参数示例：
    --机器人 标志=robot_1 服务器=国际服 最小资源=200000 刷墙 英雄=弓箭女皇,亡灵王子
    标志必填，其它可选，刷墙/刷主世界/刷夜世界只要存在即开启"""
    )

    args = parser.parse_args()
    if not args.机器人:
        # 控制台只控制一个游戏：未指定时使用界面正在使用的那份配置。
        from 应用.控制器 import 选择主实例ID
        args.机器人 = [[f"标志={选择主实例ID(任务数据库())}"]]

    # ==== 初始化监控系统 ====
    # 注意：这里假设 机器人监控中心 已经定义
    机器人监控系统 = 机器人监控中心()


    # ==== 帮助函数：解析一组参数为字典 ====
    def 解析机器人参数(参数列表):
        参数字典 = {}
        for item in 参数列表:
            if "=" in item:
                key, value = item.split("=", 1)
                参数字典[key] = value
            else:
                # 布尔参数
                参数字典[item] = True
        return 参数字典


    # ==== 遍历每个机器人参数组并启动机器人 ====
    for 单机器人参数 in args.机器人:
        参数字典 = 解析机器人参数(单机器人参数)
        标志 = 参数字典.get("标志")
        if not 标志:
            print("每个机器人必须指定标志")
            continue

        # 获取数据库旧设置
        旧设置 = 机器人监控系统.数据库.获取机器人设置(标志)
        if not 旧设置:
            旧设置 = 机器人设置()

        # 判断是否只传入了标志参数
        # 参数字典中可能包含"标志"和其他参数，如果只有"标志"，则直接使用旧设置
        传入参数数量 = len([k for k in 参数字典.keys() if k != "标志"])

        if 传入参数数量 == 0:
            # 只传了标志，直接使用旧设置
            最终设置 = 旧设置
        else:
            # 处理英雄列表参数
            欲升级的英雄列表 = None
            if "英雄" in 参数字典:
                # 将逗号分隔的字符串转换为列表
                欲升级的英雄列表 = [英雄.strip() for 英雄 in 参数字典["英雄"].split(",") if 英雄.strip()]

            # 从旧设置复制后只覆盖命令行明确传入的字段。旧实现重新
            # 构造 dataclass，漏掉的开关会回到默认值（例如传“刷墙”
            # 会意外打开“建议建筑”任务），导致任务计划被悄悄改变。
            最终设置 = replace(旧设置)
            if "服务器" in 参数字典:
                最终设置.服务器 = 参数字典["服务器"]
                最终设置.__post_init__()
            if "最小资源" in 参数字典:
                最终设置.欲进攻的最小资源 = int(参数字典["最小资源"])
            if "刷墙" in 参数字典:
                最终设置.开启刷墙 = True
            if "边缘比例" in 参数字典:
                最终设置.欲进攻资源建筑靠近地图边缘最小比例 = float(参数字典["边缘比例"])
            if "刷墙金币" in 参数字典:
                最终设置.刷墙起始金币 = int(参数字典["刷墙金币"])
            if "刷墙圣水" in 参数字典:
                最终设置.刷墙起始圣水 = int(参数字典["刷墙圣水"])
            if "刷主世界" in 参数字典:
                最终设置.是否刷主世界 = True
            if "刷夜世界" in 参数字典:
                最终设置.是否刷夜世界 = True
            if 欲升级的英雄列表:
                最终设置.欲升级的英雄或建筑 = 欲升级的英雄列表

        # 创建并启动机器人
        机器人监控系统.创建并启动机器人(标志, 最终设置)
        print(f"已启动机器人: {标志}")

    # 等待所有机器人线程结束
    try:
        短暂延迟 = 10  # 秒数，用于确认没有重启

        空闲计数 = 0
        确认次数 = 短暂延迟  # 每秒检查一次

        while True:
            活跃线程 = [
                r.主线程
                for r in 机器人监控系统.机器人池.values()
                if hasattr(r, "主线程") and r.主线程.is_alive()
            ]
            if not 活跃线程:
                空闲计数 += 1
            else:
                空闲计数 = 0  # 有线程活动，重置计数

            if 空闲计数 >= 确认次数:
                print("所有机器人线程已结束，监控系统退出")
                break

            sleep(1)
    except KeyboardInterrupt:
        print("收到退出信号，停止所有机器人")
        超时未退出 = 停止所有活跃机器人(机器人监控系统, 超时秒=10.0)
        if 超时未退出:
            print(f"以下机器人主线程等待超时未退出：{', '.join(超时未退出)}")
        else:
            print("所有机器人已安全停止，退出程序")
