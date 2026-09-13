"""配置持久化：~/.cc-wire-analyzer/config.json。

跨用户隔离（不污染项目目录）。打包分发后用户在「设置」里改这里。存储字段：
  - ui_lang: 界面语言 zh/en/ja（默认 zh）
  - auto_start_proxy: 启动软件时是否自动启动代理（默认 False；260713 前是死配置，从没接线）
  - retention_days: 捕获录制保留天数（默认 30；260713 前是死配置，UI 承诺自动清理却零实现）
  - cold_storage: 自动冷藏（enabled 默认 True / days 默认 7）——久不点开的日期深压收起，
    点一下解冻；days <= 0 = 从不自动冷藏
  - translate: LLM 配置（api_key/base_url/model/temperature 供翻译与 AI 解读共用）
    + target_lang: 翻译目标语言 zh/en/ja（默认 zh）
  - explain: AI 解读配置（prompt 留空 = 用内置默认提示词，按界面语言取）
  - analysis: 归纳提示词（turns_prompt/steps_prompt 留空 = 内置默认任务段，260826 开放）

已移除：`redact_headers`（260713）。它曾是个假开关——设置页承诺"可关闭脱敏"，而 `proxy._redact()`
一直是无条件调用的。没有把它接线实现，而是**连开关一起删掉、脱敏恒开**：真让它生效 =
提供一个把 API key 明文写进 jsonl 的选项，而我们刚给 AI agent 开了读这些 jsonl 的 CLI
（见 docs/usage/AI_USAGE.md）—— 等于给 key 修一条直通 AI 上下文的路。老 config.json 里残留该键会被忽略。
"""
from __future__ import annotations

import copy
import json
import os
import re as _re
from pathlib import Path

# 两个环境变量覆盖（默认值不变，普通用户无感）：
#   CCWA_HOME            —— 数据目录（录制/配置/日志/marker）
#   CCWA_CLAUDE_SETTINGS —— 上游 settings.json 路径
# 动机：本软件最危险的动作是改用户的 ~/.claude/settings.json，而在 260713 之前
# **这条路径根本没法端到端自测**——一测就得动真配置，等于拿用户的 CC 当小白鼠。
# 有了覆盖，e2e 自测可以在临时目录里把「起代理→patch→停→恢复」整条链跑真的。
# 顺带也照顾了把数据放别处、或 settings.json 不在默认位置的用户。
CONFIG_DIR = Path(os.environ.get("CCWA_HOME") or (Path.home() / ".cc-wire-analyzer"))
CONFIG_FILE = CONFIG_DIR / "config.json"

_DEFAULTS = {
    "ui_lang": "zh",
    # 界面缩放百分比（80~200，默认 100）。260801 用户反馈：2K 分辨率 + 系统缩放 100% 下
    # 字号偏小——全部 CSS 是绝对 px，此前软件里没有任何调节手段，只能去改系统缩放（会波及所有软件）。
    "ui_scale": 100,
    "auto_start_proxy": False,
    "retention_days": 30,
    # 滚动压实（260831）：今天的录制写到阈值就把已写完的前缀封存成分片，不必等跨天。
    # 动机是**当天磁盘峰值**——实测单日 500~860MB 是常态，而 compact_date 拒绝碰今天，
    # 于是 28x 的压缩比在当天一秒都享受不到。
    # 默认开启：按维护者实际使用配置，及时压实当天已写完的录制前缀。
    "rolling_compact": True,
    # 切段阈值（MB），读写两侧夹到 20~2000（见 _clamp_seg_mb）。
    "rolling_compact_mb": 200,
    # 自动冷藏（260913）：超过 days 天没点开过的日期收进 captures/cold/，实测在压实之上
    # 再省约 4 倍（13.12MB → 3.11MB）。代价是冷藏态不能直接翻，点一下解冻——这正是
    # 「已冷藏折起来」那个交互要的形态。
    # 默认开：录制是只增不减的，而绝大多数历史录制录完就再也没被点开过。
    # days <= 0 = 从不自动冷藏（显式出口，与 retention_days 同一条口径，不是当成 0 天全冻）。
    "cold_storage": {"enabled": True, "days": 7},
    "translate": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "temperature": 0.3,
        "max_tokens": 16384,   # 长文本翻译/解读输出上限；不足会被上游截断（260713 开放到设置页）
        "target_lang": "zh",
        # 输入侧上限，单位**字符**（不是 token——客户端算不出 token 数，提示里报的也是
        # 字符，配置项必须与提示同一单位，所见即所得）。260825 从 app.py 的写死 20000
        # 开放成配置：截断有自陈（260801），但砍在哪一刀该由用户定——实测单条 system
        # prompt 40K+ 常见，20K 一刀砍掉的分析结论本身就是失真的。
        # input_max_chars：单轮（翻译/AI 解读/差异解读）发送原文的上限
        # chat_context_max_chars：分析对话每轮注入的快照上下文上限
        # 两个都读写两侧夹取（1000~2,000,000，见 _clamp_chars）：下限防"填 0 截成空串
        # 还挂已截断提示"，上限防手滑天文数字一次烧穿。
        "input_max_chars": 80000,
        "chat_context_max_chars": 80000,
    },
    "explain": {
        "prompt": "",
    },
    # 归纳提示词（260826 开放进设置页）：留空 = 内置默认任务段，非空整段替换。
    # 防注入 GUARD 骨架在 app.py 固定拼接、不进配置——用户能调任务描述，不能拆隔离墙。
    "analysis": {
        "turns_prompt": "",
        "steps_prompt": "",
        # 归纳批次的并发数（260827）。批次之间无依赖，串行纯粹是在等——实测 27 批 26 分钟。
        # 上限 8 不是性能考虑，是别把用户的上游打成限流：限流会让失败批变多，总时间反而更长。
        "concurrency": 4,
    },
}


def _deepcopy_defaults() -> dict:
    return copy.deepcopy(_DEFAULTS)


def get_config() -> dict:
    """读配置并与默认值合并。文件不存在/损坏返回默认。"""
    if not CONFIG_FILE.exists():
        return _deepcopy_defaults()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _deepcopy_defaults()
    merged = _deepcopy_defaults()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in merged:
                # 嵌套 dict 浅合并（translate 这类）
                if isinstance(merged[k], dict) and isinstance(v, dict):
                    merged[k].update(v)
                else:
                    merged[k] = v
    merged["ui_scale"] = _clamp_scale(merged.get("ui_scale"))   # 手改坏的 config.json 也不许把界面缩没
    tr = merged.get("translate") or {}
    tr["input_max_chars"] = _clamp_chars(tr.get("input_max_chars"))
    tr["chat_context_max_chars"] = _clamp_chars(tr.get("chat_context_max_chars"))
    an = merged.get("analysis") or {}
    an["concurrency"] = _clamp_workers(an.get("concurrency"))
    merged["rolling_compact_mb"] = _clamp_seg_mb(merged.get("rolling_compact_mb"))
    cold = merged.get("cold_storage") or {}
    cold["days"] = _clamp_cold_days(cold.get("days"))
    cold["enabled"] = bool(cold.get("enabled"))
    return merged


def _clamp_seg_mb(v, default: int = 200) -> int:
    """滚动压实的切段阈值夹到 20~2000 MB。

    下限防「填 0 或很小的数 → 每条记录都触发一次切段」，那会把一天切成几十个分片，
    而每个分片一份独立 blob 池，去重率反而掉下来；上限防手滑填个天文数字，
    那等于把开关关掉却以为它开着——比明确关掉更糟，因为它看起来是开的。
    """
    try:
        return max(20, min(2000, int(v) or default))
    except (TypeError, ValueError):
        return default


def _clamp_cold_days(v, default: int = 7) -> int:
    """自动冷藏天数夹到 0~365。0 是显式的「从不自动冷藏」出口（与 retention_days 同一条
    口径），所以下限不是 1；上限 365 防手滑填个天文数字——那等于把开关关掉却以为它开着，
    比明确关掉更糟，因为它看起来是开的（与 _clamp_seg_mb 末段同一条理由）。"""
    try:
        return max(0, min(365, int(v)))
    except (TypeError, ValueError):
        return default


def _clamp_scale(v) -> int:
    """界面缩放百分比夹到 80~200。前端把它直接写进 CSS zoom——0/负数/天文数字会让界面
    缩没或撑爆，而这是个**改坏了就没法再打开设置页改回来**的字段，所以读写两侧都夹。"""
    try:
        return max(80, min(200, int(v)))
    except (TypeError, ValueError):
        return 100


def _clamp_workers(v, default: int = 4) -> int:
    """归纳并发数夹到 1~8。与 _clamp_chars 同一条纪律：这是花钱又会撞限流的旋钮，
    0 会让归纳一批都跑不动，天文数字会把上游打成 429——防呆必须在工具侧。"""
    try:
        return max(1, min(8, int(v) or default))
    except (TypeError, ValueError):
        return default


def _clamp_chars(v, default: int = 20000) -> int:
    """LLM 输入上限（字符）夹到 1000~2,000,000。与 _clamp_scale 同一条纪律：
    0/负数会把文本截成空串还挂「已截断」提示；天文数字一次请求就烧穿上游。
    这是花钱的旋钮，防呆必须在工具侧，不能指望用户自己小心。"""
    try:
        return max(1000, min(2_000_000, int(v)))
    except (TypeError, ValueError):
        return default


def set_config(updates: dict) -> dict:
    """合并写入 updates（白名单字段），返回写后的完整配置。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current = get_config()
    for k, v in updates.items():
        if k in _DEFAULTS:
            if isinstance(current.get(k), dict) and isinstance(v, dict):
                current[k].update(v)
            else:
                current[k] = v
    current["ui_scale"] = _clamp_scale(current.get("ui_scale"))
    tr = current.get("translate") or {}
    tr["input_max_chars"] = _clamp_chars(tr.get("input_max_chars"))
    tr["chat_context_max_chars"] = _clamp_chars(tr.get("chat_context_max_chars"))
    an = current.get("analysis") or {}
    an["concurrency"] = _clamp_workers(an.get("concurrency"))
    cold = current.get("cold_storage") or {}
    cold["days"] = _clamp_cold_days(cold.get("days"))
    cold["enabled"] = bool(cold.get("enabled"))
    CONFIG_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return current


# 录制主文件名形态。与 capture_store._DATE_RE 同一约定（那边还用于入参校验防路径穿越）；
# 两处各自 compile 而非互相 import——config 是最底层模块，不能反向依赖 capture_store。
_DATE_STEM_RE = _re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def list_capture_dates(source: str = "") -> list[dict]:
    """有哪些日期的录制（含体积、条数、形态）。按日期降序。

    260825 起**两种形态都要认**（jsonl / pack 目录），而形态判断的单一真源在
    `capture_store`——本函数改成薄壳委托过去，用函数内延迟 import 绕开
    `capture_store → config` 的循环依赖。

    此前这里自己 glob `*.jsonl` 并逐个数行，踩过一个同型坑（260801）：派生文件
    `{date}.idx.jsonl` 也以 .jsonl 结尾，`f.stem` 变成 "2026-08-01.idx" 这种假日期，
    于是 `cmd_get` 的历史回落会命中索引行、静默返回 `ok:true + data:null`。
    收口到一处之后，「再加一种派生文件」不必改两个地方。
    """
    import capture_store as _cs
    out = []
    for date in _cs._available_dates(source):
        info = _cs.day_info(date, source)
        out.append({
            "date": date,
            "size": info["bytes"],
            "capture_count": info["count"],
            "packed": info["packed"],
            "raw_bytes": info.get("raw_bytes"),
            "last_mtime": info.get("mtime", 0.0),
        })
    return out


# ===== 运行时：日志 + 端口协调（pywebview 外壳共用）=====
LOG_FILE = CONFIG_DIR / "run.log"
PORT_FILE = CONFIG_DIR / "port.txt"

# 上游 settings.json（settings_guard 读写）。见文件头：CCWA_CLAUDE_SETTINGS 可覆盖。
CLAUDE_SETTINGS = Path(os.environ.get("CCWA_CLAUDE_SETTINGS")
                       or (Path.home() / ".claude" / "settings.json"))


def find_free_port(start: int = 5051, end: int = 5100) -> int | None:
    """找空闲端口（5051-5100，错开其他常见本地服务）。

    返回端口号或 None。
    """
    import socket
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def setup_logging() -> None:
    """日志到 ~/.cc-wire-analyzer/run.log + 进程级异常钩子（noconsole 也能查崩溃）。"""
    import logging
    import sys
    import traceback
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # encoding 必须显式 utf-8：不传则 Windows 按 locale(GBK) 写，中文日志用 UTF-8 工具
    # 打开全是乱码（260717 用户实测满屏 ��）。历史 GBK 段不迁移，新行起 UTF-8。
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )

    def _excepthook(exc_type, exc, tb):
        logging.getLogger().error(
            "Unhandled %s: %s",
            exc_type.__name__,
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        # **记进日志之后必须照常打出来**。这个钩子的目的是"noconsole 构建也能查崩溃"，
        # 也就是给没有控制台的场合**补**一条出路；它从来不该把有控制台的场合原本就有的那条
        # 堵死。而直接赋值 sys.excepthook 就是替换掉默认行为，于是任何未捕获异常在终端和 CI
        # 里都变成"exit=1 + 一片空白"——260913 发 v0.4.38 时 CI 红了一次，完整日志 49 行里
        # 没有一个字的报错，就是这么来的（当时只能靠重跑通过，根因查了才知道在这儿）。
        # upstream_history.py 的自测入口早就撞过同一个坑，但当时是在那一个文件里自己
        # try/except 绕开的，没回到这里修——于是 settings_guard.py 再撞一次时照样哑。
        # noconsole 构建里 sys.stderr 可能是 None，__excepthook__ 自己会处理，但仍兜一层。
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _excepthook


def write_port(port: int) -> None:
    """把选中端口写文件，供外部进程（CLI）发现正在跑的实例。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port), encoding="utf-8")

# 曾有个 read_port()（轮询等 PORT_FILE 出现）—— 旧架构里外壳是独立进程才需要它。
# 现在 desktop.py 直接把端口传给 Flask，CLI 自己有 _read_port()，它零调用多时了，260713 删除。
