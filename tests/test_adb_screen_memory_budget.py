import unittest
from unittest.mock import Mock

from 核心.ADB屏幕 import ADB屏幕


class ADB屏幕内存预算接口测试(unittest.TestCase):
    def test_内存预算检查转发到实际ADB设备(self):
        设备 = Mock()
        设备.检查主机内存预算.return_value = (True, "健康")
        屏幕 = ADB屏幕(设备)

        self.assertEqual(
            屏幕.检查主机内存预算(强制刷新=True),
            (True, "健康"),
        )
        设备.检查主机内存预算.assert_called_once_with(强制刷新=True)


if __name__ == "__main__":
    unittest.main()
