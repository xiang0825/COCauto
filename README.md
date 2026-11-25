# COCauto · 城控

[![Latest Release](https://img.shields.io/github/v/release/xiang0825/COCauto?label=Latest%20Release)](https://github.com/xiang0825/COCauto/releases/latest)

面向 Windows 模拟器的《部落冲突》桌面自动化工具。本项目与 Supercell 无关；自动化操作可能违反游戏规则，使用者需自行承担账号风险。

## 下载与启动

从 [GitHub Releases](https://github.com/xiang0825/COCauto/releases) 获取 Windows 发布包，完整解压到可写目录，并运行包内的 **部落冲突.exe**。请保留同级的 **_internal** 目录；普通使用者只通过 exe 启动，不需要 Python、命令行启动器或手机控制端。

手机控制与 Windows 计划任务自动启动已从主线移除，见提交 `8f5276a`。模拟器需要由主人自行安装和启动；程序可按任务设置通过 ADB 启动游戏。

## 使用

- [简明使用说明](docs/使用说明.md)：exe 启动、F1/F2、任务选项、桌面通知与旧版回滚。
- [rc142–rc149 更新日志](docs/更新日志.md)：按提交和实测记录整理，并标明缺少逐版发布映射的范围。
- [免责声明](docs/法律声明/免责声明.md) · [风险分析](docs/法律声明/风险分析.md)。

F1 开始或继续，F2 暂停；暂停机器人不会暂停游戏内倒计时。部落竞赛奖励由主人手动领取。

## 开发者

源码面向 Windows 与 Python 3.11，界面使用 PySide6。下列命令仅用于开发环境；日常使用仍通过发布包中的 exe。

```powershell
python UI入口.py
python -m unittest discover -s tests -q
```

发布包应包含 exe 与 `_internal`。请勿把本地数据库、日志、虚拟环境或构建缓存提交到仓库。
