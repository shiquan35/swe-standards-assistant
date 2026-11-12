# Shi Quan's Post-Project Reflections

## What went well

The utilisation of `spec-driven-development`using `skills`enabled me to pilot how I wanted features to be built. It goes beyond just the typical prompting and let the coding agent go wild without restraint. Through `spec-driven-development`, I was playing a part in iterative decision making, as well as being made aware of the considerations and concerns that I have missed out. I know what will be implemented even before implementation began. I think this is what distinguishes people from vibe coders and an engineer.

The skills and workflow I used was in this order:

1. `explore`
2. `grill-with-docs`
3. `feature-plan`
4. `implement`

## Improvements

### Dataset

The Engineering Handbook was deliberately simple (LLM-generated and in markdown files).

In real world applications, documents to be ingested are typically in .docx or in PDF. And sometimes images, tables are included in the documents which contains relevant information. This makes document parsing more complex but its the standard.

Also, the documents in the Engineering Handbook were small in size. The smallest document only had 303 tokens and the largest at 694. These documents are merely 1 page documents whereas documents of several pages are expected.

Therefore, working with "realistic" documents would have been a great exposure to real world applications.

### Conducting experiments

I only tried 3 chunking strategies and conducted 6 experiments by permutating the Top-K.

I can definitely expand on the chunking strategies by varying the tokens and exploring other non-linear strategies beyong `heading-aware`.

I can also improve on how I conduct my ingestion-experiment workflow. Right now a few SQL tables an ingestion function and an evaluation function supports this process. But the functions are too rigid for implementing other strategies. I have no plan in mind yet and I will research and consult experienced minds on how this process can be improved.

### Future enhancements

The current version of `Developer Standards Assistant` only has `Single-turn` and `Stateless RAG capabilties`.

There were plans to add conversation support, build RAG evaluation and implement an Agentic workflow for code analysis.

However, this project had to be put on hold to prioritise other projects.

### Guardrails

I believe this is where I am lacking the most and its the most crucial aspect.

I never spent much time on this and relied on the `grill`to raise this topic to me.

Learning about guardrails will be the absolute next thing I will do in my learning journey.

## Conclusion

I embarked on this project to dip my toes into what AI Engineering is all about. To learn about data ingestion, vector search, evaluation and invoking LLMs.

I believe I have achieved all that and have a better understanding on what the Data Engineers and Data Scientists in my company do.

I know this is just the beginning and I am excited and hungry for more.
