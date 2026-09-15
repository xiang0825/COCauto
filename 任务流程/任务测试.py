"""只读 ADB 烟雾测试；导入本模块不会启动游戏、触控或执行任务。"""
from __future__ import annotations

from 数据库.任务数据库 import 任务数据库
from 模块.ADB设备操作类 import ADB设备操作类


def 测试ADB连接(机器人标志: str = "robot_") -> tuple[int, int]:
    设置 = 任务数据库().获取机器人设置(机器人标志)
    if not 设置.ADB已确认模拟器 or not 设置.ADB设备序列号:
        raise RuntimeError("请先在界面中保存 ADB 设备序列号，并确认目标是模拟器。")
    设备 = ADB设备操作类(设置.ADB路径, 设置.ADB设备序列号)
    设备.确认在线()
    图像 = 设备.获取屏幕图像cv()
    尺寸 = (图像.shape[1], 图像.shape[0])
    print(f"ADB 只读截图成功：{设置.ADB设备序列号}，分辨率 {尺寸[0]}×{尺寸[1]}")
    return 尺寸


if __name__ == "__main__":
    测试ADB连接()
