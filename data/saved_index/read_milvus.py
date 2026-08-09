# -*- coding: utf-8 -*-
"""
Milvus 数据库读取工具
用于查看 milvus.db 中的索引数据和内容
"""

import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

try:
    from pymilvus import MilvusClient
except ImportError:
    print("请先安装 pymilvus: pip install pymilvus")
    sys.exit(1)


def connect_milvus(db_path: str = None) -> MilvusClient:
    """连接 Milvus 数据库"""
    if db_path is None:
        # 默认使用当前目录下的 milvus.db
        db_path = os.path.join(os.path.dirname(__file__), "milvus.db")
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        print(f"当前目录文件: {os.listdir(os.path.dirname(db_path))}")
        sys.exit(1)
    
    file_size = os.path.getsize(db_path) / (1024 * 1024)  # MB
    print(f"📂 数据库路径: {db_path}")
    print(f"📊 文件大小: {file_size:.2f} MB")
    print("-" * 60)
    
    client = MilvusClient(db_path)
    return client


def list_collections(client: MilvusClient):
    """列出所有集合"""
    collections = client.list_collections()
    print(f"📚 共有 {len(collections)} 个集合:")
    
    for idx, col_name in enumerate(collections, 1):
        stats = client.get_collection_stats(col_name)
        row_count = stats.get('row_count', 0)
        print(f"  {idx}. {col_name} - {row_count} 条记录")
    
    print("-" * 60)
    return collections


def show_collection_schema(client: MilvusClient, collection_name: str):
    """显示集合的结构信息"""
    print(f"\n📋 集合 '{collection_name}' 的结构:")
    
    try:
        # 获取集合描述
        desc = client.describe_collection(collection_name)
        
        print(f"  自动 ID: {desc.get('auto_id', False)}")
        print(f"  描述: {desc.get('description', 'N/A')}")
        print(f"\n  字段列表:")
        
        for field in desc.get('fields', []):
            field_name = field.get('name', 'unknown')
            field_type = field.get('type', 'unknown')
            is_primary = field.get('is_primary', False)
            
            primary_mark = " [主键]" if is_primary else ""
            print(f"    - {field_name}: {field_type}{primary_mark}")
            
    except Exception as e:
        print(f"  ⚠️ 获取结构失败: {e}")
    
    print("-" * 60)


def query_sample_data(client: MilvusClient, collection_name: str, limit: int = 5):
    """查询样例数据"""
    print(f"\n🔍 集合 '{collection_name}' 的前 {limit} 条数据:")
    
    try:
        # 获取所有字段名
        desc = client.describe_collection(collection_name)
        field_names = [f['name'] for f in desc.get('fields', [])]
        
        # 排除向量字段（太长不显示）
        display_fields = [f for f in field_names if f not in ['vector', 'embedding']]
        
        results = client.query(
            collection_name=collection_name,
            filter="",
            output_fields=display_fields,
            limit=limit
        )
        
        for idx, doc in enumerate(results, 1):
            print(f"\n  [{idx}] {doc.get('unique_id', 'N/A')[:50]}...")
            
            # 显示关键字段
            for key in ['page', 'doc_type', 'metadata', 'parent_id']:
                if key in doc:
                    value = doc[key]
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:100] + "..."
                    print(f"      {key}: {value}")
            
            # 显示内容预览
            if 'page_content' in doc:
                content = doc['page_content']
                if isinstance(content, str):
                    preview = content[:200].replace('\n', ' ')
                    print(f"      content: {preview}...")
                    
    except Exception as e:
        print(f"  ⚠️ 查询失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("-" * 60)


def search_similar(client: MilvusClient, collection_name: str, query_text: str = None):
    """测试向量搜索"""
    print(f"\n🔎 测试相似度搜索:")
    
    # 如果没有提供查询文本，使用默认
    if not query_text:
        query_text = "充电口在哪里"
    
    print(f"  查询: '{query_text}'")
    
    try:
        # 这里需要嵌入模型才能搜索，简单演示结构
        print("  ⚠️  注意：实际搜索需要加载 BGE-M3 嵌入模型")
        print("  可以使用项目中 BGE-M3 模型进行真实搜索测试")
        
    except Exception as e:
        print(f"  ⚠️ 搜索失败: {e}")
    
    print("-" * 60)


def export_to_json(client: MilvusClient, collection_name: str, output_file: str = None):
    """导出数据到 JSON 文件（可选）"""
    import json
    
    if output_file is None:
        output_file = f"{collection_name}_export.json"
    
    print(f"\n📤 导出集合 '{collection_name}' 到 {output_file}...")
    
    try:
        desc = client.describe_collection(collection_name)
        field_names = [f['name'] for f in desc.get('fields', [])]
        
        # 获取所有数据
        stats = client.get_collection_stats(collection_name)
        total = stats.get('row_count', 0)
        
        print(f"  共 {total} 条记录，开始导出...")
        
        all_data = []
        batch_size = 1000
        offset = 0
        
        while offset < total:
            batch = client.query(
                collection_name=collection_name,
                filter="",
                output_fields=field_names,
                limit=batch_size,
                offset=offset
            )
            all_data.extend(batch)
            offset += len(batch)
            print(f"  已导出 {len(all_data)}/{total}...")
        
        # 保存到文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        
        print(f"  ✅ 导出完成: {output_file}")
        
    except Exception as e:
        print(f"  ❌ 导出失败: {e}")
    
    print("-" * 60)


def main():
    """主函数"""
    print("=" * 60)
    print("🔍 Milvus 数据库查看工具")
    print("=" * 60)
    
    # 连接数据库
    client = connect_milvus()
    
    # 列出所有集合
    collections = list_collections(client)
    
    if not collections:
        print("⚠️ 数据库为空，没有集合")
        client.close()
        return
    
    # 对每个集合显示详细信息
    for col_name in collections:
        show_collection_schema(client, col_name)
        query_sample_data(client, col_name, limit=3)
    
    # 交互式菜单
    while True:
        print("\n" + "=" * 60)
        print("📋 操作菜单:")
        print("  1. 查看集合列表")
        print("  2. 查看某集合详情")
        print("  3. 查看更多样例数据")
        print("  4. 导出集合到 JSON")
        print("  0. 退出")
        print("=" * 60)
        
        choice = input("\n选择操作: ").strip()
        
        if choice == "0":
            print("👋 再见")
            break
        
        elif choice == "1":
            list_collections(client)
        
        elif choice == "2":
            print(f"\n可用集合: {collections}")
            col_name = input("输入集合名: ").strip()
            if col_name in collections:
                show_collection_schema(client, col_name)
                query_sample_data(client, col_name, limit=5)
            else:
                print("❌ 集合不存在")
        
        elif choice == "3":
            print(f"\n可用集合: {collections}")
            col_name = input("输入集合名: ").strip()
            if col_name in collections:
                limit = input("查看条数 (默认10): ").strip()
                limit = int(limit) if limit.isdigit() else 10
                query_sample_data(client, col_name, limit=limit)
            else:
                print("❌ 集合不存在")
        
        elif choice == "4":
            print(f"\n可用集合: {collections}")
            col_name = input("输入集合名: ").strip()
            if col_name in collections:
                output = input("输出文件名 (默认自动生成): ").strip()
                output = output if output else None
                export_to_json(client, col_name, output)
            else:
                print("❌ 集合不存在")
        
        else:
            print("⚠️ 无效选择")
    
    client.close()


if __name__ == "__main__":
    main()
