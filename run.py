# -*- coding: utf-8 -*-
import importlib
import os
import sys
import time
import json
import asyncio
import traceback
import logging
from pathlib import Path
from fastapi.staticfiles import StaticFiles  #
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from config.settings import PORT
from config import prompts
from context import (
    IntentType, recognize_intent, handle_chat_intent,
    load_all_skill_metas, route_skills,
    select_function, select_multiple_functions,
    execute_function, execute_multiple_functions, format_multi_results,
    RAGEngine, clean_query, format_params
)
from context.client import LLMClientWrapper
from context.memory_manager import (
    MemoryManager, MemoryIntentType, get_memory_manager, 
    generate_memory_prompt, reset_memory_manager
)

# ==========================================
# 日志系统配置 (记录所有 LLM 输入输出到 chat.log)
# ==========================================
chat_logger = logging.getLogger("LLM_Chat_Logger")
chat_logger.setLevel(logging.INFO)
chat_logger.propagate = False 

if not chat_logger.handlers:
    file_handler = logging.FileHandler("chat.log", encoding="utf-8")
    formatter = logging.Formatter(
        "============================================================\n"
        "时间: %(asctime)s\n"
        "%(message)s\n"
        "============================================================"
    )
    file_handler.setFormatter(formatter)
    chat_logger.addHandler(file_handler)

def log_llm_interaction(caller_name, system_prompt, user_prompt, response):
    """格式化写入 chat.log"""
    log_msg = (
        f"【调用环节】: {caller_name}\n\n"
        f"[System Prompt]\n{system_prompt}\n\n"
        f"[User Prompt]\n{user_prompt}\n\n"
        f"[LLM Response]\n{response}"
    )
    chat_logger.info(log_msg)

class LoggingLLMClient:
    """
    LLM 客户端拦截器：自动记录所有非流式 LLM 对话到 chat.log
    """
    def __init__(self, real_client, model_name="unknown"):
        self.real_client = real_client
        self.model_name = model_name

    def chat(self, system, user, stream=False, **kwargs):
        response = self.real_client.chat(system=system, user=user, stream=stream, **kwargs)
        log_llm_interaction(f"LLM_API_CALL ({self.model_name})", system, user, response)
        return response

    def __getattr__(self, name):
        return getattr(self.real_client, name)

# 本地vLLM客户端封装
class LocalVLLMClient:
    """本地vLLM客户端封装"""
    def __init__(self, base_url="http://127.0.0.1:8000/v1", model_name="qwen-4b-tesla"):
        self.base_url = base_url
        self.model_name = model_name
        self.client = None
        self._try_connect()
    
    def _try_connect(self):
        """尝试连接本地vLLM服务"""
        try:
            import openai
            self.client = openai.OpenAI(api_key="EMPTY", base_url=self.base_url)
            # 测试连接
            self.client.models.list()
            print(f"[LocalLLM] 本地模型连接成功: {self.model_name}")
            return True
        except Exception as e:
            print(f"[LocalLLM] 本地模型连接失败: {e}")
            self.client = None
            return False
    
    def is_available(self):
        """检查是否可用"""
        return self.client is not None
    
    def chat(self, system, user, stream=False, **kwargs):
        """调用本地模型"""
        if not self.client:
            raise Exception("本地模型未连接")
        
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=kwargs.get("temperature", 0.3),
            stream=stream
        )
        
        if stream:
            return response
        else:
            return response.choices[0].message.content

# ==========================================
# FastAPI 应用初始化
# ==========================================
print("=" * 60)
print(f"Tesla 多意图Agent (双模型版本)")
print(f"端口: {PORT}")
print("=" * 60)

app = FastAPI(title="Tesla 多意图Agent")
templates = Jinja2Templates(directory="webui")

# 全局变量
rag_engine = None
remote_client = None  # 阿里百炼
local_client = None   # 本地vLLM
memory_manager = None
local_model_available = False

# ====================== 用户手册PDF功能（新增，不影响原有代码） ======================
import os
from fastapi.responses import FileResponse

# 获取当前文件所在目录，自动拼绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(BASE_DIR, "static", "pdf", "Tesla_Manual.pdf")

@app.get("/manual")
async def download_manual():
    if os.path.exists(PDF_PATH):
        return FileResponse(
            PDF_PATH,
            media_type="application/pdf",
        )
    return {
        "error": "PDF 文件不存在",
        "期望路径": PDF_PATH
    }
# ====================================================================================

# ==========================================
# Pydantic 模型
# ==========================================
class ChatRequest(BaseModel):
    query: str
    model: str = "remote"  # "remote" 或 "local"

class ModelStatusResponse(BaseModel):
    remote_available: bool
    local_available: bool
    local_model_name: str

# ==========================================
# 启动事件
# ==========================================
@app.on_event("startup")
async def startup_event():
    """初始化 - 同时尝试加载远程和本地模型"""
    global rag_engine, remote_client, local_client, memory_manager, local_model_available
    print("初始化后端模型...")
    
    # 1. 汽车重启：重置 state.json 和 memory.json
    reset_script = Path(__file__).parent / "utils" / "reset_state.py"
    reset_result = {"state_reset": False, "memory_reset": False, "errors": []}
    
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("reset_state", reset_script)
        reset_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reset_module)
        reset_result = reset_module.reset_all_states(verbose=True)
    except Exception as e:
        print(f"[Reset Error] 导入失败: {e}")
    
    # 2. 初始化RAG引擎
    rag_engine = RAGEngine()
    try:
        rag_engine.milvus.retrieve_topk("warmup query", topk=3)
    except Exception as e:
        print(f"[RAG] 热身查询跳过: {str(e)}")
    print("[RAG] 知识库加载完成")
    
    # 3. 初始化远程LLM客户端（阿里百炼）
    try:
        real_remote_client = LLMClientWrapper()
        remote_client = LoggingLLMClient(real_remote_client, model_name="qwen3.5-flash")
        print("[RemoteLLM] 远程模型加载成功: qwen3.5-flash")
    except Exception as e:
        print(f"[RemoteLLM] 远程模型加载失败: {e}")
        remote_client = None
    
    # 4. 尝试初始化本地vLLM客户端
    try:
        local_vllm = LocalVLLMClient(
            base_url="http://127.0.0.1:8000/v1",
            model_name="qwen-4b-tesla"
        )
        if local_vllm.is_available():
            local_client = LoggingLLMClient(local_vllm, model_name="Qwen3.5-4B-AWQ(local)")
            local_model_available = True
        else:
            print("[LocalLLM] 本地模型不可用，仅使用远程模型")
            local_client = None
            local_model_available = False
    except Exception as e:
        print(f"[LocalLLM] 本地模型初始化失败: {e}")
        local_client = None
        local_model_available = False
    
    # 5. 初始化对话记忆管理器
    memory_manager = get_memory_manager()
    stats = memory_manager.get_memory_stats()
    print(f"[Memory] 对话记忆系统加载完成")
    print(f"[Memory]   - 总记忆数: {stats['total']}")
    print(f"[Memory]   - KNOWLEDGE: {stats['by_type']['KNOWLEDGE']}")
    print(f"[Memory]   - TOOL: {stats['by_type']['TOOL']}")
    print(f"[Memory]   - CHAT: {stats['by_type']['CHAT']}")
    
    print(f"模型加载完成。Web服务已启动: http://localhost:{PORT}")


# ==========================================
# API 端点
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/model-status", response_class=JSONResponse)
async def get_model_status():
    """获取模型状态 - 用于前端判断本地模型是否可用"""
    global local_model_available, remote_client
    
    # 重新检查本地模型状态
    if not local_model_available:
        try:
            test_client = LocalVLLMClient()
            if test_client.is_available():
                local_model_available = True
        except:
            pass
    
    return {
        "remote_available": remote_client is not None,
        "local_available": local_model_available,
        "local_model_name": "Qwen3.5-4B-AWQ(local)"
    }


@app.get("/api/image")
async def get_image(path: str):
    """获取图片"""
    from src.utils import convert_db_path_to_local, to_absolute_path
    
    local_path = to_absolute_path(convert_db_path_to_local(path))
    
    if os.path.exists(local_path):
        return FileResponse(local_path)
    
    if os.path.exists(path):
        return FileResponse(path)
    
    print(f"[图片404] 未找到: {path}")
    return HTMLResponse(status_code=404)

@app.post("/api/reset-state")
async def reset_state():
    """清空车辆状态 state.json 和对话记忆 memory.json"""
    try:
        # 动态加载 reset_state.py，和启动时一样
        reset_script = Path(__file__).parent / "utils" / "reset_state.py"
        spec = importlib.util.spec_from_file_location("reset_state", reset_script)
        reset_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reset_module)
        result = reset_module.reset_all_states(verbose=False)
        
        return JSONResponse({
            "success": True,
            "message": "状态与记忆已重置",
            "detail": result
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """聊天端点 - 支持模型选择"""
    
    # 选择模型客户端
    global remote_client, local_client, local_model_available
    
    selected_client = None
    client_name = ""
    
    if request.model == "local" and local_model_available and local_client:
        selected_client = local_client
        client_name = "local"
        print(f"[ModelSelect] 使用本地模型: Qwen3.5-4B-AWQ")
    else:
        selected_client = remote_client
        client_name = "remote"
        print(f"[ModelSelect] 使用远程模型: qwen3.5-flash")
    
    if not selected_client:
        async def error_generator():
            yield json.dumps({"type": "error", "data": "所选模型不可用，请检查模型状态"}) + "\n"
        return StreamingResponse(error_generator(), media_type="application/x-ndjson")
    
    async def event_generator():
        try:
            query = clean_query(request.query)
            if not query:
                yield json.dumps({"type": "error", "data": "输入无效或为空"}) + "\n"
                return
            
            yield json.dumps({"type": "status", "data": "识别意图中..."}) + "\n"
            yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 分析用户意图...**\n>\n"}) + "\n"
            
            intent_result = recognize_intent(query, selected_client)
            
            yield json.dumps({"type": "intent", "data": {"type": intent_result.intent.value, "confidence": intent_result.confidence, "reason": intent_result.reason}}) + "\n"
            
            intent_log_msg = f"> **[{time.strftime('%H:%M:%S')}] 意图识别结果**: `{intent_result.intent.name}` (置信度: {intent_result.confidence:.2f}, 原因: {intent_result.reason})\n\n---\n\n"
            yield json.dumps({"type": "token", "data": intent_log_msg}) + "\n"
            await asyncio.sleep(0.1)
            
            if intent_result.intent == IntentType.KNOWLEDGE:
                yield json.dumps({"type": "status", "data": "检索知识库中..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 知识查询，检索中(MongoDB+Milvus)...**\n>\n"}) + "\n"
                
                docs = rag_engine.retrieve(query)
                
                if not docs:
                    yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 知识库中未找到相关内容。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 检索到{len(docs)}篇文档，生成回答中...**\n\n---\n\n"}) + "\n"
                
                context_str, context_list = rag_engine.build_context(docs)
                yield json.dumps({"type": "context", "data": context_list}) + "\n"
                
                knowledge_system_prompt = prompts.KNOWLEDGE_SYSTEM_PROMPT
                full_response = ""
                user_prompt_str = f"用户问题: {query}\n\n参考文档:\n{context_str}\n\n请基于参考文档回答。"
                
                if client_name == "remote":
                    # 远程模型 - 非流式
                    try:
                        response = selected_client.chat(
                            system=knowledge_system_prompt,
                            user=user_prompt_str,
                            stream=True
                        )
                        
                        full_response = response.strip()
                        for char in full_response:
                            yield json.dumps({"type": "token", "data": char}) + "\n"
                            await asyncio.sleep(0.01)
                        
                        result = rag_engine.post_process(full_response, docs)
                        cite_pages = [p - 2 for p in result.get("cite_pages", [])]
                        final_data = {"cite_pages": cite_pages, "related_images": result.get("related_images", [])}
                        yield json.dumps({"type": "final", "data": final_data}) + "\n"
                    except Exception as e:
                        yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 远程LLM错误: {str(e)}"}) + "\n"
                else:
                    # 本地模型 - 流式
                    try:
                        import openai
                        local_openai_client = openai.OpenAI(api_key="EMPTY", base_url="http://127.0.0.1:8000/v1")
                        
                        messages = [
                            {"role": "system", "content": knowledge_system_prompt},
                            {"role": "user", "content": user_prompt_str}
                        ]
                        
                        response = local_openai_client.chat.completions.create(
                            model="qwen-4b-tesla", 
                            messages=messages, 
                            temperature=0.3, 
                            stream=True
                        )
                        
                        full_response = ""
                        for chunk in response:
                            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                                content = chunk.choices[0].delta.content
                                full_response += content
                                yield json.dumps({"type": "token", "data": content}) + "\n"
                                await asyncio.sleep(0.01)
                        
                        log_llm_interaction("LOCAL_STREAM_KNOWLEDGE", knowledge_system_prompt, user_prompt_str, full_response)
                        
                        result = rag_engine.post_process(full_response, docs)
                        cite_pages = [p - 2 for p in result.get("cite_pages", [])]
                        final_data = {"cite_pages": cite_pages, "related_images": result.get("related_images", [])}
                        yield json.dumps({"type": "final", "data": final_data}) + "\n"
                    except Exception as e:
                        yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 本地LLM错误: {str(e)}"}) + "\n"
                
                # 保存对话记忆
                # 修复 KNOWLEDGE 记忆保存 —— 正确获取文档标题
                if memory_manager and full_response:
                    try:
                        # 正确写法：对象属性，不是字典 get()
                        titles = []
                        for d in docs[:3]:
                            # 适配 99% 的 Document 对象
                            if hasattr(d, 'title'):
                                titles.append(d.title)
                            elif hasattr(d, 'page_title'):
                                titles.append(d.page_title)
                            else:
                                titles.append("知识库文档")
                        
                        mem_prompt = generate_memory_prompt(
                            MemoryIntentType.KNOWLEDGE, 
                            query, 
                            {
                                "doc_topics": ", ".join(titles),
                                "answer_summary": full_response[:100] + "..." if len(full_response) > 100 else full_response
                            }
                        )
                        summary = selected_client.chat(
                            system="你是一个对话摘要助手。请用一句话简洁地总结用户的问题。只输出总结内容。",
                            user=mem_prompt,
                            stream=False
                        ).strip()
                        memory_manager.add_memory(MemoryIntentType.KNOWLEDGE, summary, query)
                    except Exception as e:
                        print(f"[Memory] 保存KNOWLEDGE记忆失败: {e}")
            
            elif intent_result.intent == IntentType.MULTI_TOOL or intent_result.is_multi:
                yield json.dumps({"type": "status", "data": "执行多任务控制..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 多工具处理(最多3个任务)...**\n\n---\n\n"}) + "\n"
                
                memory_context = ""
                if memory_manager:
                    memory_context = memory_manager.get_memories_for_prompt(query=query, limit=5)
                    if memory_context.strip():
                        yield json.dumps({"type": "token", "data": f"> [Memory] 已加载相关操作历史\n\n"}) + "\n"
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤1: Skills路由...**\n>\n"}) + "\n"
                
                skill_metas = load_all_skill_metas()
                yield json.dumps({"type": "token", "data": f"> 加载了 {len(skill_metas)} 个Skills\n\n"}) + "\n"
                
                selected_skills = route_skills(query, skill_metas, selected_client)
                yield json.dumps({"type": "token", "data": f"> 选中Skill: {selected_skills}\n\n---\n\n"}) + "\n"
                
                if not selected_skills:
                    yield json.dumps({"type": "error", "data": "抱歉，无法处理这些指令。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤2: 多函数选择...**\n>\n"}) + "\n"
                func_calls = select_multiple_functions(query, selected_skills, selected_client)
                
                if not func_calls:
                    yield json.dumps({"type": "error", "data": "抱歉，未找到匹配的函数。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> 找到 {len(func_calls)} 个任务:\n"}) + "\n"
                for i, call in enumerate(func_calls, 1):
                    yield json.dumps({"type": "token", "data": f">   任务{i}: {call.skill}.{call.script} - {call.reason}\n"}) + "\n"
                yield json.dumps({"type": "token", "data": f"\n---\n\n"}) + "\n"
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤3: 执行{len(func_calls)}个任务...**\n\n---\n\n"}) + "\n"
                results = execute_multiple_functions(func_calls)
                
                for item in results:
                    idx = item["index"]
                    call = item["call"]
                    result = item["result"]
                    status = "成功" if result["success"] else "失败"
                    yield json.dumps({"type": "token", "data": f"> 任务{idx} {status}: {call.skill}.{call.script}\n"}) + "\n"
                yield json.dumps({"type": "token", "data": f"\n---\n\n"}) + "\n"
                
                final_message = format_multi_results(results)
                
                for char in final_message:
                    yield json.dumps({"type": "token", "data": char}) + "\n"
                    await asyncio.sleep(0.01)
                
                final_data = {
                    "tool_result": {
                        "task_count": len(func_calls),
                        "tasks": [{"skill": r["call"].skill, "script": r["call"].script, "parameters": r["call"].parameters} for r in results]
                    },
                    "cite_pages": [],
                    "related_images": []
                }
                yield json.dumps({"type": "final", "data": final_data}) + "\n"
                
                if memory_manager:
                    try:
                        tasks_summary = ", ".join([f"{r['call'].skill}.{r['call'].script}" for r in results])
                        mem_prompt = generate_memory_prompt(
                            MemoryIntentType.TOOL, 
                            query, 
                            {
                                "tasks": tasks_summary,
                                "result_summary": f"执行了{len(results)}个任务"
                            }
                        )
                        summary = selected_client.chat(
                            system="你是一个对话摘要助手。请用一句话简洁地总结执行的操作。只输出总结内容。",
                            user=mem_prompt,
                            stream=False
                        ).strip()
                        memory_manager.add_memory(MemoryIntentType.TOOL, summary, query)
                    except Exception as e:
                        print(f"[Memory] 保存MULTI_TOOL记忆失败: {e}")
            
            elif intent_result.intent == IntentType.TOOL:
                yield json.dumps({"type": "status", "data": "执行车辆控制..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 工具处理...**\n\n---\n\n"}) + "\n"
                
                memory_context = ""
                if memory_manager:
                    memory_context = memory_manager.get_memories_for_prompt(query=query, limit=5)
                    if memory_context.strip():
                        yield json.dumps({"type": "token", "data": f"> [Memory] 已加载相关操作历史\n\n"}) + "\n"
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤1: Skills路由...**\n>\n"}) + "\n"
                
                skill_metas = load_all_skill_metas()
                yield json.dumps({"type": "token", "data": f"> 加载了 {len(skill_metas)} 个Skill\n\n"}) + "\n"
                
                selected_skills = route_skills(query, skill_metas, selected_client)
                yield json.dumps({"type": "token", "data": f"> 选中Skill: {selected_skills}\n\n---\n\n"}) + "\n"
                
                if not selected_skills:
                    yield json.dumps({"type": "error", "data": "抱歉，无法处理此指令。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤2: 函数选择...**\n>\n"}) + "\n"
                func_call = select_function(query, selected_skills, selected_client)
                
                if not func_call:
                    yield json.dumps({"type": "error", "data": "抱歉，未找到匹配的函数。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> 选中: {func_call.skill}.{func_call.script}\n> 参数: {func_call.parameters}\n> 原因: {func_call.reason}\n\n---\n\n"}) + "\n"
                
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤3: 执行中...**\n\n---\n\n"}) + "\n"
                result = execute_function(func_call)
                
                call_info = f"{func_call.script}({format_params(func_call.parameters)})"
                if result["success"]:
                    final_message = f"{result['message']} ({call_info})"
                else:
                    final_message = f"操作失败: {result['message']} ({call_info})"
                
                for char in final_message:
                    yield json.dumps({"type": "token", "data": char}) + "\n"
                    await asyncio.sleep(0.01)
                
                final_data = {
                    "tool_result": {
                        "skill": func_call.skill,
                        "script": func_call.script,
                        "parameters": func_call.parameters
                    },
                    "cite_pages": [],
                    "related_images": []
                }
                yield json.dumps({"type": "final", "data": final_data}) + "\n"
                
                if memory_manager:
                    try:
                        mem_prompt = generate_memory_prompt(
                            MemoryIntentType.TOOL, 
                            query, 
                            {
                                "tasks": f"{func_call.skill}.{func_call.script}",
                                "result_summary": result.get("message", "")
                            }
                        )
                        summary = selected_client.chat(
                            system="你是一个对话摘要助手。请用一句话简洁地总结执行的操作。只输出总结内容。",
                            user=mem_prompt,
                            stream=False
                        ).strip()
                        memory_manager.add_memory(MemoryIntentType.TOOL, summary, query)
                    except Exception as e:
                        print(f"[Memory] 保存TOOL记忆失败: {e}")
            
            elif intent_result.intent == IntentType.SEARCH:
                yield json.dumps({"type": "status", "data": "查询车辆状态..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] SEARCH: 查询状态中...**\n\n---\n\n"}) + "\n"
                
                from context.state import load_state
                state = load_state()
                if not state:
                    yield json.dumps({"type": "error", "data": "加载车辆状态失败。"}) + "\n"
                    return
                
                state_data = {k: v for k, v in state.items() if k != "meta"}
                state_json = json.dumps(state_data, ensure_ascii=False, indent=2)
                
                search_system_prompt = prompts.build_search_prompt(state_json)
                search_user_prompt = f"用户查询: {query}\n\n请基于车辆当前状态简洁准确地回答。"
                
                try:
                    response = selected_client.chat(
                        system=search_system_prompt,
                        user=search_user_prompt,
                        stream=False
                    )
                    
                    message = response.strip()
                    for char in message:
                        yield json.dumps({"type": "token", "data": char}) + "\n"
                        await asyncio.sleep(0.01)
                    
                    yield json.dumps({"type": "final", "data": {"cite_pages": [], "related_images": []}}) + "\n"
                    
                    if memory_manager:
                        try:
                            mem_prompt = generate_memory_prompt(
                                MemoryIntentType.CHAT,  
                                query, 
                                {"chat_content": message[:100] + "..." if len(message) > 100 else message}
                            )
                            summary = selected_client.chat(
                                system="你是一个对话摘要助手。请用一句话简洁地总结用户的查询。只输出总结内容。",
                                user=mem_prompt,
                                stream=False
                            ).strip()
                            memory_manager.add_memory(MemoryIntentType.CHAT, summary, query)
                        except Exception as e:
                            print(f"[Memory] 保存SEARCH记忆失败: {e}")
                except Exception as e:
                    yield json.dumps({"type": "error", "data": f"状态查询失败: {str(e)}"}) + "\n"
            
            elif intent_result.intent == IntentType.CHAT:
                yield json.dumps({"type": "status", "data": "思考中..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 闲聊模式...**\n\n---\n\n"}) + "\n"
                
                memory_context = ""
                if memory_manager:
                    memory_context = memory_manager.get_memories_for_prompt(query=None, limit=20)
                    print("memory:",memory_context)
                    if memory_context.strip():
                        yield json.dumps({"type": "token", "data": f"> [Memory] 已加载相关对话历史\n\n"}) + "\n"
                
                chat_system_prompt = prompts.build_chat_prompt_with_memory(memory_context)
                
                try:
                    response = selected_client.chat(
                        system=chat_system_prompt,
                        user=f"用户: {query}\n\n请友好地回答。",
                        stream=True,
                        temperature=0.8
                    )
                    message = response.strip()
                except Exception as e:
                    result = handle_chat_intent(query, selected_client)
                    message = result["message"]
                
                for char in message:
                    yield json.dumps({"type": "token", "data": char}) + "\n"
                    await asyncio.sleep(0.01)
                
                yield json.dumps({"type": "final", "data": {"cite_pages": [], "related_images": []}}) + "\n"
                
                if memory_manager:
                    try:
                        mem_prompt = generate_memory_prompt(
                            MemoryIntentType.CHAT, 
                            query, 
                            {"chat_content": message}
                        )
                        summary = selected_client.chat(
                            system="你是一个对话摘要助手。请用一句话简洁地总结用户的意图。只输出总结内容。",
                            user=mem_prompt,
                            stream=False
                        ).strip()
                        memory_manager.add_memory(MemoryIntentType.CHAT, summary, query)
                    except Exception as e:
                        print(f"[Memory] 保存CHAT记忆失败: {e}")
            else:
                yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 抱歉，我不明白您的意思。"}) + "\n"
        
        except Exception as e:
            err_msg = traceback.format_exc()
            print("\n[后端错误]:")
            print(err_msg)
            error_message = f"\n\n[{time.strftime('%H:%M:%S')}] 系统内部错误: {str(e)}"
            yield json.dumps({"type": "error", "data": error_message}) + "\n"
    
    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
