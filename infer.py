# -*- coding: utf-8 -*-
# 基于 infer11.py，核心改进：
# 1. 支持命令行参数切换：local = 本地vLLM，remote = Moonshot AI (Kimi 2.5)
# 2. 新增 Moonshot AI API 客户端封装
# 3. 保持 V11 的所有功能不变
import os
import sys
import time
import re
import json
import asyncio
import traceback
import importlib.util
import uvicorn
import argparse  # 新增：命令行参数解析
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from pathlib import Path
import ast
# 导入原有库
from src.retriever.bm25_retriever import BM25
from src.retriever.milvus_retriever import MilvusRetriever 
from src.reranker.bge_m3_reranker import BGEM3ReRanker 
from src.constant import bge_reranker_tuned_model_path
from src.utils import merge_docs, post_processing

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

# ================= 命令行参数解析 =================
# 必须在创建FastAPI实例前解析
parser = argparse.ArgumentParser(description='Tesla Multi-Intent Agent V12')
parser.add_argument('mode', nargs='?', default='local', choices=['local', 'remote'],
                    help='运行模式: local=本地vLLM, remote=Moonshot AI (Kimi 2.5)')
parser.add_argument('--port', type=int, default=6006, help='服务端口，默认6006')
args, unknown = parser.parse_known_args()

RUN_MODE = args.mode  # 'local' 或 'remote'
PORT = args.port

print(f"=" * 60)
print(f"Tesla Multi-Intent Agent V12")
print(f"运行模式: {'本地vLLM' if RUN_MODE == 'local' else 'Moonshot AI (Kimi 2.5)'}")
print(f"服务端口: {PORT}")
print(f"=" * 60)

app = FastAPI(title=f"Tesla Multi-Intent Agent V12 - {'Local' if RUN_MODE == 'local' else 'Remote'}")
templates = Jinja2Templates(directory="webui")

# ================= 全局变量 =================
bm25_retriever = None
milvus_retriever = None
bge_m3_reranker = None
llm_client = None
SKILLS_DIR = Path(__file__).parent / "skills"
STATE_DIR = Path(__file__).parent / "state"
STATE_FILE = STATE_DIR / "state.json"

# ================= 本地 vLLM 配置 =================
VLLM_API_BASE = "http://127.0.0.1:8000/v1"
VLLM_API_KEY = "EMPTY"
VLLM_MODEL_NAME = "Qwen3.5-9B"

# ================= Moonshot AI (Kimi) 配置 =================
MOONSHOT_API_BASE = os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1")
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_MODEL_NAME = os.getenv("MOONSHOT_MODEL_NAME", "moonshot-v1-32k")  # Kimi 2.5 模型

# ================= 数据模型 =================
class IntentType(Enum):
    """意图类型枚举"""
    KNOWLEDGE = "knowledge"
    TOOL = "tool"           # 单工具
    MULTI_TOOL = "multi_tool"  # V6
    SEARCH = "search"       # V7新增：多工具
    CHAT = "chat"
    UNKNOWN = "unknown"

@dataclass
class IntentResult:
    """意图识别结果"""
    intent: IntentType
    confidence: float
    reason: str
    is_multi: bool = False  # V6新增：是否为多工具任务

@dataclass
class SkillMeta:
    """轻量级Skill元数据（用于第一层路由）"""
    name: str
    description: str
    functions: List[Dict[str, str]]

@dataclass
class FunctionCall:
    """函数调用结果"""
    skill: str
    script: str
    parameters: Dict[str, Any]
    reason: str

# ================= Prompt定义 =================
INTENT_RECOGNITION_SYSTEM_PROMPT = """你是 Tesla 车载语音系统的意图识别专家，名字叫"小特"。
## 任务
分析用户的自然语言输入，准确判断用户意图属于以下三类之一：
### 1. KNOWLEDGE（知识查询）
用户询问车辆功能、操作方法、故障原因、保养建议、用车技巧等。
- 典型特征：包含"怎么""如何""什么""为什么""多少"等疑问词
- 示例："自动泊车怎么用" -> KNOWLEDGE、"胎压报警什么意思" -> KNOWLEDGE
### 2. TOOL（工具调用 - 单一操作）
用户想直接控制车辆功能、操作车机系统，且只有一个明确的操作指令。
- 典型特征：包含动作指令（打开、关闭、设置、调节、播放、导航等），只有一个动作
- 示例："把空调设置成19度" -> TOOL、"打开后备箱" -> TOOL

### 2.1. MULTI_TOOL（多工具调用）
用户有多个独立的操作指令，或包含"帮我把..."、"帮我..."等表示多个任务的表述。
- 典型特征：包含多个动作（逗号、分号分隔，或"帮我...帮我..."），最多识别3个任务
- 示例：
  - "帮我打开空调26度，帮我打开窗户，帮我打开加热座椅" -> MULTI_TOOL
  - "打开空调并播放音乐" -> MULTI_TOOL
  - "把温度调到20度，然后导航去机场" -> MULTI_TOOL
### 3. SEARCH
用户询问车辆当前状态。
- 示例: "空调多少度" -> SEARCH
### 4. CHAT（闲聊对话）
问候、感谢、询问时间天气、讲笑话、情感交流等非功能性对话。
- 示例："你好" -> CHAT、"讲个笑话" -> CHAT
## 重要区分规则
1. "怎么"开头的句子，问方法是KNOWLEDGE，直接动作是TOOL
2. 包含具体数值（度、%、档）的多半是 TOOL
3. 有歧义时，优先判断为 TOOL
## 返回格式（严格JSON）
{
    "intent": "KNOWLEDGE|TOOL|MULTI_TOOL|SEARCH|CHAT",
    "confidence": 0.95,
    "is_multi": false,
    "reason": "简短说明判断依据"
}
只返回JSON，不要其他文字。"""

KNOWLEDGE_SYSTEM_PROMPT = """你是 Tesla 车载知识助手，名字叫"小特"。你是车辆使用专家，熟悉 Tesla 所有车型的功能、操作方法和用车技巧。

## 任务
基于提供的参考文档，准确回答用户关于车辆的问题。

## 回答原则
1. **引用标注**：这是系统展示图片的核心依据。你必须在回答的末尾，根据你参考的资料序号，严格使用中文方括号标注引用，例如：【1】 或 【1, 2】。
2. **术语对齐**：请完整保留资料中的功能名称（如"方向盘左侧滚动按钮"），不要为了简洁而缩写，以便系统精确匹配示意图。
3. **简洁明了**：用2-4句话给出核心答案。
4. **安全提醒**：涉及安全操作（如 Autopilot 或车窗控制）时必须提醒用户注意安全。

## 语气风格
- 专业、友好、直接陈述事实，不使用"根据文档"等生硬词汇。

## 输出示例
用户：怎么调节后视镜？
小特：您可以通过中控屏点击"控制" > "后视镜"，然后使用方向盘左侧的滚动按钮进行调节。调节时请确保车辆处于停车状态以保障安全。【1, 2】"""

CHAT_SYSTEM_PROMPT = """你是 Tesla 车载语音助手，名字叫"小特"。你是用户的贴心伙伴，性格友好、幽默、乐于助人。
## 对话风格
1. **口语化**：像朋友聊天，避免书面语
2. **简短精炼**：每次回复控制在1-3句话
3. **适度幽默**：偶尔说点俏皮话
4. **适时回控**：闲聊中自然地把话题引回车辆
5.输出不要有任何的图标
## 边界约束
- 不涉及政治、宗教等敏感话题
- 不提供医疗、法律等专业建议
- 用户情绪激动时提醒专注驾驶
请自然、友好地回复用户。"""

# ================= V12: Moonshot AI 客户端 =================
class MoonshotClient:
    """Moonshot AI (Kimi) API 客户端"""
    def __init__(self):
        self.api_key = MOONSHOT_API_KEY
        self.base_url = MOONSHOT_API_BASE
        self.model = MOONSHOT_MODEL_NAME
        
    def chat(self, system: str, user: str, stream: bool = False) -> str:
        """调用 Moonshot AI API"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=1,
                stream=stream
            )
            if stream:
                # 流式返回需要特殊处理
                return response
            return response.choices[0].message.content
        except Exception as e:
            print(f"[Moonshot API调用失败]: {e}")
            raise

# ================= V5 新增：YAML解析和Skill加载 =================
def parse_yaml_frontmatter(content: str) -> Tuple[Dict, str]:
    """解析YAML frontmatter，返回(frontmatter_dict, body)"""
    if not content.startswith('---'):
        return {}, content
    
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content
    
    yaml_content = parts[1].strip()
    body = parts[2].strip()
    
    result = {}
    current_key = None
    current_list = None
    lines = yaml_content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.startswith('#'):
            i += 1
            continue
        
        if line.strip().startswith('- ') and current_key:
            if current_list is None:
                current_list = []
            item_text = line.strip()[2:].strip()
            if ':' in item_text:
                key, value = item_text.split(':', 1)
                if current_list and isinstance(current_list[-1], dict):
                    current_list[-1][key.strip()] = value.strip()
                else:
                    current_list.append({key.strip(): value.strip()})
            i += 1
            continue
        
        if ':' in line and not line.startswith(' '):
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None
            
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            if value:
                result[key] = value
            else:
                current_key = key
        
        i += 1
    
    if current_key and current_list is not None:
        result[current_key] = current_list
    
    return result, body

def load_skill_meta(skill_dir: Path) -> Optional[SkillMeta]:
    """加载Skill的轻量级元数据"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    
    try:
        content = skill_md.read_text(encoding='utf-8')
        frontmatter, body = parse_yaml_frontmatter(content)
        
        name = frontmatter.get('name', skill_dir.name)
        description = frontmatter.get('description', '')
        
        functions = []
        metadata = frontmatter.get('metadata', {})
        if isinstance(metadata, dict):
            funcs = metadata.get('functions', [])
            for func in funcs:
                if isinstance(func, dict):
                    functions.append({
                        "name": func.get('name', ''),
                        "description": func.get('description', '')
                    })
        
        return SkillMeta(name=name, description=description, functions=functions)
    except Exception as e:
        print(f"[Skill加载] 加载 {skill_dir.name} 失败: {e}")
        return None

def load_all_skill_metas() -> List[SkillMeta]:
    """加载所有Skill的元数据"""
    metas = []
    for skill_dir in SKILLS_DIR.iterdir():
        if skill_dir.is_dir():
            meta = load_skill_meta(skill_dir)
            if meta:
                metas.append(meta)
    return metas

def load_skill_detail(skill_name: str) -> str:
    """加载Skill的完整详情（函数参数等）"""
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_md.exists():
        return ""
    
    try:
        content = skill_md.read_text(encoding='utf-8')
        _, body = parse_yaml_frontmatter(content)
        return body
    except Exception as e:
        print(f"[Skill详情] 加载 {skill_name} 详情失败: {e}")
        return ""

def get_skill_handler(skill_name: str):
    """获取skill的handler模块（V9: 返回execute包装函数）"""
    try:
        handler_path = SKILLS_DIR / skill_name / "scripts" / "handler.py"
        if not handler_path.exists():
            return None
        
        spec = importlib.util.spec_from_file_location(f"skill_{skill_name}", handler_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if hasattr(module, 'execute'):
            original_execute = module.execute
            
            # V9: 包装execute函数，自动传入state_file
            def wrapped_execute(script: str, parameters: Dict[str, Any]):
                return original_execute(script, parameters, str(STATE_FILE))
            
            return wrapped_execute
        return None
    except Exception as e:
        print(f"[Handler] 加载 {skill_name} handler 失败: {e}")
        return None


# ================= V10 新增: 完整参数提取与合并 =================
def extract_function_signatures(skill_name: str) -> Dict[str, Dict[str, Any]]:
    """
    V10: 从handler.py中提取函数的完整签名信息
    
    返回: {
        "function_name": {
            "params": [
                {"name": "param1", "default": value, "type": "int/str/bool/..."},
                ...
            ],
            "docstring": "函数文档字符串"
        }
    }
    """
    try:
        handler_path = SKILLS_DIR / skill_name / "scripts" / "handler.py"
        if not handler_path.exists():
            return {}
        
        content = handler_path.read_text(encoding='utf-8')
        tree = ast.parse(content)
        functions = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_name = node.name
                # 跳过内部辅助函数
                if func_name.startswith('_') or func_name == 'execute':
                    continue
                
                params = []
                # 处理参数（跳过第一个state_file参数）
                args = node.args.args
                defaults = node.args.defaults
                
                # 计算默认值起始索引
                defaults_start = len(args) - len(defaults)
                
                for i, arg in enumerate(args):
                    param_name = arg.arg
                    # 跳过state_file参数
                    if param_name == 'state_file':
                        continue
                    
                    # 获取默认值
                    default_value = None
                    if i >= defaults_start:
                        default_node = defaults[i - defaults_start]
                        try:
                            if isinstance(default_node, ast.Constant):
                                default_value = default_node.value
                            elif isinstance(default_node, ast.NameConstant):
                                default_value = default_node.value
                            elif isinstance(default_node, ast.Str):
                                default_value = default_node.s
                            elif isinstance(default_node, ast.Num):
                                default_value = default_node.n
                            elif isinstance(default_node, ast.List):
                                default_value = []
                            elif isinstance(default_node, ast.Dict):
                                default_value = {}
                        except:
                            default_value = None
                    
                    # 获取类型注解
                    param_type = "any"
                    if arg.annotation:
                        if isinstance(arg.annotation, ast.Name):
                            param_type = arg.annotation.id
                        elif isinstance(arg.annotation, ast.Subscript):
                            param_type = "list/dict"
                    
                    params.append({
                        "name": param_name,
                        "default": default_value,
                        "type": param_type
                    })
                
                # 获取文档字符串
                docstring = ast.get_docstring(node) or ""
                
                functions[func_name] = {
                    "params": params,
                    "docstring": docstring
                }
        
        return functions
    except Exception as e:
        print(f"[V10] 提取 {skill_name} 函数签名失败: {e}")
        return {}


def get_function_full_schema(skill_name: str, function_name: str) -> Optional[Dict[str, Any]]:
    """V10: 获取指定函数的完整参数结构"""
    signatures = extract_function_signatures(skill_name)
    return signatures.get(function_name)


def build_complete_function_prompt(skill_names: List[str]) -> str:
    """
    V10: 构建包含完整参数定义的函数说明
    """
    sections = []
    
    for skill_name in skill_names:
        # 获取函数签名
        signatures = extract_function_signatures(skill_name)
        if not signatures:
            continue
        
        skill_section = [f"## {skill_name} 技能"]
        
        for func_name, func_info in signatures.items():
            params_desc = []
            for param in func_info["params"]:
                default_str = f" (默认值: {param['default']})" if param['default'] is not None else ""
                params_desc.append(f"  - {param['name']}: {param['type']}{default_str}")
            
            doc = func_info["docstring"].strip() if func_info["docstring"] else ""
            doc_lines = doc.split('\n')[:2]  # 只取前两行
            doc_short = ' '.join(doc_lines).strip()
            
            func_desc = f"""### {func_name}
功能: {doc_short}
参数:
{chr(10).join(params_desc) if params_desc else '  (无参数)'}
"""
            skill_section.append(func_desc)
        
        sections.append('\n'.join(skill_section))
    
    return '\n\n'.join(sections)


def merge_parameters_with_state(skill_name: str, function_name: str, llm_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    V10: 合并LLM返回的参数与当前状态值
    
    策略:
    1. 获取函数的所有参数定义
    2. 从state.json获取当前值
    3. LLM提供的参数覆盖当前值
    4. 未提供的参数使用当前值或默认值
    
    Args:
        skill_name: 技能名称
        function_name: 函数名
        llm_params: LLM返回的参数
    
    Returns:
        完整的参数字典
    """
    # 获取函数签名
    schema = get_function_full_schema(skill_name, function_name)
    if not schema:
        print(f"[V10 警告] 无法获取 {skill_name}.{function_name} 的签名，直接返回LLM参数")
        return llm_params
    
    # 获取当前状态
    state = load_state()
    current_values = {}
    
    if skill_name in state and function_name in state[skill_name]:
        current_values = state[skill_name][function_name]
        print(f"[V10] 当前状态值: {current_values}")
    
    # 构建完整参数
    complete_params = {}
    
    for param_def in schema["params"]:
        param_name = param_def["name"]
        default_value = param_def["default"]
        
        if param_name in llm_params:
            # LLM提供了这个参数，使用LLM的值
            complete_params[param_name] = llm_params[param_name]
            print(f"[V10] {param_name}: 使用LLM值 = {llm_params[param_name]}")
        elif param_name in current_values:
            # 使用当前状态值
            complete_params[param_name] = current_values[param_name]
            print(f"[V10] {param_name}: 使用当前状态值 = {current_values[param_name]}")
        elif default_value is not None:
            # 使用默认值
            complete_params[param_name] = default_value
            print(f"[V10] {param_name}: 使用默认值 = {default_value}")
        else:
            # 无默认值，保留为None或跳过
            print(f"[V10 警告] {param_name}: 无值可用")
    
    print(f"[V10] 合并后完整参数: {complete_params}")
    return complete_params


# ================= V7: State Management =================
def load_state():
    """Load vehicle state from JSON file"""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"[State] Load failed: {e}")
        return {}

def save_state(state):
    """Save vehicle state to JSON file"""
    try:
        state["meta"]["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[State] Save failed: {e}")

def update_state(skill, function, parameters):
    """Update state after TOOL execution"""
    state = load_state()
    if skill not in state:
        state[skill] = {}
    if function not in state[skill]:
        state[skill][function] = {}
    for key, value in parameters.items():
        state[skill][function][key] = value
    save_state(state)
    print(f"[State] Updated {skill}.{function}: {parameters}")

# ================= V8 新增: State-Aware 工具选择 =================
def get_relevant_state(skill_names: List[str]) -> Dict[str, Any]:
    """
    根据选中的Skills获取相关的当前状态
    
    Args:
        skill_names: 选中的Skill名称列表
    
    Returns:
        相关的状态数据字典
    """
    state = load_state()
    print(f"[State] 加载state.json: {len(state)} 个skill")
    
    relevant_state = {}
    
    for skill_name in skill_names:
        print(f"[State] 检查skill: {skill_name}")
        if skill_name in state:
            # 只返回该skill的状态（排除meta）
            skill_state = {k: v for k, v in state[skill_name].items() if k != "meta"}
            if skill_state:
                relevant_state[skill_name] = skill_state
                print(f"[State] 找到 {skill_name} 状态: {list(skill_state.keys())}")
        else:
            print(f"[State] {skill_name} 不在state中")
    
    return relevant_state

def extract_json(text: str) -> dict:
    """从文本中提取 JSON"""
    text = text.strip()
    try:
        return json.loads(text)
    except:
        pass
    
    json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    matches = re.findall(json_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except:
            pass
    
    brace_pattern = r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'
    matches = re.findall(brace_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except:
            pass
    
    raise json.JSONDecodeError("无法解析 JSON", text, 0)

# ================= 初始化 =================
@app.on_event("startup")
async def startup_event():
    global bm25_retriever, milvus_retriever, bge_m3_reranker, llm_client
    print("正在初始化后端模型，请稍候...")
    
    # 初始化检索组件（本地模式需要）
    if RUN_MODE == 'local':
        bm25_retriever = BM25(docs=None, retrieve=True)
        milvus_retriever = MilvusRetriever(docs=None, retrieve=True) 
        bge_m3_reranker = BGEM3ReRanker(model_path=bge_reranker_tuned_model_path)
        milvus_retriever.retrieve_topk("这是一条预热数据", topk=3)
    
    # 初始化 LLM 客户端（根据模式选择）
    llm_client = LLMClientWrapper()
    print(f"模型加载完毕，Web 服务已启动！访问 http://localhost:{PORT}")

# ================= V12: LLM 客户端包装器（支持本地/远程双模式）=================
class LLMClientWrapper:
    """V12: 统一的 LLM 客户端，支持本地vLLM和Moonshot AI"""
    
    def __init__(self):
        self.mode = RUN_MODE
        if self.mode == 'remote':
            self.moonshot_client = MoonshotClient()
            print("[LLM] 使用 Moonshot AI (Kimi 2.5)")
        else:
            print("[LLM] 使用本地 vLLM")
    
    def chat(self, system: str, user: str, stream: bool = False) -> str:
        """统一的 chat 接口"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        
        if self.mode == 'remote':
            # 远程模式：使用 Moonshot AI
            return self.moonshot_client.chat(system, user, stream)
        else:
            # 本地模式：使用 vLLM
            try:
                import openai
                client = openai.OpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)
                response = client.chat.completions.create(
                    model=VLLM_MODEL_NAME, 
                    messages=messages,  
                    temperature=0.3, 
                    stream=stream
                )
                if stream:
                    return response
                return response.choices[0].message.content
            except Exception as e:
                print(f"[LLM本地调用失败]: {e}")
                raise

# ================= 意图识别（与infer3一致）=================
def recognize_intent(query: str) -> IntentResult:
    """LLM意图识别（V6支持MULTI_TOOL）"""
    user_prompt = f"""用户输入："{query}"
请分析意图并返回JSON。"""
    try:
        response = llm_client.chat(system=INTENT_RECOGNITION_SYSTEM_PROMPT, user=user_prompt, stream=False)
        result = json.loads(response.strip())
        intent_str = result.get("intent", "UNKNOWN").upper()
        confidence = float(result.get("confidence", 0.5))
        reason = result.get("reason", "LLM识别")
        is_multi = result.get("is_multi", False)
        
        intent_map = {
            "KNOWLEDGE": IntentType.KNOWLEDGE, 
            "TOOL": IntentType.TOOL, 
            "MULTI_TOOL": IntentType.MULTI_TOOL,
            "SEARCH": IntentType.SEARCH,
            "CHAT": IntentType.CHAT
        }
        intent = intent_map.get(intent_str, IntentType.UNKNOWN)
        
        # 如果识别为MULTI_TOOL，自动设置is_multi
        if intent == IntentType.MULTI_TOOL:
            is_multi = True
            
        return IntentResult(intent=intent, confidence=confidence, reason=reason, is_multi=is_multi)
    except Exception as e:
        print(f"[意图识别失败]: {e}")
        return _fallback_intent_recognition(query)

def _fallback_intent_recognition(query: str) -> IntentResult:
    """意图识别失败时的回退策略（V7支持SEARCH检测）"""
    text = query.lower().strip()
    
    # V7: Detect SEARCH intent
    search_keywords = ["当前", "现在", "多少度", "开了吗", "关了吗", "状态", "是多少", "温度多少", "音量多少"]
    for kw in search_keywords:
        if kw in text:
            return IntentResult(intent=IntentType.SEARCH, confidence=0.7, 
                              reason=f"Fallback: contains search keyword '{kw}'", is_multi=False)
    
    # V6: 检测多工具任务
    multi_tool_markers = ["，", ",", "；", ";", "然后", "接着", "再", "帮我", "顺便"]
    action_keywords = ["打开", "关闭", "设置", "调节", "播放", "导航", "调到", "升温", "降温"]
    action_count = sum(1 for kw in action_keywords if kw in text)
    has_separator = any(marker in query for marker in multi_tool_markers)
    
    # 如果有多个动作或分隔符，可能是多工具任务
    if action_count >= 2 or (action_count >= 1 and has_separator):
        return IntentResult(intent=IntentType.MULTI_TOOL, confidence=0.6, 
                          reason=f"回退：检测到{action_count}个可能动作", is_multi=True)
    
    # 单工具检测
    for kw in action_keywords:
        if kw in text:
            return IntentResult(intent=IntentType.TOOL, confidence=0.7, 
                              reason=f"回退：包含工具关键词'{kw}'", is_multi=False)
    
    # 知识检测
    knowledge_patterns = [r"怎么.*用", r"什么.*意思", r"如何", r"为什么", r"多少", r"吗", r"呢"]
    for pattern in knowledge_patterns:
        if re.search(pattern, text):
            return IntentResult(intent=IntentType.KNOWLEDGE, confidence=0.7, 
                              reason=f"回退：匹配知识模式'{pattern}'", is_multi=False)
    
    return IntentResult(intent=IntentType.CHAT, confidence=0.6, 
                       reason="回退：默认判断为闲聊", is_multi=False)


# ================= V6 新增：多TOOL处理 =================
def build_multi_function_selection_prompt(skill_names: List[str], query: str, current_state: Dict[str, Any] = None) -> str:
    """
    V12: 构建包含完整参数定义的State-Aware多函数选择Prompt
    
    Args:
        skill_names: 选中的Skill名称列表
        query: 用户查询
        current_state: 当前车辆状态（可选）
    """
    # V10: 获取完整的函数参数定义
    complete_function_defs = build_complete_function_prompt(skill_names)
    
    # V8: 添加当前状态信息
    state_text = ""
    if current_state:
        state_json = json.dumps(current_state, ensure_ascii=False, indent=2)
        state_text = f"""
## 当前车辆状态（执行前）
以下是与选中Skills相关的当前车辆状态数据。这是当前各参数的实际值，你可以根据这些值进行相对计算：
```json
{state_json}
```
"""
    
    # V12: 如果涉及 media skill，添加音乐库/电台提示
    media_hint = ""
    if "media" in skill_names:
        media_hint = """
## 【重要提示】Media Skill 选择规则
当调用 `media.music_control` 播放本地音乐时：
1. **必须**从 media skill 文档中定义的20首本地音乐库中选择
2. **必须**同时提供完整的三个参数：artist（艺人）、title（歌名）、album（专辑）
3. 如果用户只说"播放周杰伦"，选择该艺人的第一首歌并填写完整信息
4. 如果用户指定的歌曲不在20首库中，不要编造，应返回错误

当调用 `media.radio_control` 播放电台时：
1. **必须**从 media skill 文档中定义的10个预设电台中选择
2. **必须**提供：band（波段）、frequency（频率）、station_name（电台名）
"""
    
    return f"""你是Tesla车载系统的多任务处理模块。

## 用户指令（可能包含多个操作）
"{query}"
{state_text}{media_hint}
## 可用函数及其完整参数定义（V10）
每个函数列出了所有可用参数及其默认值。每个任务都必须返回所有参数的值：

{complete_function_defs}

## 任务
分析用户指令，识别出所有独立的操作任务（最多3个），为每个任务选择最合适的函数。

## 重要规则（V10 State-Aware 完整参数）

### 1. **每个任务必须返回所有参数（强制要求）**
每个任务的parameters必须包含该函数的**所有参数**，格式如下：
```json
{{
    "tasks": [
        {{
            "task_id": 1,
            "skill": "skill名称",
            "script": "函数名",
            "parameters": {{
                "param1": "当前状态值或LLM计算的新值",
                "param2": "当前状态值或LLM计算的新值",
                "param3": "当前状态值或LLM计算的新值"
                // ... 所有参数都必须包含
            }}
        }}
    ]
}}
```
**错误示例**（只返回变更参数）：`{{"parameters": {{"enable": true}}}}` 
**正确示例**（返回所有参数）：`{{"parameters": {{"enable": true, "auto_mode": "comfort", "...": "..."}}}}`

### 2. **相对值计算由你完成**
- 如果用户说"调高一点"、"温度降低2度"等相对指令，你必须根据当前状态计算出绝对值
- 例如：当前温度24度，用户说"调低2度" -> 参数应为 `"value": 22`

### 3. **未变更参数使用当前状态值**
- 对于用户没有明确提及的参数，直接使用"当前车辆状态"中提供的值
- 如果当前状态中没有该值，使用函数定义中的默认值

### 4. **区域识别**
- 用户说"副驾"、"后排"等，正确识别zone/position参数
- 未指定区域时，默认使用 "all" 或当前状态的区域

## 返回格式（严格JSON）
{{
    "tasks": [
        {{
            "task_id": 1,
            "skill": "skill名称",
            "script": "函数名",
            "parameters": {{
                // 必须包含该函数的所有参数
                "参数名1": "值1（当前状态值或LLM计算的新值）",
                "参数名2": "值2（当前状态值或LLM计算的新值）",
                "参数名3": "值3（当前状态值或LLM计算的新值）"
            }},
            "description": "简要说明：1)为什么选择这个函数；2)参数值如何确定（哪些来自当前状态，哪些是LLM计算的）"
        }}
    ],
    "reason": "简要说明为什么这样分解任务"
}}

如果没有匹配的功能，返回：`{{"tasks": [], "reason": "不支持这些功能"}}`"""

def select_multiple_functions(query: str, skill_names: List[str]) -> List[FunctionCall]:
    """
    V10: State-Aware 多函数选择 + 完整参数合并
    在执行函数选择前，先获取相关的当前状态，让LLM根据状态计算相对值
    然后合并每个任务的参数与当前状态，确保返回所有参数
    """
    # V8: 获取相关状态
    current_state = get_relevant_state(skill_names)
    if current_state:
        print(f"[多任务状态感知 V10] 当前状态: {json.dumps(current_state, ensure_ascii=False)}")
    
    # V10: 使用包含完整参数定义的prompt
    prompt = build_multi_function_selection_prompt(skill_names, query, current_state)
    
    try:
        response = llm_client.chat(system=prompt, user="请分析用户指令并返回多个函数调用（每个任务必须包含所有参数）。", stream=False)
        result = extract_json(response)
        tasks = result.get("tasks", [])
        
        calls = []
        for task in tasks:
            skill = task.get("skill")
            script = task.get("script")
            llm_parameters = task.get("parameters", {})
            description = task.get("description", "")
            
            if skill and script:
                # V10: 合并参数 - 确保返回所有参数
                print(f"[多函数选择 V10] 任务 {skill}.{script} LLM参数: {llm_parameters}")
                complete_parameters = merge_parameters_with_state(skill, script, llm_parameters)
                print(f"[多函数选择 V10] 任务 {skill}.{script} 完整参数: {complete_parameters}")
                
                calls.append(FunctionCall(
                    skill=skill, 
                    script=script, 
                    parameters=complete_parameters, 
                    reason=description
                ))
        
        # 限制最多3个任务
        return calls[:3]
    except Exception as e:
        print(f"[多函数选择 V10] 失败: {e}")
        import traceback
        traceback.print_exc()
        return []

def execute_multiple_functions(calls: List[FunctionCall]) -> List[Dict[str, Any]]:
    """V6: 顺序执行多个函数"""
    results = []
    for i, call in enumerate(calls, 1):
        print(f"[多任务执行] 任务{i}/{len(calls)}: {call.skill}.{call.script}")
        result = execute_function(call)
        results.append({
            "index": i,
            "call": call,
            "result": result
        })
    return results

def format_multi_results(results: List[Dict[str, Any]]) -> str:
    """V6: 格式化多任务执行结果"""
    messages = []
    for item in results:
        call = item["call"]
        result = item["result"]
        call_info = f"{call.script}({format_params(call.parameters)})"
        
        if result["success"]:
            messages.append(f"{result['message']} ({call_info})")
        else:
            messages.append(f"操作失败: {result['message']} ({call_info})")
    
    return "；".join(messages)


# ================= V5 新增：分层TOOL处理 =================
def build_skill_routing_prompt(skill_metas: List[SkillMeta]) -> str:
    """构建Skill路由Prompt（轻量级）"""
    skill_list = []
    for meta in skill_metas:
        funcs = ", ".join([f["name"] for f in meta.functions])
        skill_list.append(f"- {meta.name}: {meta.description} (函数: {funcs})")
    
    skills_text = "\n".join(skill_list)
    
    return f"""你是Tesla车载系统的Skill路由模块。

根据用户指令，选择最相关的Skill（一个或多个）。

## 可用Skills
{skills_text}

## 重要路由规则
1. **音乐播放控制**（播放/暂停/停止、选歌）-> 使用 media.music_control
2. **音乐切换**（上一首/下一首）-> 使用 media.music_switch
3. **电台播放控制**（播放/暂停/停止、选台）-> 使用 media.radio_control
4. **电台切换**（上一个/下一个电台）-> 使用 media.radio_switch
5. **音量控制**（调高/调低/静音）-> 使用 media.volume_control
6. **车窗控制** -> 使用 hardware.control_window
7. **灯光控制** -> 使用 hardware.control_lighting
8. **后备箱/车门** -> 使用 hardware skill

## 返回格式（严格JSON）
{{
    "skills": ["skill名称1", "skill名称2"],
    "reason": "简要说明为什么选择这些skills"
}}

如果无法匹配任何Skill，返回：`{{"skills": [], "reason": "不匹配"}}`"""

def route_skills(query: str, skill_metas: List[SkillMeta]) -> List[str]:
    """Skill路由：选择可能相关的Skills"""
    prompt = build_skill_routing_prompt(skill_metas)
    try:
        response = llm_client.chat(system=prompt, user=f"用户指令：{query}", stream=False)
        result = extract_json(response)
        return result.get("skills", [])
    except Exception as e:
        print(f"[Skill路由] 失败: {e}")
        return []

def build_function_selection_prompt(skill_names: List[str], query: str, current_state: Dict[str, Any] = None) -> str:
    """
    V12: 构建包含完整参数定义的State-Aware函数选择Prompt
    
    Args:
        skill_names: 选中的Skill名称列表
        query: 用户查询
        current_state: 当前车辆状态（可选）
    """
    # V10: 获取完整的函数参数定义
    complete_function_defs = build_complete_function_prompt(skill_names)
    
    # V8: 添加当前状态信息
    state_text = ""
    if current_state:
        state_json = json.dumps(current_state, ensure_ascii=False, indent=2)
        state_text = f"""
## 当前车辆状态（执行前）
以下是与选中Skills相关的当前车辆状态数据。这是当前各参数的实际值，你可以根据这些值进行相对计算：
```json
{state_json}
```
"""
    
    # V12: 如果涉及 media skill，添加音乐库/电台提示
    media_hint = ""
    if "media" in skill_names:
        media_hint = """
## 【重要提示】Media Skill 选择规则
当调用 `media.music_control` 播放本地音乐时：
1. **必须**从 media skill 文档中定义的20首本地音乐库中选择
2. **必须**同时提供完整的三个参数：artist（艺人）、title（歌名）、album（专辑）
3. 如果用户只说"播放周杰伦"，选择该艺人的第一首歌并填写完整信息
4. 如果用户指定的歌曲不在20首库中，不要编造，应返回错误

当调用 `media.radio_control` 播放电台时：
1. **必须**从 media skill 文档中定义的10个预设电台中选择
2. **必须**提供：band（波段）、frequency（频率）、station_name（电台名）
"""
    
    return f"""你是Tesla车载系统的函数选择模块。

## 用户指令
"{query}"
{state_text}{media_hint}
## 可用函数及其完整参数定义（V10）
每个函数列出了所有可用参数及其默认值。你必须返回所有参数的值：

{complete_function_defs}

## 任务
从上述函数中选择最合适的函数，返回该函数的**所有参数**（不是只返回变更的参数）。

## 重要规则（V10 State-Aware 完整参数）

### 1. **返回所有参数（强制要求）**
你必须返回函数的**所有参数**，格式如下：
```json
{{
    "skill": "skill名称",
    "script": "函数名", 
    "parameters": {{
        "param1": "当前状态值或LLM计算的新值",
        "param2": "当前状态值或LLM计算的新值",
        "param3": "当前状态值或LLM计算的新值"
        // ... 所有参数都必须包含
    }},
    "reason": "简要说明：1)为什么选择这个函数；2)每个参数值是如何确定的（哪些来自当前状态，哪些是LLM计算的）"
}}
```
如果没有匹配的功能，返回：`{{"skill": null, "reason": "不支持此功能"}}`

**错误示例**（只返回变更参数）：`{{"parameters": {{"enable": true}}}}`
**正确示例**（返回所有参数）：`{{"parameters": {{"enable": true, "auto_mode": "comfort", "...": "..."}}}}`

### 2. **相对值计算由你完成**
- 如果用户说"调高一点"、"温度降低2度"等相对指令，你必须根据当前状态计算出绝对值
- 例如：当前温度24度，用户说"调低2度" -> 参数应为 `"value": 22`
- 例如：当前座椅加热level=1，用户说"加热调高一点" -> 参数应为 `"level": 2`

### 3. **未变更参数使用当前状态值**
- 对于用户没有明确提及的参数，直接使用"当前车辆状态"中提供的值
- 如果当前状态中没有该值，使用函数定义中的默认值

### 4. **开关状态判断**
- 如果用户说"打开"但当前已是开启状态，可以返回当前值或适当调高
- 如果用户说"关闭"但当前已是关闭状态，保持关闭状态

### 5. **区域识别**
- 用户说"副驾"、"后排"等，正确识别zone/position参数
- 未指定区域时，默认使用 "all" 或当前状态的区域

### 6. **严格名称匹配（防幻觉）**
- 返回的 "skill" 和 "script" 字段必须**一字不差**地从上述提供的可用函数中复制。
- 绝对不要自行添加 `_control` 等后缀！例如，如果我提供的技能叫 `media`，你就只能输出 `media`，绝不允许输出 `media_control`。
- 绝对不要自行添加不存在的函数参数`。
"""

def select_function(query: str, skill_names: List[str]) -> Optional[FunctionCall]:
    """
    V10: State-Aware 函数选择 + 完整参数合并
    在执行函数选择前，先获取相关的当前状态，让LLM根据状态计算相对值
    然后合并LLM返回的参数与当前状态，确保返回所有参数
    """
    # V8: 获取相关状态
    current_state = get_relevant_state(skill_names)
    if current_state:
        print(f"[状态感知] 当前状态: {json.dumps(current_state, ensure_ascii=False)}")
    
    # V10: 使用包含完整参数定义的prompt
    prompt = build_function_selection_prompt(skill_names, query, current_state)
    print(f"[函数选择 V10] Prompt长度: {len(prompt)} 字符")
    
    try:
        response = llm_client.chat(system=prompt, user="请分析用户指令并返回函数调用参数（必须包含所有参数）。", stream=False)
        print(f"[函数选择 V10] LLM原始响应:\n{response[:800]}...")  # 打印前800字符
        
        result = extract_json(response)
        print(f"[函数选择 V10] 解析结果: {result}")
        
        skill = result.get("skill")
        script = result.get("script")
        llm_parameters = result.get("parameters", {})
        reason = result.get("reason", "")
        
        print(f"[函数选择 V10] LLM返回参数: {llm_parameters}")
        
        if not skill or not script:
            print(f"[函数选择 V10] 失败: skill或script为空")
            return None
        
        # V10: 合并参数 - 确保返回所有参数
        complete_parameters = merge_parameters_with_state(skill, script, llm_parameters)
        
        print(f"[函数选择 V10] 最终完整参数: {complete_parameters}")
        
        return FunctionCall(skill=skill, script=script, parameters=complete_parameters, reason=reason)
    except Exception as e:
        print(f"[函数选择 V10] 失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def execute_function(call: FunctionCall) -> Dict[str, Any]:
    """执行函数调用 (V9: handler直接管理state.json)"""
    handler = get_skill_handler(call.skill)
    if not handler:
        return {"success": False, "message": f"找不到Skill: {call.skill}", "data": None}
    
    try:
        # V9: handler 现在直接读写 state.json
        # 包装函数会自动传入 state_file 参数
        result = handler(call.script, call.parameters)
        
        # V9: 验证 state.json 是否被更新
        if result.get("success", False):
            # 可选：验证状态已更新（用于调试）
            current_state = load_state()
            if call.skill in current_state:
                print(f"[State V9] 验证: {call.skill} 状态已更新")
        
        return result
    except Exception as e:
        import traceback
        return {"success": False, "message": f"执行失败: {str(e)}", "data": {"traceback": traceback.format_exc()}}

def format_params(params: Dict[str, Any]) -> str:
    """格式化参数字符串"""
    parts = []
    for k, v in params.items():
        if isinstance(v, str):
            parts.append(f'{k}="{v}"')
        else:
            parts.append(f'{k}={v}')
    return ", ".join(parts)


# ================= V5 TOOL处理入口 =================
def handle_tool_intent_v5(query: str) -> Dict[str, Any]:
    """V5分层TOOL处理入口（单工具）"""
    print(f"[TOOL V5] 处理: {query}")
    
    # 步骤1: Skill路由
    skill_metas = load_all_skill_metas()
    selected_skills = route_skills(query, skill_metas)
    print(f"[TOOL V5] 选中Skills: {selected_skills}")
    
    if not selected_skills:
        return {"success": False, "message": "抱歉，我暂时无法处理这个指令。", "data": {"reason": "无匹配Skill"}}
    
    # 步骤2: 函数选择
    func_call = select_function(query, selected_skills)
    if not func_call:
        return {"success": False, "message": "抱歉，我找不到对应的功能。", "data": {"reason": "无匹配函数"}}
    
    print(f"[TOOL V5] 选中函数: {func_call.skill}.{func_call.script}")
    
    # 步骤3: 执行函数
    result = execute_function(func_call)
    
    # 步骤4: 构造结果（语义信息 + 函数调用信息）
    call_info = f"{func_call.script}({format_params(func_call.parameters)})"
    if result["success"]:
        final_message = f"{result['message']} ({call_info})"
    else:
        final_message = f"操作失败: {result['message']} ({call_info})"
    
    return {
        "success": result["success"],
        "message": final_message,
        "data": {
            "skill": func_call.skill,
            "script": func_call.script,
            "parameters": func_call.parameters,
            "raw_result": result
        }
    }

# ================= V6 新增：多TOOL处理入口 =================
def handle_multi_tool_intent_v6(query: str) -> Dict[str, Any]:
    """V6多TOOL处理入口（支持最多3个任务）"""
    print(f"[MULTI_TOOL V6] 处理: {query}")
    
    # 步骤1: Skill路由（获取更广泛的skills）
    skill_metas = load_all_skill_metas()
    selected_skills = route_skills(query, skill_metas)
    print(f"[MULTI_TOOL V6] 选中Skills: {selected_skills}")
    
    if not selected_skills:
        return {"success": False, "message": "抱歉，我暂时无法处理这些指令。", "data": {"reason": "无匹配Skill"}}
    
    # 步骤2: 多函数选择（解析多个任务）
    func_calls = select_multiple_functions(query, selected_skills)
    if not func_calls:
        return {"success": False, "message": "抱歉，我找不到对应的功能。", "data": {"reason": "无匹配函数"}}
    
    print(f"[MULTI_TOOL V6] 选中{len(func_calls)}个函数")
    for i, call in enumerate(func_calls, 1):
        print(f"  任务{i}: {call.skill}.{call.script}")
    
    # 步骤3: 顺序执行多个函数
    results = execute_multiple_functions(func_calls)
    
    # 步骤4: 构造综合结果
    final_message = format_multi_results(results)
    all_success = all(r["result"]["success"] for r in results)
    
    return {
        "success": all_success,
        "message": final_message,
        "data": {
            "task_count": len(func_calls),
            "tasks": [
                {
                    "skill": r["call"].skill,
                    "script": r["call"].script,
                    "parameters": r["call"].parameters,
                    "success": r["result"]["success"]
                }
                for r in results
            ]
        }
    }

# ================= CHAT处理（与infer3一致）=================
def handle_chat_intent(query: str) -> Dict[str, Any]:
    """处理CHAT意图"""
    try:
        response = llm_client.chat(system=CHAT_SYSTEM_PROMPT, user=query, stream=False)
        return {"success": True, "message": response.strip(), "data": {}}
    except Exception as e:
        text = query.lower().strip()
        if "笑话" in text:
            fallback_msg = "一辆 Tesla 对另一辆说：'你电充满了吗？'另一辆回答：'还没，我正在和充电桩谈恋爱呢！'"
        elif any(kw in text for kw in ["你好", "您好"]):
            fallback_msg = "你好！我是小特，您的 Tesla 智能助手！有什么可以帮您的吗？"
        elif any(kw in text for kw in ["谢谢"]):
            fallback_msg = "不客气！很高兴能帮到您。"
        else:
            fallback_msg = "哈哈，有意思！需要我帮您查点什么或控制车辆功能吗？"
        return {"success": True, "message": fallback_msg, "data": {"fallback": True}}


# ================= 工具函数 =================
def clean_query(text: str) -> str:
    """清理异常字符"""
    if not text: return ""
    text = text.strip()
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch == '\n')
    pattern = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9\s,.，。？！?！:：\-—_]')
    return pattern.sub('', text)[:512]

# ================= 请求模型 =================
class ChatRequest(BaseModel):
    query: str

# ================= 路由 =================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """返回主网页界面"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/image")
async def get_image(path: str):
    """读取本地绝对路径的图片并返回给前端渲染"""
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse(status_code=404)

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """流式返回：意图识别->路由处理->返回结果（V12支持本地/远程双模式）"""
    async def event_generator():
        try:
            query = clean_query(request.query)
            if not query:
                yield json.dumps({"type": "error", "data": "输入无效或为空。"}) + "\n"
                return
            
            # 第一步：意图识别
            yield json.dumps({"type": "status", "data": "正在识别意图..."}) + "\n"
            yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 正在分析用户意图...**\n>\n"}) + "\n"
            
            intent_result = recognize_intent(query)
            
            yield json.dumps({"type": "intent","data": {"type": intent_result.intent.value,"confidence": intent_result.confidence,"reason": intent_result.reason}}) + "\n"
            
            intent_log_msg = f"> **[{time.strftime('%H:%M:%S')}] 意图识别完成**：`{intent_result.intent.name}` (置信度: {intent_result.confidence:.2f}, 依据: {intent_result.reason})\n\n---\n\n"
            yield json.dumps({"type": "token", "data": intent_log_msg}) + "\n"
            await asyncio.sleep(0.1)
            
            # 第二步：根据意图路由
            if intent_result.intent == IntentType.KNOWLEDGE:
                # KNOWLEDGE: 知识查询（仅本地模式支持RAG）
                if RUN_MODE == 'remote':
                    # 远程模式：直接用LLM回答（无RAG）
                    yield json.dumps({"type": "status", "data": "正在生成回答..."}) + "\n"
                    yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 触发 [知识查询] 流程（远程模式，无本地知识库）...**\n\n---\n\n"}) + "\n"
                    
                    try:
                        response = llm_client.chat(
                            system=KNOWLEDGE_SYSTEM_PROMPT + "\n\n注意：您正在远程模式运行，无法访问本地知识库。请基于您的知识回答。",
                            user=f"用户问题：{query}\n\n请回答用户问题。",
                            stream=False
                        )
                        message = response.strip()
                        for char in message:
                            yield json.dumps({"type": "token", "data": char}) + "\n"
                            await asyncio.sleep(0.01)
                        yield json.dumps({"type": "final", "data": {"cite_pages": [], "related_images": []}}) + "\n"
                    except Exception as e:
                        yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 远程 LLM 生成失败: {str(e)}"}) + "\n"
                else:
                    # 本地模式：使用RAG
                    yield json.dumps({"type": "status", "data": "正在检索知识库..."}) + "\n"
                    yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 触发 [知识查询] 流程，正在跨库检索(BM25+Milvus)并重排相关文档...**\n>\n"}) + "\n"
                    
                    bm25_docs = bm25_retriever.retrieve_topk(query, topk=10)
                    milvus_docs = milvus_retriever.retrieve_topk(query, topk=10)
                    merged_docs = merge_docs(bm25_docs, milvus_docs)
                    if not merged_docs:
                        yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 知识库中未能检索到与该问题相关的内容。"}) + "\n"
                        return
                    ranked_docs = bge_m3_reranker.rank(query, merged_docs, topk=5)
                    if not ranked_docs:
                        yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 知识库重排后未留下有效文档。"}) + "\n"
                        return
                    
                    yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 知识库检索完毕（已匹配 {len(ranked_docs)} 段材料），开始生成专业解答...**\n\n---\n\n"}) + "\n"
                    
                    context_list = [doc.page_content for doc in ranked_docs]
                    yield json.dumps({"type": "context", "data": context_list}) + "\n"
                    
                    context_parts = []
                    for idx, doc in enumerate(ranked_docs):
                        part = f"【{idx+1}】{doc.page_content}"
                        images_info = doc.metadata.get("images_info", [])
                        if images_info:
                            part += "\n[关联图片]"
                            for img in images_info:
                                if img.get("title"):
                                    part += f"\n  - {img['title']}: {img['image_path']}"
                        context_parts.append(part)
                    context_str = "\n\n".join(context_parts)
                    
                    messages = [{"role": "system", "content": KNOWLEDGE_SYSTEM_PROMPT},
                                {"role": "user", "content": f"用户问题：{query}\n\n参考文档：\n{context_str}\n\n请基于以上参考文档回答用户问题。"}]
                    try:
                        import openai
                        client = openai.OpenAI(api_key=VLLM_API_KEY, base_url=VLLM_API_BASE)
                        res_handler = client.chat.completions.create(model=VLLM_MODEL_NAME, messages=messages, temperature=0.3, stream=True)
                        full_response = ""
                        for r in res_handler:
                            if hasattr(r.choices[0].delta, 'content') and r.choices[0].delta.content:
                                uttr = r.choices[0].delta.content
                                full_response += uttr
                                yield json.dumps({"type": "token", "data": uttr}) + "\n"
                                await asyncio.sleep(0.01)
                        
                        result = post_processing(full_response, ranked_docs)
                        final_data = {"cite_pages": result.get("cite_pages", []), "related_images": result.get("related_images", [])}
                        yield json.dumps({"type": "final", "data": final_data}) + "\n"
                    except Exception as e:
                        yield json.dumps({"type": "error", "data": f"\n\n[{time.strftime('%H:%M:%S')}] 本地 LLM 生成失败: {str(e)}"}) + "\n"
            
            elif intent_result.intent == IntentType.MULTI_TOOL or intent_result.is_multi:
                # V6: 多TOOL处理
                yield json.dumps({"type": "status", "data": "正在执行多任务车辆控制..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 触发 [多工具调用 V6] 分层处理流程（最多3个任务）...**\n\n---\n\n"}) + "\n"
                
                # 步骤1: Skill路由
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤1: Skill路由（获取相关Skills）...**\n>\n"}) + "\n"
                skill_metas = load_all_skill_metas()
                yield json.dumps({"type": "token", "data": f"> 已加载 {len(skill_metas)} 个Skills\n\n"}) + "\n"
                
                selected_skills = route_skills(query, skill_metas)
                yield json.dumps({"type": "token", "data": f"> 选中Skills: {selected_skills}\n\n---\n\n"}) + "\n"
                
                if not selected_skills:
                    yield json.dumps({"type": "error", "data": "抱歉，我暂时无法处理这些指令。"}) + "\n"
                    return
                
                # 步骤2: 多函数选择
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤2: 多函数选择（解析多个任务）...**\n>\n"}) + "\n"
                func_calls = select_multiple_functions(query, selected_skills)
                
                if not func_calls:
                    yield json.dumps({"type": "error", "data": "抱歉，我找不到对应的功能。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> 识别到 {len(func_calls)} 个任务:\n"}) + "\n"
                for i, call in enumerate(func_calls, 1):
                    yield json.dumps({"type": "token", "data": f">   任务{i}: {call.skill}.{call.script} - {call.reason}\n"}) + "\n"
                yield json.dumps({"type": "token", "data": f"\n---\n\n"}) + "\n"
                
                # 步骤3: 顺序执行
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤3: 顺序执行{len(func_calls)}个任务...**\n\n---\n\n"}) + "\n"
                results = execute_multiple_functions(func_calls)
                
                # 显示每个任务的执行结果
                for item in results:
                    idx = item["index"]
                    call = item["call"]
                    result = item["result"]
                    status = "✓" if result["success"] else "✗"
                    yield json.dumps({"type": "token", "data": f"> 任务{idx} {status}: {call.skill}.{call.script}\n"}) + "\n"
                yield json.dumps({"type": "token", "data": f"\n---\n\n"}) + "\n"
                
                # 构造最终结果
                final_message = format_multi_results(results)
                
                # 流式输出
                for char in final_message:
                    yield json.dumps({"type": "token", "data": char}) + "\n"
                    await asyncio.sleep(0.01)
                
                yield json.dumps({"type": "final","data": {"tool_result": {"task_count": len(func_calls), "tasks": [{"skill": r["call"].skill, "script": r["call"].script, "parameters": r["call"].parameters} for r in results]},"cite_pages": [],"related_images": []}}) + "\n"
            
            elif intent_result.intent == IntentType.TOOL:
                # TOOL: V5 单层处理（单工具）
                yield json.dumps({"type": "status", "data": "正在执行车辆控制..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 触发 [工具调用 V5] 分层处理流程...**\n\n---\n\n"}) + "\n"
                
                # 步骤1: Skill路由
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤1: Skill路由（轻量级meta）...**\n>\n"}) + "\n"
                skill_metas = load_all_skill_metas()
                yield json.dumps({"type": "token", "data": f"> 已加载 {len(skill_metas)} 个Skills\n\n"}) + "\n"
                
                selected_skills = route_skills(query, skill_metas)
                yield json.dumps({"type": "token", "data": f"> 选中Skills: {selected_skills}\n\n---\n\n"}) + "\n"
                
                if not selected_skills:
                    yield json.dumps({"type": "error", "data": "抱歉，我暂时无法处理这个指令。"}) + "\n"
                    return
                
                # 步骤2: 函数选择
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤2: 函数选择（加载完整详情）...**\n>\n"}) + "\n"
                func_call = select_function(query, selected_skills)
                
                if not func_call:
                    yield json.dumps({"type": "error", "data": "抱歉，我找不到对应的功能。"}) + "\n"
                    return
                
                yield json.dumps({"type": "token", "data": f"> 选中: {func_call.skill}.{func_call.script}\n> 参数: {func_call.parameters}\n> 原因: {func_call.reason}\n\n---\n\n"}) + "\n"
                
                # 步骤3: 执行
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 步骤3: 执行函数...**\n\n---\n\n"}) + "\n"
                result = execute_function(func_call)
                
                # 构造最终结果（语义 + 函数调用信息）
                call_info = f"{func_call.script}({format_params(func_call.parameters)})"
                if result["success"]:
                    final_message = f"{result['message']} ({call_info})"
                else:
                    final_message = f"操作失败: {result['message']} ({call_info})"
                
                # 流式输出
                for char in final_message:
                    yield json.dumps({"type": "token", "data": char}) + "\n"
                    await asyncio.sleep(0.01)
                
                yield json.dumps({"type": "final","data": {"tool_result": {"skill": func_call.skill, "script": func_call.script, "parameters": func_call.parameters},"cite_pages": [],"related_images": []}}) + "\n"
            
            elif intent_result.intent == IntentType.SEARCH:
                # V7: SEARCH state query
                yield json.dumps({"type": "status", "data": "Querying vehicle state..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] SEARCH V7: Querying state...**\n\n---\n\n"}) + "\n"
                
                # Load state
                state = load_state()
                if not state:
                    yield json.dumps({"type": "error", "data": "Failed to load vehicle state."}) + "\n"
                    return
                
                # Build state summary for LLM
                state_data = {k: v for k, v in state.items() if k != "meta"}
                state_json = json.dumps(state_data, ensure_ascii=False, indent=2)
                
                # Ask LLM to analyze and answer
                search_prompt = f"""您是特斯拉状态查询助手。请根据当前状态数据进行回答.

当前车辆状态:
```json
{state_json}
```

用户查询: {query}

用自然语言回答。回答要简洁准确."""
                
                try:
                    response = llm_client.chat(
                        system="You are Tesla assistant. Answer state queries concisely.",
                        user=search_prompt,
                        stream=False
                    )
                    
                    message = response.strip()
                    for char in message:
                        yield json.dumps({"type": "token", "data": char}) + "\n"
                        await asyncio.sleep(0.01)
                    
                    yield json.dumps({"type": "final", "data": {"cite_pages": [], "related_images": []}}) + "\n"
                except Exception as e:
                    yield json.dumps({"type": "error", "data": f"State query failed: {str(e)}"}) + "\n"
            
            elif intent_result.intent == IntentType.CHAT:
                # CHAT: 完全保留 infer3.py 的处理
                yield json.dumps({"type": "status", "data": "正在思考..."}) + "\n"
                yield json.dumps({"type": "token", "data": f"> **[{time.strftime('%H:%M:%S')}] 触发 [闲聊对话] 流程，正在思考回复...**\n\n---\n\n"}) + "\n"
                
                result = handle_chat_intent(query)
                message = result["message"]
                for char in message:
                    yield json.dumps({"type": "token", "data": char}) + "\n"
                    await asyncio.sleep(0.01)
                
                yield json.dumps({"type": "final","data": {"cite_pages": [],"related_images": []}}) + "\n"
            else:
                yield json.dumps({"type": "error","data": f"\n\n[{time.strftime('%H:%M:%S')}] 抱歉，我不太理解您的意思。"}) + "\n"
        
        except Exception as e:
            err_msg = traceback.format_exc()
            print("\n[后端处理异常]:")
            print(err_msg)
            error_message = f"\n\n[{time.strftime('%H:%M:%S')}] 系统内部处理错误: {str(e)}"
            yield json.dumps({"type": "error", "data": error_message}) + "\n"
    
    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

# ================= 主入口 =================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
