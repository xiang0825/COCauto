"""部落冲突桌面控制台入口。"""
import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox


_单实例句柄 = None
_启动窗口就绪事件 = threading.Event()
_控制台退出事件 = threading.Event()


def _启动或唤醒已有窗口():
    """避免重复启动造成“进程在后台、窗口却找不到”的假象。

    只在 Windows 打包版启用命名互斥体。若已有实例，优先将它恢复并
    置顶；即使暂时找不到窗口，也必须结束本次重复启动，避免两个实例
    同时打开数据库、设备连接和 Tk 窗口。
    """
    global _单实例句柄
    if sys.platform != "win32":
        return True

    # 必须通过 use_last_error=True 读取 CreateMutexW 的线程错误码；
    # 直接调用 ctypes.windll 后，GetLastError 可能残留其它 API 的 183，
    # 把首次启动误判成已有实例，留下“进程存在但没有窗口”的假象。
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _单实例句柄 = kernel32.CreateMutexW(None, False, "Local\\COCAUTO_DESKTOP_CONSOLE")
    if not _单实例句柄:
        return True

    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
        return True

    # Tk 窗口在部分 Windows 环境中无法仅按标题查找，限定 TkTopLevel
    # 可以稳定找到真正的主窗口，避免双击后既不唤醒也不给提示。
    窗口句柄 = user32.FindWindowW("TkTopLevel", "部落冲突")
    if 窗口句柄:
        user32.ShowWindow(窗口句柄, 9)  # SW_RESTORE
        user32.BringWindowToTop(窗口句柄)
        user32.SetForegroundWindow(窗口句柄)
        return False

    # 命名互斥体由 Windows 在进程退出时自动释放，不会因为崩溃留下
    # 永久“孤立锁”。因此这里不能在短等待后继续创建第二个控制台，
    # 否则两个机器人会同时操作同一个模拟器。等待窗口初始化完成；
    # 仍找不到时也退出本次启动，交给原进程的窗口守护释放互斥体。
    for _ in range(300):
        time.sleep(0.1)
        窗口句柄 = user32.FindWindowW("TkTopLevel", "部落冲突")
        if 窗口句柄:
            user32.ShowWindow(窗口句柄, 9)
            user32.BringWindowToTop(窗口句柄)
            user32.SetForegroundWindow(窗口句柄)
            return False
    return False


class 增强型机器人控制界面:
    """简洁的三栏控制台：控制、任务、日志同时可见。"""

    def __init__(self, master, 监控中心):
        self.master = master
        self.监控中心 = 监控中心
        self.日志队列 = 监控中心.日志队列
        self.数据库 = 任务数据库()

        set_theme("light")
        配置现代化样式()

        master.title("部落冲突")
        master.protocol("WM_DELETE_WINDOW", self._窗口关闭处理)
        self._设置窗口尺寸(1360, 820)
        self._创建菜单栏()
        self._创建面板()
        self._加载保存的配置()
        self._定时刷新顶部状态()

    def _创建面板(self):
        主框架 = ttk.Frame(self.master, padding=(12, 10, 12, 12))
        主框架.pack(fill=tk.BOTH, expand=True)

        self._创建页眉(主框架)

        内容区 = ttk.PanedWindow(主框架, orient=tk.HORIZONTAL)
        内容区.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        # 左栏：选择机器人并控制启动/暂停/停止。
        左栏 = ttk.Frame(内容区, width=285)
        左栏.pack_propagate(False)
        self.机器人管理 = 机器人管理面板(
            父容器=左栏,
            监控中心=self.监控中心,
            选择变化回调=self._处理机器人选择变化,
        )
        self.机器人管理.pack(fill=tk.BOTH, expand=True)
        内容区.add(左栏, weight=1)

        # 中栏：任务计划置于首位，连接与自动启动收进同一工作区。
        中栏 = ttk.LabelFrame(内容区, text="任务与连接", padding=8)
        内容区.add(中栏, weight=3)
        选项卡 = ttk.Notebook(中栏)
        选项卡.pack(fill=tk.BOTH, expand=True)
        选项卡.bind("<<NotebookTabChanged>>", self._选项卡切换回调)
        self.选项卡 = 选项卡

        self.任务计划面板 = 任务计划面板(
            父容器=选项卡,
            数据库=self.数据库,
            获取机器人回调=lambda: self.机器人管理.当前机器人ID,
            操作日志回调=lambda 内容: self.日志面板.记录操作日志(内容),
        )
        选项卡.add(self.任务计划面板, text="任务计划")

        self.设备连接面板 = 设备连接面板(
            父容器=选项卡,
            数据库=self.数据库,
            获取机器人回调=lambda: self.机器人管理.当前机器人ID,
        )
        选项卡.add(self.设备连接面板, text="模拟器连接")

        自动启动 = 自动启动界面(选项卡, self.监控中心)
        选项卡.add(自动启动, text="自动启动")

        # 右栏：日志常驻显示，拖动分隔条即可扩大，不再挤在窗口底部。
        日志框 = ttk.LabelFrame(内容区, text="运行日志 · 实时", padding=6, width=560)
        内容区.add(日志框, weight=2)
        self.日志面板 = 日志面板(
            父容器=日志框,
            日志队列=self.日志队列,
            获取当前机器人回调=lambda: self.机器人管理.获取当前机器人(),
            获取所有机器人回调=lambda: self.监控中心.机器人池,
        )
        self.日志面板.pack(fill=tk.BOTH, expand=True)

    def _创建页眉(self, 父容器):
        页眉 = ttk.Frame(父容器, style="Header.TFrame", padding=(12, 10))
        页眉.pack(fill=tk.X)

        标识 = 创建CoC标识(页眉, 58)
        标识.pack(side=tk.LEFT, padx=(0, 12))

        标题区 = ttk.Frame(页眉, style="Header.TFrame")
        标题区.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(标题区, text="部落冲突", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            标题区,
            text=f"CoC 模拟器控制台  ·  版本 {获取本地版本号()}",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(3, 0))

        状态区 = ttk.Frame(页眉, style="Header.TFrame")
        状态区.pack(side=tk.RIGHT, padx=(12, 0))
        self.顶部状态标签 = ttk.Label(
            状态区, text="● 未运行", style="Status.TLabel", anchor=tk.E
        )
        self.顶部状态标签.pack(anchor=tk.E)
        self.顶部连接标签 = ttk.Label(
            状态区, text="未选择机器人", style="Subtitle.TLabel", anchor=tk.E
        )
        self.顶部连接标签.pack(anchor=tk.E, pady=(3, 0))

    def _定时刷新顶部状态(self):
        """只读取内存状态，保持窗口缩放和日志滚动顺畅。"""
        try:
            机器人 = self.机器人管理.获取当前机器人()
            if 机器人 is None:
                状态 = "● 未运行"
                机器人文本 = "未选择机器人"
            else:
                当前状态 = str(getattr(机器人, "当前状态", "未运行"))
                状态 = f"● {当前状态}"
                机器人文本 = f"当前机器人：{机器人.机器人标志}"
            self.顶部状态标签.configure(text=状态)
            self.顶部连接标签.configure(text=机器人文本)
        except tk.TclError:
            return
        except Exception:
            pass
        self.master.after(1000, self._定时刷新顶部状态)

    def _处理机器人选择变化(self, 机器人ID, 删除=None):
        if 删除:
            try:
                self.数据库.删除机器人设置(删除)
                self.日志面板.记录操作日志(f"{删除}：配置已删除")
            except Exception as e:
                messagebox.showerror("删除失败", f"删除数据库配置时发生异常：{e}")
            self.设备连接面板.载入机器人(None)
            self.任务计划面板.载入机器人(None)
        else:
            self.设备连接面板.载入机器人(机器人ID)
            self.任务计划面板.载入机器人(机器人ID)
            self.日志面板.通知机器人切换()
            self.机器人管理.更新状态显示()

    def _选项卡切换回调(self, event):
        当前标签 = event.widget.tab(event.widget.select(), "text")
        if 当前标签 == "任务计划":
            self.任务计划面板.刷新()

    def _设置窗口尺寸(self, 宽度, 高度):
        屏幕宽度 = self.master.winfo_screenwidth()
        屏幕高度 = self.master.winfo_screenheight()
        宽度 = min(宽度, max(1040, 屏幕宽度 - 100))
        高度 = min(高度, max(660, 屏幕高度 - 120))
        x = max(0, (屏幕宽度 - 宽度) // 2)
        y = max(0, (屏幕高度 - 高度) // 2)
        self.master.geometry(f"{宽度}x{高度}+{x}+{y}")
        self.master.minsize(1040, 660)

    def _加载保存的配置(self):
        所有配置 = self.数据库.查询所有机器人设置()
        if not 所有配置:
            默认标识 = "robot_1"
            默认设置 = 机器人设置()
            self.数据库.保存机器人设置(默认标识, 默认设置)
            所有配置 = {默认标识: 默认设置}
        for 机器人标志, 设置 in 所有配置.items():
            try:
                self.监控中心.创建机器人(机器人标志=机器人标志, 初始设置=设置)
            except Exception as e:
                messagebox.showerror("配置加载错误", f"加载{机器人标志}失败：{e}")
        if 所有配置:
            self.机器人管理.选中机器人(next(iter(所有配置)))

    def _创建菜单栏(self):
        菜单栏 = tk.Menu(self.master)
        self.master.config(menu=菜单栏)
        帮助菜单 = tk.Menu(菜单栏, tearoff=0)
        菜单栏.add_cascade(label="帮助", menu=帮助菜单)
        帮助菜单.add_command(label="关于部落冲突", command=self._显示关于)

    def _显示关于(self):
        messagebox.showinfo(
            "关于部落冲突",
            f"部落冲突\nCoC 模拟器控制台\n\n版本：{获取本地版本号()}",
        )

    def _窗口关闭处理(self):
        if getattr(self, "_正在关闭", False):
            return
        self._正在关闭 = True
        try:
            self.监控中心.关闭()
        except Exception:
            self.监控中心.运行标志 = False
        self.master.quit()
        self.master.destroy()


if __name__ == "__main__":
    if not _启动或唤醒已有窗口():
        sys.exit(0)
    # 实时日志只保留有限的待显示消息，避免窗口卡顿时无限占用内存。
    日志队列 = queue.Queue(maxsize=2000)
    监控中心 = None
    root = None

    def _无窗口启动超时保护():
        """不允许无窗口进程永久占住单实例互斥体。

        过去的顺序会先打开数据库/监控线程，之后才创建 Tk。任意前置
        初始化卡住时，进程会继续存活、窗口句柄却始终为空，之后双击 EXE
        都会被单实例逻辑拦截。窗口创建完成后立即取消该保护；否则在
        30 秒后退出，让用户可以正常重新启动。
        """
        if _启动窗口就绪事件.wait(timeout=30):
            return
        try:
            if 监控中心 is not None:
                监控中心.关闭()
        except Exception:
            pass
        os._exit(1)

    def _运行期窗口守护():
        """主窗口异常消失时释放单实例锁，避免 EXE 永久“打不开”。"""
        if not _启动窗口就绪事件.wait(timeout=31):
            return
        user32 = ctypes.windll.user32
        连续无窗口秒数 = 0
        while not _控制台退出事件.wait(timeout=1):
            窗口句柄 = user32.FindWindowW("TkTopLevel", "部落冲突")
            当前进程窗口 = False
            if 窗口句柄:
                窗口进程ID = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(
                    窗口句柄,
                    ctypes.byref(窗口进程ID),
                )
                当前进程窗口 = 窗口进程ID.value == os.getpid()
            if 当前进程窗口:
                连续无窗口秒数 = 0
                continue
            连续无窗口秒数 += 1
            # 用户正常关闭时 finally 会先设置退出事件；只有异常情况留下
            # 无窗口进程超过 8 秒，才强制结束本桌面控制台。不会操作游戏、
            # 模拟器或 ADB，目的仅为释放命名互斥体让 EXE 能再次启动。
            if 连续无窗口秒数 >= 8:
                try:
                    if 监控中心 is not None:
                        监控中心.关闭()
                except Exception:
                    pass
                os._exit(1)

    启动保护线程 = threading.Thread(
        target=_无窗口启动超时保护,
        name="控制台启动保护",
        daemon=True,
    )
    启动保护线程.start()
    窗口守护线程 = threading.Thread(
        target=_运行期窗口守护,
        name="控制台窗口守护",
        daemon=True,
    )
    窗口守护线程.start()
    try:
        # 必须先创建一个可见的窗口。即使后续数据库或后台服务初始化被
        # 外部程序拖慢，用户也不会遇到“进程存在但 EXE 打不开”的假象。
        root = tk.Tk()
        # 保持与单实例唤醒逻辑相同的标题；启动期间再次双击时可以准确
        # 找到并恢复这个早期窗口，而不会误判为“没有窗口”。
        root.title("部落冲突")
        root.minsize(760, 460)
        root.geometry("960x620")
        root.update_idletasks()
        root.deiconify()
        _启动窗口就绪事件.set()

        # 先显示可操作的主窗口，再加载监控中心、OCR/模型和各面板。
        # 这些模块在低内存或 DLL 初始化异常时可能耗时很久；若在创建
        # Tk 之前导入，用户只能看到“进程存在但没有窗口”，启动守护也
        # 无法及时接管。延后导入后，窗口至少可以显示启动状态/错误。
        from 主入口 import 机器人监控中心
        from 工具包.版本管理 import 获取本地版本号
        from 数据库.任务数据库 import 机器人设置, 任务数据库
        from sv_ttk import set_theme

        from 界面.自动启动界面 import 自动启动界面
        from 界面.CoC标识 import 创建CoC标识
        from 界面.样式配置 import 配置现代化样式
        from 界面.日志面板 import 日志面板
        from 界面.机器人管理面板 import 机器人管理面板
        from 界面.设备连接面板 import 设备连接面板
        from 界面.任务计划面板 import 任务计划面板

        获取本地版本号()
        监控中心 = 机器人监控中心(日志队列)
        界面 = 增强型机器人控制界面(root, 监控中心)
        root.mainloop()
    except Exception as 异常:
        错误文本 = f"{type(异常).__name__}: {异常}"
        try:
            if root is not None:
                messagebox.showerror("部落冲突启动失败", 错误文本, parent=root)
            elif sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(None, 错误文本, "部落冲突启动失败", 0x10)
        finally:
            raise
    finally:
        _控制台退出事件.set()
        _启动窗口就绪事件.set()
        # 无论窗口是正常关闭还是初始化异常，都回收后台监控线程，
        # 避免只剩无窗口进程继续占用单实例互斥体。
        if 监控中心 is not None:
            监控中心.关闭()
