---
title: "从零搭建一个 RAG 知识库问答系统：核心链路与踩坑记录"
date: 2026-08-20
tags: ["RAG", "LLM", "Python"]
summary: "记录一次 RAG 系统从 0 到 1 的落地过程：文档切片、向量检索、重排序与生成链路的完整设计，以及实际踩过的几个坑。"
---

RAG（Retrieval-Augmented Generation）是当前大模型落地最成熟的技术路线之一。这篇文章记录我从零搭建一套知识库问答系统的核心链路与踩坑经验。

## 整体链路

一个典型的 RAG 系统包含四个阶段：

1. **文档解析**：把 PDF、Word、Markdown 等文档转成纯文本
2. **切片与向量化**：将文本切分为合适粒度的 chunk，调用 embedding 模型生成向量
3. **检索与重排**：根据用户问题召回 Top-K 相关片段，再做重排序
4. **生成**：把召回片段作为上下文拼进 Prompt，交给大模型生成回答

## 切片策略是关键

切片粒度直接决定检索质量。经验值：

- chunk 大小控制在 300-500 token，相邻 chunk 保留 10%-20% 重叠
- 优先按语义边界切（标题、段落），而不是机械地按字数切
- 表格、代码块尽量保持完整，不要切开

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=400,
    chunk_overlap=80,
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", ""],
)
chunks = splitter.split_text(document)
```

## 检索质量优化

### 混合检索

纯向量检索对专有名词、缩写的召回效果不稳定。实践中采用「向量 + BM25」混合检索，再用 RRF（Reciprocal Rank Fusion）融合结果，召回率明显提升。

### 重排序

在召回 Top-20 之后，用 Cross-Encoder 重排模型（如 bge-reranker）精排到 Top-5 再送给大模型，回答准确率的提升立竿见影。

## 踩过的坑

- **切片把上下文切断了**：表格被切碎后，检索到的片段语义不完整，回答质量骤降。解决方式是解析阶段就保护结构化内容。
- **Embedding 模型换版本没有全量重建索引**：新旧向量空间不一致，检索结果混乱。必须记录 embedding 模型版本，换模型时全量重建。
- **Prompt 里没约束「不知道就说不知道」**：模型会对检索不到的內容强行编造。加入明确的兜底指令后，幻觉显著减少。

## 小结

RAG 不是「向量数据库 + 大模型」的简单拼接，而是一套需要精心调优的工程链路。把每个环节的数据质量做好，效果提升远比换更大的模型划算。
