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
            启动提示.setText("城控正在启动…（首次整理历史日志，约需 20 秒）")
            应用.processEvents()
        会话日志轮转(路径)
    except Exception:
        traceback.print_exc()


def main() -> int:
    if "--自检" in sys.argv:
        from 工具包.自检 import 运行自检
        位置 = sys.argv.index("--自检")
        报告 = sys.argv[位置 + 1] if len(sys.argv) > 位置 + 1 else "自检报告.txt"
        return 运行自检(报告)
    _配置高DPI()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

    应用 = QApplication(sys.argv)
    应用.setApplicationName("城控")
    应用.setOrganizationName("COCauto")
    应用.setQuitOnLastWindowClosed(True)

    from 界面.单实例 import 单实例服务, 抢占单实例
    if not 抢占单实例():
        return 0

    from 界面.组件 import 应用图标
    应用.setWindowIcon(应用图标())

    # 先显示一个可见的启动提示，再载入数据库、监控中心和各页面；
    # 即使后续初始化很慢，用户也能看到程序已经在启动。
    启动提示 = QLabel("城控正在启动…")
    启动提示.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint)
    启动提示.setAlignment(Qt.AlignCenter)
    启动提示.setStyleSheet(
        "QLabel { background:#ffffff; color:#1f2733; border:1px solid #e3e7ec;"
        " border-radius:12px; padding:28px 48px; font-size:15px;"
        " font-family:'Microsoft YaHei UI'; }"
    )
    启动提示.show()
    应用.processEvents()

    _整理上次日志(启动提示, 应用)

    监控中心 = None
    try:
        from 主入口 import 机器人监控中心
        from 应用.控制器 import 应用控制器
        from 界面.主窗口 import 主窗口

        日志队列: queue.Queue = queue.Queue(maxsize=2000)
        监控中心 = 机器人监控中心(日志队列)
        控制器 = 应用控制器(监控中心)
        窗口 = 主窗口(控制器, 日志队列, 读取版本号())
        单实例 = 单实例服务(窗口.唤醒)
        窗口.show()
        启动提示.close()
        窗口.载入()
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
