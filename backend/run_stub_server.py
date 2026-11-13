"""开发/测试用：安装 LLM stub 后启动后端（无需真实 API Key）。

用法（在 backend 目录）：
  .\.venv\Scripts\python.exe run_stub_server.py [--port 8765]
"""
import argparse

from tests.llm_stub import install

install()

from novel_agent import db  # noqa: E402

db.init_db()
if not db.get_config().get("api_key"):
    db.set_config_values({"api_key": "stub-local"})

import uvicorn  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run("novel_agent.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
