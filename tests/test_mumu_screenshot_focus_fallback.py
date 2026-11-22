import unittest
from unittest.mock import patch

from 模块.ADB设备操作类 import ADB设备操作类


游戏包名 = "com.supercell.clashofclans"
输入状态 = """
FocusedApplications:
  displayId=2, name='ActivityRecord{game u0 com.supercell.clashofclans/com.supercell.titan.GameApp t104}'
  displayId=0, name='ActivityRecord{launcher u0 app.lawnchair/.LawnchairLauncher t2}'
FocusedWindows:
  displayId=0, name='e73b728 app.lawnchair/app.lawnchair.LawnchairLauncher'
"""
显示状态 = b"""
mViewports=[DisplayViewport{type=INTERNAL, valid=true, displayId=0, uniqueId='local:4619827820427265280'}, DisplayViewport{type=INTERNAL, valid=true, displayId=2, uniqueId='local:4619827767814508545'}]
"""


class MuMu截图显示回退测试(unittest.TestCase):
    def test_只从FocusedApplications恢复截图显示且不授权游戏输入(self):
        解析截图显示 = getattr(ADB设备操作类, "_解析MuMu截图逻辑显示ID", None)
        self.assertTrue(callable(解析截图显示), "应提供截图专用的显示解析器")
        self.assertEqual(解析截图显示(输入状态, 游戏包名), "2")

        # 输入授权仍只认 FocusedWindows，启动器持有焦点时必须拒绝 CoC 输入。
        self.assertIsNone(ADB设备操作类._解析MuMu逻辑显示ID(输入状态, 游戏包名))
        self.assertEqual(
            ADB设备操作类._解析MuMu焦点包名(输入状态, 游戏包名),
            "app.lawnchair",
        )

    def test_截图流程可使用游戏的FocusedApplications显示层(self):
        设备 = ADB设备操作类(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
            "127.0.0.1:16416",
        )
        设备.设置目标包名(游戏包名)
        with patch.object(设备, "_MuMu显示服务仍缺失", return_value=False), \
                patch.object(设备, "_获取MuMu输入显示ID", return_value=None), \
                patch.object(设备, "_获取MuMu窗口状态", return_value=输入状态), \
                patch.object(设备, "执行", return_value=显示状态):
            self.assertEqual(设备._获取MuMu截图显示ID(), "4619827767814508545")


if __name__ == "__main__":
    unittest.main()
