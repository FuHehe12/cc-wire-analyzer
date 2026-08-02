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
        session="s-1", sys_text="You are an interactive agent that helps users",
        host="api.anthropic.com", cc_version="2.1.220"):
    """造一条**真形状**的完整 record，再走 index_record（与生产同一条路径）。
    host/cc_version 写进 upstream + user-agent，让 _host_of/_cc_version 真跑（260802）。"""
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
        "upstream": f"https://{host}/v1/messages",
        "request": {"headers_safe": {
            "x-claude-code-session-id": session,
            "user-agent": (f"claude-cli/{cc_version}" if cc_version else "claude-cli/"),
        }, "body": body},
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

# ---- 7. 跨天归并 ----
print("\n[7] 跨天归并")
recs_3day = {
    "2026-07-25": [rec("req_d1a", "2026-07-25T10:00:00.000", status=429,
                       err=upstream_err(429, "rate_limit_error", "rate limited, retry after 1234 ms (req_aaa111)"))],
    "2026-07-26": [rec("req_d1b", "2026-07-26T11:00:00.000", status=429,
                       err=upstream_err(429, "rate_limit_error", "rate limited, retry after 5678 ms (req_bbb222)"))],
    "2026-07-27": [rec("req_d1c", "2026-07-27T12:00:00.000", status=429,
                       err=upstream_err(429, "rate_limit_error", "rate limited, retry after 9012 ms (req_ccc333)"))],
}
# 注意：消息里的数字必须 ≥4 位、id ≥6 位才会被 _fingerprint 归一抹掉（_NORM 用 \b\d{4,}\b
# 与 req_[A-Za-z0-9]{6,}，故意不抹 3 位数字以免误伤状态码/版本号）——否则同因失败会被
# 算成不同指纹、跨天合并失败。这也是「测试数据要符合归一规则」的一例（教训 ④ 同源）。
t = diagnose.trends(recs_3day)
check("同键跨3天 → 1 组", t["totals"]["all_groups"] == 1, str(t["totals"]["all_groups"]))
g = t["items"][0]
check("count=跨天总和(3)", g["count"] == 3, str(g["count"]))
check("days_span=3", g["days_span"] == 3, str(g["days_span"]))
check("per_day 仅活跃天 + 数值正确",
      g["per_day"] == {"2026-07-25": 1, "2026-07-26": 1, "2026-07-27": 1}, str(g["per_day"]))
check("first_seen/last_seen 跨天首末",
      g["first_seen"].startswith("2026-07-25") and g["last_seen"].startswith("2026-07-27"),
      f'{g["first_seen"]} → {g["last_seen"]}')
check("cross_day_groups=1", t["totals"]["cross_day_groups"] == 1, str(t["totals"]["cross_day_groups"]))
recs_2kind = {
    "2026-07-25": [
        rec("req_x1", "2026-07-25T10:00:00.000", status=429,
            err=upstream_err(429, "rate_limit_error", "rate limited A")),
        rec("req_x2", "2026-07-25T10:01:00.000", status=500,
            err=upstream_err(500, "api_error", "server error B")),
    ],
    "2026-07-26": [rec("req_x3", "2026-07-26T10:00:00.000", status=429,
                       err=upstream_err(429, "rate_limit_error", "rate limited A"))],
}
check("不同键跨天保持分组",
      diagnose.trends(recs_2kind)["totals"]["all_groups"] == 2)

# ---- 8. 趋势标记（_trend）----
print("\n[8] 趋势标记（_trend）")
check("单天少量 → sporadic", diagnose._trend({"2026-07-25": 5}) == "sporadic")
# 260802：单天爆发与单天零星分家。此前两者都叫 sporadic，于是一天 2650 次的真事故
# 顶着"零星"标签排在一个 5 次的组之下——对只读 trend 的 agent 是反向指示。
check("单天爆发 → burst", diagnose._trend({"2026-07-25": 100}) == "burst")
check("burst 阈值边界（=50 算爆发）",
      diagnose._trend({"2026-07-25": diagnose.BURST_MIN}) == "burst")
check("burst 阈值边界（49 仍零星）",
      diagnose._trend({"2026-07-25": diagnose.BURST_MIN - 1}) == "sporadic")
check("5天各1 → recurring",
      diagnose._trend({f"2026-07-{20+i}": 1 for i in range(5)}) == "recurring")
check("3天 19/5/2 → declining",
      diagnose._trend({"2026-07-25": 19, "2026-07-26": 5, "2026-07-27": 2}) == "declining")
check("2天 1/3 → rising", diagnose._trend({"2026-07-25": 1, "2026-07-26": 3}) == "rising")
check("2天 3/1 → declining", diagnose._trend({"2026-07-25": 3, "2026-07-26": 1}) == "declining")
check("2天 1/1 → recurring", diagnose._trend({"2026-07-25": 1, "2026-07-26": 1}) == "recurring")
check("3天 10/1/10 中间弃 → recurring",
      diagnose._trend({"2026-07-25": 10, "2026-07-26": 1, "2026-07-27": 10}) == "recurring")

# ---- 9. 跨天有界 ----
print("\n[9] 跨天有界")
big = {}
for i in range(30):
    d = f"2026-07-{(i % 3) + 25:02d}"   # 跨 07-25/26/27 三天
    big.setdefault(d, []).append(rec(f"req_b{i}", f"{d}T10:{i:02d}:00.000", status=400,
        err=upstream_err(400, "invalid_request_error", f"distinct kind {chr(65 + i)}")))
t = diagnose.trends(big, limit=5)
check("limit 生效", len(t["items"]) == 5, str(len(t["items"])))
check("truncated 如实标注", t["truncated"] is True)
check("all_groups 报真实组数（不被 limit 掩盖）",
      t["totals"]["all_groups"] == 30, str(t["totals"]["all_groups"]))
check("未截断 truncated=False", diagnose.trends(big, limit=100)["truncated"] is False)

# ---- 10. by_host / by_model / by_cc_version 维度 ----
print("\n[10] by_host / by_model / by_cc_version 维度")
multi = {
    "2026-07-25": [
        rec("req_h1", "2026-07-25T10:00:00.000", status=504, model="glm-5.2",
            host="open.bigmodel.cn", cc_version="2.1.220",
            err={"kind": "upstream_5xx", "status": 504, "body_snippet": '{"error":"timeout"}'}),
        rec("req_h2", "2026-07-25T10:01:00.000", status=504, model="claude-opus-5",
            host="api.anthropic.com", cc_version="2.1.219",
            err={"kind": "upstream_5xx", "status": 504, "body_snippet": '{"error":"timeout"}'}),
    ],
}
t = diagnose.trends(multi)
check("by_host 全局切片", len(t["by_host"]) == 2 and t["by_host"][0]["count"] >= 1, str(t["by_host"]))
check("by_model 全局切片", len(t["by_model"]) == 2, str(t["by_model"]))
check("by_cc_version 全局切片", len(t["by_cc_version"]) == 2, str(t["by_cc_version"]))
g = t["items"][0]
check("组内 by_host 出现", isinstance(g["by_host"], dict) and len(g["by_host"]) >= 1, str(g["by_host"]))
check("req_fields host 出现", g["req_fields"].get("host") is not None, str(g["req_fields"].get("host")))
check("req_fields cc_version 出现（跨值→列表）",
      isinstance(g["req_fields"].get("cc_version"), list), str(g["req_fields"].get("cc_version")))
check("缺版本 → by_cc_version 空",
      diagnose.trends({"2026-07-25": [rec("req_nv", "2026-07-25T10:00:00.000", status=500,
                                          cc_version="", err=upstream_err(500, "api_error", "boom"))]}
                     )["by_cc_version"] == [])

# ---- 11. model / kind 过滤 ----
print("\n[11] model / kind 过滤")
recs_filt = {
    "2026-07-25": [
        rec("req_f1", "2026-07-25T10:00:00.000", status=400, model="glm-5.2",
            err=upstream_err(400, "invalid_request_error", "err A")),
        rec("req_f2", "2026-07-25T10:01:00.000", status=400, model="claude-opus-5",
            err=upstream_err(400, "invalid_request_error", "err A")),
    ],
}
t = diagnose.trends(recs_filt, model="glm-5.2")
check("model 过滤：records 只数该 model", t["totals"]["records"] == 1, str(t["totals"]["records"]))
check("model 过滤：failures 只数该 model", t["totals"]["failures"] == 1, str(t["totals"]["failures"]))
check("model 过滤：by_model 只剩该 model",
      len(t["by_model"]) == 1 and t["by_model"][0]["value"] == "glm-5.2", str(t["by_model"]))
recs_title = {
    "2026-07-25": [
        rec("req_t1", "2026-07-25T10:00:00.000", status=400,
            sys_text="Generate a concise, sentence-case title for this coding session",
            err=upstream_err(400, "invalid_request_error", "title err")),
        rec("req_t2", "2026-07-25T10:01:00.000", status=400,
            err=upstream_err(400, "invalid_request_error", "main err")),
    ],
}
check("kind 过滤 title 只剩 title 失败",
      diagnose.trends(recs_title, kind="title")["totals"]["failures"] == 1)

# ---- 12. 空天 / 缺天 ----
print("\n[12] 空天 / 缺天")
check("空 dict 不崩", diagnose.trends({})["totals"]["records"] == 0)
check("全空天不崩", diagnose.trends({"2026-07-25": []})["totals"]["failures"] == 0)
recs_empty = {"2026-07-25": [],
              "2026-07-26": [rec("req_e1", "2026-07-26T10:00:00.000", status=500,
                                 err=upstream_err(500, "api_error", "boom"))]}
t = diagnose.trends(recs_empty)
check("空天 records=0 记 0 不崩",
      any(pd["date"] == "2026-07-25" and pd["records"] == 0 for pd in t["per_day"]), str(t["per_day"]))

# ---- 13. span=1 退化对齐单天 ----
print("\n[13] 单天退化对齐 aggregate")
one_day = {"2026-07-25": [
    rec("req_s1", "2026-07-25T10:00:00.000", status=400, effort="max", thinking="disabled",
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
    rec("req_s2", "2026-07-25T10:01:00.000", status=400, effort="max", thinking="disabled",
        err=upstream_err(400, "invalid_request_error", EFFORT_MSG)),
]}
t = diagnose.trends(one_day)
a = diagnose.aggregate(one_day["2026-07-25"])
check("span=1 组数与 aggregate 一致", t["totals"]["all_groups"] == a["groups"], str(t["totals"]["all_groups"]))
check("span=1 首组 count 与 aggregate 一致", t["items"][0]["count"] == a["items"][0]["count"])
check("单天 trend 全 sporadic", all(it["trend"] == "sporadic" for it in t["items"]))

# ---- 14. 退化消息 / 新鲜度 / 回环 host（260802 复查修正）----
print("\n[14] 退化消息 / 新鲜度 / 回环 host")
check("'Error' 判为退化", diagnose._is_degenerate("Error"))
check("'timeout' 判为退化", diagnose._is_degenerate("timeout"))
check("空串判为退化", diagnose._is_degenerate(""))
check("有信息量的消息不算退化", not diagnose._is_degenerate(EFFORT_MSG))
# 上游只回一个 'Error' 时，不同供应商的失败此前会并成一个没有诊断价值的垃圾桶组，
# 还因为跨天出现被排到最前。现在按 host 拆开。
recs_degen = {
    "2026-07-25": [rec("req_g1", "2026-07-25T10:00:00.000", status=500, host="open.bigmodel.cn",
                       err={"kind": "upstream_5xx", "status": 500, "body_snippet": "Error"})],
    "2026-07-26": [rec("req_g2", "2026-07-26T10:00:00.000", status=500, host="api.anthropic.com",
                       err={"kind": "upstream_5xx", "status": 500, "body_snippet": "Error"})],
}
t = diagnose.trends(recs_degen)
check("退化消息按 host 拆组", t["totals"]["all_groups"] == 2, str(t["totals"]["all_groups"]))
check("退化组标 degenerate=True", all(it["degenerate"] for it in t["items"]))
check("有信息量的组 degenerate=False",
      diagnose.trends(one_day)["items"][0]["degenerate"] is False)
# 新鲜度与趋势正交：形状平（recurring）但两周没再发生的组要能被认出来。
recs_stale = {f"2026-07-{20 + i}": [rec(f"req_st{i}", f"2026-07-{20 + i}T10:00:00.000", status=500,
                                        err=upstream_err(500, "api_error", "stale boom"))]
              for i in range(5)}
recs_stale["2026-08-02"] = []          # 窗口末日无该失败
t = diagnose.trends(recs_stale)
g = t["items"][0]
check("trend 仍按形状给 recurring", g["trend"] == "recurring", g["trend"])
check("days_since_last 以窗口末日为基准", g["days_since_last"] == 9, str(g["days_since_last"]))
check("stale=True（已经不在发生）", g["stale"] is True)
check("刚发生过的组 stale=False", diagnose.trends(one_day)["items"][0]["stale"] is False)
# 本机回环不是供应商：BASE_URL 自指的失败风暴会把真实供应商分布淹没（实测占 95%）。
recs_loop = {"2026-07-25": [
    rec("req_lo", "2026-07-25T10:00:00.000", status=504, host="127.0.0.1:5051",
        err=upstream_err(504, "api_error", "upstream timeout self")),
    rec("req_up", "2026-07-25T10:01:00.000", status=504, host="api.anthropic.com",
        err=upstream_err(504, "api_error", "upstream timeout self")),
]}
t = diagnose.trends(recs_loop)
check("回环 host 不进 by_host",
      [x["value"] for x in t["by_host"]] == ["api.anthropic.com"], str(t["by_host"]))
check("回环 host 单列 by_local_loopback",
      [x["value"] for x in t["by_local_loopback"]] == ["127.0.0.1:5051"],
      str(t["by_local_loopback"]))
check("localhost/::1 也算回环",
      diagnose._is_loopback("localhost:8080") and diagnose._is_loopback("::1"))
# 日期列表：route 与 CLI 共用，别两边各算一份。
import datetime as _dt
sd = diagnose.span_dates(3, today=_dt.date(2026, 8, 2))
check("span_dates 升序含今天",
      sd == ["2026-07-31", "2026-08-01", "2026-08-02"], str(sd))
check("span_dates 至少一天", len(diagnose.span_dates(0)) == 1)

print("\n" + "=" * 46)
if FAILED:
    print(f"[FAILED] {len(FAILED)} 项：{FAILED}")
else:
    print("[ALL PASSED] 失败聚合：归并 / 失败判定 / 字段语义 / 有界 / 健壮性 验证通过")
