# -*- coding: utf-8 -*-
import os
import re
import pickle
import time
import random
import threading
import json
import hashlib

import concurrent.futures
from tqdm.auto import tqdm
from openai import OpenAI
from langchain_core.documents import Document


random.seed(42)

MINMAL_CHUNK_SIZE = 100
MAX_WORKERS = 20
INPUT_PATH = './data/processed_docs/clean_docs.pkl'
QA_PATH = "./data/qa_pairs/qa_pair.json"
CHATS_PATH = "./data/ut/raw_general_chats.txt"
OUTPUT_PATH = "./data/qa_pairs/expand_qa_pair.json"
TRAIN_PATH = "./data/qa_pairs/train_qa_pair.json"
TEST_PATH = "./data/qa_pairs/test_qa_pair.json"
TEST_KEYWORDS_PATH = "./data/qa_pairs/test_keywords_pair.json"



CONTEXT_PROMPT_TPL = """
我会给你一段文本（<document></document>之间的部分），你需要阅读这段文本，分别针对这段文本生成5个问题，和基于这段文本对问题的回答，回答请保持完整，无须重复问题。

对问题、答案的要求：
1.问题：问题要与这段文本相关，不要询问类似“这个问题的答案在哪一章”这样的问题;
2.答案：回答请保持完整且简洁，无须重复问题。答案要能够独立回答问题，而不是引用其他章节和页码，例如答案内容不能出现请参阅xx页码;
3.5个问题里面至少要包含一个需要综合*大段*文本才能回答的问题，但不要问类似“这一段主要讲了什么内容”这样的问题;

对输出的要求：
1.返回结果以JSON形式组织，格式为[{"question": "...", "answer": "..."}, ...]。
2.如果当前文本主要是目录，或者是一些人名、地址、电子邮箱等没有办法生成有意义的问题时，可以返回[]。

下方是文本：
<document>
{{document}}
</document>

请生成结果：
"""

GENERALIZE_PROMPT_TPL = """
你是一个造句大师，请根据我输入的问题，生成具有意思相近的5个问题。

要求：
1.生成的问题要表达相近的意思，请探索采用不同的问法。
2.生成问题尽量口语化一点，可以不遵循原来的句式，例如：怎么打开车窗=》这个车的窗子要怎么才能开启
3.每一个问题用回车符连接，前面用序号开头，例如：1., 2., 3.

注意：不是回答问题，任务是输出5个同义句。

下方是输入的问题：
<question>
{{document}}
</question>

请生成结果：
"""

KEYWORDS_PROMPT_TPL = """
你是一名专业的汽车领域NLP工程师，任务是从给定的汽车行业文本中提取核心关键词。请按以下要求操作：

抽取原则：
1.优先提取汽车专业术语（如"涡轮增压"、"ADAS系统"）
2.保留产品型号/规格（如"MQB平台"、"2023款Model Y"）
3.包含技术特征（如"L2级自动驾驶"、"48V轻混"）
4.提取关键动作（如"召回"、"OTA升级"）


输出要求：
1.重点关注：动力总成/车身结构/汽车零部件/智能网联/辅助驾驶/新能源技术/充电设施/售后服务
2.过滤通用词汇（如"使用"、"包括"）
3.请输出最重要的关键词，关键词数量不得超过5个
4.如果没有关键词，请直接输出“无”


输出格式：
关键词列表，用逗号分隔
例如：行车记录仪,探测功能,辅助驾驶,车辆功率


下方是输入的问题：
<question>
{{document}}
</question>

请生成结果：

"""

QA_QUALITY_PROMPT_TPL = """
你是一个汽车领域的专家，现在有人根据一份汽车用车手册，构造了一些问题，并对问题进行了回答。
你的任务是对这些问题（<question></question>之间的部分）和回答（<answer></answer>）进行打分。

结果请以JSON形式组织，格式如下（<result></result>之间的部分）：
<result>
{"score": ..., "reason": ...}
</result>
其中score是对问题-回答的打分，分值是一个int类型的值，取值范围为1-5。reason是打分的理由。

好的问题，应该是询问事实、观点等，不好的问题，通常要求做一些文本摘要等初级文字处理工作，类似于“这一段描述了什么”，“文本描述了什么”；或者询问的内容是图相关的，例如“图4展示了什么数据？”。
好的答案，应该能够回应问题，而不是回答无关的内容，不好的回答，会给出在原文中的引用，例如“第3章”等。

问题：
<question>
{{question}}
</question>

答案：
<answer>
{{answer}}
</answer>

请进返回JSON格式的数据即可，不要添加其他任何描述性信息。
"""



llm_client = OpenAI(
    api_key=os.environ['DOUBAO_API_KEY'],
    base_url=os.environ['DOUBAO_BASE_URL']
)


def build_qa_prompt(prompt_tmpl, text):
    prompt = prompt_tmpl.replace('{{document}}', text).strip()
    return prompt


def chat(prompt, max_retry=3, debug=False, temperature=0.85, top_p=0.95):

    def do_chat(prompt):
        completion = llm_client.chat.completions.create(
            model=os.environ["DOUBAO_MODEL_NAME"],
            messages=[
                {"role": "system", "content": "你是一个有用的人工智能助手."},
                {"role": "user", "content": prompt}
            ],
            top_p=top_p,
            temperature=temperature
        )
        return completion.choices[0].message.content

    x = do_chat(prompt)
    while max_retry > 0:
        try:
            return do_chat(prompt)
        except Exception as e:
            max_retry -= 1
            sleep_seconds = random.randint(1, 4)
            if debug:
                print(f"{str(e)}, remain retry: {max_retry}, sleeping {sleep_seconds}s {prompt}")
            time.sleep(sleep_seconds)
    return None

def gen_qa(splitted_docs, prompt_tmpl, qa_ckpt_filename, expand=False):
    qa_ckpt = {}
    file_lock = threading.Lock()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        if expand:
            futures = {doc.page_content: executor.submit(chat, build_qa_prompt(
                prompt_tmpl, doc.page_content), 3, True) for doc in splitted_docs if
                           doc.metadata['unique_id'] not in qa_ckpt}
        else:
            futures = {doc.metadata['unique_id']: executor.submit(chat, build_qa_prompt(
                prompt_tmpl, doc.page_content), 3, True) for doc in splitted_docs
                       if len(doc.page_content.replace('\n', '')) >= MINMAL_CHUNK_SIZE and
                           doc.metadata['unique_id'] not in qa_ckpt}
        for unique_id in tqdm(futures):
            future = futures[unique_id]
            result = future.result()
            if result is None:
                continue

            item = {'unique_id': unique_id, 'raw_resp': result}
            qa_ckpt[unique_id] = item

            # global file_lock
            file_lock.acquire()

            try:
                with open(qa_ckpt_filename, 'a') as f:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
            except Exception as e:
                print(e)
            finally:
                file_lock.release()
    return qa_ckpt


if __name__ == "__main__":
    """
    splitted_docs = pickle.load(open(INPUT_PATH, "rb"))
    print("待处理文件数：", len(splitted_docs))
    print(splitted_docs[0])

    qa_dict = gen_qa(splitted_docs, CONTEXT_PROMPT_TPL, QA_PATH) 
    question_docs = []
    fd = open(QA_PATH, "r")
    idx = 0
    for line in fd:
        info = json.loads(line)
        resp = json.loads(info["raw_resp"])
        for qa in resp:
            question_docs.append(Document(page_content=qa["question"], metadata={"unique_id": str(idx)}))
            idx += 1
    print("待泛化问题数：", len(question_docs))
    expand_qa_dict = gen_qa(question_docs, GENERALIZE_PROMPT_TPL, OUTPUT_PATH, expand=True) 

    """
    qa_dict = {}
    with open(QA_PATH) as fd:
        for line in fd:
            info = json.loads(line)
            qa_dict[info["unique_id"]] = info
    expand_qa_dict = {}
    with open(OUTPUT_PATH) as fd:
        for line in fd:
            info = json.loads(line)
            expand_qa_dict[info["unique_id"]] = info

    expand_qa_pairs = {}
    for unique_id, info in expand_qa_dict.items():
        question = info["unique_id"]
        expand_questions = info["raw_resp"]
        expand_questions = expand_questions.split("\n")
        expand_questions = [re.sub(r'^\d[.. ]', '', item).strip() for item in expand_questions]
        expand_qa_pairs[question] = expand_questions


    train_qa_pairs = []
    test_qa_pairs = []
    for unique_id, info in qa_dict.items():
        resp = json.loads(info["raw_resp"])
        for qa in resp:
            question = qa["question"].strip()
            answer = qa["answer"].strip()
            if "无法准确" in answer or "未提及" in answer:
                continue
            expand_questions = [question] + expand_qa_pairs[question] 
            for query in expand_questions:
                unique_id = hashlib.md5(query.encode('utf-8')).hexdigest()
                item = {
                    "unique_id": unique_id,
                    "question": query,
                    "answer": answer 
                }
                if random.random() < 0.9:
                    train_qa_pairs.append(item)
                else:
                    test_qa_pairs.append(item)

    
    print("训练集QA数：", len(train_qa_pairs), "测试集QA数：", len(test_qa_pairs))

    test_answer_docs = []
    unique_test_answers = set([item["answer"] for item in test_qa_pairs])
    for idx, answer in enumerate(unique_test_answers):
        test_answer_docs.append(Document(page_content=answer, metadata={"unique_id": str(idx)}))

    print("待抽取关键词docs数：", len(test_answer_docs))
    keywords_dict = gen_qa(test_answer_docs, KEYWORDS_PROMPT_TPL, TEST_KEYWORDS_PATH, expand=True) 


    keywords_mapping = {}
    for unique_id, info in keywords_dict.items():
        keywords = info["raw_resp"].split(",")
        kewyords = [item for item in keywords if item not in ["无", "Model 3"]]
        keywords_mapping[info["unique_id"]] = kewyords 

    for info in test_qa_pairs:
        keywords = keywords_mapping[info["answer"]]
        info["keywords"] = keywords


    # 负样本
    chats_data = open(CHATS_PATH).readlines()
    chats_data = [item.strip() for item in chats_data]

    random.seed(42)
    for line in chats_data:
        if random.random() < 0.95:
            train_qa_pairs.append({
                "unique_id": hashlib.md5(line.encode('utf-8')).hexdigest(),
                "question": line, 
                "answer": "无答案"
            })

        else:
            test_qa_pairs.append({
                "unique_id": hashlib.md5(line.encode('utf-8')).hexdigest(),
                "question": line, 
                "answer": "无答案",
                "keywords": []

            })

    random.seed(42)
    with open(TRAIN_PATH, "w") as fd:
        random.shuffle(train_qa_pairs)
        fd.write(json.dumps(train_qa_pairs, ensure_ascii=False, indent=2))
        print("训练集已写入:", TRAIN_PATH, len(train_qa_pairs))

    random.seed(42)
    with open(TEST_PATH, "w") as fd:
        random.shuffle(test_qa_pairs)
        fd.write(json.dumps(test_qa_pairs, ensure_ascii=False, indent=2))
        print("测试集已写入:", TEST_PATH, len(test_qa_pairs))
