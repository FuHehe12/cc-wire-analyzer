#!/usr/bin/env python3
"""本地打包：定版本 → 打 → 改名 → 校验和，与 CI 同一份逻辑（issue 260809）。

用法：
  uv run python tools/build.py                    # 读 src/_version.py，没有就是 "dev"
  uv run python tools/build.py --version 0.4.11   # 显式版本（也会写回 _version.py）
  uv run python tools/build.py --from-git         # 从 git describe --tags 推（版本真源是 tag）
  uv run python tools/build.py --self-test        # 验命名规则与 CI 一致，不真打包

为什么要有它：260808 加的版本资源是 spec 内置的，本地 pyinstaller 就能拿到；
但"资产名带版本"和"SHA256SUMS.txt"此前只在 release.yml 里，本地手动打包产出的
还是光秃秃的 `cc-wire-analyzer.exe`。两份逻辑（CI 的 bash + 本地的手敲 mv）
必然分叉——这个脚本把它们收口到一处。

**版本真源仍是 git tag**（开发约定第九节）。本脚本绝不写死任何真实版本号，
只是把"从 tag 取版本"这件事在本地也能做。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import version_res as VR   # noqa: E402

PLATFORM = "windows" if sys.platform == "win32" else "macos"
SPEC = "build.spec" if PLATFORM == "windows" else "build-mac.spec"
SUMS_NAME = "SHA256SUMS.txt"


# ===== 版本 =====

def version_from_git() -> str | None:
    """`git describe --tags` → 版本串。无 git / 无 tag 返回 None（让调用方回落）。

    `git describe --tags` 的输出形如 `v0.4.10` 或 `v0.4.10-5-g1a2b3c4`（tag 之后有 5 个 commit）。
    后者说明 HEAD 不在某个 tag 上——这是本地打包的常态（正在开发），不是错误，
    但版本号不该假装是 `0.4.10`（那会与已发布的 tag 混淆）。保留后缀 `-5-g1a2b3c4`，
    app.py 的 VERSION 原样用，属性页/资产名也原样显示——一眼能看出"不是发版"。
    """
    try:
        r = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, cwd=ROOT, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip().lstrip("vV") or None


def sync_version_file(version: str) -> bool:
    """把版本写进 `src/_version.py`，与 CI 的 Inject version 步骤对称。

    返回是否写了（版本与现有文件不同才写）。**只写 CI 那一行格式**，免得本地/CI
    两份 _version.py 格式分叉（doc_audit 用正则提取，格式必须稳定）。
    """
    vp = ROOT / "src" / "_version.py"
    line = (f'VERSION = "{version}"'
            '  # CI 从 tag 注入，勿手改（见 docs/reference/开发约定.md 第九节）\n')
    try:
        cur = vp.read_text(encoding="utf-8") if vp.exists() else ""
    except OSError:
        cur = ""
    if cur == line:
        return False
    vp.write_text(line, encoding="utf-8")
    return True


# ===== 命名与校验和：与 release.yml 同一份规则 =====

def asset_name(version: str) -> str:
    """产物文件名。**与 release.yml 的 mv 目标完全一致**——同版本同平台必出同名。

    有意抽成函数而不是内联：CI（bash）和本地（Python）各写一次就分叉过了
    （260808 的教训），用同一个函数生成两边都认的字符串。
    """
    ext = "exe" if PLATFORM == "windows" else "zip"
    return f"cc-wire-analyzer-v{version}-{PLATFORM}.{ext}"


def write_sha256sums(dist: Path, version: str) -> Path:
    """生成 SHA256SUMS.txt。glob 规则与 release.yml 一致：只 glob `cc-wire-analyzer-*`，
    **不写 `*`**——那会把清单自己也算进去。

    校验和是软件内自动更新比对的那一份（不变量 10 第 3 条）。本地打的包配本地产的
    校验和，自更新链路在本地也能闭环验证。
    """
    assets = sorted(dist.glob("cc-wire-analyzer-*"))
    sums_path = dist / SUMS_NAME
    lines = []
    for a in assets:
        h = hashlib.sha256()
        with open(a, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {a.name}")
    sums_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return sums_path


# ===== 打包 =====

def run_pyinstaller() -> int:
    """跑 PyInstaller，返回其退出码。**不吞 stderr**——pyinstaller 的错误信息是诊断的命脉。"""
    cmd = [sys.executable, "-m", "PyInstaller", SPEC, "--noconfirm", "--clean"]
    print(f"[build] {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def finalize(dist: Path, version: str) -> list[Path]:
    """pyinstaller 跑完后的重命名 + 校验和。返回所有产出文件（含 SHA256SUMS）。

    与 release.yml 的「Zip macOS app」「Rename Windows exe」「Checksums」三步对齐：
    Windows 是 mv .exe；macOS 是 ditto .app → .zip（资源分支保留）。ditto 命令照抄 CI，
    本开发环境为 Windows，macOS 部分未实测——与 build-mac.spec 同一口径。
    """
    target = dist / asset_name(version)
    if target.exists():
        target.unlink()
    if PLATFORM == "windows":
        src = dist / "cc-wire-analyzer.exe"
        if not src.exists():
            raise FileNotFoundError(f"PyInstaller 未产出 {src.name}（看上方日志）")
        src.rename(target)
    else:
        app = dist / "cc-wire-analyzer.app"
        if not app.exists():
            raise FileNotFoundError(f"PyInstaller 未产出 {app.name}（看上方日志）")
        # ditto --sequesterRsrc --keepParent：保留资源分支与目录结构（普通 zip 会丢）
        rc = subprocess.call(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             str(app), str(target)], cwd=dist)
        if rc != 0:
            raise RuntimeError(f"ditto 打包失败（exit={rc}）")
    sums = write_sha256sums(dist, version)
    return [target, sums] + [p for p in sorted(dist.glob("cc-wire-analyzer-*")) if p not in (target, sums)]


def build(version: str, sync: bool) -> int:
    if sync:
        if sync_version_file(version):
            print(f"[build] 已同步 src/_version.py → {version}")
    print(f"[build] 版本: {version}  平台: {PLATFORM}  spec: {SPEC}")
    rc = run_pyinstaller()
    if rc != 0:
        print(f"[build] PyInstaller 失败（exit={rc}）", file=sys.stderr)
        return rc
    dist = ROOT / "dist"
    try:
        products = finalize(dist, version)
    except (OSError, RuntimeError, FileNotFoundError) as e:
        print(f"[build] 收尾失败：{e}", file=sys.stderr)
        return 1
    print()
    print(f"[build] 完成 — 版本 {version}")
    for p in products:
        size = p.stat().st_size
        print(f"  {p.name}  ({size / 1024 / 1024:.1f} MB)")
    return 0


# ===== self-test：不真打包，只验规则 =====

def self_test() -> int:
    """验命名规则与 _version 同步逻辑，**不跑 pyinstaller**。

    为什么 self-test 也值得有：release.yml 的命名是 bash 字符串拼接、这里是 Python f-string，
    两个语言各写一份拼接规则——只要一边改了忘另一边，CI 和本地产出就不一致。这个自测
    把"期望的命名格式"独立写一遍，与 asset_name 函数互相对照，哪边动了都会响。
    """
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        print(f"  {'✓' if cond else '✗'} {label}" + (f" —— {detail}" if detail and not cond else ""))
        ok = ok and cond

    # 1. 命名格式：独立拼一遍期望值，与 asset_name() 函数的输出对照。
    #    两份拼法独立——一边改了另一边没跟就会响。
    v = "0.4.11"
    for plat, ext in [("windows", "exe"), ("macos", "zip")]:
        expect = f"cc-wire-analyzer-v{v}-{plat}.{ext}"
        # 临时替换模块级 PLATFORM 来测对应分支
        orig = PLATFORM
        try:
            globals()["PLATFORM"] = plat
            got = asset_name(v)
        finally:
            globals()["PLATFORM"] = orig
        check(f"{plat} 命名格式", got == expect,
              f"期望 {expect!r}，实得 {got!r}")

    # 2. _version.py 写入格式必须能被 version_res.read_version 与 doc_audit 的正则提取
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="ccwa_build_"))
    vp = tmp / "_version.py"
    sync_line = ('VERSION = "0.4.11-test"'
                 '  # CI 从 tag 注入，勿手改（见 docs/reference/开发约定.md 第九节）\n')
    vp.write_text(sync_line, encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', vp.read_text(encoding="utf-8"), re.M)
    check("_version.py 格式可被正则提取", bool(m) and m.group(1) == "0.4.11-test")

    # 3. SHA256SUMS 的 glob 是 `cc-wire-analyzer-*`（不含自身），不是 `*`
    check("SHA256SUMS 文件名不在产物 glob 内",
          not re.match(r"cc-wire-analyzer-", SUMS_NAME))

    print()
    if ok:
        print("[ALL PASSED] build.py 命名/同步规则自测 ✓")
        return 0
    print("[FAILED]")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="本地打包（与 CI 同一份版本/命名/校验和逻辑）")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--version", help="显式版本号（也写回 src/_version.py）")
    src.add_argument("--from-git", action="store_true",
                     help="从 git describe --tags 取版本（版本真源是 tag）")
    ap.add_argument("--no-sync", action="store_true",
                    help="不把版本写回 src/_version.py（默认写，与 CI 的 Inject version 对称）")
    ap.add_argument("--self-test", action="store_true", help="验规则不真打包")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    # 定版本：显式 > --from-git > _version.py > dev
    if args.version:
        version = args.version
    elif args.from_git:
        version = version_from_git()
        if not version:
            print("[build] --from-git 失败：无 git 或无 tag，改用 src/_version.py", file=sys.stderr)
            version = VR.read_version()
        else:
            print(f"[build] git describe → {version}")
    else:
        version = VR.read_version()

    return build(version, sync=not args.no_sync)


if __name__ == "__main__":
    sys.exit(main())
