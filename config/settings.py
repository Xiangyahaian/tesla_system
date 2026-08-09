# -*- coding: utf-8 -*-
"""
应用配置与全局设置

密钥请放在项目根目录 .env 中，不要提交到 Git。
"""
import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

parser = argparse.ArgumentParser(description='Tesla 多意图任务型对话系统')
parser.add_argument('mode', nargs='?', default='remote', choices=['local', 'remote'],
                    help='运行模式: local=本地vLLM, remote=阿里百炼API')
parser.add_argument('--port', type=int, default=6006, help='服务端口号')
args, _ = parser.parse_known_args()

RUN_MODE = args.mode
PORT = args.port

BASE_DIR = Path(__file__).parent.parent
SKILLS_DIR = BASE_DIR / "skills"
STATE_DIR = BASE_DIR / "state"
STATE_FILE = STATE_DIR / "state.json"
WEBUI_DIR = BASE_DIR / "webui"

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://127.0.0.1:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "qwen-2b-tesla")

MOONSHOT_API_BASE = os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1")
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_MODEL_NAME = os.getenv("MOONSHOT_MODEL_NAME", "moonshot-v1-32k")

# 阿里百炼配置
BAILIAN_API_BASE = os.getenv("BAILIAN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
BAILIAN_API_KEY = os.getenv("BAILIAN_API_KEY", "")
BAILIAN_MODEL_NAME = os.getenv("BAILIAN_MODEL_NAME", "qwen3.5-flash")
