# Come-Blog Future Plan

## Vision

Evolve Come-Blog from a local blog generator into a reliable blog-writing agent that can plan, research, write, critique, revise, and publish high-quality content through reusable agent interfaces.

## Roadmap

### 1. Strengthen the Writing Core

- Add configurable writing styles, audiences, tones, lengths, and content formats.
- Introduce source-aware research with citations and fact-checking.
- Improve evaluation beyond a single score: structure, accuracy, clarity, originality, SEO, and audience fit.
- Add deterministic quality gates so weak drafts cannot be published silently.

### 2. Build the Blog Agent

- Move from a fixed graph to a capable agent with clear tools and bounded planning.
- Support article briefs, outlines, section planning, revision history, and human approval checkpoints.
- Add durable runs, resumable workflows, streaming progress, and traceable decisions.
- Keep model providers interchangeable, with Ollama as the local-first option.

### 3. Make It a Reusable Capability

- Package the blog writer as a reusable Skill with documented inputs, outputs, constraints, and examples.
- Expose the agent through an MCP server so development harnesses and other AI tools can request previews, drafts, evaluations, and publishing actions.
- Define stable contracts, versioned prompts, structured schemas, and capability discovery.
- Add authentication, rate limits, audit logs, and safe handling of user content before external use.

### 4. Become an Excellent Service

- Add a polished web interface for briefs, drafts, comparisons, approvals, and downloads.
- Persist projects, sources, templates, and generated articles.
- Add observability for latency, model usage, cost estimates, quality scores, and failure rates.
- Create evaluation datasets and regression benchmarks so improvements are measurable.

## Ambitious Target

Come-Blog should become a dependable writing collaborator that works locally, integrates with agent harnesses through Skill and MCP interfaces, and produces explainable, source-aware content that humans can review and trust.
