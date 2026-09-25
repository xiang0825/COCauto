import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from 模块.自动启动管理器 import 自动启动管理器


class 自动启动管理器测试(unittest.TestCase):
    def test_带空格项目路径生成可执行的带引号脚本(self):
        with tempfile.TemporaryDirectory(prefix="COC Auto ") as 临时目录:
            根目录 = Path(临时目录) / "Project With Space"
            根目录.mkdir()
            管理器 = 自动启动管理器(str(根目录))

            路径 = 管理器._生成bat文件("robot_1", 使用虚拟环境=True)
            内容 = 路径.read_text(encoding="utf-8")

            self.assertIn(f'cd /d "{根目录}"', 内容)
            self.assertIn(
                f'call "{根目录 / ".venv\\Scripts\\activate.bat"}"',
                内容,
            )
            self.assertIn(
                f'python "{根目录 / "主入口.py"}" --机器人 "标志=robot_1"',
                内容,
            )

    def test_计划任务TR整体引用bat路径(self):
        with tempfile.TemporaryDirectory(prefix="COC Task ") as 临时目录:
            根目录 = Path(临时目录) / "Project With Space"
            根目录.mkdir()
            管理器 = 自动启动管理器(str(根目录))
            bat路径 = 根目录 / "自动启动脚本" / "启动_robot_1.bat"
            bat路径.parent.mkdir(parents=True, exist_ok=True)

            with patch("模块.自动启动管理器.subprocess.run") as 运行:
                运行.return_value.returncode = 0
                管理器._创建计划任务("COC_Robot_robot_1", bat路径, "09:00")

            命令 = 运行.call_args.args[0]
            self.assertEqual(command := 命令[命令.index("/TR") + 1], f'"{bat路径}"')
            self.assertEqual(command, f'"{bat路径}"')


if __name__ == "__main__":
    unittest.main()
