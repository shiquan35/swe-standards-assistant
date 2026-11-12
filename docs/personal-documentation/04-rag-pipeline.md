# RAG pipeline

This document is written solely by Shi Quan. No LLM was involved.

## Workflow

1. User sends a question
2. Convert question to embeddings
3. Vector similarity search
4. Retrieve Top-K chunks
5. Construct LLM prompt
6. LLM generates answer
7. Return answer

Current implementation is a **Single-turn, ****Stateless RAG**.

* Each request contains one independent question.
* The system retrieves relevant chunks from the knowledge base.
* The LLM generates an answer based on the retrieved context.
* No conversation history or session state is retained.
* Every new question starts a fresh RAG execution.

## Chosen strategy

- Heading-aware, 200 tokens + 40 overlap
