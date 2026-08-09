# -*- coding: utf-8 -*-
"""
用户查询意图识别
"""
import json
import re
from context.models import IntentType, IntentResult
from config import prompts
from context.memory_manager import get_memory_manager


def recognize_intent(query: str, llm_client) -> IntentResult:
    """基于LLM的意图识别，支持MULTI_TOOL"""
    # ========== 核心：内部直接调用，无需外部传参 ==========

    
    # 自动获取记忆管理器 + 取前5条记忆
    memory_manager = get_memory_manager()
    memory_context = memory_manager.get_memories_for_prompt(query=None, limit=10)
    
    # 直接构建带记忆的意图Prompt（你要的格式）
    system_prompt = prompts.build_intent_prompt_with_memory(memory_context)
    # ====================================================
    
    user_prompt = f"""用户输入: "{query}"
请分析意图并返回JSON。"""
    try:
        # 使用带记忆的提示词
        response = llm_client.chat(system=system_prompt, user=user_prompt, stream=False)
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
        
        if intent == IntentType.MULTI_TOOL:
            is_multi = True
        
        return IntentResult(intent=intent, confidence=confidence, reason=reason, is_multi=is_multi)
    except Exception as e:
        print(f"[意图识别失败]: {e}")
        return _fallback_intent_recognition(query)

def _fallback_intent_recognition(query: str) -> IntentResult:
    """意图识别失败时的降级策略"""
    text = query.lower().strip()
    
    search_keywords = ["当前", "现在", "多少度", "开了吗", "关了吗", "状态", "是多少", "温度多少", "音量多少"]
    for kw in search_keywords:
        if kw in text:
            return IntentResult(intent=IntentType.SEARCH, confidence=0.7,
                              reason=f"降级: 包含状态查询关键词'{kw}'", is_multi=False)
    
    multi_tool_markers = ["，", ",", "；", ";", "然后", "接着", "再", "帮我", "顺便"]
    action_keywords = ["打开", "关闭", "设置", "调节", "播放", "导航", "调到", "升温", "降温"]
    action_count = sum(1 for kw in action_keywords if kw in text)
    has_separator = any(marker in query for marker in multi_tool_markers)
    
    if action_count >= 2 or (action_count >= 1 and has_separator):
        return IntentResult(intent=IntentType.MULTI_TOOL, confidence=0.6,
                          reason=f"降级: 检测到{action_count}个可能动作", is_multi=True)
    
    for kw in action_keywords:
        if kw in text:
            return IntentResult(intent=IntentType.TOOL, confidence=0.7,
                              reason=f"降级: 包含工具关键词'{kw}'", is_multi=False)
    
    knowledge_patterns = [r"怎么.*用", r"什么.*意思", r"如何", r"为什么", r"多少", r"吗", r"呢"]
    for pattern in knowledge_patterns:
        if re.search(pattern, text):
            return IntentResult(intent=IntentType.KNOWLEDGE, confidence=0.7,
                              reason=f"降级: 匹配知识查询模式'{pattern}'", is_multi=False)
    
    return IntentResult(intent=IntentType.CHAT, confidence=0.6,
                       reason="降级: 默认闲聊", is_multi=False)


def handle_chat_intent(query: str, llm_client) -> dict:
    """处理CHAT意图"""
    try:
        response = llm_client.chat(system=prompts.CHAT_SYSTEM_PROMPT, user=query, stream=False)
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
