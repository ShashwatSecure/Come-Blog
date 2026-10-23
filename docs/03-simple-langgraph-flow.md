# Simple LangGraph Flow

## Goal

The first working LangGraph version uses one straight workflow. It accepts a
topic, prepares the context for writing, generates a draft, evaluates it, and
saves the final draft as a Markdown file.

## Flow

```text
START
  -> Orchestrator
  -> Generator
  -> Evaluator -- retry (until passed or attempt 3) --> Generator
  -> Writer
  -> END
```

## Steps Implemented

1. **Orchestrator** makes one structured LLM call that returns a blog title,
   a concise 3-4 line summary, and exactly five strong points for the topic.
2. **Generator** receives the topic and all five points and writes a simple
   10-sentence blog. On retry, it also receives evaluator feedback.
3. **Evaluator** makes a structured LLM call and checks relevance, clarity,
   usefulness, coverage of the five points, and sentence count.
4. **Conditional retry** sends failed drafts back to the Generator. The loop
   stops when the evaluator passes the draft or after three attempts.
5. **Writer** saves the accepted draft to `output/` with Markdown frontmatter.
6. **API** now invokes the compiled graph for `POST /blogs` and returns the
   summary, strong points, draft result, attempts, and output path.

## Deliberate Simplifications

- No dynamic fan-out or parallel section workers.
- No reducer or section subgraph.
- The writer does not make an LLM call; it only writes the final draft.
- The existing legacy node functions remain temporarily for compatibility with
  the current unit tests, but they are no longer used by the blog API flow.

## Validation

The existing node test suite passes with 10 tests. The live end-to-end path
requires Ollama and the configured models to be running.