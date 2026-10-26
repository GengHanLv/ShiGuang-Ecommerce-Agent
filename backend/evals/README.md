# RAG检索评测

本目录的评测代码可随源码发布。真实平台测试集、平台资料与评测报告保存在本地Others 和 data/knowledge_base，不随GitHub发布。它不调用聊天模型，不消耗聊天API额度；需要可用的后端、BGE模型与Milvus。

## 运行

先启动服务，在项目根目录运行：

```powershell
.venv\Scripts\python.exe -m backend.evals.retrieval_benchmark --base-url http://127.0.0.1:8001
```

本机默认测试集：`Others/evaluation/rag_cases.jsonl`；输出：`Others/evaluation/latest/results.json`及`报告.md`。可以指定自己的文件：

```powershell
.venv\Scripts\python.exe -m backend.evals.retrieval_benchmark --cases path/to/cases.jsonl --output Others/evaluation/my-run --ks 1 3 5
```

公开clone不会包含私人测试集。需要先上传自己的资料，调用`POST /knowledge/search`确认来源/向量编号，再人工整理标签。JSONL每行一个问题，例如以下**虚构格式示例**：

```json
{"id":"case-001","query":"示例说明书里如何更换电池？","collection":"product_knowledge","platform":"all","relevant_ids":["vector:123"]}
```

有source_id时以source_id标注；普通上传文件没有source_id时使用`vector:`加检索结果id。每个问题可列出多个相关ID。相关ID应在评测前固定，不要只把系统已经返回的结果当作正确答案；否则会形成循环验证。每个问题按其指定平台和集合检索，所以本评测不测Agent选错工具/集合/平台的情况。

## 最常用的四项指标

设前K条返回结果里命中的标注证据数为H，该问题全部标注相关证据数为R。

| 指标 | 公式/含义 | 关注点 |
| --- | --- | --- |
| Recall@K | H / R | 需要的证据有没有找全 |
| Precision@K | H / K | 前K个位置里正确证据占多少 |
| MRR@K | 首个正确证据排名的倒数；前K没有则为0，再跨问题平均 | 第一个正确证据是否靠前 |
| nDCG@K | DCG / 理想DCG；二元标签下每条相关证据贡献1/log2(排名+1) | 多条相关证据的排序质量 |

所有问题同权宏平均。没有用一个问题的单次命中率冒充所有相关证据的召回率。Precision分母固定为K，即使返回不足K条；所有结果为空时四项为0。标签为空属于数据错误，会停止评测。

例如正确证据为A和C，返回B、A、C：Recall@3=1，Precision@3=2/3，MRR@3=1/2，nDCG@3约0.6934。手算样例由`backend/tests/test_retrieval_metrics.py`验证。

## 实现说明

- `retrieval_metrics.py`：标准库计算公式，可独立测试。
- `retrieval_benchmark.py`：调用当前真实API，K=1、3、5分别请求，记录返回编号、各路得分、耗时、分平台指标与未命中样本。
- API失败或平台越界会停止并输出failed报告，避免把服务故障静默忽略成漂亮成绩。
- 保留测试集SHA256、知识集合数量和服务状态；本机dataset-manifest.json额外保存语料校验值。
- 使用当前线上缓存策略；报告耗时可能包含缓存命中与模型冷启动，不应当作并发性能指标。

## 怎样理解结果

数字只对标签所定义的相关性有效。当前本机60题是从现有语料整理的目标证据回归集，包含6道双证据题；不是随机真实用户日志，也不是独立双人全量标注。未标注但语义相关的段落也会被公式当作不相关，Precision尤其依赖标签完整性。

60题共66个目标证据标签，所以即使全部找回，Precision@3最高也只有66/(60*3)=36.67%，Precision@5最高22%。不要因为看到35%的Precision@3，就直接认为65%的段落内容一定无用。

检索指标不能代替最终回答准确率、引用是否支持答案或模型有没有编造事实。后续扩大未参与调试的测试集、由人工复核全部相关段落，再重新评测，才能更可靠地比较不同方案。本次没有根据失败样本修改检索参数或标签。

指标定义参考：[ir-measures官方文档](https://ir-measur.es/en/latest/measures.html)、[Qdrant检索评测课程](https://qdrant.tech/course/beginners/module-6/measure-first/)。
