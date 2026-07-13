"""配置持久化：~/.cc-wire-analyzer/config.json。

跨用户隔离（不污染项目目录）。打包分发后用户在「设置」里改这里。存储字段：
  - ui_lang: 界面语言 zh/en/ja（默认 zh）
  - auto_start_proxy: 启动软件时是否自动启动代理（默认 False）
  - retention_days: 捕获录制保留天数（默认 30）
  - redact_headers: headers 入库脱敏（默认 True）
  - translate: LLM 配置（api_key/base_url/model/temperature 供翻译与 AI 解读共用）
    + target_lang: 翻译目标语言 zh/en/ja（默认 zh）
  - explain: AI 解读配置（prompt 留空 = 用内置默认提示词，按界面语言取）
"""
from __future__ import annotations

import copy
import json
import os
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
    "auto_start_proxy": False,
    "retention_days": 30,
    "redact_headers": True,
    "translate": {
        "api_key": "",
        "base_url": "",
        "model": "",
        "temperature": 0.3,
        "target_lang": "zh",
    },
    "explain": {
        "prompt": "",
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
    return merged


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
    CONFIG_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return current


def list_capture_dates() -> list[dict]:
    """扫描 ~/.cc-wire-analyzer/captures/ 下所有按天 jsonl 文件。

    返回 [{date, size, capture_count, last_mtime}]，按日期降序。
    capture_count = 文件行数（粗略，不解析 JSON）。
    """
    captures_dir = CONFIG_DIR / "captures"
    if not captures_dir.exists():
        return []
    out = []
    for f in captures_dir.glob("*.jsonl"):
        try:
            st = f.stat()
            with f.open("r", encoding="utf-8") as fh:
                count = sum(1 for _ in fh)
        except OSError:
            continue
        out.append({
            "date": f.stem,  # YYYY-MM-DD
            "size": st.st_size,
            "capture_count": count,
            "last_mtime": st.st_mtime,
        })
    out.sort(key=lambda x: x["date"], reverse=True)
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
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    def _excepthook(exc_type, exc, tb):
        logging.getLogger().error(
            "Unhandled %s: %s",
            exc_type.__name__,
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )

    sys.excepthook = _excepthook


def write_port(port: int) -> None:
    """把选中端口写文件，供外壳读。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port), encoding="utf-8")


def read_port(timeout_s: float = 30.0) -> int | None:
    """外壳等 PORT_FILE 出现并读端口。"""
    import time
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if PORT_FILE.exists():
            try:
                return int(PORT_FILE.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                return None
        time.sleep(0.2)
    return None
