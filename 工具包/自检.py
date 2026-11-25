"""打包版自检：在 EXE 内部逐项跑通关键能力，结果写入报告文件。

用法：部落冲突.exe --自检 [报告路径]
只读检查：不点击游戏、不修改设置；检测模拟器时会执行 adb connect。
"""
from __future__ import annotations

import os
import sys
import time
import traceback


def 运行自检(报告路径: str) -> int:
    行: list[str] = []
    失败 = 0

    def 记(名称, 函数):
        nonlocal 失败
        开始 = time.time()
        try:
            结果 = 函数()
            行.append(f"[通过] {名称}（{time.time() - 开始:.1f}s）{('：' + str(结果)) if 结果 is not None else ''}")
            return 结果
        except Exception as 异常:
            失败 += 1
            行.append(f"[失败] {名称}：{type(异常).__name__}: {异常}")
            行.append("".join(traceback.format_exc()).rstrip())
            return None

    行.append(f"自检开始 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    行.append(f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable} cwd={os.getcwd()}")

    def 版本():
        from 工具包.版本管理 import 获取本地版本号
        return 获取本地版本号()

    记("版本号", 版本)

    def 数据库():
        from 数据库.任务数据库 import 任务数据库
        库 = 任务数据库()
        return f"{库.文件路径}；配置 {list(库.查询所有机器人设置())}"

    记("数据库", 数据库)

    def 图像库():
        import cv2
        import numpy as np
        return f"cv2 {cv2.__version__}, numpy {np.__version__}"

    记("OpenCV/Numpy", 图像库)

    def OCR():
        import numpy as np
        from 模块.检测.OCR识别器 import 安全OCR引擎
        引擎 = 安全OCR引擎()
        图 = np.full((60, 200, 3), 255, np.uint8)
        import cv2
        cv2.putText(图, "1/7", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
        结果, _ = 引擎(图)
        return [项[1] for 项 in 结果 or []]

    记("OCR 模型", OCR)

    def YOLO():
        from 模块.检测.YOLO检测器 import 线程安全YOLO检测器
        线程安全YOLO检测器()
        return "已加载"

    记("YOLO 模型", YOLO)

    def 模板():
        from 模块.检测.模板匹配器 import 模板匹配引擎
        from 模块.检测.页面识别器 import 页面识别器
        页面识别器(模板匹配引擎())
        return "已加载"

    记("模板/页面识别", 模板)

    def 任务模块():
        import importlib
        名单 = [
            "任务流程.启动模拟器", "任务流程.检测游戏登录状态", "任务流程.升级城墙",
            "任务流程.主世界打鱼.进攻", "任务流程.主世界打鱼.等待战斗结束并回营",
            "任务流程.建筑升级", "任务流程.战宠升级", "任务流程.兵种或法术升级",
            "任务流程.夜世界.夜世界打鱼.下兵", "模块.模拟器探测",
            "服务.官方API",
        ]
        for 名 in 名单:
            importlib.import_module(名)
        return f"{len(名单)} 个模块"

    记("任务模块导入", 任务模块)

    def 官方API连通():
        """确认打包版带有 HTTPS 支持并能连到官方 API；有配置时顺便验证 Token。"""
        import ssl  # noqa: F401  缺少 ssl 时这里直接失败
        from 数据库.任务数据库 import 任务数据库
        from 服务 import 官方API
        已配置 = [
            (标志, 设置) for 标志, 设置 in 任务数据库().查询所有机器人设置().items()
            if 设置.官方API令牌 and 设置.玩家标签
        ]
        if not 已配置:
            try:
                官方API.获取玩家("selftest-invalid-token", "#2PP", 重试次数=0)
            except 官方API.官方API错误 as 异常:
                if 异常.状态码 == 403:
                    return "HTTPS 正常，可连到官方 API（尚无机器人填写 Token）"
                raise
            return "HTTPS 正常"
        结果 = []
        for 标志, 设置 in 已配置:
            try:
                摘要 = 官方API.同步账号(设置.官方API令牌, 设置.玩家标签)
                结果.append(f"{标志}：{摘要.名字}（{摘要.标签}）大本营{摘要.大本营}")
            except 官方API.官方API错误 as 异常:
                结果.append(f"{标志}：{异常}")
        return "；".join(结果)

    记("官方 API", 官方API连通)

    检测结果 = 记("模拟器一键检测", lambda: _检测())
    if 检测结果 and 检测结果[0]:
        adb路径, 序列号 = 检测结果

        def 截图与识别():
            from 模块.ADB设备操作类 import ADB设备操作类
            from 核心.ADB屏幕 import ADB屏幕
            from 模块.检测.模板匹配器 import 模板匹配引擎
            from 模块.检测.页面识别器 import 页面识别器
            设备 = ADB设备操作类(adb路径, 序列号, 自动检测路径=False)
            设备.设置目标包名("com.supercell.clashofclans")
            图 = ADB屏幕(设备).获取屏幕图像cv(0, 0, 800, 600, 强制刷新=True)
            结果 = 页面识别器(模板匹配引擎()).识别(图, 战斗中=False)
            return f"截图 {图.shape[1]}×{图.shape[0]}，页面={结果.页面}，可信度={结果.可信度:.2f}"

        记("ADB 截图与页面识别", 截图与识别)

    行.append(f"自检结束：{'全部通过' if not 失败 else f'{失败} 项失败'}")
    with open(报告路径, "w", encoding="utf-8") as 文件:
        文件.write("\n".join(行) + "\n")
    return 0 if not 失败 else 1


def _检测():
    from 模块.模拟器探测 import 检测
    结果 = 检测()
    if 结果.推荐 is None:
        return (None, "；".join(结果.日志[-2:]))
    return (结果.adb路径, 结果.推荐.序列号)
