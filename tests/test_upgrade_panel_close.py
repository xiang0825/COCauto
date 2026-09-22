import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.建筑升级.升级英雄 import 升级英雄任务
from 任务流程.兵种或法术升级.完成兵种或法术升级 import 完成兵种或法术升级任务
from 任务流程.战宠升级.完成宠物升级 import 完成宠物升级任务
from 任务流程.战宠升级.打开要升级的宠物 import 打开要升级的宠物任务


class 升级面板关闭安全测试(unittest.TestCase):
    def test_英雄面板关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭英雄升级页面()

        返回.assert_called_once_with(
            "关闭英雄升级页面", 已确认可关闭面板=True
        )

    def test_研究面板关闭两次都授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 完成兵种或法术升级任务.__new__(完成兵种或法术升级任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务._关闭升级面板()

        self.assertEqual(返回.call_count, 2)
        for 调用, 说明 in zip(
            返回.call_args_list, ("关闭升级详情", "关闭研究面板")
        ):
            self.assertEqual(
                调用,
                unittest.mock.call(说明, 已确认可关闭面板=True),
            )

    def test_战宠升级面板关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 完成宠物升级任务.__new__(完成宠物升级任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        self.assertTrue(任务._安全关闭面板("关闭战宠升级页面", "关闭战宠小屋"))
        self.assertEqual(返回.call_count, 2)
        self.assertTrue(all(
            调用.kwargs.get("已确认可关闭面板") is True
            for 调用 in 返回.call_args_list
        ))

    def test_战宠小屋关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 打开要升级的宠物任务.__new__(打开要升级的宠物任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭战宠小屋页面()

        返回.assert_called_once_with(
            "关闭战宠小屋页面", 已确认可关闭面板=True
        )


if __name__ == "__main__":
    unittest.main()
