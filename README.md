# Developer Standards Assistant

A centralized, conversational interface for accessing engineering knowledge.

To help developers quickly find and understand engineering best practices, development standards, and company-specific guidelines.

## Application Workflow

1. Developer asks a question
2. Question embedding
   * convert question into a vector
3. Vector search
   * Retrieve relevant handbook chunks
4. LLM answer generation
5. Developer receives answer with source citations

## Stack

| Component       | Technology                        |
| --------------- | --------------------------------- |
| Frontend        | NextJS                            |
| Backend         | FastAPI                           |
| Authentication  | Supabase Auth                     |
| Database        | Supabase PostgreSQL               |
| Vector storage  | pgvector                          |
| Embedding model | OpenAI `text-embedding-3-small` |
| LLM             | OpenAI API                        |
| Knowledge base  | Markdown files in repo            |


## Running this app

More info to be added
