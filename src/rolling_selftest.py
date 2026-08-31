"""滚动分片压实自测：切段 / 读取一致 / 失败回退 / 断电残留 / 合并还原 / 删除覆盖。

用法：uv run python src/rolling_selftest.py

滚动压实（issue 260831）把「今天」拆成 `{date}.pNN.pack` 若干分片 + 还在写的尾巴 jsonl，
跨天再合并回单 `{date}.pack`。它动的是本项目最敏感的地方——**正在被 append 写的那个文件**，
所以这里的重点不是"功能能跑"，而是几条**错了不会报错**的线：

  - **顺序**：分片在前、尾巴在后。反了则整天的时序是错的，而且没有任何东西会报错
  - **一致**：切段前后，list_index / iter_records / get_capture 必须逐条相同
  - **回退**：压实失败要能还原成"就像没切过"，不能留下一截谁都读不到的录制
  - **残留**：断电留下的 sealing 文件里是真录制。**删了就是静默丢数据**——
    要靠哈希区分"已压实所以可删"与"没压完所以要并回"
  - **可见**：只剩分片（尾巴为空）的一天，仍要出现在日期列表里
"""
from __future__ import annotations

import json
import os
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

# **两个都要隔离**：只隔离 CCWA_HOME 会让 settings 那一半仍指向用户真配置
# （见开发约定第五节）。本自测会写录制、会删录制，绝不能碰到真目录。
_HOME = Path(tempfile.mkdtemp(prefix="ccwa_rollhome_"))
os.environ["CCWA_HOME"] = str(_HOME)
os.environ["CCWA_CLAUDE_SETTINGS"] = str(_HOME / "fake_settings.json")

import config as CFG                                  # noqa: E402
CFG.CONFIG_DIR = _HOME
import pack as P                                      # noqa: E402
import capture_store as CS                            # noqa: E402
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


BILLING = "x-anthropic-billing-header: cc_version=2.1.233.d25; cc_entrypoint=cli;"
IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
RULES = "# 规则库\n" + ("约定内容 " * 400)
TOOLS = [{"name": n, "description": f"{n} 工具" * 30,
          "input_schema": {"type": "object", "properties": {}}}
         for n in ("Read", "Edit", "Bash", "Grep")]


def make_recs(n: int, start: int = 0, session: str = "s-1") -> list[dict]:
    """照真流量的形状造记录：历史逐轮增长、前缀完全相同（prompt caching 的样子）。

    形状不像真流量的话，测出来的是自己的幻觉（惯犯 bug ④）——这里尤其要紧，
    因为分片的价值就建立在"跨记录大量重复"上。
    """
    recs, messages = [], []
    for k in range(n):
        i = start + k
        messages = messages + [
            {"role": "user", "content": [{"type": "text", "text": f"第 {i} 问" + "细节" * 40}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"tu_{i}", "name": "Read",
                 "input": {"file_path": f"/x/{i}.py"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"tu_{i}", "content": "文件内容" * 150}]},
        ]
        recs.append({
            "id": f"req_{i:07d}",
            "ts_start": f"2026-08-24T10:{i % 60:02d}:00.000",
            "ts_end": f"2026-08-24T10:{i % 60:02d}:05.000",
            "method": "POST", "path": "/v1/messages",
            "upstream": "https://api.anthropic.com/v1/messages",
            "request": {
                "headers_safe": {"X-Claude-Code-Session-Id": session,
                                 "Authorization": "<redacted>"},
                "body": {"model": "claude-opus-5",
                         "system": [{"type": "text", "text": BILLING},
                                    {"type": "text", "text": IDENTITY},
                                    {"type": "text", "text": RULES,
                                     "cache_control": {"type": "ephemeral"}}],
                         "tools": TOOLS, "messages": messages,
                         "max_tokens": 32000, "stream": True},
            },
            "response": {"status": 200, "total_ms": 4200, "ttft_ms": 900,
                         "headers_safe": {"content-type": "text/event-stream"},
                         "stop_reason": "end_turn",
                         "usage": {"input_tokens": 1000 + i, "output_tokens": 50},
                         "content_blocks": [{"type": "text", "text": f"回答 {i}"}]},
            "error": None,
        })
    return recs


def write_tail(date: str, recs: list[dict]) -> None:
    """把记录追加进尾巴 jsonl（`append` 的写法，逐字一致——还原验收线靠这个）。"""
    CS.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    with (CS.CAPTURES_DIR / f"{date}.jsonl").open("ab") as f:
        for r in recs:
            f.write((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8"))


def ids_via_index(date: str) -> list[str]:
    CS._IDX_CACHE.clear()
    return [e.get("id") for e in CS.list_index(date)]


def ids_via_iter(date: str) -> list[str]:
    return [r.get("id") for r in CS._Day(date).iter_records()]


DATE = "2026-08-24"


def run() -> None:
    root = CS.CAPTURES_DIR

    # ========== [1] 切段基本流程 ==========
    print("\n[1] 切段：尾巴 → 分片")
    all_recs = make_recs(30)
    write_tail(DATE, all_recs[:10])
    raw_before = (root / f"{DATE}.jsonl").stat().st_size
    ids_before = ids_via_index(DATE)

    r = CS.seal_tail(DATE)
    ok(r is not None and r["count"] == 10, "封存了 10 条", str(r))
    ok((root / f"{DATE}.p01.pack").is_dir(), "分片 p01 就位")
    _tail = root / f"{DATE}.jsonl"
    ok(not _tail.exists() or _tail.stat().st_size == 0, "尾巴已清空（append 会新建）")
    ok(r["packed_bytes"] < raw_before, f"确实变小了：{raw_before} → {r['packed_bytes']}")
    ok(ids_via_index(DATE) == ids_before, "切段后索引读出来的 id 序列不变")
    ok(ids_via_iter(DATE) == ids_before, "切段后遍历读出来的 id 序列不变")

    # ========== [2] 多分片 + 尾巴的顺序 ==========
    print("\n[2] 多分片 + 尾巴：顺序必须是 分片1 → 分片2 → 尾巴")
    write_tail(DATE, all_recs[10:20])
    CS.seal_tail(DATE)
    write_tail(DATE, all_recs[20:30])          # 这 10 条留在尾巴里不封
    day = CS._Day(DATE)
    ok(len(day.segments) == 2, f"两个分片：{[d.name for d in day.segments]}")
    want = [x["id"] for x in all_recs]
    ok(ids_via_iter(DATE) == want, "遍历顺序 = 录制顺序（分片在前、尾巴在后）")
    ok(ids_via_index(DATE) == want, "索引顺序 = 录制顺序")
    ok(day.count() == 30, f"条数 = 分片之和 + 尾巴：{day.count()}")

    # ========== [3] 按 seg 取记录 ==========
    print("\n[3] 索引的 seg 标签：每条都要能取回**它自己**")
    entries = CS.list_index(DATE)
    segs_seen = {e.get("seg") for e in entries}
    ok(segs_seen == {1, 2, None}, f"seg 标签覆盖两个分片与尾巴：{sorted(segs_seen, key=str)}")
    bad = []
    for e in entries:
        got = CS._Day(DATE).record_at(e["off"], e["len"], e.get("seg"))
        if got is None or got.get("id") != e.get("id"):
            bad.append(e.get("id"))
    ok(not bad, "30 条按 off/len/seg 逐条取回且 id 对得上", f"错的：{bad[:5]}")
    ok(CS.get_capture("req_0000005", DATE) is not None, "get_capture 能取到分片里的记录")
    ok(CS.get_capture("req_0000025", DATE) is not None, "get_capture 能取到尾巴里的记录")

    # ========== [4] 只剩分片的一天仍要可见 ==========
    print("\n[4] 尾巴为空时，这天不能从日期列表里消失")
    (root / f"{DATE}.jsonl").unlink()
    (root / f"{DATE}.idx.jsonl").unlink(missing_ok=True)
    CS._IDX_CACHE.clear()
    ok(DATE in CS.list_dates(), "只有分片的一天仍在日期列表里")
    ok(CS._Day(DATE).exists, "_Day.exists 认分片")
    ok(len(ids_via_index(DATE)) == 20, "读到两个分片的 20 条")
    write_tail(DATE, all_recs[20:30])          # 尾巴放回去，继续后面的用例
    CS._IDX_CACHE.clear()

    # ========== [5] 合并回单 pack，逐字节还原 ==========
    print("\n[5] 跨天合并：分片 + 尾巴 → 单 pack，且逐字节还原")
    ref = root / "reference.jsonl"             # 同样内容从头写一遍，当还原的比对基准
    with ref.open("wb") as f:
        for x in all_recs:
            f.write((json.dumps(x, ensure_ascii=False) + "\n").encode("utf-8"))
    m = CS.merge_segments(DATE)
    ok(m is not None and m["segments"] == 2, f"合并了 2 个分片：{m}")
    ok((root / f"{DATE}.pack").is_dir(), "单 pack 就位")
    ok(not CS._Day(DATE).segments, "分片已清")
    ok(not (root / f"{DATE}.jsonl").exists(), "尾巴已清")
    ok(CS._Day(DATE).is_pack, "形态回到单 pack（历史天的终态）")
    restored = root / "restored.jsonl"
    P.unpack(root / f"{DATE}.pack", restored)
    ok(restored.read_bytes() == ref.read_bytes(),
       "合并后 unpack 与原始录制**逐字节**一致")
    ok(ids_via_iter(DATE) == want, "合并后顺序仍是录制顺序")
    ok(m["count"] == 30, f"合并后条数 30：{m['count']}")

    # ========== [6] compact_date 对带分片的天要分流到合并 ==========
    print("\n[6] compact_date 遇到分片：分流到合并，不是报错")
    d2 = "2026-08-23"
    write_tail(d2, make_recs(8, start=100))
    CS.seal_tail(d2)
    write_tail(d2, make_recs(4, start=200))
    res = CS.compact_date(d2)
    ok(CS._Day(d2).is_pack, "compact_date 把带分片的天做成了单 pack")
    ok(res["count"] == 12, f"12 条都在：{res['count']}")
    ok("saved_bytes" in res and "ratio" in res, "返回形状与 compact_date 对齐（调用方不必分支）")

    # ========== [7] 切段失败要还原成"就像没切过" ==========
    print("\n[7] 压实失败 → 回退（这是最要命的一条：不能留下谁都读不到的录制）")
    d3 = "2026-08-22"
    write_tail(d3, make_recs(6, start=300))
    before_ids = ids_via_index(d3)
    before_bytes = (root / f"{d3}.jsonl").read_bytes()
    orig = P.write_pack

    def boom(*a, **k):
        raise P.PackError("disk_full", "自测注入的失败")

    P.write_pack = boom
    try:
        CS.seal_tail(d3)
        ok(False, "压实失败应该抛 StoreError")
    except CS.StoreError as e:
        ok(e.code == "disk_full", f"抛出原始 code：{e.code}")
    finally:
        P.write_pack = orig
    CS._IDX_CACHE.clear()
    ok((root / f"{d3}.jsonl").exists(), "尾巴还原回来了")
    ok((root / f"{d3}.jsonl").read_bytes() == before_bytes, "尾巴内容**逐字节**没变")
    ok(not CS._Day(d3).segments, "没有留下半拉分片")
    ok(ids_via_index(d3) == before_ids, "读取侧看到的记录与切段前完全一致")
    ok(not list(root.glob(f".{d3}.sealing.*")), "sealing 中转文件已清")

    # ========== [8] 断电残留：没压完的要并回，压完的才能删 ==========
    print("\n[8] 断电留下的 sealing 残留：靠哈希区分「并回」与「可删」")
    d4 = "2026-08-21"
    write_tail(d4, make_recs(5, start=400))
    stray = root / f".{d4}.sealing.120000.jsonl"
    (root / f"{d4}.jsonl").rename(stray)       # 模拟：改完名就断电
    write_tail(d4, make_recs(3, start=500))    # append 期间又写了新尾巴
    CS._IDX_CACHE.clear()
    ok(len(ids_via_index(d4)) == 3, "并回之前，sealing 里那 5 条确实读不到（所以不能删）")
    CS.cleanup_partials()
    CS._IDX_CACHE.clear()
    got = ids_via_index(d4)
    ok(len(got) == 8, f"并回后 8 条都在：{len(got)}")
    ok(got == [f"req_{i:07d}" for i in list(range(400, 405)) + list(range(500, 503))],
       "并回的顺序正确（sealing 那截在前，新尾巴在后）")
    ok(not list(root.glob(f".{d4}.sealing.*")), "残留已处理掉")

    d5 = "2026-08-20"
    write_tail(d5, make_recs(5, start=600))
    CS.seal_tail(d5)                            # 正常切段，分片就位
    seg1 = root / f"{d5}.p01.pack"
    src_hash = P.read_manifest(seg1)["raw_blake2b"]
    ghost = root / f".{d5}.sealing.130000.jsonl"
    # 造一个"内容已经在分片里"的残留：拿分片还原出来的字节，哈希必然与 manifest 相同
    P.unpack(seg1, ghost)
    ok(CS._file_blake2b(ghost) == src_hash, "构造的残留哈希与分片 manifest 对得上")
    n_before = len(ids_via_index(d5))
    CS.cleanup_partials()
    CS._IDX_CACHE.clear()
    ok(not ghost.exists(), "已压实的残留被删掉了")
    ok(len(ids_via_index(d5)) == n_before, "而且没有把那 5 条重复并进来一次")

    # ========== [9] 删除要覆盖分片 ==========
    print("\n[9] purge / retention 要把分片一起删干净")
    d6 = "2026-08-19"
    write_tail(d6, make_recs(6, start=700))
    CS.seal_tail(d6)
    write_tail(d6, make_recs(2, start=800))
    n = CS.purge_date(d6)
    ok(n == 8, f"报出删掉 8 条：{n}")
    ok(not list(root.glob(f"{d6}.p*{P.PACK_SUFFIX}")), "分片目录已删")
    ok(not (root / f"{d6}.jsonl").exists(), "尾巴已删")
    ok(not (root / f"{d6}.idx.jsonl").exists(), "索引已删")
    ok(d6 not in CS.list_dates(), "日期列表里也没了")

    # ========== [10] 阈值触发（走 append 真实热路径） ==========
    print("\n[10] 阈值触发：append 写过线就自己切")
    import time as _t
    d7 = CS.time.strftime("%Y-%m-%d", CS.time.localtime())
    CS.set_rolling(True, 20)                    # 20MB 是下限（_clamp_seg_mb）
    CS._ROLL_BYTES = 300 * 1024                 # 自测里直接压到 300KB，不然要写 20MB
    try:
        for rec in make_recs(40, start=900):
            CS.append(rec)
        for _ in range(100):                    # 切段在后台线程，等它落地
            if CS._Day(d7).segments and not CS._SEALING_NOW:
                break
            _t.sleep(0.05)
        day7 = CS._Day(d7)
        ok(bool(day7.segments), f"过线后自动切出了分片：{[d.name for d in day7.segments]}")
        ok(day7.count() == 40, f"40 条一条不少：{day7.count()}")
        ok(ids_via_iter(d7) == [f"req_{i:07d}" for i in range(900, 940)],
           "自动切段后顺序仍然正确")
    finally:
        CS.set_rolling(False)

    # ========== [11] 归档带分片的一天：不能只归尾巴那一截 ==========
    print("\n[11] 归档带分片的一天（归档默认删原录制，漏了就真没了）")
    d9 = "2026-08-17"
    write_tail(d9, make_recs(7, start=1100))
    CS.seal_tail(d9)                            # 前 7 条进分片
    write_tail(d9, make_recs(3, start=1200))    # 后 3 条留尾巴
    info = CS.archive_date(d9, keep=True)
    ok(info.get("count") == 10, f"归档里是 10 条而不是尾巴的 3 条：{info.get('count')}")
    CS.import_archive(info["path"], label="roundtrip")
    back = CS._Day(d9, "roundtrip")
    ok(back.count() == 10, f"导入回来还是 10 条：{back.count()}")
    ok([r["id"] for r in back.iter_records()]
       == [f"req_{i:07d}" for i in list(range(1100, 1107)) + list(range(1200, 1203))],
       "导入回来的顺序也对（分片那截在前）")
    ok(not list(root.glob(f".{d9}.archiving.*")), "归档的中转文件已清")
    CS.delete_source("roundtrip")

    # ========== [12] 关掉开关就真的不切 ==========
    print("\n[12] 开关关掉时不许切段")
    d8 = "2026-08-18"
    write_tail(d8, make_recs(4, start=1000))
    CS.set_rolling(False)
    CS._maybe_seal(d8, 999 * 1024 * 1024)       # 远超任何阈值
    ok(not CS._Day(d8).segments, "开关关着，过线也不切")


def main() -> None:
    try:
        run()
    except Exception:
        traceback.print_exc()
        FAILED.append("自测本身抛异常")
    finally:
        shutil.rmtree(_HOME, ignore_errors=True)
    print()
    if FAILED:
        print(f"[FAILED] {len(FAILED)} 条：")
        for f in FAILED:
            print("  -", f)
        sys.exit(1)
    print("[ALL PASSED] 滚动分片压实：切段 / 顺序 / 一致 / 回退 / 残留 / 合并 / 删除 全部通过 ✓")


if __name__ == "__main__":
    main()
