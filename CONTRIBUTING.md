# 本地工作约定

软件运行支持 Python 3.10+；本地说明书生成使用 Python 3.12+。安装依赖：`uv sync`；macOS 使用 `uv sync --extra mac`。

- 启动桌面：`uv run python src/desktop.py`。
- 浏览器调试：`uv run python src/app.py`，使用启动日志或数据目录 `port.txt` 的实际端口；模板改后重启服务。
- 测试数据入口：`tests/dev_seed.py`；采集或修改配置的测试先按开发约定双隔离，不能操作真实设置。
- 软件构建入口：`tools/build/build.py`；本地说明书：`uv run python tools/build/build_manual.py`。
- 文档检查：`uv run python tools/checks/doc_audit.py`；具体测试与前端检查见[开发约定的验证章节](docs/development/开发约定.md#八验证改完必须跑什么)。
- 目录与披露断面检查：`uv run python tools/checks/workspace_audit.py`；验证 `public` 原始文件哈希及本地入口边界。

改动前写 issue，按任务读取[开发约定](docs/development/开发约定.md)相关章节。新功能、字段、用法和约束同步到唯一正文；验证记录回填 issue。机械检查不能代替真实界面和语义核对，平台未实测应明确记录。

`public/` 已冻结，不修改披露断面。发版流程已于 260908 恢复：本地迭代验证通过后可以推送、打 `v*` tag 触发 CI 构建并发布 Release，步骤见[开发约定第十二节](docs/development/开发约定.md)。不改动原始录制，不覆盖其他 agent 的未提交成果。
