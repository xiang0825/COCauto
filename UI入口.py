"""城控桌面控制台入口（PySide6）。"""
from __future__ import annotations

import os
import queue
import sys
import traceback


def 读取版本号() -> str:
    try:
        from 工具包.版本管理 import 获取本地版本号
        return str(获取本地版本号() or "").strip() or "本地版"
    except Exception:
        return "本地版"


def 生成控制台副标题() -> str:
    return f"部落冲突控制台 · 版本：{读取版本号()}"


def _配置高DPI():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    if sys.platform == "win32":
        try:
            import ctypes
            # 告诉 Windows 本程序自行处理缩放，避免 125%/150% 下界面发虚。
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("COCauto.Desktop")
        except Exception:
            pass


def _整理上次日志(启动提示, 应用) -> None:
    """每次打开都是空日志：上一次会话导出到 数据库/上次日志.bak.jsonl 后清空。

    必须在单实例检查之后、监控中心创建之前执行，第二个实例不会清空正在
    运行的实例的日志。首次运行要导出全部历史日志并 VACUUM，会多等十几秒。
    """
    try:
        from 数据库.任务数据库 import 任务数据库
        from 数据库.日志轮转 import 会话日志轮转, 需要压缩

        路径 = 任务数据库.默认数据库路径()
        if 需要压缩(路径):
            启动提示.更新进度(12, "首次整理历史日志，约需 20 秒…")
            应用.processEvents()
        会话日志轮转(路径)
    except Exception:
        traceback.print_exc()


def main() -> int:
    if "--自检" in sys.argv:
        from 工具包.自检 import 运行自检
        from 工具包.运行路径 import 解析数据子路径
        位置 = sys.argv.index("--自检")
        报告 = (
            sys.argv[位置 + 1]
            if len(sys.argv) > 位置 + 1
            else str(解析数据子路径("自检报告.txt"))
        )
        return 运行自检(报告)
    _配置高DPI()
    import time

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    应用 = QApplication(sys.argv)
    应用.setApplicationName("城控")
    应用.setOrganizationName("COCauto")
    应用.setQuitOnLastWindowClosed(True)

    from 界面.单实例 import 单实例服务, 抢占单实例
    if not 抢占单实例():
        return 0

    from 界面.组件 import 应用图标
    应用.setWindowIcon(应用图标())

    # 先显示启动画面，再载入数据库、监控中心和主界面；进度条显示的是真实启动阶段。
    from 界面.启动动画 import 高级启动画面

    开始时间 = time.monotonic()
    启动提示 = 高级启动画面("城控", "部落冲突控制台", 读取版本号())
    启动提示.show()
    启动提示.启动动画()
    启动提示.更新进度(5, "正在初始化…")
    应用.processEvents()

    def 阶段(百分比: int, 文案: str):
        启动提示.更新进度(百分比, 文案)
        应用.processEvents()

    阶段(10, "整理上次日志…")
    _整理上次日志(启动提示, 应用)

    监控中心 = None
    try:
        from 主入口 import 机器人监控中心
        from 应用.控制器 import 应用控制器
        from 界面.主窗口 import 主窗口

        阶段(35, "启动监控中心…")
        日志队列: queue.Queue = queue.Queue(maxsize=2000)
        监控中心 = 机器人监控中心(日志队列)
        阶段(55, "连接任务数据库…")
        控制器 = 应用控制器(监控中心)
        阶段(75, "构建主界面…")
        窗口 = 主窗口(控制器, 日志队列, 读取版本号())
        单实例 = 单实例服务(窗口.唤醒)
        阶段(90, "载入任务设置…")
        窗口.载入()
        阶段(100, "准备就绪")
        # 至少展示 0.8 秒让动画走完，最多不额外等待超过 1.3 秒。
        已过 = (time.monotonic() - 开始时间) * 1000
        余下 = int(max(0, min(高级启动画面.推荐最小展示毫秒 - 已过, 高级启动画面.推荐最大展示毫秒)))
        QTimer.singleShot(余下, lambda: 启动提示.淡出并显示主窗(窗口))
        退出码 = 应用.exec()
        单实例.关闭()
        return 退出码
    except Exception as 异常:
        启动提示.close()
        traceback.print_exc()
        QMessageBox.critical(None, "城控启动失败", f"{type(异常).__name__}: {异常}")
        return 1
    finally:
        # 无论正常关闭还是初始化异常，都回收后台监控线程。
        if 监控中心 is not None:
            try:
                监控中心.关闭()
            except Exception:
                pass
            # 干净退出：本次会话日志导出为 上次日志.bak.jsonl 并清空。
            try:
                from 数据库.任务数据库 import 任务数据库
                from 数据库.日志轮转 import 会话日志轮转
                会话日志轮转(任务数据库.默认数据库路径(), 压缩=False, 轮转错误=False)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
