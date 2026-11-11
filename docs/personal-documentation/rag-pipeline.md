# RAG pipeline

## Workflow

1. User sends a question
2. Convert question to embeddings
3. Vector similarity search
4. Retrieve Top-K chunks
5. Construct LLM prompt
6. LLM generates answer
7. Return answer

## Chosen strategy

- Heading-aware, 200 tokens + 40 overlap
