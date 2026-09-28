import subprocess
import sys
import unittest
from pathlib import Path


class 启动性能测试(unittest.TestCase):
    def test_默认启动路径不加载重型图像依赖(self):
        """首页只显示控制台时，不应先加载图像模型和 Pillow。"""
        项目根目录 = Path(__file__).resolve().parents[1]
        检查代码 = """
import sys
from 主入口 import 机器人监控中心
from 界面.自动启动界面 import 自动启动界面
from 界面.CoC标识 import 创建CoC标识
from 界面.设备连接面板 import 设备连接面板
from 界面.概览面板 import 概览面板
from 界面.日志面板 import 日志面板
from 界面.机器人管理面板 import 机器人管理面板
from 界面.任务计划面板 import 任务计划面板
重型模块 = ("cv2", "numpy", "onnxruntime", "PIL")
print(any(名称 in sys.modules for 名称 in 重型模块))
"""
        结果 = subprocess.run(
            [sys.executable, "-c", 检查代码],
            cwd=项目根目录,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        self.assertEqual(结果.stdout.strip(), "False", 结果.stderr)


if __name__ == "__main__":
    unittest.main()
