"""压实格式自测：去重 / 随机访问 / 逐字节还原 / 版本门 / 单文件归档往返。

用法：uv run python src/pack_selftest.py

fixture 按**真形状**造（惯犯 bug ④：mock 形状错则测试全绿却什么都没测到）——system 三块
（计费头 / 身份行 / 规则库）、tools 定义每轮原样重发、messages 逐轮增长且前缀完全相同
（这正是 prompt caching 造成的冗余形状，也是本格式存在的理由）、响应侧只有 content_blocks。

重点断言最容易静默失效的几处：
  - **逐字节**还原（不是"看起来一样"）——这是「压实成功才删原文件」那道门的门锁
  - 校验真的会响：源文件被改一个字节，`verify_against` 必须抛，而不是放行
  - 版本门：pack_schema 不认识时**拒绝读**，不是按旧字段猜着读
  - 坏行不丢：崩溃残留的半行原样搬过去（压实是搬家不是清理）
  - 去重真的发生了：blob 数必须远小于块总数，否则格式白写了
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os                                            # noqa: E402
# **两个都要隔离**：只隔离 CCWA_HOME 会让 settings 那一半仍指向用户真配置
# （260802 实测闯过祸，见开发约定第五节）。本自测只读不写用户配置，也不留这个口子。
_HOME = Path(tempfile.mkdtemp(prefix="ccwa_packhome_"))
os.environ["CCWA_HOME"] = str(_HOME)
os.environ["CCWA_CLAUDE_SETTINGS"] = str(_HOME / "fake_settings.json")

import pack as P                                     # noqa: E402
import config as CFG                                 # noqa: E402
CFG.CONFIG_DIR = _HOME
import capture_store as CS                           # noqa: E402
CS.CAPTURES_DIR = _HOME / "captures"
CS.ARCHIVES_DIR = _HOME / "archives"
CS.SOURCES_DIR = _HOME / "sources"

FAILED: list[str] = []


def ok(cond, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {label}")
    else:
        FAILED.append(label)
        print(f"  ✗ {label}" + (f" —— {detail}" if detail else ""))


# ===== fixture：照真流量复刻 =====

BILLING = "x-anthropic-billing-header: cc_version=2.1.233.d25; cc_entrypoint=cli;"
IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
RULES = "# 规则库\n" + ("你必须遵守以下约定。\n" * 40)          # 每轮原样重发的大块
TOOLS = [{"name": n, "description": f"{n} 工具" + "。说明" * 30,
          "input_schema": {"type": "object", "properties": {"p": {"type": "string"}}}}
         for n in ("Read", "Edit", "Bash", "Grep")]


def make_day(n_turns: int = 12) -> list[dict]:
    """造一天录制：同一会话逐轮增长，历史前缀完全相同（prompt caching 的真实形状）。"""
    recs, messages = [], []
    for i in range(n_turns):
        messages = messages + [
            {"role": "user", "content": [{"type": "text", "text": f"第 {i} 个问题" + "细节" * 50}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"tu_{i}", "name": "Read",
                 "input": {"file_path": f"/x/{i}.py"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"tu_{i}",
                 "content": "文件内容" * 200}]},
        ]
        recs.append({
            "id": f"req_{i:07d}",
            "ts_start": f"2026-08-24T10:{i:02d}:00.000",
            "ts_end": f"2026-08-24T10:{i:02d}:05.000",
            "method": "POST", "path": "/v1/messages",
            "upstream": "https://api.anthropic.com/v1/messages",
            "request": {
                "headers_safe": {"X-Claude-Code-Session-Id": "s-1", "Authorization": "<redacted>"},
                "body": {
                    "model": "claude-opus-5",
                    "system": [{"type": "text", "text": BILLING},
                               {"type": "text", "text": IDENTITY},
                               {"type": "text", "text": RULES,
                                "cache_control": {"type": "ephemeral"}}],
                    "tools": TOOLS,
                    "messages": messages,
                    "max_tokens": 32000, "stream": True,
                },
            },
            "response": {
                "status": 200, "total_ms": 4200, "ttft_ms": 900,
                "headers_safe": {"content-type": "text/event-stream"},
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1000 + i, "output_tokens": 50},
                "content_blocks": [{"type": "text", "text": f"回答 {i}"}],
            },
            "error": None,
        })
    return recs


def write_jsonl(path: Path, recs: list[dict], *, bad_line: bool = False) -> None:
    with path.open("wb") as f:
        for r in recs:
            f.write((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8"))
        if bad_line:
            f.write(b'{"id": "req_broken", "request": {"body": {"mess\n')   # 崩溃残留半行


def main() -> None:
    TMP = Path(tempfile.mkdtemp(prefix="ccwa_pack_"))
    try:
        run(TMP)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
        shutil.rmtree(_HOME, ignore_errors=True)


def run(TMP: Path) -> None:
    recs = make_day()
    src = TMP / "2026-08-24.jsonl"
    write_jsonl(src, recs)
    raw_size = src.stat().st_size

    # ===== 1. 压实：去重发生了吗 =====
    print("\n[1] 压实与去重")
    pk = TMP / "2026-08-24.pack"
    mf = P.write_pack(src, pk, date="2026-08-24", tool_version="test")
    ok(mf["count"] == len(recs), "条数与源文件一致", f"{mf['count']} vs {len(recs)}")
    total_blocks = sum(len(r["request"]["body"]["messages"]) + 3 + len(TOOLS) for r in recs)
    ok(mf["blob_count"] < total_blocks / 3,
       f"去重真的发生（{mf['blob_count']} blob ← {total_blocks} 个块）")
    pack_size = sum(f.stat().st_size for f in pk.iterdir())
    ok(pack_size < raw_size / 3, f"体积显著下降（{raw_size} → {pack_size}）")
    ok(mf["raw_bytes"] == raw_size and len(mf["raw_blake2b"]) == 32,
       "manifest 记下了源文件字节数与哈希")

    # ===== 2. 逐字节还原 =====
    print("\n[2] 无损（逐字节，不是逐字段）")
    try:
        P.verify_against(pk, src)
        ok(True, "全量逐字节比对通过")
    except P.PackError as e:
        ok(False, "全量逐字节比对通过", str(e))

    back = TMP / "restored.jsonl"
    n = P.unpack(pk, back)
    ok(n == len(recs) and back.read_bytes() == src.read_bytes(),
       "unpack 还原出的文件与原文件逐字节一致")

    # ===== 3. 校验真的会响（不响的校验等于没有）=====
    print("\n[3] 校验会不会响")
    tampered = TMP / "tampered.jsonl"
    b = bytearray(src.read_bytes())
    i = b.find("第 5 个问题".encode("utf-8"))
    b[i + 2] = ord("9") if b[i + 2] != ord("9") else ord("8")     # 只改一个字节
    tampered.write_bytes(bytes(b))
    try:
        P.verify_against(pk, tampered)
        ok(False, "源文件改一个字节 → verify 必须抛", "居然放行了")
    except P.PackError as e:
        ok(e.code == "verify_failed", "源文件改一个字节 → verify 抛 verify_failed", e.code)

    # 少一行 / 多一行 都要抓到
    short = TMP / "short.jsonl"
    short.write_bytes(b"".join(src.read_bytes().splitlines(keepends=True)[:-1]))
    try:
        P.verify_against(pk, short)
        ok(False, "源文件少一行 → verify 必须抛", "居然放行了")
    except P.PackError:
        ok(True, "源文件少一行 → verify 抛")

    # ===== 4. 随机访问 =====
    print("\n[4] 随机访问")
    with P.PackReader(pk) as r:
        ok(r.count == len(recs), "lines 表条数正确")
        got = r.record_i(7)
        ok(got == recs[7], "按下标取第 7 条 == 原记录（逐字段）")
        off, ln = r.lines[3]
        ok(r.record_at(off, ln) == recs[3], "按 off/len 取（索引就是这么喂的）")
        ok(r.find_by_id("req_0000009") == recs[9], "按 id 兜底扫描命中")
        ok(r.find_by_id("req_nope") is None, "找不到的 id 返回 None 而不是报错")
        ok(len(list(r.iter_records())) == len(recs), "iter_records 遍历完整")
        ok(r.skel_size > 0 and r.skel_size < raw_size / 3, "骨架远小于原文件（索引锚点用它）")

    # ===== 5. 版本门 =====
    print("\n[5] 版本不符要拒绝读，不是猜着读")
    bad = TMP / "badver.pack"
    shutil.copytree(pk, bad)
    m = json.loads((bad / "map.json").read_text(encoding="utf-8"))
    m["pack_schema"] = 999
    (bad / "map.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    try:
        P.PackReader(bad)
        ok(False, "未来版本的 pack 必须拒读", "居然读了")
    except P.PackError as e:
        ok(e.code == "schema_mismatch", "未来版本的 pack 报 schema_mismatch", e.code)
    ok(not P.is_pack(TMP / "nope"), "不存在的目录不算 pack")

    # ===== 6. 坏行不丢 =====
    print("\n[6] 坏行原样搬过去（压实是搬家不是清理）")
    src2 = TMP / "2026-08-23.jsonl"
    write_jsonl(src2, recs[:3], bad_line=True)
    pk2 = TMP / "2026-08-23.pack"
    mf2 = P.write_pack(src2, pk2, date="2026-08-23")
    ok(mf2["bad_lines"] == 1, "坏行被计数（不是静默跳过）")
    try:
        P.verify_against(pk2, src2)
        ok(True, "含坏行的一天照样逐字节还原")
    except P.PackError as e:
        ok(False, "含坏行的一天照样逐字节还原", str(e))
    with P.PackReader(pk2) as r:
        ok(len(list(r.iter_records())) == 3, "iter_records 跳过坏行（与读取侧既有行为一致）")

    # ===== 7. 写入侧的门 =====
    print("\n[7] 写入侧的门")
    try:
        P.write_pack(src, pk, date="2026-08-24")
        ok(False, "往非空目录写 pack 必须拒绝", "居然写了")
    except P.PackError as e:
        ok(e.code == "dst_not_empty", "往非空目录写 pack 报 dst_not_empty", e.code)
    try:
        P.unpack(pk, back)
        ok(False, "还原到已存在的文件必须拒绝", "居然覆盖了")
    except P.PackError as e:
        ok(e.code == "dst_exists", "还原到已存在的文件报 dst_exists", e.code)

    # ===== 8. 单文件归档往返 =====
    print("\n[8] .ccwa 单文件往返（跨机搬运）")
    P.idx_path(pk).write_text('{"v":15,"id":"req_0000000","off":0,"len":10}\n', encoding="utf-8")
    ccwa = TMP / "2026-08-24.laptop.ccwa"
    info = P.to_ccwa(pk, ccwa, label="laptop", tool_version="9.9.9", host="TEST-BOX")
    ok(ccwa.exists() and info["label"] == "laptop", "归档成单文件并带上来源标签")
    peek = P.peek_ccwa(ccwa)
    ok(peek["date"] == "2026-08-24" and peek["count"] == len(recs),
       "不解包就能读出日期与条数")
    ok(peek.get("tool_version") == "9.9.9" and peek.get("host") == "TEST-BOX",
       "manifest 答得出「谁在哪台机器上打的包」（260826：答不出就会被当成本机数据）",
       f"{peek.get('tool_version')!r}/{peek.get('host')!r}")

    imported = TMP / "imported.pack"
    P.from_ccwa(ccwa, imported)
    ok(P.is_pack(imported), "导入解出的是个合法 pack")
    im = P.read_manifest(imported)
    ok(im.get("host") == "TEST-BOX" and im.get("tool_version") == "9.9.9",
       "产出者身份跟着落地（导入后仍答得出是哪台机器录的）",
       f"{im.get('tool_version')!r}/{im.get('host')!r}")
    # 转手归档不许改签：把别人的证据签上自己的名字，正是 sources/ 独立命名空间要防的事
    ccwa2 = TMP / "relay.ccwa"
    P.to_ccwa(imported, ccwa2)
    ok(P.peek_ccwa(ccwa2).get("host") == "TEST-BOX", "重新归档不覆盖原机器身份")
    ok(P.to_ccwa(pk2, TMP / "nostamp.ccwa").get("host") == "",
       "没人签名时 host 留空——空 = 答不上来，不等于本机")
    ok(P.idx_path(imported).exists(), "索引跟着归档走（导入端免掉一次全量重建）")
    with P.PackReader(imported) as r:
        ok(r.record_i(5) == recs[5], "导入后的 pack 能取出与原记录一致的内容")
    back2 = TMP / "restored2.jsonl"
    P.unpack(imported, back2)
    ok(back2.read_bytes() == src.read_bytes(), "跨「机器」往返后仍逐字节一致")

    # 坏归档要拒绝，且不留半成品
    print("\n[9] 坏归档")
    junk = TMP / "junk.ccwa"
    junk.write_bytes(b"not a zip at all")
    try:
        P.peek_ccwa(junk)
        ok(False, "非 zip 文件必须拒绝", "居然读了")
    except P.PackError as e:
        ok(e.code == "bad_archive", "非 zip 文件报 bad_archive", e.code)
    dst3 = TMP / "shouldnotexist.pack"
    try:
        P.from_ccwa(junk, dst3)
    except P.PackError:
        pass
    ok(not dst3.exists(), "导入失败不留半成品目录")

    # ===== 10. 存储分层：压实前后读取行为必须一致 =====
    # 这一节测的不是格式而是**契约**：同一天压实前后，列表 / DAG / 详情 / grep / 索引条数
    # 必须逐字节相同。压实是"换个存法"，不是"换份数据"——这条一破，压实就从优化变成了
    # 数据损坏，而界面上看不出任何异常（惯犯 ③ 的最坏版本）。
    print("\n[10] 存储分层：压实前后读取行为一致")
    CS.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    D = "2026-08-20"
    write_jsonl(CS.CAPTURES_DIR / f"{D}.jsonl", recs)

    def snap():
        lst = CS.list_captures(D, limit=10000)
        ids = [i["id"] for i in lst["items"]]
        return {
            "list": lst, "idx": len(CS.list_index(D)),
            "grep": CS.grep(D, "Claude Code", limit=20),
            "detail": {r: CS.get_capture(r, D) for r in ids[:3] + ids[-3:]},
            "dates": CS.list_dates(),
        }

    before = snap()
    info = CS.compact_date(D)
    after = snap()
    J = lambda o: json.dumps(o, ensure_ascii=False, sort_keys=True)
    ok(CS.is_packed(D), f"压实成功（{info['ratio']}x，省 {info['saved_bytes']} 字节）")
    ok(not (CS.CAPTURES_DIR / f"{D}.jsonl").exists(), "原 jsonl 已删（校验通过之后才删）")
    for key in ("list", "idx", "grep", "detail", "dates"):
        ok(J(before[key]) == J(after[key]), f"压实前后 {key} 逐字节一致")
    ok(CS.stats(D)["records"] == len(recs), "stats 条数不变")
    ok(CS.stats(D)["packed"] is True, "stats 如实报出已压实（体积字段变小不是异常）")

    # 今天不许压（代理正往里写）
    today = __import__("time").strftime("%Y-%m-%d")
    write_jsonl(CS.CAPTURES_DIR / f"{today}.jsonl", recs[:2])
    try:
        CS.compact_date(today)
        ok(False, "压实今天必须被拒绝", "居然压了")
    except CS.StoreError as e:
        ok(e.code == "is_today", "压实今天被拒绝（is_today）", e.code)

    # 还原。**比 items 不比整个响应**：上面刚给"今天"造了一份录制，`dates_available`
    # 因此多了一天——那是测试自己制造的差异，不是还原带来的。
    CS.uncompact_date(D)
    ok(not CS.is_packed(D) and (CS.CAPTURES_DIR / f"{D}.jsonl").exists(), "uncompact 还原回 jsonl")
    ok(J(snap()["list"]["items"]) == J(before["list"]["items"]), "还原后读取行为回到原样")

    # 归档 → 导入 → 按来源读
    a = CS.archive_date(D, keep=True)
    ok(Path(a["path"]).exists() and a["removed"] == 0, "归档产出单文件且默认不删原录制")
    imp = CS.import_archive(a["path"], label="laptop")
    ok(imp["label"] == "laptop" and imp["date"] == D, "导入落到 sources/<标签>/")
    ok(J(CS.list_captures(D, limit=10000, source="laptop")["items"])
       == J(before["list"]["items"]), "导入来源的列表与本机一致")
    ok(J(CS.get_capture(recs[0]["id"], D, source="laptop")) == J(before["detail"][recs[0]["id"]]),
       "导入来源的详情与本机一致")
    ok([x["label"] for x in CS.list_sources()] == ["laptop"], "来源清单列出它")
    # 溯源：归档要答得出"谁在哪台机器上用哪个版本录的"。这里走的是 **jsonl 直录态** 那条
    # 归档路径（上面刚 uncompact 回去），压实态那条在下面单独跑一遍——260826 的教训就是
    # 两条路径只有一条签了名，而没签名的那条产出的文件被当成了本机数据。
    host = CS.local_host()
    ok(imp["host"] == host and imp["foreign"] is False and imp["from"],
       "导入本机自己的归档：机器名对得上、不标外来、版本非空",
       f"{imp.get('host')!r}/{imp.get('foreign')!r}/{imp.get('from')!r}")
    ok(CS.list_sources()[0]["host"] == host, "来源清单带机器名（判断外来数据的唯一依据）")
    ok(any(x.get("host") == host for x in CS.list_archives()), "归档清单也带机器名")
    # 来源命名空间必须真的隔离：删来源不能碰本机同一天
    CS.delete_source("laptop")
    ok(not CS.list_sources() and (CS.CAPTURES_DIR / f"{D}.jsonl").exists(),
       "删来源不影响本机同一天（命名空间真的隔开了）")
    # 压实态那条归档路径也要签名（jsonl 路径过压实临时目录，pack 路径直通 to_ccwa）
    CS.compact_date(D)
    a2 = CS.archive_date(D, keep=True, label="packed")
    imp2 = CS.import_archive(a2["path"], label="packed")
    ok(imp2["host"] == host and imp2["from"], "压实态归档同样带机器名与版本",
       f"{imp2.get('host')!r}/{imp2.get('from')!r}")
    CS.delete_source("packed")
    CS.uncompact_date(D)
    try:
        CS.import_archive(a["path"], label="../evil")
        ok(False, "非法来源标签必须被拒（路径穿越）", "居然接受了")
    except CS.StoreError as e:
        ok(e.code == "bad_label", "非法来源标签被拒（bad_label）", e.code)

    print()
    if FAILED:
        print(f"[FAILED] {len(FAILED)} 条断言未通过：")
        for f in FAILED:
            print("  -", f)
        raise SystemExit(1)
    print("[ALL PASSED] 压实格式：去重 / 随机访问 / 逐字节还原 / 版本门 / 归档往返 全部通过 ✓")


if __name__ == "__main__":
    # 断言失败时不能只留 exit=1（那就是惯犯 ③「静默吞异常」的自测版）
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
