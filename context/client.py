# -*- coding: utf-8 -*-
"""
LLM客户端封装 - 支持本地vLLM、Moonshot AI、阿里百炼
新增：chat_stream 方法支持异步流式输出
"""
import openai
from config.settings import (
    RUN_MODE, VLLM_API_BASE, VLLM_API_KEY, VLLM_MODEL_NAME,
    MOONSHOT_API_BASE, MOONSHOT_API_KEY, MOONSHOT_MODEL_NAME,
    BAILIAN_API_BASE, BAILIAN_API_KEY, BAILIAN_MODEL_NAME
)


class MoonshotClient:
    """Moonshot AI (Kimi) API 客户端"""
    
    def __init__(self):
        self.api_key = MOONSHOT_API_KEY
        self.base_url = MOONSHOT_API_BASE
        self.model = MOONSHOT_MODEL_NAME
    
    async def chat_stream(self, system: str, user: str):
        """流式调用Moonshot AI API - 异步生成器"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        try:
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=1,
                stream=True
            )
            for chunk in response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            print(f"[Moonshot API 流式错误]: {e}")
            raise


class BailianClient:
    """阿里百炼 API 客户端 (Qwen3.5-Flash)"""
    
    def __init__(self):
        self.api_key = BAILIAN_API_KEY
        self.base_url = BAILIAN_API_BASE
        self.model = BAILIAN_MODEL_NAME
        print(f"[阿里百炼] 使用模型: {self.model}")
    
    async def chat_stream(self, system: str, user: str):
        """流式调用阿里百炼 API - 异步生成器"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        try:
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            extra_body = {"enable_thinking": False}
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                stream=True,
                extra_body=extra_body
            )
            for chunk in response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            print(f"[阿里百炼 API 流式错误]: {e}")
            raise


class LLMClientWrapper:
    """统一LLM客户端 - 支持本地vLLM、Moonshot AI、阿里百炼"""
    
    def __init__(self):
        self.mode = RUN_MODE
        if self.mode == 'remote':
            self.bailian_client = BailianClient()
            print("[LLM] 使用 阿里百炼 (Qwen3.5-Flash)")
        else:
            print("[LLM] 使用本地 vLLM")
    
    def chat(self, system: str, user: str, stream: bool = False):
        """同步对话接口（兼容旧代码：RAG查询等场景）"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        
        if self.mode == 'remote':
            # 使用阿里百炼
            client = openai.OpenAI(api_key=BAILIAN_API_KEY, base_url=BAILIAN_API_BASE)
            extra_body = {"enable_thinking": False}
            response = client.chat.completions.create(
                model=BAILIAN_MODEL_NAME,
                messages=messages,
                temperature=0.3,
                stream=False,
                extra_body=extra_body
            )
            return response.choices[0].message.content
        else:
            # 本地 vLLM
            client = openai.OpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)
            response = client.chat.completions.create(
                model=VLLM_MODEL_NAME,
                messages=messages,
                temperature=0.3,
                stream=False
            )
            return response.choices[0].message.content
    
    async def chat_stream(self, system: str, user: str):
        """统一流式对话接口 - 异步生成器
        
        用于 tool 执行后的流式回复生成
        """
        if self.mode == 'remote':
            async for token in self.bailian_client.chat_stream(system, user):
                yield token
        else:
            try:
                import openai
                client = openai.OpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ]
                response = client.chat.completions.create(
                    model=VLLM_MODEL_NAME,
                    messages=messages,
                    temperature=0.3,
                    stream=True
                )
                for chunk in response:
                    if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            except Exception as e:
                print(f"[LLM 本地流式错误]: {e}")
                raise
