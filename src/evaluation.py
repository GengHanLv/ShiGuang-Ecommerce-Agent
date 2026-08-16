"""
自建评测集用于离线评估意图分类准确率（多标签）与端到端回答质量。

"""
import asyncio
from typing import List, Set

from openai import AsyncOpenAI

from config import CHAT_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from graph import classify_intents

client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 意图分类测试集
test_intent_cases = [
    # order_query 类
    {"message": "我的订单发货了吗？", "expected": "order_query"},
    {"message": "查一下我的订单状态", "expected": "order_query"},
    {"message": "订单号123456到哪了？", "expected": "order_query"},
    {"message": "物流信息查不到，帮我看看", "expected": "order_query"},
    {"message": "帮我查一下前天那个订单", "expected": "order_query"},
    {"message": "快递到哪了？", "expected": "order_query"},
    {"message": "催一下我的订单", "expected": "order_query"},
    {"message": "给我看看所有订单", "expected": "order_query"},
    {"message": "订单ID 7890 是什么状态", "expected": "order_query"},
    {"message": "帮我跟踪一下包裹", "expected": "order_query"},
    {"message": "订单怎么取消？", "expected": "order_query"},
    {"message": "能不能改地址？", "expected": "order_query"},
    {"message": "能不能改收货地址？", "expected": "order_query"},
    {"message": "发货了吗", "expected": "order_query"},
    {"message": "我的包裹签收了吗", "expected": "order_query"},
    {"message": "查一下订单号1", "expected": "order_query"},
    {"message": "订单 10086 什么状态", "expected": "order_query"},
    {"message": "物流停更新了帮我看看", "expected": "order_query"},
    {"message": "催单，怎么还没动静", "expected": "order_query"},
    {"message": "我买的那个快递到哪了", "expected": "order_query"},
    {"message": "取消订单可以吗", "expected": "order_query"},
    {"message": "我想改一下收货地址", "expected": "order_query"},
    {"message": "订单号：888888 到哪了", "expected": "order_query"},
    {"message": "帮我看看昨天的包裹", "expected": "order_query"},
    {"message": "查一下我的订单", "expected": "order_query"},
    # 多意图 order + knowledge 类
    {"message": "我有个订单要退款", "expected": ["order_query", "knowledge"]},
    {"message": "帮我申请退货", "expected": ["order_query", "knowledge"]},
    {"message": "查一下订单顺便问怎么退货", "expected": ["order_query", "knowledge"]},
    {"message": "订单号123想退货怎么操作", "expected": ["order_query", "knowledge"]},
    {"message": "我的快递到哪了，另外退款多久到账", "expected": ["order_query", "knowledge"]},
    {"message": "包裹还没到，能退货吗", "expected": ["order_query", "knowledge"]},
    {"message": "取消订单后怎么退款", "expected": ["order_query", "knowledge"]},
    {"message": "查订单状态，并告诉我保修多久", "expected": ["order_query", "knowledge"]},
    {"message": "物流在哪，支持七天无理由吗", "expected": ["order_query", "knowledge"]},
    {"message": "订单发货了吗，发票怎么开", "expected": ["order_query", "knowledge"]},
    # knowledge类
    {"message": "怎么退货？", "expected": "knowledge"},
    {"message": "蓝牙耳机续航多久？", "expected": "knowledge"},
    {"message": "机械键盘有质保吗？", "expected": "knowledge"},
    {"message": "你们支持7天无理由吗？", "expected": "knowledge"},
    {"message": "客服电话多少？", "expected": "knowledge"},
    {"message": "可以开电子发票吗？", "expected": "knowledge"},
    {"message": "退货流程是什么？", "expected": "knowledge"},
    {"message": "退款多久到账？", "expected": "knowledge"},
    {"message": "发货用什么快递？", "expected": "knowledge"},
    {"message": "售后电话是多少？", "expected": "knowledge"},
    {"message": "如何退货", "expected": "knowledge"},
    {"message": "支持七天无理由退货吗", "expected": "knowledge"},
    {"message": "一般多久发货", "expected": "knowledge"},
    {"message": "发货时间是多久", "expected": "knowledge"},
    {"message": "键盘质保多长时间", "expected": "knowledge"},
    {"message": "耳机有降噪吗", "expected": "knowledge"},
    {"message": "机械键盘是青轴吗", "expected": "knowledge"},
    {"message": "能开发票吗", "expected": "knowledge"},
    {"message": "保修政策是什么", "expected": "knowledge"},
    {"message": "退货需要保持商品完好吗", "expected": "knowledge"},
    {"message": "客服热线是多少", "expected": "knowledge"},
    {"message": "下单后几天发货", "expected": "knowledge"},
    {"message": "顺丰包邮吗", "expected": "knowledge"},
    {"message": "蓝牙耳机充电接口是什么", "expected": "knowledge"},
    {"message": "怎么申请退款", "expected": "knowledge"},
    # transfer_human
    {"message": "我要转人工", "expected": "transfer_human"},
    {"message": "转人工客服", "expected": "transfer_human"},
    {"message": "找经理", "expected": "transfer_human"},
    {"message": "找你们经理", "expected": "transfer_human"},
    {"message": "找主管", "expected": "transfer_human"},
    {"message": "我要投诉", "expected": "transfer_human"},
    {"message": "给我接人工", "expected": "transfer_human"},
    {"message": "转接人工", "expected": "transfer_human"},
    {"message": "我要和人说话", "expected": "transfer_human"},
    {"message": "找真人", "expected": "transfer_human"},
    {"message": "转人工处理", "expected": "transfer_human"},
    {"message": "人工客服在吗", "expected": "transfer_human"},
    {"message": "投诉你们服务", "expected": "transfer_human"},
    {"message": "请帮我转人工", "expected": "transfer_human"},
    # 转人工 + 业务 
    {"message": "查一下订单并转人工", "expected": ["order_query", "transfer_human"]},
    {"message": "怎么退货，转人工客服", "expected": ["knowledge", "transfer_human"]},
    {"message": "我要投诉，先帮我查订单", "expected": ["order_query", "transfer_human"]},
    # chitchat / 偏好
    {"message": "今天天气真好", "expected": "chitchat"},
    {"message": "你好", "expected": "chitchat"},
    {"message": "你是谁？", "expected": "chitchat"},
    {"message": "讲个笑话", "expected": "chitchat"},
    {"message": "晚安", "expected": "chitchat"},
    {"message": "在吗", "expected": "chitchat"},
    {"message": "谢谢", "expected": "chitchat"},
    {"message": "哈哈好的", "expected": "chitchat"},
    {"message": "早上好", "expected": "chitchat"},
    {"message": "你能做什么", "expected": "chitchat"},
    {"message": "记住我晚上收货", "expected": "chitchat"},
    {"message": "我偏好晚间收货", "expected": "chitchat"},
    {"message": "以后都别早上送", "expected": "chitchat"},
    {"message": "配送时间希望晚上", "expected": "chitchat"},
    {"message": "不要打电话，记住一下", "expected": "chitchat"},
    {"message": "收货时间改成晚上可以吗", "expected": "chitchat"},
    {"message": "帮我记住不要早上送货", "expected": "chitchat"},
    {"message": "想晚上收货", "expected": "chitchat"},
    {"message": "晚间收货可以吗", "expected": "chitchat"},
    {"message": "我的收货偏好是晚上", "expected": "chitchat"},
    {"message": "order id 555666 状态", "expected": "order_query"},
    {"message": "质保怎么申请", "expected": "knowledge"},
    {"message": "退货地址怎么拿", "expected": "knowledge"},
]

# 回答质量（约25 条，与 insert_data 知识对齐）
qa_pairs = [
    {"question": "怎么退货？", "answer": "7天内无理由退货，需保持商品完好，联系客服获取退货地址。"},
    {"question": "如何退货", "answer": "7天内无理由退货，商品需完好，联系客服拿退货地址。"},
    {"question": "支持七天无理由吗？", "answer": "支持7天内无理由退货，需保持商品完好。"},
    {"question": "退货需要注意什么", "answer": "7天内申请，保持商品完好，联系客服获取退货地址。"},
    {"question": "退货流程是什么？", "answer": "在7天内联系客服，保持商品完好后按指引退回。"},
    {"question": "耳机续航多久？", "answer": "蓝牙耳机续航约20小时。"},
    {"question": "蓝牙耳机续航多久？", "answer": "续航20小时。"},
    {"question": "耳机有降噪吗", "answer": "蓝牙耳机支持降噪。"},
    {"question": "蓝牙耳机是什么接口充电", "answer": "Type-C充电。"},
    {"question": "键盘有RGB吗？", "answer": "机械键盘支持RGB背光。"},
    {"question": "机械键盘有质保吗？", "answer": "机械键盘有1年质保。"},
    {"question": "键盘是青轴吗", "answer": "机械键盘为87键青轴。"},
    {"question": "机械键盘怎么连接", "answer": "USB有线连接。"},
    {"question": "发货用什么快递？", "answer": "顺丰包邮发货。"},
    {"question": "发货时间是多久", "answer": "下单后48小时内发货。"},
    {"question": "一般多久发货", "answer": "下单后48小时内发货，顺丰包邮。"},
    {"question": "顺丰包邮吗", "answer": "是的，顺丰包邮。"},
    {"question": "客服电话多少？", "answer": "400-123-4567"},
    {"question": "售后电话是多少？", "answer": "400-123-4567"},
    {"question": "客服热线是多少", "answer": "400-123-4567"},
    {"question": "可以开电子发票吗？", "answer": "如知识库未覆盖具体开票规则，应如实说明或引导联系客服，不要编造。"},
    {"question": "退款多久到账？", "answer": "如知识库无明确时效，应说明需以实际退款进度为准或引导联系客服，不要编造天数。"},
    {"question": "保修多久", "answer": "机械键盘1年质保。"},
    {"question": "耳机蓝牙版本是多少", "answer": "蓝牙5.3。"},
    {"question": "下单后几天能发货", "answer": "下单后48小时内发货。"},
]


def _as_set(expected) -> Set[str]:
    if isinstance(expected, (list, tuple, set)):
        return set(expected)
    return {expected}


def _f1(pred: Set[str], gold: Set[str]) -> float:
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    tp = len(pred & gold)
    precision = tp / len(pred)
    recall = tp / len(gold)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


async def evaluate_intent():
    """评估意图分类（子集命中 + 微平均 F1）。"""
    hit = 0
    f1_scores: List[float] = []
    for case in test_intent_cases:
        gold = _as_set(case["expected"])
        state = {
            "messages": [{"role": "user", "content": case["message"]}],
            "intents": [],
            "tool_results": [],
            "memory_hits": [],
            "user_id": "test_user",
            "session_id": "test_session",
            "order_id": None,
        }
        result = await classify_intents(state)
        pred = set(result.get("intents") or [])
        score = _f1(pred, gold)
        f1_scores.append(score)
        # 命中：预测覆盖全部期望意图
        if gold.issubset(pred):
            hit += 1
        else:
            print(f"漏检/错分：{case['message']} -> 预期 {gold}，实际 {pred}，F1={score:.2f}")

    total = len(test_intent_cases)
    avg_f1 = sum(f1_scores) / total if total else 0.0
    print(f"\n意图分类样本数：{total}")
    print(f"子集命中率（expected 包含于 pred）：{hit}/{total} = {hit / total:.1%}")
    print(f"平均 F1：{avg_f1:.1%}\n")
    return hit / total if total else 0.0, avg_f1


async def evaluate_answer_quality(use_agent: bool = False):
    """
    回答质量打分。
    use_agent=False：对参考答案自检（冒烟）
    use_agent=True：跑真实 Agent 再与参考对比
    """
    from graph import build_graph

    agent = build_graph() if use_agent else None
    scores = []
    for pair in qa_pairs:
        if use_agent:
            state = {
                "messages": [{"role": "user", "content": pair["question"]}],
                "intents": [],
                "tool_results": [],
                "memory_hits": [],
                "user_id": "eval_user",
                "session_id": "eval_session",
                "order_id": None,
            }
            result = await agent.ainvoke(state)
            answer = result["messages"][-1]["content"]
        else:
            answer = pair["answer"]

        prompt = f"""你是严格的电商客服评测员。根据「参考答案」评估「模型回答」的准确性与完整性，只回复1-5的整数。
问题：{pair['question']}
参考答案：{pair['answer']}
模型回答：{answer}
评分："""
        resp = await client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        score = int(digits[0]) if digits else 0
        scores.append(score)
        print(f"问题：{pair['question']}  得分：{score}  回答摘要：{answer[:60]}")

    avg = sum(scores) / len(scores) if scores else 0
    print(f"\n回答质量样本数：{len(qa_pairs)}")
    print(f"平均得分：{avg:.2f}/5 （use_agent={use_agent}）")
    return avg


if __name__ == "__main__":
    print("=" * 50)
    print("开始意图分类评估...")
    asyncio.run(evaluate_intent())

    print("=" * 50)
    print("开始回答质量评估（参考答案冒烟）...")
    asyncio.run(evaluate_answer_quality(use_agent=False))
    print("=" * 50)
    print("评估完成（端到端请加: evaluate_answer_quality(use_agent=True)）")
