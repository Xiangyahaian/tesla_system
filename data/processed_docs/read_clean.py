import pickle

# 1. 读取 pkl 数据
with open('split_docs.pkl', 'rb') as f:
    data = pickle.load(f)

# 2. 将结果写入 Markdown 文件
output_filename = 'split_docs.md'
with open(output_filename, 'w', encoding='utf-8') as md_file:
    # 可选：写入一个 Markdown 标题
    md_file.write("# 提取的文档预览\n\n")

    for i in range(min(10, len(data))):
        # 格式化字符串
        content = f"**[{i}]** {data[i]}"

        # 写入文件，\n\n 用于在 Markdown 中创建标准的段落间距
        md_file.write(content + "\n\n")

        # 如果你还想在控制台同步看到进度，可以保留 print
        print(content)

print(f"✅ 前 10 条数据已成功保存至 {output_filename}")