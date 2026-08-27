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
import json
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


class _Router:
    """按 URL 路由的假 opener：API / 校验和清单 / 资产可以各给各的字节。

    校验和拉取挪进下载线程后（260809），`_download` 自己会先打 api.github.com——
    假传输必须能区分"哪个地址回什么"，否则 API 请求吃到 exe 字节、json.loads 炸成
    一堆看不懂的失败。"""

    def __init__(self, routes: dict, gate=None):
        self.routes, self.gate = routes, gate

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        U._assert_allowed(url)                            # 守卫是真跑的
        for key, val in self.routes.items():
            if key in url:
                data, length = val if isinstance(val, tuple) else (val, None)
                if self.gate is not None and key == "fake/asset":
                    ok(self.gate.wait(timeout=10), "阻塞假传输：10 秒内放行（防死等）")
                return _FakeResp(data, length)
        raise OSError("假传输没有这个地址：" + url[:100])


def with_bytes(data: bytes, length: int | None = None, gate=None):
    """只给资产字节：API 请求得到一个不带校验和资产的空 release。"""
    with_route({"fake/asset": (data, length)}, sums_text=None, gate=gate)


def with_route(asset: dict, sums_text: str | None, gate=None):
    """API JSON 里只有校验和资产会被 _download 真的去读（主资产走的是 state 里的那份）。"""
    assets = []
    if sums_text is not None:
        assets.append({"name": "SHA256SUMS.txt", "size": len(sums_text),
                       "browser_download_url": "https://github.com/fake/SHA256SUMS.txt"})
    api = json.dumps({"tag_name": "v9.9.9", "assets": assets}).encode()
    routes = {"api.github.com": api, "SHA256SUMS.txt": (sums_text or "").encode(), **asset}
    U._opener = lambda: _Router(routes, gate=gate)       # noqa: SLF001 —— 自测替传输层


EXE_BYTES = b"MZ" + b"\x00" * 4094                     # 像个 PE：魔数 + 4KB
import hashlib                                         # noqa: E402
EXE_SHA = hashlib.sha256(EXE_BYTES).hexdigest()
ASSET = {"name": "cc-wire-analyzer-v9.9.9-windows.exe", "size": len(EXE_BYTES),
         "url": "https://objects.githubusercontent.com/fake/asset"}
SUMS_OK = f"{EXE_SHA}  {ASSET['name']}\n"
SUMS_BAD = f"{'a' * 64}  {ASSET['name']}\n"


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

print("\n[4] 下载与校验（校验和拉取在线程内，260809）")
with_route({"fake/asset": EXE_BYTES}, sums_text=SUMS_OK)
U._download("test", ASSET)
st = U.status("test")
dest = U.UPDATES_DIR / ASSET["name"]
ok(st["phase"] == "ready" and dest.exists(), "校验通过 → ready 且文件落地")
ok(st["sha256"] == EXE_SHA and st["sha256_verified"], "校验和比对通过并如实标注")
ok(not list(U.UPDATES_DIR.glob("*.part")),
   "临时 .part 已改名（半成品不会被当成可安装的包）")

with_route({"fake/asset": EXE_BYTES}, sums_text=SUMS_BAD)
U._download("test", ASSET)                             # 声明的校验和对不上
st = U.status("test")
ok(st["phase"] == "error" and not dest.exists(),
   "校验和不符 → 报错并删文件（留着就会在下次点安装时被装上）")

with_bytes(b"<html>rate limited</html>", length=len(EXE_BYTES))
U._download("test", ASSET)
ok(U.status("test")["phase"] == "error" and not dest.exists(),
   "下到 HTML 错误页（无 MZ 魔数）→ 报错")

with_bytes(EXE_BYTES[:100], length=len(EXE_BYTES))
U._download("test", ASSET)
ok(U.status("test")["phase"] == "error", "体积与 release 声明不符 → 报错")

with_bytes(EXE_BYTES)
U._download("test", ASSET)                             # release 没给校验和清单
st = U.status("test")
ok(st["phase"] == "ready" and st["sha256"] and not st["sha256_verified"],
   "没有校验和清单时**如实标注未校验**，不假装验过（惯犯 ③ 的形状）")

U._cancel.set()
U._download("test", ASSET)
U._cancel.clear()
ok(U.status("test")["phase"] == "idle" and not U.status("test")["error"],
   "取消 → 回到 idle 且不算错误")

print("\n[4.5] 单 flight 与 staging 唯一名（260809 事故根因）")
ok(U._staging_path(Path("x.exe")) != U._staging_path(Path("x.exe")),
   "staging 文件名每次唯一（并发写者不再共享同一文件，rename 不撞句柄）")

import threading                                        # noqa: E402
gate = threading.Event()
with_bytes(EXE_BYTES, gate=gate)                       # 资产 open 阻塞 = 线程停在 starting
U._set(phase="idle", asset=ASSET, error=None)
r1 = U.start_download("test")
r2 = U.start_download("test")                          # 线程还在 connect 窗口内的重复点击
ok(r1.get("ok") is True, "第一次启动成功")
ok(r2.get("ok") is False and r2.get("already_running") is True
   and r2.get("phase") == "starting",
   "connect 窗口内的重复点击被拒（旧版在此放出了 13 个并发下载线程）",
   str(r2))
ok(U.status("test")["phase"] == "starting",
   "starting 是独立 phase：连上 GitHub 之前不再是 idle（前端停表 bug 的那扇窗）")
gate.set()
U._thread.join(timeout=10)
ok(U.status("test")["phase"] == "ready", "放行后下载完成 → ready")

# starting 期间的取消也要能停
gate.clear()
with_bytes(EXE_BYTES, gate=gate)
U._set(phase="idle", asset=ASSET)
U.start_download("test")
U.cancel()
gate.set()
U._thread.join(timeout=10)
U._cancel.clear()                                      # cancel() 只置旗，清旗是下一轮的义务
ok(U.status("test")["phase"] == "idle" and not U.status("test")["error"],
   "starting 期间取消 → 停回 idle")

# check 不盖活动任务的 phase（260809：下载中点"检查更新"把 phase 打回 idle，轮询停表）
U._set(phase="downloading")
rc = U.check("test")
ok(rc.get("phase") == "downloading" and U.status("test")["phase"] == "downloading",
   "下载进行中 check 只更新版本信息，不碰 phase")
U._set(phase="idle")
rc = U.check("test")
ok(rc.get("ok") is True and rc.get("phase") == "idle",
   "空闲时 check 照常回落 idle，返回值带 phase 供前端渲染")

print("\n[5] 前置门（三道，各自给原因码）")
with_route({"fake/asset": EXE_BYTES}, sums_text=SUMS_OK)
U._set(phase="idle", asset=ASSET)
U._download("test", ASSET)
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

print("\n[8] 重启新实例的环境（260827：版本号变了、界面还是旧的）")
_saved_env = dict(os.environ)
try:
    os.environ.update({
        "_PYI_PARENT_PROCESS_LEVEL": "1",
        "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI76282",
        "_PYI_ARCHIVE_FILE": r"C:\app\cc-wire-analyzer.exe",
        "_PYI_SPLASH_IPC": "1234",
        "_MEIPASS2": r"C:\Temp\_MEI76282",
        "CCWA_SELFTEST_KEEPME": "keep",
    })
    env = U._child_env()
    leaked = [k for k in env if k.startswith("_PYI_") or k == "_MEIPASS2"]
    ok(not leaked,
       "剥掉 PyInstaller 引导器私有变量（漏一个，新 exe 就复用旧解压目录 → "
       f"版本号是新的、界面是旧的）；泄漏：{leaked}")
    # 反向断言：只剥那几个键。连坐剥掉 PATH/TEMP 会引出一批新问题，而那种错误
    # 在源码模式下完全不显形——必须在这里挡住。
    ok(env.get("CCWA_SELFTEST_KEEPME") == "keep", "其余环境变量原样保留")
    ok("CCWA_HOME" in env and "CCWA_CLAUDE_SETTINGS" in env,
       "数据目录与 settings 路径两个隔离变量都要传给新实例")
finally:
    os.environ.clear()
    os.environ.update(_saved_env)

print("\n[9] 能力自陈")
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
