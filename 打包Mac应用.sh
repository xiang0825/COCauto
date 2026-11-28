#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${COC_MAC_VENV:-/tmp/coc-mac-app-venv}"
BUILD_ROOT="${COC_MAC_BUILD_ROOT:-/tmp/coc-mac-app-build}"
WORK_DIR="${BUILD_ROOT}/work"
DIST_DIR="${BUILD_ROOT}/dist"
PYTHON="${COC_MAC_PYTHON:-${VENV_DIR}/bin/python}"
SPEC_PATH="${REPO_ROOT}/自动脚本_mac.spec"
APP_PATH="${DIST_DIR}/COCauto.app"
BIN_PATH="${APP_PATH}/Contents/MacOS/COCauto"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "错误：此脚本仅支持在 macOS 上运行。" >&2
    exit 1
fi

if [[ ! -x "${PYTHON}" ]]; then
    echo "错误：找不到打包 Python：${PYTHON}" >&2
    echo "请先在仓库外创建 venv（例如 /tmp/coc-mac-app-venv）并安装项目依赖与 PyInstaller。" >&2
    exit 1
fi

if [[ ! -f "${SPEC_PATH}" ]]; then
    echo "错误：找不到 spec 文件：${SPEC_PATH}" >&2
    exit 1
fi

mkdir -p "${WORK_DIR}" "${DIST_DIR}"

echo "[1/4] 使用 PyInstaller 打包 COCauto.app（arm64）..."
PYTHONDONTWRITEBYTECODE=1 "${PYTHON}" -m PyInstaller \
    --noconfirm \
    --clean \
    --workpath "${WORK_DIR}" \
    --distpath "${DIST_DIR}" \
    "${SPEC_PATH}"

if [[ ! -d "${APP_PATH}" || ! -x "${BIN_PATH}" ]]; then
    echo "错误：打包输出缺失：${APP_PATH}" >&2
    exit 1
fi

echo "[2/4] 校验打包模块、源码一致性、资源与架构..."
PYTHONDONTWRITEBYTECODE=1 "${PYTHON}" - "${REPO_ROOT}" "${APP_PATH}" "${BIN_PATH}" <<'PY'
import marshal
import plistlib
import sys
from pathlib import Path
from types import CodeType

from PyInstaller.archive.readers import CArchiveReader, PKG_ITEM_PYZ, pkg_archive_contents

repo_root = Path(sys.argv[1]).resolve()
app_path = Path(sys.argv[2]).resolve()
bin_path = Path(sys.argv[3]).resolve()

sys.path.insert(0, str(repo_root))
from scripts import verify_packaged_modules as v

expected_version = (repo_root / "版本号.txt").read_text(encoding="utf-8").strip()
if not expected_version:
    raise SystemExit("版本号.txt 为空")

plist = plistlib.loads((app_path / "Contents" / "Info.plist").read_bytes())
bundle_id = plist.get("CFBundleIdentifier")
if bundle_id != "com.xiang0825.cocauto":
    raise SystemExit(f"CFBundleIdentifier 不匹配：{bundle_id}")
if plist.get("CFBundleShortVersionString") != expected_version:
    raise SystemExit(f"Info.plist 版本不匹配：{plist.get('CFBundleShortVersionString')} != {expected_version}")

resource_roots = [app_path / "Contents" / "Frameworks", app_path / "Contents" / "Resources"]

def find_bundled(rel: str) -> Path | None:
    for root in resource_roots:
        p = root / rel
        if p.exists():
            return p
    return None

ver_file = find_bundled("版本号.txt")
if ver_file is None or ver_file.read_text(encoding="utf-8").strip() != expected_version:
    raise SystemExit(f"包内版本号文件缺失或不匹配：{ver_file}")

for required_rel in (
    "img",
    "模块/检测/OCR识别器/rapidocr_onnxruntime/config.yaml",
    "模块/检测/YOLO检测器/模型/best.onnx",
    "任务流程/战宠升级/模型/战宠小屋检测模块.onnx",
    "任务流程/战宠升级/img.png",
):
    if find_bundled(required_rel) is None:
        raise SystemExit(f"缺少运行时资源：{required_rel}")

for src_json in sorted((repo_root / "资源" / "识别").glob("*.json")):
    bundled_json = find_bundled(f"资源/识别/{src_json.name}")
    if bundled_json is None or bundled_json.read_bytes() != src_json.read_bytes():
        raise SystemExit(f"识别参数缺失或不一致：{src_json.name}")

required_modules = v.所需打包模块(repo_root / "线程" / "自动化机器人.py") | v.所需启动依赖模块()
packaged_modules = set(pkg_archive_contents(str(bin_path)))
missing_modules = sorted(required_modules - packaged_modules)
if missing_modules:
    raise SystemExit(f"缺少必需模块：{missing_modules}")

archive = CArchiveReader(str(bin_path))
pyz_name = next((name for name, item in archive.toc.items() if item[-1] == PKG_ITEM_PYZ), None)
if pyz_name is None:
    raise SystemExit("缺少 PYZ 归档")
pyz = archive.open_embedded_archive(pyz_name)
entry_scripts = {name for name, item in archive.toc.items() if item[-1] == "s"}
missing_scripts = v.缺失入口脚本(entry_scripts)
if missing_scripts:
    raise SystemExit(f"缺少入口脚本：{sorted(missing_scripts)}")

project_modules = v.项目归档源码模块(repo_root, set(pyz.toc), entry_scripts)
mismatched = []
for mod in sorted(project_modules):
    src_path = v.解析源码模块路径(repo_root, mod)
    code = marshal.loads(archive.extract(mod)) if mod in entry_scripts else pyz.extract(mod)
    if not isinstance(code, CodeType) or not v.模块源码匹配(src_path, code):
        mismatched.append(mod)
if mismatched:
    raise SystemExit(f"打包模块与当前源码不一致：{mismatched}")

print(
    f"模块校验通过：版本 {expected_version}，bundle_id={bundle_id}，"
    f"{len(required_modules)} 个必需模块齐全，{len(project_modules)} 个项目模块与源码一致"
)
PY

ARCHS="$(lipo -archs "${BIN_PATH}")"
if [[ "${ARCHS}" != *"arm64"* ]]; then
    echo "错误：主可执行文件架构不是 arm64：${ARCHS}" >&2
    exit 1
fi
echo "主程序架构：${ARCHS}"

echo "[3/4] 执行 ad-hoc 签名..."
codesign --force --deep --sign - "${APP_PATH}"

echo "[4/4] 校验代码签名..."
codesign --verify --deep --strict --verbose=2 "${APP_PATH}"

echo "打包完成：${APP_PATH}"
du -sh "${APP_PATH}"
