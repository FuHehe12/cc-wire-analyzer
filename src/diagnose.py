"""失败聚合：把一天里所有失败请求按「上游到底在抱怨什么」归并，供 agent 直接诊断。

为什么需要它（见 issues/open/260725_录制驱动的问题诊断.md）：
录制里的失败响应**不是噪声，是已经被上游诊断过一次的问题报告**——上游明确说了哪个字段不对、
该改成什么。但本工具此前只把它们画成红卡等人去看，而人不会去看：一条
「effort 'max' is not supported when thinking is disabled」在时序图里挂了好几天，
是维护者为别的事截图才偶然撞见的，而它意味着用户的会话标题功能一直在静默失效。

所以这里做两件事，都是为了让 agent 一次调用就能下结论：

1. **按错误消息指纹归并**。一天可以有几千个错误（实测某天 2029 个错误节点），原样吐出去
   一条就能塞满上下文（「CLI 输出必须有界」是既有安全不变量 7）。归并要按 message 而不是
   按 status —— 400 有很多种，混在一起没有诊断价值。
2. **同时摆出请求侧的相关字段**（model / effort / thinking / stream / max_tokens / tools 数）。
   只给错误消息，agent 还得回头翻原始 record 才知道这个请求的 effort 是什么；把两边并排放，
   「effort=max + thinking=disabled → 400」这种因果一眼就能对上。

本模块只整理数据，**不做分析、不调 LLM**。分析交给外面的 CC/agent —— 那是它们擅长的，
也符合本项目「人看 GUI、AI 走 CLI/API」的定位。
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

import classifier

# 指纹归一：把消息里随请求变化的部分抹掉，否则同一个问题会碎成上千组。
#
# 顺序有意义，别随意调换：长 hex 必须排在 `\d{4,}` 之前，否则纯数字前缀会先被吃成 `<n>`，
# 剩下的半截 hex 再也匹配不上。
_NORM = (
    (re.compile(r"req_[A-Za-z0-9]{6,}"), "<request-id>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<uuid>"),
    # 通用长 hex 标识符（260807 运行分析发现）。智谱网关的请求 id 形如
    # `20260802082259ad76fffd275f413f`——30 位无分隔十六进制，上面两条都不匹配：
    # 它没有 `req_` 前缀，也没有 UUID 的连字符分段。而**下面那条 `\b\d{4,}\b` 同样够不着**，
    # 因为 `20260802082259` 后面紧跟着 `a`，数字与字母之间不存在词边界。
    # 后果不是难看：16 个碎片（每组 count=1）挤占 `--limit` 配额，把真正的跨天模式挤出视野
    # ——**错误越多、碎得越碎、越看不见重点**，聚合功能在最需要它的时候失效。
    # 阈值取 16 位：短 hex 可能是有诊断意义的值（错误码、掩码），16 位以上的纯 hex 串
    # 在错误消息里几乎必然是标识符。**误合并的代价远小于误拆分**——并错了组还看得见，
    # 碎成 16 组就直接看不见了。
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hex-id>"),
    (re.compile(r"\b\d{4,}\b"), "<n>"),          # token 数、字节数、行号这类大数字
)
SAMPLES_PER_GROUP = 3        # 每组最多留几个代表样本 id
DEFAULT_LIMIT = 20           # 默认最多回几组（输出有界）


# 退化消息：上游只回一个空洞的词（或干脆空串）。这类消息不足以定义一个"问题"——
# 任何供应商、任何原因的失败都会并进同一组，组的 count/trend 都没有诊断价值，
# 而它还会因为跨天出现被排到最前（实测：`Error` 5 次散在两周里，排在一天 2650 次的
# 真事故之上）。跨天归并时给这类组补 host，至少让"智谱回的 Error"和"官方回的 Error"分开。
_DEGENERATE_WORDS = {"error", "timeout", "failed", "failure", "unknown", "exception", ""}
_DEGENERATE_MAX_LEN = 12


def _fingerprint(msg: str) -> str:
    norm = msg
    for pat, rep in _NORM:
        norm = pat.sub(rep, norm)
    return norm.strip()[:200]


def _is_degenerate(fp: str) -> bool:
    """这个指纹是否空洞到不足以单独定义一组。"""
    s = fp.strip().strip(".:;!。：；").lower()
    return s in _DEGENERATE_WORDS or len(s) < _DEGENERATE_MAX_LEN


def _req_fields(idx: dict) -> dict:
    """请求侧的诊断相关字段。全是小标量，安全可直接给 agent。"""
    return {
        "model": idx.get("model"),
        "effort": idx.get("effort"),
        "thinking": idx.get("thinking"),
        "stream": idx.get("stream"),
        "max_tokens": idx.get("max_tokens"),
        "tools_n": idx.get("tools_n"),
        "host": idx.get("host"),
        "cc_version": idx.get("cc_version"),
    }


def _is_failure(idx: dict) -> bool:
    """失败 = 有错误记录，或 HTTP 状态非 2xx，或响应体没解开。三个条件都要看：
    本地错误（连不上/超时）没有 status，上游 4xx/5xx 则可能没填 error，
    而解码失败**两者都不是**——上游 200、转发无异常，但正文丢了（260801）。"""
    if idx.get("has_error") or idx.get("decode_error"):
        return True
    st = idx.get("status")
    return isinstance(st, int) and not (200 <= st < 300)


def _kind_and_msg(idx: dict) -> tuple:
    """(err_kind, err_msg)。解码失败单列一类，**不并进上游的 err_kind**——
    「上游拒绝了我们」和「我们没解开上游的回答」是两个完全不同的结论，混在一组里
    会让「上游健康度」这个判断失真。有真 err_kind 时以它为准（解码失败往往是次生的）。"""
    kind = idx.get("err_kind") or ""
    msg = idx.get("err_msg") or ""
    dec = idx.get("decode_error") or ""
    if dec and not kind:
        return "decode_failed", dec
    return kind, msg


def aggregate(records: list[dict], limit: int = DEFAULT_LIMIT) -> dict:
    """索引记录（capture_store.list_index 提供）→ 失败分组，按出现次数降序。

    分组键 = (err_kind, status, 消息指纹)。同一组里请求侧字段若不一致，`req_fields` 记下
    出现过的值集合——「同一个错误在不同 effort 下都出现」和「只在某个 effort 下出现」
    是完全不同的诊断结论，不能被合并掉。
    """
    total = len(records)
    failures = [r for r in records if _is_failure(r)]
    groups: dict[tuple, dict] = {}
    for r in failures:
        kind, msg = _kind_and_msg(r)
        fp = _fingerprint(msg)
        key = (kind, r.get("status"), fp)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "err_kind": kind,
                "status": r.get("status"),
                "message": msg[:300],
                "fingerprint": hashlib.md5(fp.encode("utf-8", "replace")).hexdigest()[:8],
                "count": 0,
                "first_ts": r.get("ts_start"),
                "last_ts": r.get("ts_start"),
                "kinds": {},
                "sessions": set(),
                "samples": [],
                "req_fields": {k: set() for k in _req_fields(r)},
            }
        g["count"] += 1
        ts = r.get("ts_start") or ""
        if ts and (not g["first_ts"] or ts < g["first_ts"]):
            g["first_ts"] = ts
        if ts and (not g["last_ts"] or ts > g["last_ts"]):
            g["last_ts"] = ts
        kind = classifier.classify_idx(r)
        g["kinds"][kind] = g["kinds"].get(kind, 0) + 1
        if r.get("session_id"):
            g["sessions"].add(r["session_id"])
        if len(g["samples"]) < SAMPLES_PER_GROUP:
            g["samples"].append(r.get("id"))
        for k, v in _req_fields(r).items():
            g["req_fields"][k].add(v)

    out = []
    for g in sorted(groups.values(), key=lambda x: -x["count"]):
        rf = {}
        for k, vals in g["req_fields"].items():
            vs = [v for v in vals if v is not None]
            rf[k] = (vs[0] if len(vs) == 1 else (sorted(vs, key=str) if vs else None))
        out.append({**g, "req_fields": rf, "sessions": len(g["sessions"]),
                    "kinds": dict(sorted(g["kinds"].items(), key=lambda kv: -kv[1]))})
    truncated = len(out) > limit
    return {
        "ok": True,                      # 与其他 CLI/API 输出一致（260803：此前唯独 errors 缺）
        "total_records": total,
        "failures": len(failures),
        "groups": len(out),
        "truncated": truncated,          # 契约：给 AI 的输出一律标注是否被截断
        "items": out[:limit],
        "note": ("Failures grouped by upstream error message (ids/numbers normalized). "
                 "req_fields shows the request side of each group — a list means the group "
                 "spans several values, which usually decides whether a field is the cause."),
    }


# ===== 跨天趋势（/api/diagnose/trends）=====
DEFAULT_TRENDS_LIMIT = 20      # 跨天组输出上限（route 又 clamp 到 ≤50）
DEFAULT_SPAN = 7               # 默认看最近几天（route 与 CLI 共用）
BURST_MIN = 50                 # 单日多少次算"爆发"而不是"零星"
STALE_DAYS = 3                 # 最后一次距窗口末日多少天算"已经不在发生了"


def _trend(per_day: dict) -> str:
    """活跃天 per_day{date:count}（仅活跃天，count≥1）→ 趋势标记。

    单天：count ≥ BURST_MIN → **burst**（一天内爆发＝事故），否则 sporadic（真·零星）。
    这两个此前混在一个 sporadic 里，于是窗口内最大的一次事故（一天 2650 次失败，占窗口
    失败总数 94%）顶着"零星"这个标签，对只读 trend 字段的 agent 是反向指示。

    多天：按活跃天对称二分的首尾比：mid=n//2（奇数个活跃天中间那个不算），
    ratio=后半/前半；≥1.5 rising、≤0.5 declining、否则 recurring。活跃天 count 恒 ≥1
    故前半非空、不除零。

    ⚠️ 趋势只描述**形状**，不描述新鲜度——一个两周前就停了的组，只要计数是平的，仍然
    标 recurring。新鲜度是正交维度，见每组的 days_since_last / stale（塞进同一个枚举会
    组合爆炸：rising-stale? declining-fresh?）。

    实测验证：quota_probe 429（5天各1次）→recurring；SSL 超时（3天 19/5/2）→declining；
    2天 [1,3]→rising、[3,1]→declining、[1,1]→recurring；upstream_timeout（1天 2650）→burst。"""
    days = sorted(per_day.keys())
    n = len(days)
    if n <= 1:
        return "burst" if (sum(per_day.values()) >= BURST_MIN) else "sporadic"
    mid = n // 2
    first = sum(per_day[d] for d in days[:mid])
    second = sum(per_day[d] for d in days[n - mid:])
    ratio = second / first          # first ≥ 1（活跃天 count≥1，前半非空）
    if ratio >= 1.5:
        return "rising"
    if ratio <= 0.5:
        return "declining"
    return "recurring"


def _matches(idx: dict, model: str | None, kind: str | None,
             r_kind: str | None = None) -> bool:
    """过滤：model 精确等值（None=不过滤）；kind 精确等值。r_kind 为调用方预算好的
    classify_idx 结果（避免 _matches 内部二次分类）。两个过滤 AND。"""
    if model is not None and (idx.get("model") or "") != model:
        return False
    if kind is not None and (r_kind or "") != kind:
        return False
    return True


def _norm_req_fields(vals_by_key: dict) -> dict:
    """请求侧字段集合 → 单值/列表归一（与 aggregate 行 124-129 同款）：组内一致→单值；
    跨值→排序列表；全 None→该键值 None。抽出来给 trends 复用。"""
    out = {}
    for k, vals in vals_by_key.items():
        vs = [v for v in vals if v is not None]
        out[k] = (vs[0] if len(vs) == 1 else (sorted(vs, key=str) if vs else None))
    return out


def _dims_to_list(counter: Counter) -> list:
    """Counter → [{value, count}, ...] count 降序。维度切片的统一输出形。"""
    return [{"value": v, "count": n} for v, n in counter.most_common()]


def _is_loopback(host: str) -> bool:
    """本机回环 host。它不是"路由供应商"——出现在这里通常意味着 BASE_URL 自指
    （代理转发给自己，doctor 的 self_reference 规则管这个）或指向另一个本地网关。
    实测一天的自指事故能占到窗口失败总数的 95%，混进 by_host 会把真实供应商分布彻底淹没。"""
    h = (host or "").strip().lower()
    if h.startswith("["):            # [::1]:5051 —— IPv6 带端口
        h = h[1:].split("]")[0]
    elif h.count(":") == 1:          # host:port（裸 IPv6 有多个冒号，别在这里切）
        h = h.split(":")[0]
    return h in ("localhost", "::1", "0.0.0.0") or h.startswith("127.")


def span_dates(span: int = DEFAULT_SPAN, today=None) -> list[str]:
    """最近 span 天的日期列表（升序，含今天）。route 与 CLI 共用——两边各算一份日期
    正是 stats 漏 cache_creation 那类分叉的温床。"""
    import datetime
    today = today or datetime.date.today()
    return [(today - datetime.timedelta(days=i)).isoformat()
            for i in range(max(1, span))][::-1]


def _new_group(r: dict, ek: str, msg: str, fp: str, degenerate: bool) -> dict:
    """一个跨天组的初始形状。字段分三组：身份（err_kind/status/message/fingerprint/degenerate）、
    累积量（count/per_day/days/kinds/sessions/samples）、维度（req_fields/by_*）。"""
    return {
        "err_kind": ek,
        "status": r.get("status"),
        "message": msg[:300],
        "fingerprint": hashlib.md5(fp.encode("utf-8", "replace")).hexdigest()[:8],
        "degenerate": degenerate,
        "count": 0,
        "first_ts": r.get("ts_start"),
        "last_ts": r.get("ts_start"),
        "per_day": Counter(),
        "days": set(),
        "kinds": {},
        "sessions": set(),
        "samples": [],
        "req_fields": {k: set() for k in _req_fields(r)},
        "by_host": Counter(),
        "by_model": Counter(),
        "by_cc_version": Counter(),
    }


def _accumulate(g: dict, r: dict, d: str, r_kind: str) -> None:
    """把一条失败记录并进它所属的跨天组。纯累积，与日期循环 / 序列化无耦合——
    260802 从 `trends` 抽出：那个函数在几轮迭代里长到 160 行，而这 30 行是其中唯一
    与「跨天」无关的部分。"""
    g["count"] += 1
    g["per_day"][d] += 1
    g["days"].add(d)
    ts = r.get("ts_start") or ""
    if ts and (not g["first_ts"] or ts < g["first_ts"]):
        g["first_ts"] = ts
    if ts and (not g["last_ts"] or ts > g["last_ts"]):
        g["last_ts"] = ts
    g["kinds"][r_kind] = g["kinds"].get(r_kind, 0) + 1
    if r.get("session_id"):
        g["sessions"].add(r["session_id"])
    if len(g["samples"]) < SAMPLES_PER_GROUP:
        g["samples"].append(r.get("id"))
    for k, v in _req_fields(r).items():
        g["req_fields"][k].add(v)
    for field, counter in (("host", g["by_host"]), ("model", g["by_model"]),
                           ("cc_version", g["by_cc_version"])):
        if r.get(field):
            counter[r[field]] += 1


def trends(records_by_date: dict, model: str | None = None,
           kind: str | None = None, limit: int = DEFAULT_TRENDS_LIMIT) -> dict:
    """{date: [idx records]} → 三层（每日曲线 / 跨天归并组 / 维度切片）。

    单天看 aggregate()；这里回答「今天的失败是新发还是老毛病复发 / 趋势如何 / 集中哪个供应商
    与 CC 版本」。跨天归并键复用单天 (err_kind, status, fingerprint)，不重新指纹。趋势判据
    见 _trend()。diagnose 只读、不调 LLM；输出有界 + truncated。

    route 侧负责按 span 算日期列表 + 循环 list_index，本函数只做纯归并。
    records/failures/per_day 在给定 model/kind 过滤后统计（无过滤 = 全部）。
    """
    dates = sorted(records_by_date.keys())
    per_day: list[dict] = []
    cross: dict[tuple, dict] = {}       # (err_kind, status, fp[, host]) → 组累积
    g_host = Counter()                   # 全局维度切片（过滤后的失败请求）
    g_loopback = Counter()               # 本机回环单列，别淹没真实供应商分布
    g_model = Counter()
    g_ccver = Counter()
    total_records = 0
    total_failures = 0

    for d in dates:
        recs = records_by_date.get(d) or []
        n_match = 0
        n_fail = 0
        for r in recs:
            r_kind = classifier.classify_idx(r)
            if not _matches(r, model, kind, r_kind):
                continue
            n_match += 1
            total_records += 1
            if not _is_failure(r):
                continue
            n_fail += 1
            total_failures += 1
            ek, msg = _kind_and_msg(r)
            fp = _fingerprint(msg)
            # 退化消息（'Error' / 'timeout' / 空）不足以定义一组：补 host 才不会把
            # 各供应商各原因的失败并成一个没有诊断价值的垃圾桶组。**单天 aggregate 有意
            # 不这么做**——一天之内还能靠 samples 追，跨天跨供应商跨版本才需要拆。
            degenerate = _is_degenerate(fp)
            key = (ek, r.get("status"), fp, r.get("host") if degenerate else None)
            if r.get("host"):
                (g_loopback if _is_loopback(r["host"]) else g_host)[r["host"]] += 1
            if r.get("model"):
                g_model[r["model"]] += 1
            if r.get("cc_version"):
                g_ccver[r["cc_version"]] += 1
            if key not in cross:
                cross[key] = _new_group(r, ek, msg, fp, degenerate)
            _accumulate(cross[key], r, d, r_kind)
        per_day.append({"date": d, "records": n_match, "failures": n_fail, "groups": 0})

    # 每日去重组数：从 cross 反查（每个组在某日活跃则该日 groups+1）
    pd_idx = {pd["date"]: pd for pd in per_day}
    for g in cross.values():
        for d in g["days"]:
            pd_idx[d]["groups"] += 1

    # 跨天归并组序列化（跨天天数 desc → count desc）
    last_day = dates[-1] if dates else None
    items = []
    for g in sorted(cross.values(), key=lambda x: (-len(x["days"]), -x["count"])):
        trend = _trend(g["per_day"])
        since = _days_between(max(g["days"]), last_day) if g["days"] else None
        items.append({
            "err_kind": g["err_kind"],
            "status": g["status"],
            "message": g["message"],
            "fingerprint": g["fingerprint"],
            # 上游没给有信息量的消息（'Error' / 'timeout' / 空）：这组是按 host 拆过的，
            # 组内仍可能混着不同原因，要判因得看 samples，别拿 count/trend 下结论。
            "degenerate": g["degenerate"],
            "count": g["count"],
            "days_span": len(g["days"]),
            "first_seen": g["first_ts"],
            "last_seen": g["last_ts"],
            # 新鲜度与趋势正交：stale 的组即使标着 recurring，也已经不在发生了。
            "days_since_last": since,
            "stale": bool(since is not None and since >= STALE_DAYS and trend != "burst"),
            "per_day": dict(sorted(g["per_day"].items())),
            "trend": trend,
            "kinds": dict(sorted(g["kinds"].items(), key=lambda kv: -kv[1])),
            "sessions": len(g["sessions"]),
            "samples": g["samples"],
            "req_fields": _norm_req_fields(g["req_fields"]),
            "by_host": dict(g["by_host"].most_common()),
            "by_model": dict(g["by_model"].most_common()),
            "by_cc_version": dict(g["by_cc_version"].most_common()),
        })

    truncated = len(items) > limit
    cross_day_groups = sum(1 for g in cross.values() if len(g["days"]) >= 2)
    return {
        "span": len(dates),
        "dates": dates,
        "filters": {"model": model, "kind": kind},
        "totals": {
            "records": total_records,
            "failures": total_failures,
            "cross_day_groups": cross_day_groups,
            "all_groups": len(cross),
        },
        "per_day": per_day,
        "truncated": truncated,            # 契约：给 AI 的输出一律标注是否被截断
        "items": items[:limit],
        "by_host": _dims_to_list(g_host),
        # 本机回环单列：这不是供应商，通常是 BASE_URL 自指或指向另一个本地网关。
        "by_local_loopback": _dims_to_list(g_loopback),
        "by_model": _dims_to_list(g_model),
        "by_cc_version": _dims_to_list(g_ccver),
        "note": ("Cross-day failure groups (merged across days). items sorted by days_span desc "
                 "then count desc. trend describes SHAPE only: burst=one day with >=50 hits "
                 "(an incident), sporadic=one day with fewer, rising/declining/recurring compare "
                 "first-half vs second-half counts of active days (ratio>=1.5 / <=0.5 / else). "
                 "Freshness is separate: days_since_last + stale=true means it stopped happening, "
                 "even when trend says recurring. degenerate=true means the upstream message was "
                 "empty or a bare word ('Error'), so the group was split by host and count/trend "
                 "carry little meaning — read samples instead. by_local_loopback is NOT a vendor "
                 "(usually a self-referencing BASE_URL). For one day in depth use "
                 "/api/diagnose/errors?date=."),
    }


def _days_between(d1: str | None, d2: str | None) -> int | None:
    """两个 YYYY-MM-DD 相差几天（d2 - d1）。解析不了给 None，不猜。"""
    import datetime
    try:
        return (datetime.date.fromisoformat(d2) - datetime.date.fromisoformat(d1)).days
    except (TypeError, ValueError):
        return None
