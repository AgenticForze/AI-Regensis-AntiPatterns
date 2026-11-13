# Applied AI Anti-Patterns

A field guide to production AI anti-patterns: 488 entries across 21 sections, from RAG and retrieval through agentic AI, evaluation, observability, LLMOps and CI/CD, security, governance, the three hyperscaler platforms, local vs. cloud economics, harness engineering, and Claude and other AI tools. It includes 360 telecom and financial-services production scenarios.

Each entry contains a problem statement, the anti-pattern, why it fails, a broken-vs-fixed architecture diagram (generated SVG), the recommended solution, why it succeeds, a reference implementation, and a key takeaway.

## Structure

```
content/          One YAML file per section (all text, code and diagram specs)
  site.yaml       Site metadata and part/section ordering
  imported/       Additional entries per section (<source>-<section-id>.yaml), appended after the section's own entries
build/
  build.py        Static site generator → docs/
  diagrams.py     SVG diagram engine (flows, layer stacks, TCO chart)
assets/           CSS and JS (theme toggle, search, catalog filters)
docs/             Generated site (served by GitHub Pages)
```

## Build locally

```bash
pip install -r requirements.txt
python build/build.py
python -m http.server -d docs 8000   # open http://localhost:8000
```

## Publish on GitHub Pages

Either option works:

- **GitHub Actions (recommended):** Settings → Pages → Source: *GitHub Actions*. The included workflow (`.github/workflows/pages.yml`) builds and deploys on every push to `main`.
- **Branch folder:** Settings → Pages → Source: *Deploy from a branch* → `main` / `/docs`. Commit the regenerated `docs/` folder after editing content.

## Editing content

Add or edit entries in `content/*.yaml`. Diagram specs are compact flows:

```yaml
diagram:
  bad:  ["Query", "Embed", "!Top-k vector only", "LLM"]      # "!" marks a failure point
  bad_note: "What goes wrong"
  good: ["Query", "+BM25 | Dense", "+Rerank", "LLM"]           # "+" marks a new component, "|" stacks
  good_note: "Why it holds up"
  good_loop: "Optional feedback loop label"
```

## License

Content licensed under CC BY 4.0. Platform names and capabilities reflect public documentation as of November 2026.
