# High-access star strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve the existing two-direction attack strategy for high-access, high-score targets after low-star results.

**Architecture:** Reuse current battle score/reach evidence in `更新战斗学习`; emit the existing `提高目标可达评分` suggestion, which activates the two-direction selector and bounded search gate. Require current-result evidence to avoid stale records. Add focused regression tests.

**Tech Stack:** Python, unittest, SQLite state records, existing PyInstaller candidate build.

**Spec:** `docs/superpowers/specs/2026-11-15-high-access-stars-design.md`

## Global Constraints

- High-access threshold: score `>= 8.0`, conservative reach `>= 70.0%`.
- No new vision model, dependency, screenshot input, or live process interruption.
- Keep the root EXE unchanged while PID 64284 is active.
- Build only an isolated candidate package.

## Review Focus

- Missing or malformed reach evidence must preserve existing behavior; covered by existing learning tests.
- Low-access targets must not enter the high-access branch; covered by existing accessibility tests.
- High-access two-direction advice must continue using existing candidate filtering; covered by existing adaptive-target tests.

---

### Task 1: High-access learning decision

**Files:**
- Modify: `任务流程/主世界打鱼/等待战斗结束并回营.py`
- Test: `tests/test_return_flow.py`

**Interfaces:**
- Consumes the existing current-battle record fields `资源易窃取评分` and `资源易窃取评分依据.高价值资源可达折算`.
- Produces the existing `战斗学习.下一场建议` value `提高目标可达评分`.

- [x] **Step 1: Add one failing regression test**
  - With two recent low-performance results and a current low-star result scored `8.9` with conservative reach `74.9%`, assert the next suggestion is `提高目标可达评分` and the rationale keeps two-direction exploration.
- [x] **Step 2: Run that test and confirm the expected failure**
  - Expected old behavior reproduced: it suggested `集中资源`.
- [x] **Step 3: Add the minimal high-access branch**
  - In `更新战斗学习`, current-result high-access evidence overrides a generic concentration diagnosis after repeated low performance.
- [x] **Step 4: Run the new test and the adjacent learning tests**
  - Targeted test passed; the three adjacent modules passed all 171 tests.
- [x] **Step 5a: Run the full test suite**
  - `python -m unittest discover -s tests`: 832 passed, 3 skipped.
- [x] **Step 5b: Build and verify an isolated candidate**
  - RC77 build succeeded; the packaged-module check found all 21 required lazy imports, `_internal` contains 1,273 files and `python312.dll`, and the active root EXE hash is unchanged.
