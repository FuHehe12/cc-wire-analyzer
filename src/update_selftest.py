"""就地更新自测：来源守卫 / 校验 / 替换与回滚 / 三道前置门（issue 260808）。

用法：uv run python src/update_selftest.py

**不联网**。传输层被换成一个假 opener，但 `_assert_allowed` 是真跑的——所以"白名单挡不挡得住"
这条断言测的是真守卫，只有"字节从哪来"是假的。反过来做（连真 GitHub）测的是网络通不通，
而不是这段代码对不对。

重点断言的是**几处静默失效就会很难看的地方**：

- **校验不过必须删文件**。留下一个校验失败的 exe 在更新目录里，下一次点"安装"就把它装上了。
- **回滚要真能回滚**。第三步失败时若不把 `.old` 换回来，用户的 exe 就凭空消失了——
  这是本项目唯一会动用户磁盘上可执行文件的路径，出事没有第二次机会。
- **三道前置门各自的原因码**。笼统地拒绝会被当成"坏了"，用户下一步就是去手动覆盖文件。
- **反向断言**：合法的 GitHub 对象存储地址**不许**被白名单误挡（误挡等于功能整个不可用）。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    # stderr 也要：失败路径的 log.warning 走 stderr，GBK 控制台下会变成乱码，
    # 而这些正是出问题时最该被读到的行。
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = Path(tempfile.mkdtemp(prefix="ccwa_upd_"))
# 两个变量是一对（开发约定第五节）：只隔离 CCWA_HOME，settings 那一半仍会指向用户真配置。
os.environ["CCWA_HOME"] = str(TMP)
os.environ["CCWA_CLAUDE_SETTINGS"] = str(TMP / "fake_settings.json")

import config as CFG                                  # noqa: E402
CFG.CONFIG_DIR = TMP

import updater as U                                   # noqa: E402
U.UPDATES_DIR = TMP / "updates"                       # 模块级路径也要一起重定向（260807 教训）

FAILED: list[str] = []


def ok(cond, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {label}")
    else:
        FAILED.append(label)
        print(f"  ✗ {label}" + (f" —— {detail}" if detail else ""))


# ===== 假传输：只替掉"字节从哪来"，守卫照跑 =====

class _FakeResp(io.BytesIO):
    def __init__(self, data: bytes, length: int | None = None):
        super().__init__(data)
        self.headers = {"Content-Length": str(length if length is not None else len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _FakeOpener:
    def __init__(self, data: bytes, length: int | None = None):
        self.data, self.length = data, length

    def open(self, req, timeout=None):
        U._assert_allowed(req.full_url if hasattr(req, "full_url") else str(req))
        return _FakeResp(self.data, self.length)


def with_bytes(data: bytes, length: int | None = None):
    U._opener = lambda: _FakeOpener(data, length)      # noqa: SLF001 —— 自测替传输层


EXE_BYTES = b"MZ" + b"\x00" * 4094                     # 像个 PE：魔数 + 4KB
import hashlib                                         # noqa: E402
EXE_SHA = hashlib.sha256(EXE_BYTES).hexdigest()
ASSET = {"name": "cc-wire-analyzer-v9.9.9-windows.exe", "size": len(EXE_BYTES),
         "url": "https://objects.githubusercontent.com/fake/asset"}


print("\n[1] 版本比较")
for label, cond in U.self_check():
    ok(cond, label)

print("\n[2] 来源守卫（不变量 10 第 2 条）")


def rejects(url: str) -> bool:
    try:
        U._assert_allowed(url)
        return False
    except ValueError:
        return True


ok(rejects("http://github.com/x"), "拒绝 http（明文可被中间人换掉二进制）")
ok(rejects("https://evil.com/x"), "拒绝名单外主机")
ok(rejects("https://github.com.evil.com/x"),
   "拒绝把白名单域当前缀的伪装域（github.com.evil.com）")
ok(rejects("https://notgithub.com/x"), "拒绝仅仅以白名单域结尾的字符串（notgithub.com）")
# 反向断言：真实的资产下载必然 302 到对象存储，误挡等于整个功能不可用。
ok(not rejects("https://objects.githubusercontent.com/a/b"),
   "放行 GitHub 对象存储（反向断言：误挡=功能整个不可用）")
ok(not rejects(U.API_LATEST), "放行 api.github.com")
ok(U.API_LATEST.startswith("https://api.github.com/repos/FuHehe12/"),
   "下载来源是硬编码常量，不来自配置（不变量 10 第 1 条）")

print("\n[3] 资产匹配（按模式，不按固定文件名）")
win = [{"name": "cc-wire-analyzer-v9.9.9-windows.exe", "size": 1, "browser_download_url": "u"},
       {"name": "cc-wire-analyzer-v9.9.9-macos.zip", "size": 2, "browser_download_url": "u2"},
       {"name": "SHA256SUMS.txt", "size": 3, "browser_download_url": "u3"}]
picked = U._pick_asset(win)
want = "windows.exe" if sys.platform == "win32" else "macos.zip"
ok(picked and picked["name"].endswith(want), f"挑出本平台资产（{want}）")
ok(U._pick_asset([{"name": "notes.md", "browser_download_url": "u"}]) is None,
   "没有本平台资产时返回 None（而不是随便挑一个）")
sums = U._sums_map(f"{EXE_SHA}  cc-wire-analyzer-v9.9.9-windows.exe\n"
                   f"{'b' * 64} *cc-wire-analyzer-v9.9.9-macos.zip\n")
ok(sums.get("cc-wire-analyzer-v9.9.9-windows.exe") == EXE_SHA
   and sums.get("cc-wire-analyzer-v9.9.9-macos.zip") == "b" * 64,
   "SHA256SUMS 解析（含二进制模式的 * 前缀）")

print("\n[4] 下载与校验")
with_bytes(EXE_BYTES)
U._download("test", ASSET, EXE_SHA)
st = U.status("test")
dest = U.UPDATES_DIR / ASSET["name"]
ok(st["phase"] == "ready" and dest.exists(), "校验通过 → ready 且文件落地")
ok(st["sha256"] == EXE_SHA and st["sha256_verified"], "校验和比对通过并如实标注")
ok(not (U.UPDATES_DIR / (ASSET["name"] + ".part")).exists(),
   "临时 .part 已改名（半成品不会被当成可安装的包）")

U._download("test", ASSET, "a" * 64)                   # 声明的校验和对不上
st = U.status("test")
ok(st["phase"] == "error" and not dest.exists(),
   "校验和不符 → 报错并删文件（留着就会在下次点安装时被装上）")

with_bytes(b"<html>rate limited</html>", length=len(EXE_BYTES))
U._download("test", ASSET, None)
ok(U.status("test")["phase"] == "error" and not dest.exists(),
   "下到 HTML 错误页（无 MZ 魔数）→ 报错")

with_bytes(EXE_BYTES[:100], length=len(EXE_BYTES))
U._download("test", ASSET, None)
ok(U.status("test")["phase"] == "error", "体积与 release 声明不符 → 报错")

with_bytes(EXE_BYTES)
U._download("test", ASSET, None)                       # release 没给校验和清单
st = U.status("test")
ok(st["phase"] == "ready" and st["sha256"] and not st["sha256_verified"],
   "没有校验和清单时**如实标注未校验**，不假装验过（惯犯 ③ 的形状）")

U._cancel.set()
U._download("test", ASSET, None)
U._cancel.clear()
ok(U.status("test")["phase"] == "idle" and not U.status("test")["error"],
   "取消 → 回到 idle 且不算错误")

print("\n[5] 前置门（三道，各自给原因码）")
with_bytes(EXE_BYTES)
U._download("test", ASSET, EXE_SHA)
ok(U.preflight(False) == (False, "source"),
   "源码模式拒绝替换（该 git pull，不该覆盖文件）")

sys.frozen = True                                      # type: ignore[attr-defined]
try:
    ok(U.preflight(True) == (False, "recording"),
       "录制中拒绝替换（停代理要写用户 settings.json，得用户自己按）")
    ok(U.preflight(False)[0], "冻结态 + 未录制 + 已就绪 → 放行")
    U._set(phase="idle")
    ok(U.preflight(False) == (False, "not_ready"), "没下载完不许安装")
    U._set(phase="ready")
    dest.unlink()
    ok(U.preflight(False) == (False, "file_gone"), "安装包被删掉后如实报 file_gone")
finally:
    del sys.frozen                                     # type: ignore[attr-defined]

print("\n[6] 就地替换与回滚")
sand = TMP / "sandbox"
sand.mkdir(parents=True, exist_ok=True)
cur = sand / "cc-wire-analyzer.exe"
new = sand / "downloaded.exe"
cur.write_bytes(b"OLD")
new.write_bytes(b"NEW")
old = U.swap_in_place(new, cur)
ok(cur.read_bytes() == b"NEW", "新版本就位")
ok(old.exists() and old.read_bytes() == b"OLD",
   "旧版本改名留在原地（运行中的文件删不掉但能改名，这是就地更新的全部依据）")
ok(not (sand / "cc-wire-analyzer.exe.new").exists(), "中转文件已消费掉")

# 回滚：让第三步（staging → cur）失败，断言用户的 exe 原封不动地回来。
cur.write_bytes(b"OLD2")
real_replace, calls = os.replace, {"n": 0}


def flaky(a, b):
    calls["n"] += 1
    if calls["n"] == 2:                                # 第 1 次是 cur→.old，第 2 次是 .new→cur
        raise OSError("模拟：第三步失败")
    return real_replace(a, b)


os.replace = flaky
try:
    U.swap_in_place(new, cur)
    ok(False, "第三步失败必须抛出")
except OSError:
    ok(True, "第三步失败会抛出")
finally:
    os.replace = real_replace
ok(cur.exists() and cur.read_bytes() == b"OLD2",
   "回滚：替换失败后旧 exe 原封不动地回来（不回滚 = 用户的程序凭空消失）")
ok(not (sand / "cc-wire-analyzer.exe.new").exists(), "回滚后不留中转文件")

print("\n[7] 残留清理")
ok(U.cleanup_leftovers() == 0, "源码模式没有可清理的残留（不去猜一个 exe 路径）")
sys.frozen, real_exe = True, sys.executable            # type: ignore[attr-defined]
sys.executable = str(cur)
try:
    (sand / "cc-wire-analyzer.exe.old").write_bytes(b"x")
    (sand / "cc-wire-analyzer.exe.new").write_bytes(b"x")
    ok(U.cleanup_leftovers() == 2, "启动时清掉上次更新的 .old / .new")
finally:
    sys.executable = real_exe
    del sys.frozen                                     # type: ignore[attr-defined]

print("\n[8] 能力自陈")
cap = U._capability(ASSET)
ok(cap["can_apply"] is False and cap["apply_reason"] == "source",
   "源码模式如实说不能替换，并给出原因码（笼统的'不支持'会被当成坏了）")

print()
if FAILED:
    print(f"[FAILED] {len(FAILED)} 条断言未通过：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("[ALL PASSED] 来源守卫 / 下载校验 / 前置门 / 就地替换与回滚 全部通过 ✓")
