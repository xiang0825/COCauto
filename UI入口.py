import queue
import tkinter as tk
from tkinter import ttk, messagebox
from 主入口 import 机器人监控中心
from 工具包.版本管理 import 获取本地版本号
from 数据库.任务数据库 import 机器人设置, 任务数据库
from sv_ttk import set_theme

from 界面.自动启动界面 import 自动启动界面
from 界面.样式配置 import 配置现代化样式
from 界面.日志面板 import 日志面板
from 界面.机器人管理面板 import 机器人管理面板
from 界面.设备连接面板 import 设备连接面板
from 界面.任务计划面板 import 任务计划面板


class 增强型机器人控制界面:
    def __init__(self, master, 监控中心):
        """初始化主控界面"""
        self.master = master
        self.监控中心 = 监控中心
        self.日志队列 = 监控中心.日志队列
        self.数据库 = 任务数据库()

        # 配置样式
        set_theme("light")
        配置现代化样式()

        # 设置窗口
        master.title("CoC 模拟器控制台 " + 获取本地版本号())
        master.protocol("WM_DELETE_WINDOW", self._窗口关闭处理)
        self._设置窗口尺寸(1220, 760)

        # 创建菜单
        self._创建菜单栏()

        # 创建子面板
        self._创建面板()

        # 加载保存的配置
        self._加载保存的配置()

    def _创建面板(self):
        """实例化并组装各子面板"""
        主框架 = ttk.Frame(self.master)
        主框架.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 使用垂直分割容器：日志和主内容各自拥有可伸缩空间，窗口不必全屏。
        分割区 = ttk.PanedWindow(主框架, orient=tk.VERTICAL)
        分割区.pack(fill=tk.BOTH, expand=True)

        内容区 = ttk.Frame(分割区)
        分割区.add(内容区, weight=3)

        # 左侧：机器人管理面板
        self.机器人管理 = 机器人管理面板(
            父容器=内容区,
            监控中心=self.监控中心,
            选择变化回调=self._处理机器人选择变化
        )
        self.机器人管理.pack(side=tk.LEFT, fill=tk.BOTH, padx=5, pady=5)

        # 右侧：Notebook
        右侧选项卡 = ttk.Notebook(内容区)
        右侧选项卡.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        右侧选项卡.bind("<<NotebookTabChanged>>", self._选项卡切换回调)

        # 运行日志固定在主界面底部，始终汇总全部机器人，不作为需要点击的选项卡。
        日志框 = ttk.LabelFrame(主框架, text="运行日志")
        分割区.add(日志框, weight=1)
        self.日志面板 = 日志面板(
            父容器=日志框,
            日志队列=self.日志队列,
            获取当前机器人回调=lambda: self.机器人管理.获取当前机器人(),
            获取所有机器人回调=lambda: self.监控中心.机器人池,
        )
        self.日志面板.pack(fill=tk.BOTH, expand=True)

        self.设备连接面板 = 设备连接面板(
            父容器=右侧选项卡,
            数据库=self.数据库,
            获取机器人回调=lambda: self.机器人管理.当前机器人ID,
        )
        右侧选项卡.add(self.设备连接面板, text="模拟器连接")

        self.任务计划面板 = 任务计划面板(
            父容器=右侧选项卡,
            数据库=self.数据库,
            获取机器人回调=lambda: self.机器人管理.当前机器人ID,
            操作日志回调=lambda 内容: self.日志面板.记录操作日志(内容),
        )
        右侧选项卡.add(self.任务计划面板, text="任务计划")

        # 自动启动
        自动启动 = 自动启动界面(右侧选项卡, self.监控中心)
        右侧选项卡.add(自动启动, text="自动启动")

        # 右侧内容区的宽度随窗口变化，左侧机器人列表保持可用最小宽度。
        内容区.columnconfigure(1, weight=1)

    # 中介者：协调面板间通信
    def _处理机器人选择变化(self, 机器人ID, 删除=None):
        """
        机器人选择变化时的回调
        :param 机器人ID: 新选中的机器人ID（或None）
        :param 删除: 如果提供，表示删除了指定ID的机器人
        """
        if 删除:
            # 删除数据库配置
            try:
                self.数据库.删除机器人设置(删除)
                self.日志面板.记录操作日志(f"{删除}：配置已删除")
            except Exception as e:
                messagebox.showerror("删除失败", f"删除数据库配置时发生异常：{e}")
            # 清空配置面板
            self.设备连接面板.载入机器人(None)
            self.任务计划面板.载入机器人(None)
        else:
            # 正常选择变化
            self.设备连接面板.载入机器人(机器人ID)
            self.任务计划面板.载入机器人(机器人ID)
            self.日志面板.通知机器人切换()
            self.机器人管理.更新状态显示()

    def _选项卡切换回调(self, event):
        """切换到任务计划时刷新当前机器人的任务配置"""
        notebook = event.widget
        当前索引 = notebook.index(notebook.select())
        当前标签 = notebook.tab(当前索引, "text")

        if 当前标签 == "任务计划":
            self.任务计划面板.刷新()

    # 保留的工具方法
    def _设置窗口尺寸(self, 宽度, 高度):
        """按屏幕可用空间设置初始尺寸，并允许后续自由缩放。"""
        屏幕宽度 = self.master.winfo_screenwidth()
        屏幕高度 = self.master.winfo_screenheight()
        宽度 = min(宽度, max(900, 屏幕宽度 - 80))
        高度 = min(高度, max(620, 屏幕高度 - 100))
        x = (屏幕宽度 - 宽度) // 2
        y = (屏幕高度 - 高度) // 2
        self.master.geometry(f"{宽度}x{高度}+{x}+{y}")
        self.master.minsize(900, 620)

    def _加载保存的配置(self):
        """启动时加载所有机器人配置"""
        所有配置 = self.数据库.查询所有机器人设置()
        if not 所有配置:
            # 首次运行只创建一个可直接配置的默认机器人，不要求用户先批量创建。
            默认标识 = "robot_1"
            默认设置 = 机器人设置()
            self.数据库.保存机器人设置(默认标识, 默认设置)
            所有配置 = {默认标识: 默认设置}
        for 机器人标志, 设置 in 所有配置.items():
            try:
                self.监控中心.创建机器人(
                    机器人标志=机器人标志,
                    初始设置=设置
                )
            except Exception as e:
                messagebox.showerror("配置加载错误", f"加载{机器人标志}失败: {str(e)}")
        if 所有配置:
            self.机器人管理.选中机器人(next(iter(所有配置)))

    # 菜单栏
    def _创建菜单栏(self):
        """创建菜单栏，命令委托给子模块"""
        菜单栏 = tk.Menu(self.master)
        self.master.config(menu=菜单栏)

        帮助菜单 = tk.Menu(菜单栏, tearoff=0)
        菜单栏.add_cascade(label="帮助", menu=帮助菜单)
        帮助菜单.add_command(label="关于", command=self._显示关于)

    def _显示关于(self):
        """显示关于对话框"""
        messagebox.showinfo(
            "关于",
            f"版本: {获取本地版本号()}\n\n"
            "这是一个技术学习演示项目，仅供研究和学习使用。\n\n"
            "⚠️ 警告：请勿用于真实游戏环境。\n"
            "使用本软件操作真实账号可能导致账号被封禁，\n"
            "并可能违反相关法律法规。"
        )

    def _窗口关闭处理(self):
        """关闭窗口时停止所有机器人"""
        for 机器人 in self.监控中心.机器人池.values():
            try:
                机器人.停止(等待=False)
            except:
                pass
        self.master.destroy()


if __name__ == "__main__":
    获取本地版本号()
    日志队列 = queue.Queue()
    监控中心 = 机器人监控中心(日志队列)
    root = tk.Tk()
    界面 = 增强型机器人控制界面(root, 监控中心)

    root.mainloop()
