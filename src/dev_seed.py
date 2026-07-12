"""开发用：写一套覆盖 DAG 全要素的样例捕获，供 UI 自测。

用法：uv run python src/dev_seed.py
每次运行追加 10 条（id 随机），测完删 ~/.cc-wire-analyzer/captures/<今天>.jsonl，
或用界面「清理」按钮（清除录制 / 清除并压缩存档）。

时序设计（同一天，验证分类 + DAG 推断 + 泳道多色配色）：
  A 会话线（主线 1）3 轮 + 派生子代理；B 会话线（主线 2）502；D 会话线（主线 3）2 轮；
  辅助调用（title / security / compact）落 aux lane，near 边挂最近主线。
预期 DAG：lanes = [main×3, subagent×1, aux×1]，三条主线各取色板不同色；trigger 边 A2→S1。
"""
from __future__ import annotations

import time

import capture_store as cs

TODAY = time.strftime("%Y-%m-%d", time.localtime())

# CC 主线 system prompt 开头的真实水印样例（currentDate 的撇号/斜杠变体），
# 用于演示本工具能看到链路层原始 system 文本。非真实指令。
WATERMARK = (
    "You are Claude Code, Anthropic's official CLI for Claude.\n\n"
    "# currentDate\n"
    "Todayʹs date is 2026/07/06.\n"   # U+02B9 撇号 + 斜杠日期（演示水印变体）
)
MAIN_SYS = [
    {"type": "text", "text": WATERMARK, "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "# claudeMd\n项目说明与用户约定（示例占位）…"},
]
TOOLS = [
    {"name": n, "description": f"{n} tool.",
     "input_schema": {"type": "object", "properties": {}}}
    for n in ("Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task",
              "WebFetch", "WebSearch", "NotebookEdit", "TodoWrite")
]
TASK_PROMPT = ("调研某前端库的内存泄漏常见成因：归纳 3-5 个根因假设，"
               "给出每个的验证方法与替代方案，输出简报。")
A_FIRST_USER = "「帮我给这个 Web 项目加一个暗色主题切换」"
D_FIRST_USER = "「这个 npm run build 卡在打包阶段，帮我看看」"
UID = "user_demo"


def base(ts: str, model: str = "glm-5.2"):
    r = cs.new_record()
    r["ts_start"] = f"{TODAY}T{ts}"
    r["ts_end"] = r["ts_start"]
    r.update(method="POST", path="/v1/messages",
             upstream="https://api.example.com/v1/messages")
    r["request"] = {
        "headers_safe": {"content-type": "application/json",
                         "anthropic-version": "2023-06-01",
                         "authorization": "<redacted>",
                         "user-agent": "claude-cli/2.1 (external, cli)"},
        "body": {"model": model, "max_tokens": 32000, "stream": True,
                 "metadata": {"user_id": UID}},
    }
    r["response"] = {
        "status": 200, "headers_safe": {"content-type": "text/event-stream"},
        "ttft_ms": 340, "total_ms": 4500, "stop_reason": "end_turn",
        "usage": {"input": 45000, "output": 800, "cache_read": 44000, "cache_creation": 0},
        "content_blocks": [], "chunks_count": 40,
    }
    return r


def a1():
    r = base("22:40:00.100")
    b = r["request"]["body"]
    b["system"] = MAIN_SYS; b["tools"] = TOOLS
    b["messages"] = [{"role": "user", "content": A_FIRST_USER}]
    r["response"]["content_blocks"] = [
        {"type": "thinking", "text": "先读项目结构与现有样式…"},
        {"type": "text", "text": "好的，先看一下项目的样式结构。"},
        {"type": "tool_use", "id": "toolu_a1read", "name": "Read",
         "input": {"file_path": "src/styles/globals.css"}},
    ]
    return r


def t1():
    r = base("22:40:02.400", model="glm-4.7")
    b = r["request"]["body"]
    b["max_tokens"] = 512; b["stream"] = False
    b["system"] = [{"type": "text",
                    "text": "Summarize this conversation in a short title. "
                            "Please write a 5-10 word title for this conversation."}]
    b["messages"] = [{"role": "user", "content": A_FIRST_USER + " …"}]
    r["response"].update(ttft_ms=210, total_ms=890, chunks_count=1,
                         usage={"input": 612, "output": 24, "cache_read": 0, "cache_creation": 0})
    r["response"]["content_blocks"] = [{"type": "text", "text": "Add dark theme toggle to web app"}]
    return r


def a2():
    r = base("22:41:30.200")
    b = r["request"]["body"]
    b["system"] = MAIN_SYS; b["tools"] = TOOLS
    b["messages"] = [
        {"role": "user", "content": A_FIRST_USER},
        {"role": "assistant", "content": [
            {"type": "text", "text": "好的，先看一下项目的样式结构。"},
            {"type": "tool_use", "id": "toolu_a1read", "name": "Read",
             "input": {"file_path": "src/styles/globals.css"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_a1read",
             "content": "/* globals.css */\n:root{--bg:#fff;color:#000;}"}]},
    ]
    r["response"]["content_blocks"] = [
        {"type": "text", "text": "样式结构清楚了，派一个子代理去调研主题切换的内存泄漏注意事项。"},
        {"type": "tool_use", "id": "toolu_a2task", "name": "Task",
         "input": {"subagent_type": "Explore", "description": "调研主题切换内存泄漏",
                   "prompt": TASK_PROMPT}},
    ]
    return r


def s1():
    r = base("22:41:35.800", model="glm-5v-turbo")
    b = r["request"]["body"]
    b["system"] = [{"type": "text",
                    "text": "You are an agent specialized in fast codebase exploration. "
                            "Report findings concisely."}]
    b["tools"] = TOOLS[:4]
    b["messages"] = [{"role": "user", "content": TASK_PROMPT}]
    b["metadata"] = {"user_id": UID}
    r["response"].update(ttft_ms=402, total_ms=8100,
                         usage={"input": 9800, "output": 1100, "cache_read": 0, "cache_creation": 0})
    r["response"]["content_blocks"] = [
        {"type": "text", "text": "调研结论：主题切换的内存泄漏常见于事件监听器未清理、"
                                 "IntersectionObserver 未 disconnect 等几种…"},
    ]
    return r


def b1():
    r = base("22:42:00.500")
    b = r["request"]["body"]
    b["system"] = [{"type": "text", "text": WATERMARK}]
    b["tools"] = TOOLS
    b["messages"] = [{"role": "user", "content": "「另一个会话：帮我看看 SSE 断流问题」"}]
    r["response"].update(status=502, ttft_ms=None, total_ms=30012, stop_reason=None,
                         usage={}, chunks_count=0)
    r["response"]["content_blocks"] = []
    r["error"] = {"kind": "upstream_5xx", "status": 502,
                  "body_snippet": "<html><body>502 Bad Gateway</body></html>"}
    return r


def o1():
    """安全分类器样例（system 含 security monitor，归 security kind，落 aux lane）。"""
    r = base("22:42:10.900", model="glm-4.7")
    b = r["request"]["body"]
    b["max_tokens"] = 2112; b["stream"] = False
    b["system"] = [{"type": "text",
                    "text": "You are a security monitor for autonomous AI coding agents."}]
    b["messages"] = [{"role": "user", "content": "Classify the following content category: …"}]
    b.pop("metadata", None)
    r["response"].update(ttft_ms=180, total_ms=650, chunks_count=1,
                         usage={"input": 420, "output": 8, "cache_read": 0, "cache_creation": 0})
    r["response"]["content_blocks"] = [{"type": "text", "text": "category: safe"}]
    return r


def d1():
    r = base("22:42:30.300")
    b = r["request"]["body"]
    b["system"] = MAIN_SYS; b["tools"] = TOOLS
    b["messages"] = [{"role": "user", "content": D_FIRST_USER}]
    r["response"]["content_blocks"] = [
        {"type": "text", "text": "先看构建配置和报错日志。"},
        {"type": "tool_use", "id": "toolu_d1read", "name": "Read",
         "input": {"file_path": "vite.config.ts"}},
    ]
    return r


def a3():
    r = base("22:43:12.345")
    b = r["request"]["body"]
    b["system"] = MAIN_SYS; b["tools"] = TOOLS
    b["messages"] = [
        {"role": "user", "content": A_FIRST_USER},
        {"role": "assistant", "content": [{"type": "text", "text": "…（前两轮省略）"}]},
        {"role": "user", "content": "子代理的调研结果怎么说？"},
    ]
    r["response"]["content_blocks"] = [
        {"type": "thinking", "text": "汇总子代理简报…"},
        {"type": "text", "text": "子代理结论：主题切换注意清理监听器和 observer 即可，我来实现。"},
    ]
    return r


def d2():
    r = base("22:43:50.600")
    b = r["request"]["body"]
    b["system"] = MAIN_SYS; b["tools"] = TOOLS
    b["messages"] = [
        {"role": "user", "content": D_FIRST_USER},
        {"role": "assistant", "content": [{"type": "text", "text": "…（读了配置）"}]},
        {"role": "user", "content": "是某个依赖没预构建吗？"},
    ]
    r["response"]["content_blocks"] = [
        {"type": "text", "text": "对，依赖没进预构建导致打包卡住，加上就好。"}]
    return r


def c1():
    r = base("22:44:00.700")
    b = r["request"]["body"]
    b["system"] = [{"type": "text", "text": "You are a helpful AI assistant tasked with summarizing conversations."}]
    b["messages"] = [{"role": "user",
                      "content": "Your task is to create a detailed summary of the conversation so far…"}]
    r["response"].update(ttft_ms=550, total_ms=12000,
                         usage={"input": 52000, "output": 2100, "cache_read": 0, "cache_creation": 0})
    r["response"]["content_blocks"] = [
        {"type": "text", "text": "## 会话总结\n用户在给 Web 项目加暗色主题、调试构建问题…"}]
    return r


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for rec, tag in ((a1(), "A1 main"), (t1(), "T1 title"), (a2(), "A2 main+Task"),
                     (s1(), "S1 subagent"), (b1(), "B1 main 502"), (o1(), "O1 security"),
                     (d1(), "D1 main"), (a3(), "A3 main"), (d2(), "D2 main"),
                     (c1(), "C1 compact")):
        cs.append(rec)
        print("seeded", rec["id"], "→", tag)
    print("done →", cs.CAPTURES_DIR)
