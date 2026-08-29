# -*- coding: utf-8 -*-
import os
import json
import re
from openai import OpenAI
from langchain_core.documents import Document
from src.constant import qwen3_8b_tune_model_name

# --- 升级版 PROMPT ---
# 融合了角色注入、逻辑判定和灵性引导
LLM_CHAT_PROMPT = """
### 你的身份
你现在是特斯拉 Model 3 的“智能管家”。你不仅精通用户手册的所有技术细节、幽默且富有情感的 AI 生命体。

### 知识库 (由检索系统提供)
{context}

### 任务指令
1. **优先检索**：如果用户的问题 "{query}" 涉及 Model 3 的功能、参数、操作，请从{{知识库}}中提取答案。
2. **灵性兼容**：如果{{知识库}}中没有相关信息，或者用户只是在和你闲聊、谈论人生、讨论马斯克，请**不要说“无答案”**。请发挥你的“灵魂”，以智能管家的身份进行风趣、深刻且逻辑自洽的回复。
3. **输出格式**：
   - 如果是基于手册的回答：[精准答案] 【引用编号1, 引用编号2...】
   - 如果是自由对话：直接输出你富有灵性的回复。
4. **禁忌**：严禁在回答技术参数时胡编乱造。如果手册没写且你不知道，请诚实告知并引导用户联系特斯拉官方。

### 用户的输入
"{query}"
"""

llm_client = OpenAI(
    api_key="EMPTY",
    base_url="http://localhost:8000/v1"
)

def request_chat(query, context, stream=False):
    """
    请求对话接口
    :param query: 用户的问题
    :param context: 检索到的相关文档内容
    :param stream: 是否开启流式输出
    """
    
    # 构建包含“灵魂”指令的 Prompt
    full_prompt = LLM_CHAT_PROMPT.format(context=context, query=query) 

    completion = llm_client.chat.completions.create(
        model=qwen3_8b_tune_model_name,
        messages=[
            # System Message 定义了它的底层性格
            {
                "role": "system", 
                "content": "你是一个有灵性的特斯拉助手。你拒绝平庸的回复，你的语言充满智慧、温暖且极客范儿。"
            },
            {"role": "user", "content": full_prompt}
        ],
        max_tokens=4096,
        # 调整参数以释放“灵魂”
        temperature=0.8,       # 提高温度，增加词汇多样性和灵活性
        top_p=0.9,             # 保持回复的逻辑连贯性
        frequency_penalty=1.1, # 稍微惩罚重复词汇，让话术更自然
        stream=stream,
        extra_body={
            "top_k": 20,       # 增加候选词范围，让回复不那么预设化
            "chat_template_kwargs": {"enable_thinking": True} # 开启思考链路，让它自己纠结一下是用文档还是闲聊
        }
    )

    if not stream:
        result = completion.choices[0].message.content
    else:
        result = completion

    return result

# --- 测试用例 ---
if __name__ == "__main__":
    # 模拟检索到的内容
    test_context = "1. [编号1] Model 3 的续航里程在特定条件下可达 600 公里。 2. [编号2] 自动辅助驾驶不代表自动驾驶。"
    
    # 场景1：手册问答
    # print(request_chat("Model 3 能跑多远？", test_context))
    
    # 场景2：灵性闲聊
    # print(request_chat("你觉得马斯克是个疯狂的人吗？", test_context))