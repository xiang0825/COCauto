"""从代码默认值生成/核对 资源/识别/*.json。

    python scripts/生成识别参数.py          # 写出 JSON（覆盖）
    python scripts/生成识别参数.py --检查   # 只比对，不一致时退出码 1

JSON 里的值必须与代码默认值一致；改识别参数时改 JSON，并同步代码默认值
（tests/test_recognition_config.py 会核对两者）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

根 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(根))

from 工具包.识别参数 import 资源子目录, 转为JSON值  # noqa: E402

说明 = {
    "主页": "主页/战斗/结算页识别（世界识别器、页面识别器）的模板路径、区域 [x1,y1,x2,y2]（800×600 参考画布）和相似度阈值。",
    "搜敌": "搜敌：评分门槛、资源上限、YOLO 置信度、“下一个”按钮模板与安全区域。",
    "结算": "战斗结算/回营：回营与领取奖励模板、放弃/确定按钮模板、主城确认模板和阈值、结算动画补拍。",
    "弹窗": "弹窗 OCR 关键词：英雄升级详情、主世界活动面板、官方评分弹窗（只点“稍后”）。",
}


def 映射():
    from 任务流程.基础任务框架 import 任务上下文
    from 任务流程.世界跳转.世界识别器 import 世界识别器
    from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
    from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器
    from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务
    from 模块.检测.页面识别器 import 页面识别器

    return {
        "主页": [(世界识别器, None), (页面识别器, None)],
        "搜敌": [(搜索目标敌人任务, None), (搜索页面识别器, None)],
        "结算": [(等待战斗结束并回营任务, None)],
        "弹窗": [(任务上下文, (
            "英雄详情英雄名称", "英雄详情升级词", "英雄详情升级结构词",
            "活动弹窗标题词", "活动弹窗内容词",
            "评分弹窗必需词", "评分弹窗稍后词", "评分弹窗按钮最低y",
        ))],
    }


_可写类型 = (bool, int, float, str, tuple, dict)
# 参考画布尺寸不是可调参数，改了会让所有坐标错位，不导出。
_不导出 = {"逻辑宽度", "逻辑高度"}


def 默认参数(类, 键列表=None) -> dict:
    默认 = getattr(类, "_识别参数默认值", {}) or {}
    结果 = {}
    名单 = 键列表 or [
        键 for 键, 值 in vars(类).items()
        if not 键.startswith("_") and isinstance(值, _可写类型) and 键 not in _不导出
    ]
    for 键 in 名单:
        值 = 默认.get(键, getattr(类, 键)) if 默认.get("_类") is 类 else getattr(类, 键)
        结果[键] = 转为JSON值(值)
    return 结果


def 生成() -> dict[str, dict]:
    文件 = {}
    for 名称, 列表 in 映射().items():
        内容 = {"说明": 说明[名称]}
        for 类, 键列表 in 列表:
            内容[类.__name__] = 默认参数(类, 键列表)
        文件[名称] = 内容
    return 文件


def main() -> int:
    检查 = "--检查" in sys.argv
    目录 = 根 / 资源子目录
    目录.mkdir(parents=True, exist_ok=True)
    不一致 = []
    for 名称, 内容 in 生成().items():
        路径 = 目录 / f"{名称}.json"
        文本 = json.dumps(内容, ensure_ascii=False, indent=2) + "\n"
        if 检查:
            if not 路径.is_file() or json.loads(路径.read_text(encoding="utf-8")) != 内容:
                不一致.append(str(路径))
        else:
            路径.write_text(文本, encoding="utf-8")
            print(f"写出 {路径}")
    if 不一致:
        print("与代码默认值不一致：" + "、".join(不一致))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
