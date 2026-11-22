"""从公开 GitHub Releases 检查 CoC 桌面版更新；网络失败不影响主程序。"""
from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.parse
import urllib.request


_发布列表地址 = "https://api.github.com/repos/xiang0825/COCauto/releases?per_page=20"
_发布页前缀 = "https://github.com/xiang0825/COCauto/releases/tag/"
_RC版本模式 = re.compile(r"(?:^|[^a-z0-9])rc[-_ ]?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class 版本发布:
    版本: str
    标签: str
    名称: str
    说明: str
    页面地址: str
    发布时间: str


def _版本序号(版本文本):
    匹配 = _RC版本模式.search(str(版本文本 or ""))
    return int(匹配.group(1)) if 匹配 else None


def 解析最新发布(发布列表):
    """忽略草稿和未知标签，在公开发布中选择编号最高的 rc 版本。"""
    if not isinstance(发布列表, list):
        return None

    候选 = []
    for 发布 in 发布列表:
        if not isinstance(发布, dict) or 发布.get("draft") is True:
            continue
        标签 = str(发布.get("tag_name") or "").strip()
        序号 = _版本序号(标签)
        if not 标签 or 序号 is None:
            continue

        页面地址 = str(发布.get("html_url") or "").strip()
        if not 页面地址.startswith(_发布页前缀):
            页面地址 = _发布页前缀 + urllib.parse.quote(标签, safe=".-")

        候选.append((序号, str(发布.get("published_at") or ""), 版本发布(
            版本=f"rc{序号}",
            标签=标签,
            名称=str(发布.get("name") or 标签),
            说明=str(发布.get("body") or ""),
            页面地址=页面地址,
            发布时间=str(发布.get("published_at") or ""),
        )))

    if not 候选:
        return None
    return max(候选, key=lambda 项: (项[0], 项[1]))[2]


def 有可用更新(本地版本, 最新发布):
    """只有远端 rc 编号明确更高时才提示，避免未知版本造成误报。"""
    if not isinstance(最新发布, 版本发布):
        return False
    本地序号 = _版本序号(本地版本)
    远端序号 = _版本序号(最新发布.标签)
    return 本地序号 is not None and 远端序号 is not None and 远端序号 > 本地序号


def 获取最新发布(timeout=4):
    """获取 GitHub 已发布版本；草稿、断网、超时或无效 JSON 返回 None。"""
    请求 = urllib.request.Request(
        _发布列表地址,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "COCauto-desktop-update-check",
        },
    )
    try:
        with urllib.request.urlopen(请求, timeout=max(1, float(timeout))) as 响应:
            内容 = 响应.read()
        发布列表 = json.loads(内容.decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return 解析最新发布(发布列表)
