#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import signal
import socket
import logging
import argparse
import subprocess
import urllib.request
from urllib.error import URLError, HTTPError
from pathlib import Path
from typing import Optional

# 依赖检查
try:
    import psutil
except ImportError:
    sys.exit("Error: 缺少 psutil 库。请执行: pip install psutil")

try:
    import torch
except ImportError:
    sys.exit("Error: 缺少 torch 库。请执行: pip install torch")


class VLLMServerManager:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.process: Optional[subprocess.Popen] = None
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("VLLM_Manager")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        file_handler = logging.FileHandler(self.args.log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger

    def check_environment(self) -> None:
        self.logger.info("开始执行环境预检...")
        
        if not Path(self.args.model_path).exists():
            self.logger.error(f"模型路径不存在: {self.args.model_path}")
            sys.exit(1)
            
        if not torch.cuda.is_available():
            self.logger.error("未检测到 CUDA 环境")
            sys.exit(1)
            
        device_name = torch.cuda.get_device_name(0)
        gpu_mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        self.logger.info(f"GPU 信息: {device_name} | 显存: {gpu_mem_gb:.1f} GB")
        
        if gpu_mem_gb < 10.0:
            self.logger.warning("显存较小 (RTX 4060 级别)，已自动开启显存保护策略")

    def kill_existing_server(self) -> None:
        self.logger.info(f"检查 {self.args.port} 端口占用...")
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                if 'vllm.entrypoints.openai.api_server' in ' '.join(cmdline) and str(self.args.port) in ' '.join(cmdline):
                    self.logger.warning(f"终止旧进程 PID: {proc.info['pid']}")
                    os.killpg(os.getpgid(proc.info['pid']), signal.SIGKILL)
            except:
                pass

    def _wait_for_health_check(self, timeout: int = 300) -> bool:
        health_url = f"http://{self.args.host}:{self.args.port}/v1/models"
        start_time = time.time()
        self.logger.info(f"等待模型加载（极简模式，启动速度快）...")
        
        while time.time() - start_time < timeout:
            if self.process and self.process.poll() is not None:
                self.logger.error("vLLM 进程意外终止，请检查日志")
                return False
            try:
                with urllib.request.urlopen(health_url, timeout=2) as response:
                    if response.status == 200:
                        return True
            except:
                pass
            time.sleep(5)
        return False

    def start(self) -> None:
        self.check_environment()
        self.kill_existing_server()

        # 【终极完美版配置】
        cmd = [
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
            "--model", self.args.model_path,
            "--served-model-name", self.args.served_model_name,
            "--trust-remote-code",
            "--port", str(self.args.port),
            "--host", self.args.host,
            
            # --- 显存管理 ---
            "--gpu-memory-utilization", "0.75",     # 稍微放宽显存限制，因为我们关了预热
            "--max-model-len", "4096",            # 2048 是 8GB 卡的绝对安全线，先保证活下来
            
            # --- 模型格式 ---
            "--quantization", "compressed-tensors", # 明确指定你在上一次报错中需要的量化格式
            
            # --- 8GB 卡救命参数（极简） ---
            "--enforce-eager",                    # 彻底禁用图编译预热，省下近 2GB 显存，启动瞬间完成
            "--max-num-seqs", "2",                # 极度限制并发，防止爆显存
            "--default-chat-template-kwargs", '{"enable_thinking": false}',
            # --- 其他 ---
            "--no-enable-log-requests",
            "--scheduling-policy", "fcfs"
        ]
        
        self.logger.info(f"执行命令: {' '.join(cmd)}")
        
        with open(self.args.log_file, "a", encoding="utf-8") as f:
            self.process = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid
            )
            
        if not self._wait_for_health_check():
            self.stop()
            sys.exit(1)
            
        self.logger.info(f"服务启动成功！地址: http://{self.args.host}:{self.args.port}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.logger.info("正在停止 vLLM...")
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)


def main():
    parser = argparse.ArgumentParser(description="Qwen3.5-4B 极限模式启动器")
    parser.add_argument("--model-path", type=str, 
                        default="models/cyankiwi/Qwen3___5-4B-AWQ-4bit", 
                        help="模型路径")
    parser.add_argument("--served-model-name", type=str, default="qwen-4b-tesla", help="API 模型标识名")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--log-file", type=str, default="vllm_tesla.log", help="日志文件")
    
    args = parser.parse_args()
    manager = VLLMServerManager(args)
    
    signal.signal(signal.SIGINT, lambda s, f: (manager.stop(), sys.exit(0)))
    
    try:
        manager.start()
        while manager.process and manager.process.poll() is None:
            time.sleep(1)
    except Exception as e:
        manager.logger.error(f"异常: {e}")
    finally:
        manager.stop()

if __name__ == "__main__":
    main()