"""
往 Milvus 集合中插入初始的商品知识和 FAQ 数据。
"""
import argparse

from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

from config import EMBEDDING_DIM, MILVUS_HOST, MILVUS_PORT
from embeddings import embed_texts

client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")


def ensure_collection(collection_name: str, reset: bool = False):
    if client.has_collection(collection_name):
        if not reset:
            print(f"集合 {collection_name} 已存在，跳过创建")
            return
        client.drop_collection(collection_name)
        print(f"已删除旧集合 {collection_name}")

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(
            name="embedding",
            dtype=DataType.FLOAT_VECTOR,
            dim=EMBEDDING_DIM,
        ),
    ]
    schema = CollectionSchema(fields, description="知识库")
    client.create_collection(collection_name, schema=schema)
    print(f"集合 {collection_name} 创建成功（dim={EMBEDDING_DIM}）")


def embed(texts):
    return embed_texts(texts)


def insert_data(collection_name, texts, reset: bool = False):
    ensure_collection(collection_name, reset=reset)
    embeddings = embed(texts)
    data = [{"text": t, "embedding": e} for t, e in zip(texts, embeddings)]
    res = client.insert(collection_name, data)
    print(f"向 {collection_name} 插入 {res.get('insert_count', len(data))} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="删除并重建集合",
    )
    args = parser.parse_args()

    product_texts = [
        "蓝牙耳机：支持降噪，蓝牙5.3，续航20小时，Type-C充电",
        "机械键盘：87键青轴，RGB背光，USB有线连接，1年质保",
    ]
    faq_texts = [
        "如何退货：7天内无理由退货，需保持商品完好，联系我们客服获取退货地址",
        "发货时间：下单后48小时内发货，顺丰包邮",
        "客服电话：400-123-4567",
    ]

    insert_data("product_knowledge", product_texts, reset=args.reset)
    insert_data("faq", faq_texts, reset=args.reset)
    print("初始化完成。若检索异常，请在 Attu 中确认向量索引已创建。")
