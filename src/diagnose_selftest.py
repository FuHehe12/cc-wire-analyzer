"""失败聚合自测：归并是否正确、该不该算失败、请求侧字段的单值/多值语义。

用法：uv run python src/diagnose_selftest.py

fixture 全部按**真流量的形状**复刻（CLAUDE.md 教训④）：上游错误存在
`error.body_snippet` 里、是被截断过的 JSON 原文字符串（不是解析好的 dict），
本地错误（连不上/超时）没有 body 只有 detail、`status` 为 None，
effort 在 `output_config.effort`、thinking 在 `thinking.type`——
这些形状都来自 2026-07 的实测录制，不是想象出来的。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as CFG  # noqa: E402
CFG.CONFIG_DIR = Path(tempfile.mkdtemp(prefix="ccwa_diag_"))

import classifier  # noqa: E402
import diagnose    # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        FAILED.append(name)


def rec(rid: str, ts: str, *, status=200, err=None, dec=None, model="claude-opus-5",
        effort=None, thinking=None, stream=True, max_tokens=64000, tools=0,
        session="s-1", sys_text="You are an interactive agent that helps users"):
    """造一条**真形状**的完整 record，再走 index_record（与生产同一条路径）。"""
    body = {
        "model": model, "max_tokens": max_tokens, "stream": stream,
        "messages": [{"role": "user", "content": "hi"}],
        "system": [{"type": "text",
                    "text": "x-anthropic-billing-header: cc_version=2.1.220.abc; cc_entrypoint=cli;"},
                   {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
                   {"type": "text", "text": sys_text}],
        "tools": [{"name": f"T{i}"} for i in range(tools)],
    }
    if effort is not None:
        body["output_config"] = {"effort": effort}
    if thinking is not None:
        body["thinking"] = {"type": thinking}
    resp = {"status": status, "content_blocks": [], "usage": {}} if status else None
    if resp is not None and dec:
        resp["decode_error"] = dec          # 真形状：解码失败写在 response 上（260801）
    r = {
        "id": rid, "ts_start": ts, "method": "POST", "path": "/v1/messages",
        "request": {"headers_safe": {"x-claude-code-session-id": session}, "body": body},
        "response": resp,
        "error": err,
    }
    return classifier.index_record(r)


def upstream_err(status: int, etype: str, msg: str) -> dict:
    """上游错误：真形状是 body_snippet 存**JSON 原文字符串**（可能被截断）。"""
    return {"kind": f"upstream_{status // 100}xx", "status": status,
            "body_snippet": json.dumps({"type": "error",
                                        "error": {"type": etype, "message": msg}})}


EFFORT_MSG = ("output_config.effort 'max' is not supported when thinking is disabled "
              "on this model. Use effort 'high' or below, or enable thinking.")

print(f"[setup] 索引 schema v{classifier.IDX_SCHEMA}\n")

# ---- 1. 成功请求不算失败 ----
print("[1] 什么算失败")
ok_recs = [rec("req_ok1", "2026-07-25T10:00:00.000"),
           rec("req_ok2", "2026-07-25T10:00:01.000", status=204)]
a = diagnose.aggregate(ok_recs)
check("2xx 不算失败", a["failures"] == 0, str(a["failures"]))
# 非 2xx 但没填 error（上游直接返回错误状态）
a = diagnose.aggregate([rec("req_e", "2026-07-25T10:00:02.000", status=500)])
check("非 2xx 即使无 error 记录也算失败", a["failures"] == 1)
# 本地错误：没有 status（连不上/超时），只有 error.detail
a = diagnose.aggregate([rec("req_t", "2026-07-25T10:00:03.000", status=None,
                            err={"kind": "timeout", "detail": "read timeout"})])
check("本地错误（status=None）也算失败", a["failures"] == 1)
check("本地错误取 detail 当消息",
      a["items"][0]["message"] == "read timeout", a["items"][0]["message"])

# 解码失败：上游 200、无 error 记录，但响应体没解开（260801 req_49f51e4 实例——
# gzip 流中段被截断，此前首页失败统计完全看不见）
a = diagnose.aggregate([rec("req_d", "2026-07-25T10:00:04.000",
                            dec="decompress_failed:gzip:EOFError")])
check("解码失败（200 无 error）也算失败", a["failures"] == 1)
check("解码失败单列 err_kind=decode_failed",
      a["items"][0]["err_kind"] == "decode_failed", a["items"][0]["err_kind"])
check("解码失败消息取 decode_error 原文",
      a["items"][0]["message"] == "decompress_failed:gzip:EOFError", a["items"][0]["message"])
# 同时有真 err_kind 时以真 err_kind 为准（解码失败往往是次生的，不能盖掉上游结论）
a = diagnose.aggregate([rec("req_d2", "2026-07-25T10:00:05.000", status=500,
                            err={"kind": "upstream_5xx", "status": 500,
                                 "body_snippet": '{"error":{"message":"boom"}}'},
                            dec="decompress_failed:gzip:EOFError")])
check("有真 err_kind 时 decode_error 不盖掉它",
      a["items"][0]["err_kind"] == "upstream_5xx", a["items"][0]["err_kind"])

# ---- 2. 归并：同因异 id/数字 → 一组 ----
print("\n[2] 归并（指纹归一）")
same = [
    rec("req_a1", "2026-07-25T11:00:00.000", status=400, effort="max", thinking="disabled",
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
    rec("req_a2", "2026-07-25T11:05:00.000", status=400, effort="max", thinking="disabled",
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
    rec("req_a3", "2026-07-25T11:09:00.000", status=400, effort="max", thinking="disabled",
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
]
a = diagnose.aggregate(same)
check("3 条同因 → 1 组", a["groups"] == 1, str(a["groups"]))
g = a["items"][0]
check("count=3", g["count"] == 3)
check("时间跨度取首末", g["first_ts"].endswith("11:00:00.000") and g["last_ts"].endswith("11:09:00.000"),
      f'{g["first_ts"]} → {g["last_ts"]}')
check("样本 id 有界（≤3）", len(g["samples"]) <= diagnose.SAMPLES_PER_GROUP)
check("从 body_snippet 的 JSON 里取出 message",
      g["message"].startswith("output_config.effort 'max'"), g["message"][:50])

# 消息里带不同 request-id / 不同数字 → 仍应归并（指纹归一抹掉可变部分）
varied = [
    rec("req_v1", "2026-07-25T12:00:00.000", status=429,
        err=upstream_err(429, "rate_limit_error", "rate limited, retry after 1234 ms (req_abc1234)")),
    rec("req_v2", "2026-07-25T12:01:00.000", status=429,
        err=upstream_err(429, "rate_limit_error", "rate limited, retry after 9876 ms (req_zzz9999)")),
]
a = diagnose.aggregate(varied)
check("变动的 id/数字被归一 → 仍 1 组", a["groups"] == 1, str(a["groups"]))

# 不同原因不能被合并
a = diagnose.aggregate(same + varied)
check("不同原因保持分组", a["groups"] == 2, str(a["groups"]))
check("按 count 降序", a["items"][0]["count"] >= a["items"][1]["count"])

# ---- 3. req_fields 单值 vs 多值（诊断语义的关键）----
print("\n[3] 请求侧字段：单值 = 一致，列表 = 跨值")
g = diagnose.aggregate(same)["items"][0]
check("组内一致 → 单值 effort=max", g["req_fields"]["effort"] == "max", str(g["req_fields"]["effort"]))
check("组内一致 → 单值 thinking=disabled", g["req_fields"]["thinking"] == "disabled")
mixed = [
    rec("req_m1", "2026-07-25T13:00:00.000", status=504, model="glm-5.2", tools=71,
        err={"kind": "upstream_5xx", "status": 504, "body_snippet": '{"error": "upstream_timeout"}'}),
    rec("req_m2", "2026-07-25T13:00:10.000", status=504, model="glm-5v-turbo", tools=0,
        err={"kind": "upstream_5xx", "status": 504, "body_snippet": '{"error": "upstream_timeout"}'}),
]
g = diagnose.aggregate(mixed)["items"][0]
check("跨值 → 列表 model", isinstance(g["req_fields"]["model"], list),
      str(g["req_fields"]["model"]))
check("跨值 → 列表 tools_n", isinstance(g["req_fields"]["tools_n"], list),
      str(g["req_fields"]["tools_n"]))
check("非 JSON 的 body_snippet 退回原文",
      "upstream_timeout" in g["message"], g["message"][:60])

# ---- 4. kinds / sessions 归属 ----
print("\n[4] kind 与会话归属")
grp = diagnose.aggregate([
    rec("req_k1", "2026-07-25T14:00:00.000", status=400, session="sess-A",
        sys_text="Generate a concise, sentence-case title for this coding session",
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
    rec("req_k2", "2026-07-25T14:00:01.000", status=400, session="sess-B", tools=50,
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
])["items"][0]
check("kinds 按 kind 计数", grp["kinds"].get("title") == 1 and grp["kinds"].get("main") == 1,
      str(grp["kinds"]))
check("sessions 去重计数", grp["sessions"] == 2, str(grp["sessions"]))

# ---- 5. 输出有界（安全不变量 7）----
print("\n[5] 输出有界")
many = []
for i in range(30):
    many.append(rec(f"req_x{i}", f"2026-07-25T15:{i:02d}:00.000", status=400,
                    err=upstream_err(400, "invalid_request_error", f"distinct failure kind {chr(65+i)}")))
a = diagnose.aggregate(many, limit=5)
check("limit 生效", len(a["items"]) == 5, str(len(a["items"])))
check("truncated 如实标注", a["truncated"] is True)
check("groups 报告真实组数（不被 limit 掩盖）", a["groups"] == 30, str(a["groups"]))
a = diagnose.aggregate(many, limit=100)
check("未截断时 truncated=False", a["truncated"] is False)

# ---- 6. 健壮性 ----
print("\n[6] 健壮性")
check("空输入不崩", diagnose.aggregate([])["failures"] == 0)
weird = rec("req_w", "2026-07-25T16:00:00.000", status=400, err={"kind": "upstream_4xx"})
check("error 无 body/detail 也不崩", diagnose.aggregate([weird])["failures"] == 1)
truncated_json = rec("req_tr", "2026-07-25T16:01:00.000", status=400,
                     err={"kind": "upstream_4xx", "status": 400,
                          "body_snippet": '{"type":"error","error":{"type":"invalid_req'})
a = diagnose.aggregate([truncated_json])
check("被截断的 JSON 片段不崩（退回原文）", a["failures"] == 1 and bool(a["items"][0]["message"]))

print("\n" + "=" * 46)
if FAILED:
    print(f"[FAILED] {len(FAILED)} 项：{FAILED}")
else:
    print("[ALL PASSED] 失败聚合：归并 / 失败判定 / 字段语义 / 有界 / 健壮性 验证通过")
