"""将手机 LAN API 接到现有桌面机器人状态机。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from 数据库.任务数据库 import (
    任务计划定义映射,
    任务计划是否启用,
    规范化任务计划顺序,
)
from 服务.局域网控制服务 import (
    DpapiTokenStore,
    MobileControlServer,
    PairingAuthority,
    SerializedCommandBroker,
    TlsIdentity,
    list_private_local_addresses,
)


def 计算设置指纹(设置) -> str:
    """对完整已保存机器人设置生成稳定摘要，不返回其中的私有字段。"""
    serialized = json.dumps(
        asdict(设置),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def 获取已启用任务(设置) -> list[str]:
    顺序 = 规范化任务计划顺序(getattr(设置, "任务计划顺序", None))
    return [
        task_id
        for task_id in 顺序
        if task_id in 任务计划定义映射 and 任务计划是否启用(设置, task_id)
    ]


class DesktopMobileBridge:
    """线程安全状态快照；网络线程只读缓存，控制只由 Tk 线程派发。"""

    def __init__(
        self,
        *,
        database,
        monitor_center,
        state_directory: str | Path,
        version_provider: Callable[[], str],
    ):
        self.database = database
        self.monitor_center = monitor_center
        self.state_directory = Path(state_directory)
        self.version_provider = version_provider
        self._lock = threading.RLock()
        self._snapshots: dict[str, dict] = {}
        self._signatures: dict[str, tuple] = {}
        self._authority: PairingAuthority | None = None
        self._server: MobileControlServer | None = None
        self._broker: SerializedCommandBroker | None = None
        self._bound_robot_id: str | None = None
        self._secrets: dict[str, tuple[str, ...]] = {}

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(self._server and self._server.is_running)

    @property
    def bound_robot_id(self) -> str | None:
        with self._lock:
            return self._bound_robot_id

    def refresh_snapshot(self, robot_id: str) -> dict:
        robot_id = str(robot_id or "").strip()
        robot = self.monitor_center.机器人池.get(robot_id)
        if not robot:
            raise KeyError(robot_id)

        settings = self.database.获取机器人设置(robot_id)
        fingerprint = 计算设置指纹(settings)
        selected_tasks = 获取已启用任务(settings)
        state = str(getattr(robot, "当前状态", "未知"))[:64]
        stop_reason = str(getattr(robot, "停止原因", "") or "")[:160]
        device = getattr(robot, "设备", None)
        serial = str(getattr(settings, "ADB设备序列号", "") or "").strip()
        confirmed = bool(getattr(settings, "ADB已确认模拟器", False)) and bool(serial)
        if not confirmed:
            adb_state = "未配置"
            adb_connected = False
        elif device is None:
            adb_state = "未运行时未检测"
            adb_connected = False
        elif int(getattr(device, "_连续传输失败次数", 0) or 0) >= 2:
            adb_state = "连接失败"
            adb_connected = False
        else:
            adb_state = "最近已连接"
            adb_connected = True

        if device is None:
            game_state = "未检测"
            game_installed = None
        elif bool(getattr(device, "_目标已验证", False)):
            game_state = "CoC 前台已确认"
            game_installed = True
        else:
            game_state = "尚未确认 CoC 前台"
            game_installed = None

        try:
            latest_log = self.database.读取最后日志(robot_id)
            last_step = str(latest_log.日志内容 if latest_log else "")[:160]
        except Exception:
            last_step = ""
        try:
            version = str(self.version_provider() or "本地版")[:64]
        except Exception:
            version = "本地版"

        signature = (
            fingerprint,
            state,
            stop_reason,
            adb_state,
            game_state,
            tuple(selected_tasks),
        )
        with self._lock:
            previous_signature = self._signatures.get(robot_id)
            previous_snapshot = self._snapshots.get(robot_id)
            revision = int(previous_snapshot["revision"]) if previous_snapshot else 0
            if previous_signature != signature:
                revision += 1
                self._signatures[robot_id] = signature
            snapshot = {
                "api_version": MobileControlServer.API_VERSION,
                "robot_id": robot_id,
                "plan_fingerprint": fingerprint,
                "revision": revision,
                "state": state,
                "stop_reason": stop_reason,
                "selected_tasks": selected_tasks,
                "version": version,
                "adb_connected": adb_connected,
                "adb_state": adb_state,
                "game_installed": game_installed,
                "game_state": game_state,
                "last_step": last_step,
            }
            self._snapshots[robot_id] = snapshot
            webhook = str(getattr(settings, "企业微信webhook", "") or "").strip()
            self._secrets[robot_id] = (webhook,) if webhook else ()
            return self._copy_snapshot(snapshot)

    def get_snapshot(self, robot_id: str) -> dict:
        with self._lock:
            snapshot = self._snapshots.get(str(robot_id))
            if snapshot is None:
                raise RuntimeError("桌面状态尚未准备好")
            return self._copy_snapshot(snapshot)

    @staticmethod
    def _copy_snapshot(snapshot: dict) -> dict:
        return {**snapshot, "selected_tasks": list(snapshot["selected_tasks"])}

    def get_recent_logs(self, robot_id: str, after: float, limit: int) -> list[dict]:
        rows = self.database.查询日志历史(
            robot_id,
            起始时间=after,
            最大条数=min(100, max(1, int(limit))),
        )
        with self._lock:
            secrets_to_hide = self._secrets.get(str(robot_id), ())
        results = []
        for row in reversed(rows):
            message = str(getattr(row, "日志内容", "") or "")
            for secret in secrets_to_hide:
                if secret:
                    message = message.replace(secret, "[已隐藏]")
            message = re.sub(
                r"(?i)(Bearer\s+)\S+",
                r"\1[已隐藏]",
                message,
            )
            results.append(
                {
                    "time": float(getattr(row, "记录时间", 0) or 0),
                    "level": "error" if "[错误]" in message else "warning" if "[警告]" in message else "info",
                    "message": message[:500],
                }
            )
        return results

    def start(self, bind_address: str, robot_id: str, *, port: int | None = None) -> dict:
        robot_id = str(robot_id or "").strip()
        if not robot_id:
            raise ValueError("请先选择要绑定的桌面机器人")
        with self._lock:
            if self._server is not None:
                if self._bound_robot_id == robot_id and self._server.is_running:
                    return self._server_info(self._server)
                raise RuntimeError("请先停止当前手机控制服务，再切换机器人")

        snapshot = self.refresh_snapshot(robot_id)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        authority = self._get_authority()
        identity = TlsIdentity.load_or_create(
            self.state_directory / "tls-identity.dat", bind_address
        )
        broker = SerializedCommandBroker(
            revision_provider=lambda: self.refresh_snapshot(robot_id)["revision"],
            execute=lambda command: self.execute_control(robot_id, command),
        )
        server = MobileControlServer(
            bind_address=bind_address,
            local_addresses=list_private_local_addresses(),
            port=MobileControlServer.DEFAULT_PORT if port is None else port,
            tls_identity=identity,
            pairing_authority=authority,
            command_broker=broker,
            snapshot_provider=self.get_snapshot,
            logs_provider=self.get_recent_logs,
        )
        try:
            server.start()
        except Exception:
            broker.close()
            raise
        with self._lock:
            self._server = server
            self._broker = broker
            self._bound_robot_id = robot_id
        return self._server_info(server)

    def _server_info(self, server: MobileControlServer) -> dict:
        return {
            "endpoint": server.endpoint,
            "fingerprint": server.tls_identity.fingerprint,
            "robot_id": self._bound_robot_id,
            "port": server.port,
        }

    def begin_pairing(self) -> dict:
        with self._lock:
            server = self._server
            robot_id = self._bound_robot_id
        if server is None or robot_id is None:
            raise RuntimeError("请先启动手机控制服务")
        snapshot = self.refresh_snapshot(robot_id)
        return server.begin_pairing(robot_id, snapshot["plan_fingerprint"])

    def revoke_all(self) -> int:
        return self._get_authority().revoke_all()

    def process_pending(self) -> int:
        with self._lock:
            server = self._server
        return server.process_pending() if server is not None else 0

    def refresh_bound_snapshot(self) -> dict | None:
        with self._lock:
            robot_id = self._bound_robot_id
        return self.refresh_snapshot(robot_id) if robot_id else None

    def execute_control(self, robot_id: str, command: str) -> dict:
        robot_id = str(robot_id or "").strip()
        command = str(command or "").strip().lower()
        if command not in SerializedCommandBroker.ALLOWED_COMMANDS:
            raise ValueError("仅允许开始、暂停或停止")
        robot = self.monitor_center.机器人池.get(robot_id)
        if robot is None:
            raise KeyError(robot_id)
        snapshot = self.refresh_snapshot(robot_id)
        if command == "start" and snapshot["adb_state"] == "连接失败":
            raise RuntimeError("ADB 设备最近连接失败；请先恢复并确认模拟器连接")

        state = str(getattr(robot, "当前状态", "未知"))
        if command == "start":
            if state == "暂停中":
                robot.继续()
            elif state == "已停止":
                self.monitor_center.启动机器人(robot_id)
            elif state != "运行中":
                raise RuntimeError("机器人当前状态不允许启动")
        elif command == "pause":
            if state == "运行中":
                robot.暂停()
            elif state != "暂停中":
                raise RuntimeError("只有运行中的机器人可以暂停")
        elif command == "stop" and state != "已停止":
            robot.停止("手机控制停止", 等待=False)

        snapshot = self.refresh_snapshot(robot_id)
        return {"state": snapshot["state"], "revision": snapshot["revision"]}

    def stop(self) -> None:
        with self._lock:
            server = self._server
            self._server = None
            self._broker = None
            self._bound_robot_id = None
        if server is not None:
            server.close()

    def _get_authority(self) -> PairingAuthority:
        with self._lock:
            if self._authority is None:
                store = DpapiTokenStore(
                    self.state_directory / "paired-clients.dat"
                )
                self._authority = PairingAuthority(token_store=store)
            return self._authority
