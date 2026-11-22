import io
import json
import unittest
from unittest.mock import patch

from 工具包.更新检查器 import (
    有可用更新,
    获取最新发布,
    解析最新发布,
)


class 更新检查器测试(unittest.TestCase):
    def test_远端发布低于本机rc版本时不提示更新(self):
        发布 = 解析最新发布([{
            "tag_name": "v2026.11.18-rc110",
            "name": "rc110",
            "body": "older build",
            "html_url": "https://github.com/xiang0825/COCauto/releases/tag/v2026.11.18-rc110",
            "published_at": "2026-11-18T03:35:35Z",
            "draft": False,
            "prerelease": True,
        }])

        self.assertIsNotNone(发布)
        self.assertFalse(有可用更新("rc114 · cbccceba", 发布))

    def test_高于本机的预发布版本会提示更新(self):
        发布 = 解析最新发布([{
            "tag_name": "v2026.11.19-rc115",
            "name": "rc115",
            "body": "new build",
            "html_url": "https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc115",
            "published_at": "2026-11-19T03:35:35Z",
            "draft": False,
            "prerelease": True,
        }])

        self.assertTrue(有可用更新("rc114 · cbccceba", 发布))

    def test_选择最高已发布版本并忽略草稿(self):
        发布列表 = [
            {"tag_name": "v2026.11.19-rc999", "name": "draft", "draft": True},
            {"tag_name": "v2026.11.18-rc114", "name": "older", "draft": False},
            {
                "tag_name": "v2026.11.19-rc115",
                "name": "newest",
                "body": "release notes",
                "html_url": "https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc115",
                "published_at": "2026-11-19T03:35:35Z",
                "draft": False,
                "prerelease": True,
            },
        ]

        发布 = 解析最新发布(发布列表)

        self.assertIsNotNone(发布)
        self.assertEqual(发布.标签, "v2026.11.19-rc115")
        self.assertEqual(发布.说明, "release notes")

    def test_无有效版本号时不误报更新(self):
        发布 = 解析最新发布([{"tag_name": "latest", "draft": False}])

        self.assertIsNone(发布)
        self.assertFalse(有可用更新("rc114", 发布))

    def test_请求使用短超时并将网络错误转为空结果(self):
        with patch("工具包.更新检查器.urllib.request.urlopen", side_effect=TimeoutError):
            self.assertIsNone(获取最新发布(timeout=3))

    def test_请求会解析GitHub发布列表(self):
        内容 = json.dumps([{
            "tag_name": "v2026.11.19-rc115",
            "name": "rc115",
            "body": "new build",
            "html_url": "https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc115",
            "published_at": "2026-11-19T03:35:35Z",
            "draft": False,
            "prerelease": True,
        }]).encode("utf-8")

        with patch(
            "工具包.更新检查器.urllib.request.urlopen",
            return_value=io.BytesIO(内容),
        ) as 打开:
            发布 = 获取最新发布(timeout=4)

        self.assertIsNotNone(发布)
        self.assertEqual(发布.版本, "rc115")
        self.assertEqual(打开.call_args.kwargs["timeout"], 4)


if __name__ == "__main__":
    unittest.main()
