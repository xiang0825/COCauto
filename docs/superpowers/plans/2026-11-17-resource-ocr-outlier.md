# Resource OCR Outlier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the configured full-resource standby trigger despite impossible historical OCR peaks.

**Architecture:** Filter historical peak values through the existing known-capacity recognizer before applying the historical lower-bound check. Keep the persistent database unchanged.

**Tech Stack:** Python, unittest, PyInstaller, Windows release script.

**Spec:** `docs/superpowers/specs/2026-11-17-resource-ocr-outlier-design.md`

## Global Constraints

- Keep only one production EXE in `E:\codex.task\coc` and retain its `_internal` runtime folder.
- Do not modify the live SQLite database.
- Do not change game controls while CoC is in battle.

## Review Focus

- Impossible high OCR values must not block a real full-store reading.
- A valid higher historical capacity must still prevent a false full result.
- Missing or failed resource recognition must remain conservative.

### Task 1: Filter implausible history in full-resource detection

**Files:**
- Modify: `tests/test_resource_full.py`
- Modify: `工具包/工具函数.py`

**Interfaces:** Use the existing `是否家乡资源打满(资源字典, 历史峰值=None) -> bool` interface.

- [ ] Add a regression test with current Gold/Elixir at 31,000,000 and an Elixir historical peak of 411,067,075; expect `True`.
- [ ] Run `python -m unittest tests.test_resource_full.资源打满判断测试.test_历史OCR离群峰值不阻止真实满仓判断` and verify it fails for the historical-peak guard.
- [ ] Change the guard so a historical value only constrains the current value when that history value matches a known storage-capacity range.
- [ ] Run the focused test and `python -m unittest tests.test_resource_full`.

### Task 2: Verify and deploy the repaired build

**Files:**
- Verify: full test suite, package verifier, release directory.

- [ ] Run the full unittest suite and `git diff --check`.
- [ ] Build the next release version and verify packaged modules.
- [ ] Replace the production build while the robot is safely paused; retain exactly one root EXE.
- [ ] Start the build and confirm the UI version, full-resource standby log, stable CoC home screen, and no new battle launch.
