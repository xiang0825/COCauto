# Host Memory Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resume a task safely after the host-memory screenshot guard has recovered, instead of ending the task permanently.

**Architecture:** Preserve the existing ADB memory thresholds. Expose a read-only budget check, mark only the explicit host-budget exception as resumable, and poll it from safe standby before taking another screenshot. Resume task planning only after three healthy samples and the existing two-frame home confirmation.

**Tech Stack:** Python 3.12, ADB adapter, existing task context and `unittest` suite.

**Spec:** `docs/superpowers/specs/2026-11-16-memory-recovery-design.md`

## Global Constraints

- Never lower the current physical-memory or commit thresholds.
- Never screenshot or send game input while the host-budget guard remains active.
- Explicit user stop and non-host memory errors remain fail-closed.
- Preserve all pre-existing uncommitted and untracked work; build only an isolated candidate.

## Review Focus

- Low memory must reset the healthy-sample count and prevent screenshots.
- A user stop during the wait must not be cleared by recovery logic.
- A generic `MemoryError` must not enter the automatic host-budget resume path.
- Resume must still require two consecutive recognized main-world frames.

---

### Task 1: Expose a fresh read-only host-memory budget check

**Files:**
- Modify: `模块/ADB设备操作类.py`
- Test: `tests/test_adb_device.py`

**Interface:** `检查主机内存预算(强制刷新: bool = True) -> tuple[bool, str]` returns whether the existing thresholds pass and a diagnostic string; it performs no ADB command.

- [ ] Add a test for a low budget and one for a healthy budget.
- [ ] Run those tests and confirm the new interface is missing.
- [ ] Implement the wrapper using `_检查主机内存预算` without changing thresholds.
- [ ] Rerun the focused tests.

### Task 2: Add a recoverable host-budget state and safe standby polling

**Files:**
- Modify: `任务流程/基础任务框架.py`, `线程/自动化机器人.py`
- Test: `tests/test_manual_recovery_wait.py`

**Interfaces:** The task context exposes `是否可自动恢复主机内存保护()`, `检查主机内存预算恢复()`, and `清除主机内存保护()`; `_等待人工恢复主世界` uses them before requesting a screenshot.

- [ ] Add tests proving low samples cause no screenshots, three healthy samples permit later two-frame home confirmation, explicit stop interrupts, and non-host allocation errors do not auto-resume.
- [ ] Run the new tests to confirm the missing behavior.
- [ ] Implement the resumable marker only for `主机内存保护已触发`; poll every ten seconds and reset the count on any low sample.
- [ ] Rerun the focused tests and existing recovery tests.

### Task 3: Verify the whole project and build a candidate

**Files:**
- Modify: version metadata and release notes only after Tasks 1-2 pass.
- Candidate output: isolated `.build_work_rc80`, `.build_stage_rc80`, and `dist_rc80`.

- [ ] Run the complete unittest suite, compile check, packaged-module verifier, and `git diff --check`.
- [ ] Build the candidate without replacing the root EXE or touching the running UI.
- [ ] Verify EXE version, `_internal` completeness, and launch behavior. Keep real battle/CoC interaction unclaimed until the CoC screen is explicitly confirmed.
