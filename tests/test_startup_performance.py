import subprocess
import sys
import unittest
from pathlib import Path


class 启动性能测试(unittest.TestCase):
    def test_默认启动路径不加载重型图像依赖(self):
        """打开控制台只显示界面时，不应先加载 OpenCV、Numpy、ONNX 和 Pillow。"""
        项目根目录 = Path(__file__).resolve().parents[1]
        检查代码 = """
import sys
from 主入口 import 机器人监控中心
from 应用.控制器 import 应用控制器
from 界面.主窗口 import 主窗口
from 界面.页面_运行 import 运行页
from 界面.页面_设备连接 import 设备连接页
from 界面.悬浮日志 import 悬浮日志窗
重型模块 = ("cv2", "numpy", "onnxruntime", "PIL")
print([名称 for 名称 in 重型模块 if 名称 in sys.modules])
"""
        结果 = subprocess.run(
            [sys.executable, "-c", 检查代码],
            cwd=项目根目录,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        self.assertEqual(结果.stdout.strip(), "[]", 结果.stderr)


if __name__ == "__main__":
    unittest.main()
