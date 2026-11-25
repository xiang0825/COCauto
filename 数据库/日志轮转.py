"""每次打开都是干净的日志（类似 MAA）。

- 启动时（以及干净退出时）把 ``任务日志`` 表整体导出成 ``上次日志.bak.jsonl``
  （只保留上一份，覆盖旧备份），然后清空 ``任务日志``。表本来就是空的
  （上次已在退出时清空）时什么都不做，上一份备份原样保留。
- 只动 ``任务日志``：``运行时状态``（资源/战斗学习快照）、``机器人设置``、
  ``系统配置`` 一律不碰。
- 首次清空后做一次 VACUUM 把 200MB 级的历史日志空间还给磁盘；完成后在
  ``系统配置`` 记一个标记，以后不再做。
- ``robot-error.log`` 启动时轮转为 ``robot-error.log.bak``（只留上一份）。

主人已批准这项自动清空（含历史日志），这是唯一被批准的自动删除。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

备份文件名 = "上次日志.bak.jsonl"
VACUUM标记键 = "日志清空后VACUUM完成"


def _连接(数据库路径) -> sqlite3.Connection:
    连接 = sqlite3.connect(str(数据库路径), timeout=30, check_same_thread=False)
    连接.execute("PRAGMA busy_timeout=30000")
    return 连接


def 导出并清空任务日志(数据库路径, 备份路径=None) -> int:
    """导出全部任务日志到备份文件后清空表；返回导出条数（0 表示没有动任何东西）。

    先写临时文件，确认完整写入后再原子替换旧备份，最后才删除表内容；
    任何一步失败都不删日志。
    """
    数据库路径 = Path(数据库路径)
    if not 数据库路径.is_file():
        return 0
    备份路径 = Path(备份路径) if 备份路径 else 数据库路径.with_name(备份文件名)
    连接 = _连接(数据库路径)
    try:
        try:
            最大ID = 连接.execute("SELECT MAX(记录ID) FROM 任务日志").fetchone()[0]
        except sqlite3.OperationalError:
            return 0  # 新库还没建表
        if 最大ID is None:
            return 0
        临时路径 = 备份路径.with_name(备份路径.name + ".tmp")
        条数 = 0
        with open(临时路径, "w", encoding="utf-8", newline="\n") as 文件:
            游标 = 连接.execute(
                "SELECT 记录ID, 机器人标志, 记录时间, 日志内容 FROM 任务日志 "
                "WHERE 记录ID <= ? ORDER BY 记录ID",
                (最大ID,),
            )
            while True:
                批 = 游标.fetchmany(5000)
                if not 批:
                    break
                for 记录ID, 标志, 时间, 内容 in 批:
                    文件.write(json.dumps({
                        "id": 记录ID,
                        "机器人": 标志,
                        "时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(时间 or 0))),
                        "ts": 时间,
                        "内容": 内容,
                    }, ensure_ascii=False))
                    文件.write("\n")
                    条数 += 1
            文件.flush()
            os.fsync(文件.fileno())
        os.replace(临时路径, 备份路径)
        # 只删已经导出的部分，导出期间新写入的行留到下次。
        连接.execute("DELETE FROM 任务日志 WHERE 记录ID <= ?", (最大ID,))
        连接.commit()
        return 条数
    finally:
        连接.close()


def 需要压缩(数据库路径) -> bool:
    try:
        连接 = _连接(数据库路径)
        try:
            行 = 连接.execute("SELECT 配置值 FROM 系统配置 WHERE 配置键 = ?", (VACUUM标记键,)).fetchone()
        finally:
            连接.close()
        return not (行 and 行[0] == "1")
    except sqlite3.Error:
        return False


def 压缩数据库一次(数据库路径) -> bool:
    """首次清空日志后 VACUUM 一次并记标记；已做过返回 False。"""
    if not 需要压缩(数据库路径):
        return False
    连接 = _连接(数据库路径)
    try:
        连接.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        连接.execute("VACUUM")
        连接.execute(
            "INSERT OR REPLACE INTO 系统配置 (配置键, 配置值, 更新时间) VALUES (?, '1', ?)",
            (VACUUM标记键, time.time()),
        )
        连接.commit()
        return True
    finally:
        连接.close()


def 轮转错误日志(目录) -> bool:
    """robot-error.log → robot-error.log.bak（覆盖旧 .bak，只留上一份）。"""
    源 = Path(目录) / "robot-error.log"
    if not 源.is_file() or 源.stat().st_size == 0:
        return False
    os.replace(源, 源.with_name("robot-error.log.bak"))
    return True


def 会话日志轮转(数据库路径, 压缩: bool = True, 轮转错误: bool = True, 记录=print) -> dict:
    """启动/退出时调用：导出并清空日志、轮转错误日志、必要时 VACUUM。绝不抛异常。"""
    结果 = {"导出条数": 0, "错误日志轮转": False, "已压缩": False}
    try:
        结果["导出条数"] = 导出并清空任务日志(数据库路径)
    except Exception as 异常:
        记录(f"导出/清空上次日志失败（日志保留不动）：{异常}")
    try:
        if 轮转错误:
            结果["错误日志轮转"] = 轮转错误日志(Path(数据库路径).parent)
    except Exception as 异常:
        记录(f"轮转 robot-error.log 失败：{异常}")
    if 压缩:
        try:
            结果["已压缩"] = 压缩数据库一次(数据库路径)
        except Exception as 异常:
            记录(f"数据库压缩失败（下次启动再试）：{异常}")
    return 结果
