# -*- coding: utf-8 -*-
"""
对话记忆管理模块 V2 - 增强版多轮对话记忆系统

特性:
- 按意图分类存储 (KNOWLEDGE/TOOL/CHAT)
- 语义相似度检索相关记忆
- 时间衰减权重
- 记忆去重
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import hashlib


class MemoryIntentType(Enum):
    """记忆意图类型"""
    KNOWLEDGE = "KNOWLEDGE"  # 知识查询类
    TOOL = "TOOL"            # 工具执行类
    CHAT = "CHAT"            # 闲聊类


@dataclass
class MemoryEntry:
    """单条记忆条目"""
    id: str                  # 唯一ID (hash)
    timestamp: str           # ISO格式时间戳
    intent_type: str         # KNOWLEDGE/TOOL/CHAT
    summary: str             # LLM生成的摘要
    original_query: str      # 原始用户输入
    keywords: List[str] = field(default_factory=list)  # 提取的关键词
    access_count: int = 0    # 被访问次数
    last_accessed: Optional[str] = None  # 最后访问时间


class MemoryManager:
    """对话记忆管理器 V2"""
    
    DEFAULT_MEMORY_FILE = "state/memory.json"
    MAX_MEMORY_ENTRIES = 30  # 最多保留30条记忆
    DECAY_HOURS = 24         # 24小时后记忆权重衰减
    
    def __init__(self, memory_file: str = None):
        self.memory_file = memory_file or self.DEFAULT_MEMORY_FILE
        self.memories: List[MemoryEntry] = []
        self._ensure_directory()
        self._load()
    
    def _generate_id(self, query: str, timestamp: str) -> str:
        """生成记忆唯一ID"""
        content = f"{query}:{timestamp}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def _extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        # 简单的关键词提取：保留名词和动词
        # 实际应用中可以使用更复杂的NLP方法
        words = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z]+', text)
        # 去重并保持顺序
        seen = set()
        keywords = []
        for w in words:
            w_lower = w.lower()
            if w_lower not in seen and len(w) >= 2:
                seen.add(w_lower)
                keywords.append(w)
        return keywords[:10]  # 最多10个关键词
    
    def _ensure_directory(self):
        """确保目录存在"""
        dir_path = os.path.dirname(self.memory_file)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
    
    def _load(self):
        """从文件加载记忆"""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.memories = [
                        MemoryEntry(
                            id=item.get('id', self._generate_id(item.get('original_query', ''), item.get('timestamp', ''))),
                            timestamp=item.get('timestamp', ''),
                            intent_type=item.get('intent_type', 'CHAT'),
                            summary=item.get('summary', ''),
                            original_query=item.get('original_query', ''),
                            keywords=item.get('keywords', []),
                            access_count=item.get('access_count', 0),
                            last_accessed=item.get('last_accessed')
                        )
                        for item in data.get('memories', [])
                    ]
            except Exception as e:
                print(f"[MemoryManager] 加载记忆失败: {e}")
                self.memories = []
        else:
            self.memories = []
    
    def _save(self):
        """保存记忆到文件"""
        try:
            data = {
                'meta': {
                    'last_updated': datetime.now().isoformat(),
                    'total_entries': len(self.memories),
                    'version': '2.0'
                },
                'memories': [
                    {
                        'id': m.id,
                        'timestamp': m.timestamp,
                        'intent_type': m.intent_type,
                        'summary': m.summary,
                        'original_query': m.original_query,
                        'keywords': m.keywords,
                        'access_count': m.access_count,
                        'last_accessed': m.last_accessed
                    }
                    for m in self.memories
                ]
            }
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MemoryManager] 保存记忆失败: {e}")
    
    def _calculate_similarity(self, query: str, memory: MemoryEntry) -> float:
        """计算查询与记忆的相似度 (0-1)"""
        query_lower = query.lower()
        summary_lower = memory.summary.lower()
        original_lower = memory.original_query.lower()
        
        # 直接包含匹配
        if query_lower in summary_lower or query_lower in original_lower:
            return 1.0
        
        # 关键词匹配
        query_keywords = set(self._extract_keywords(query))
        memory_keywords = set(memory.keywords)
        
        if not query_keywords or not memory_keywords:
            return 0.0
        
        intersection = query_keywords & memory_keywords
        union = query_keywords | memory_keywords
        
        jaccard = len(intersection) / len(union) if union else 0
        return jaccard
    
    def _calculate_time_weight(self, memory: MemoryEntry) -> float:
        """计算时间权重 (越新的记忆权重越高)"""
        try:
            mem_time = datetime.fromisoformat(memory.timestamp)
            hours_ago = (datetime.now() - mem_time).total_seconds() / 3600
            
            # 指数衰减
            import math
            weight = math.exp(-hours_ago / self.DECAY_HOURS)
            return max(0.1, weight)  # 最小权重0.1
        except:
            return 0.5
    
    def _is_duplicate(self, query: str, intent_type: MemoryIntentType) -> bool:
        """检查是否为重复记忆"""
        query_keywords = set(self._extract_keywords(query))
        
        for mem in self.memories[-5:]:  # 只检查最近5条
            if mem.intent_type != intent_type.value:
                continue
            mem_keywords = set(mem.keywords)
            
            # 如果关键词重合度超过70%，认为是重复
            if query_keywords and mem_keywords:
                intersection = query_keywords & mem_keywords
                similarity = len(intersection) / len(query_keywords)
                if similarity > 0.7:
                    return True
        return False
    
    def add_memory(self, intent_type: MemoryIntentType, summary: str, original_query: str) -> bool:
        """
        添加一条记忆
        
        Returns:
            bool: 是否成功添加（False表示重复被过滤）
        """
        # 检查重复
        if self._is_duplicate(original_query, intent_type):
            print(f"[MemoryManager] 跳过重复记忆: {summary[:40]}...")
            return False
        
        timestamp = datetime.now().isoformat()
        entry = MemoryEntry(
            id=self._generate_id(original_query, timestamp),
            timestamp=timestamp,
            intent_type=intent_type.value,
            summary=summary,
            original_query=original_query,
            keywords=self._extract_keywords(original_query + " " + summary),
            access_count=0,
            last_accessed=None
        )
        self.memories.append(entry)
        
        # 保持记忆数量在限制内（移除最旧的且访问次数最少的）
        if len(self.memories) > self.MAX_MEMORY_ENTRIES:
            # 按访问次数和时间排序，移除最不重要的
            sorted_memories = sorted(
                self.memories,
                key=lambda m: (m.access_count, m.timestamp)
            )
            self.memories = sorted_memories[-self.MAX_MEMORY_ENTRIES:]
        
        self._save()
        print(f"[MemoryManager] 已添加记忆 [{intent_type.value}]: {summary[:50]}...")
        return True
    
    def retrieve_relevant_memories(self, query: str, top_k: int = 5, 
                                   intent_filter: List[MemoryIntentType] = None) -> List[MemoryEntry]:
        """
        检索与查询相关的记忆
        
        Args:
            query: 查询文本
            top_k: 返回多少条
            intent_filter: 按意图类型过滤
            
        Returns:
            相关记忆列表
        """
        if not self.memories:
            return []
        
        # 过滤意图类型
        candidates = self.memories
        if intent_filter:
            allowed_types = {t.value for t in intent_filter}
            candidates = [m for m in candidates if m.intent_type in allowed_types]
        
        # 计算综合得分 (相似度 * 时间权重 * 访问次数加成)
        scored = []
        for mem in candidates:
            sim = self._calculate_similarity(query, mem)
            time_weight = self._calculate_time_weight(mem)
            access_bonus = 1 + (mem.access_count * 0.1)  # 访问越多权重越高
            
            score = sim * time_weight * access_bonus
            scored.append((score, mem))
        
        # 按得分排序
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # 返回top_k，并更新访问统计
        results = []
        for score, mem in scored[:top_k]:
            if score > 0.1:  # 相似度阈值
                mem.access_count += 1
                mem.last_accessed = datetime.now().isoformat()
                results.append(mem)
        
        if results:
            self._save()  # 保存访问次数更新
        
        return results
    
    def get_memories_for_prompt(self, query: str = None, limit: int = 10) -> str:
        """
        获取格式化的记忆文本，用于组装到 prompt 中
        
        Args:
            query: 当前查询（用于检索相关记忆）
            limit: 最多返回多少条记忆
            
        Returns:
            格式化的记忆文本
        """
        if not self.memories:
            return ""
        
        # 如果有查询，检索相关记忆；否则返回最近记忆
        if query:
            memories = self.retrieve_relevant_memories(query, top_k=limit)
        else:
            memories = self.memories[-limit:]
        
        if not memories:
            return ""
        
        lines = ["\n=== 对话历史 ==="]
        
        for m in memories:
            time_str = m.timestamp.split('T')[1][:5] if 'T' in m.timestamp else "--:--"
            lines.append(f"[{time_str}] [{m.intent_type}] {m.summary}")
        
        lines.append("================\n")
        return "\n".join(lines)
    
    def get_memories_by_type(self, intent_type: MemoryIntentType, limit: int = 10) -> List[MemoryEntry]:
        """获取特定类型的记忆"""
        filtered = [m for m in self.memories if m.intent_type == intent_type.value]
        return filtered[-limit:]
    
    def get_all_memories(self) -> List[MemoryEntry]:
        """获取所有记忆"""
        return self.memories.copy()
    
    def get_memory_stats(self) -> Dict:
        """获取记忆统计信息"""
        stats = {
            "total": len(self.memories),
            "by_type": {
                "KNOWLEDGE": len([m for m in self.memories if m.intent_type == "KNOWLEDGE"]),
                "TOOL": len([m for m in self.memories if m.intent_type == "TOOL"]),
                "CHAT": len([m for m in self.memories if m.intent_type == "CHAT"])
            },
            "most_accessed": [],
            "recent": []
        }
        
        # 最常访问的
        by_access = sorted(self.memories, key=lambda m: m.access_count, reverse=True)
        stats["most_accessed"] = [{"summary": m.summary[:50], "count": m.access_count} for m in by_access[:3]]
        
        # 最近的
        stats["recent"] = [{"summary": m.summary[:50], "time": m.timestamp} for m in self.memories[-3:]]
        
        return stats
    
    def clear(self):
        """清空所有记忆"""
        self.memories = []
        self._save()
    
    def delete_memory(self, memory_id: str) -> bool:
        """删除特定记忆"""
        original_len = len(self.memories)
        self.memories = [m for m in self.memories if m.id != memory_id]
        if len(self.memories) < original_len:
            self._save()
            return True
        return False


# 全局记忆管理器实例
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager(memory_file: str = None) -> MemoryManager:
    """获取全局记忆管理器实例（单例模式）"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(memory_file)
    return _memory_manager


def reset_memory_manager():
    """重置全局记忆管理器（用于测试）"""
    global _memory_manager
    _memory_manager = None


def generate_memory_prompt(intent_type: MemoryIntentType, query: str, context: dict) -> str:
    """
    生成用于让 LLM 总结记忆的 prompt
    
    Args:
        intent_type: 意图类型
        query: 用户原始查询
        context: 上下文信息（根据意图类型不同而变化）
    
    Returns:
        用于生成记忆摘要的 prompt
    """
    if intent_type == MemoryIntentType.KNOWLEDGE:
        return f"""请总结以下知识查询对话的核心内容，用一句话概括用户询问的问题。

用户查询: {query}
检索到的文档主题: {context.get('doc_topics', '未知')}
回答摘要: {context.get('answer_summary', '')}

要求:
- 只输出一句话总结
- 格式: "询问了关于...的问题"
- 示例: "询问了手机和蓝牙配对方法的问题"
- 示例: "询问了如何关闭后备箱的问题"

总结:"""

    elif intent_type == MemoryIntentType.TOOL:
        return f"""请总结以下工具执行操作，用一句话概括执行了什么操作。

用户指令: {query}
执行的任务: {context.get('tasks', '未知')}
执行结果: {context.get('result_summary', '')}

要求:
- 只输出一句话总结
- 格式: "执行了...操作"
- 示例: "播放了周杰伦的歌曲《晴天》，专辑《叶惠美》"
- 示例: "打开了副驾驶(左前方)的座椅加热，设置为两档"
- 示例: "设置了空调温度为22度，风速为3档"

总结:"""

    elif intent_type == MemoryIntentType.CHAT:
        return f"""请总结以下闲聊对话，请用一句话简洁地总结整个对话的内容，包括用户的问题和LLM的回答。

用户输入: {query}
对话内容: {context.get('chat_content', '')}

要求:
- 只输出一句话说明，包含用户和助手双方的内容
- 格式: "询问了一个...问题" 或 "表达了..."，"回答/告知/推荐...."
- 示例: "用户了推荐一部电影的问题，助手推荐了《流浪地球2》"
- 示例: "用户表达了自己技不如人很痛苦的问题，助手安慰了用户并鼓励他继续努力。"

总结:"""

    else:
        return f"""请总结以下对话内容，用一句话概括。

用户输入: {query}

要求:
- 只输出一句话总结
- 简洁明了

总结:"""
