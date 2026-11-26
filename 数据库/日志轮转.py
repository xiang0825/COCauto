"""每次打开都是干净的日志（类似 MAA）。

- 启动时（以及干净退出时）把 ``任务日志`` 表整体导出成 ``上次日志.bak.jsonl``
  （只保留上一份，覆盖旧备份），然后清空 ``任务日志``。表本来就是空的
  （上次已在退出时清空）时什么都不做，上一份备份原样保留。
- 只动 ``任务日志``：``运行时状态``（资源/战斗学习快照）、``机器人设置``、
  ``系统配置`` 一律不碰。
- 首次清空后做一次 VACUUM 把 200MB 级的历史日志空间还给磁盘；完成后在
  ``系统配置`` 记一个标记，以后不再做。
- ``robot-error.log`` 启动时轮转为 ``robot-error.log.bak``（只留上一份）。
- 脚本停止后（停止按钮、任务计划结束、异常停止）界面在后台调用
  ``停止后导出并清空``：同样先导出备份再清空 ``任务日志``，不做 VACUUM、
  不轮转错误日志。异常留证/问题包要读最近日志时用 ``读取最近日志``，
  表里不够时自动从备份补齐。

主人已批准这项自动清空（含历史日志，仅限 任务日志 表与界面日志），这是唯一被批准的自动删除。
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
        try:
            条数 = _写出临时备份(连接, 临时路径, 最大ID)
            os.replace(临时路径, 备份路径)
        except BaseException:
            # 导出失败：只清理本次写了一半的临时文件，旧备份和表内容都不动。
            try:
                临时路径.unlink()
            except OSError:
                pass
            raise
        # 战报/每日通知要从日志解析今天和昨天的战斗、收益、搜敌、竞赛积分：
        # 先把这些行归档进 运行时状态（同一事务），归档失败就不清空。
        from 数据库.日志统计归档 import 归档待清空日志

        try:
            归档待清空日志(连接, 最大ID)
        except BaseException:
            连接.rollback()
            raise
        # 只删已经导出的部分，导出期间新写入的行留到下次。
        连接.execute("DELETE FROM 任务日志 WHERE 记录ID <= ?", (最大ID,))
        连接.commit()
        return 条数
    finally:
        连接.close()


def _写出临时备份(连接, 临时路径: Path, 最大ID) -> int:
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
    return 条数


def 停止后导出并清空(数据库路径, 记录=print) -> int | None:
    """脚本停止后调用：导出备份（覆盖上一份）、归档统计行，再清空任务日志；绝不抛异常。

    返回清空的条数（0 表示表本来就空）；任何一步失败返回 ``None``，此时数据库
    日志原样保留，调用方也不能清空界面日志。
    """
    try:
        return 导出并清空任务日志(数据库路径)
    except Exception as 异常:
        记录(f"停止后导出/清空日志失败（日志保留不动）：{异常}")
        return None


def 读取备份日志(备份路径, 机器人标志: str | None = None, 最大条数: int = 100) -> list[dict]:
    """读 ``上次日志.bak.jsonl`` 末尾最多 ``最大条数`` 条（按时间正序）；文件不存在返回空列表。"""
    路径 = Path(备份路径)
    if not 路径.is_file() or 最大条数 <= 0:
        return []
    from collections import deque

    结果: deque = deque(maxlen=int(最大条数))
    with open(路径, encoding="utf-8", errors="replace") as 文件:
        for 行 in 文件:
            try:
                项 = json.loads(行)
            except ValueError:
                continue
            if not isinstance(项, dict):
                continue
            if 机器人标志 is not None and 项.get("机器人") != 机器人标志:
                continue
            结果.append(项)
    return list(结果)


def 读取最近日志(数据库路径, 机器人标志: str, 最大条数: int = 100, 备份路径=None) -> list[tuple[float, str]]:
    """最近日志 [(时间戳, 内容)]，按时间正序。

    停止后表已清空时，异常留证/问题包仍要看得到停止前的日志：表里不足
    ``最大条数`` 时用备份文件里同一机器人的最后几条补在前面。只读，不改任何东西。
    """
    数据库路径 = Path(数据库路径)
    备份路径 = Path(备份路径) if 备份路径 else 数据库路径.with_name(备份文件名)
    表内: list[tuple[float, str]] = []
    if 数据库路径.is_file():
        try:
            连接 = _连接(数据库路径)
            try:
                行列表 = 连接.execute(
                    "SELECT 记录时间, 日志内容 FROM 任务日志 WHERE 机器人标志 = ? "
                    "ORDER BY 记录ID DESC LIMIT ?",
                    (str(机器人标志), int(最大条数)),
                ).fetchall()
            finally:
                连接.close()
            表内 = [(float(时间 or 0), str(内容)) for 时间, 内容 in reversed(行列表)]
        except sqlite3.Error:
            表内 = []
    缺少 = int(最大条数) - len(表内)
    if 缺少 <= 0:
        return 表内
    try:
        备份 = 读取备份日志(备份路径, str(机器人标志), 缺少)
    except OSError:
        备份 = []
    最早 = 表内[0][0] if 表内 else float("inf")
    补齐 = [(float(项.get("ts") or 0), str(项.get("内容", ""))) for 项 in 备份]
    return [项 for 项 in 补齐 if 项[0] <= 最早] + 表内


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
