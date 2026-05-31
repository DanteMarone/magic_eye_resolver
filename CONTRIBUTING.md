# Contributing

## Documentation mandate

Documentation is part of every change — not an afterthought. The goal is that we
never lose functionality accidentally, and that the docs double as a checklist for
testing for broken or missing behaviour.

Rules:

1. **Every feature and behaviour is documented.** When you add functionality,
   write its documentation in the same change. When you change what a feature
   does, update its documentation in the same change. A feature without docs is
   not done.
2. **The README stays lean and current.** It holds the project overview, the
   getting-started guide, and a short features/functionality summary that links
   out. It must always reflect the current toolset.
3. **Everything else lives in `docs/`.** Detailed usage, flags, algorithms,
   controls, and edge cases go in a dedicated doc under `docs/`, linked from the
   README. Create a new doc when a component grows its own surface area.
4. **Docs are the source of truth for testing.** Before claiming a change is
   complete, check the affected doc against the actual behaviour. If they
   disagree, one of them is a bug — fix it.

### Where things live

| Doc | Covers |
|-----|--------|
| `README.md` | Overview, getting started, features summary, links |
| `docs/resolver.md` | Recovering depth from a Magic Eye |
| `docs/creator.md` | Generating a Magic Eye; carriers; performance |
| `docs/depth-maps.md` | Photo cutout, subject shapes, painting your own depth |
| `docs/studio.md` | The interactive studio (`editor.py`), step by step |

## Keep the bundled agent skill in sync

`skills/magic-eye/` is a portable Agent Skill that keeps its **own copies** of the
CLI scripts (`scripts/resolver.py`, `scripts/creator.py`, `scripts/depthmap.py`) so
it runs without the repo. Because they are copies, they can drift:

- When you change `resolver.py`, `creator.py`, or `depthmap.py` at the repo root,
  **refresh the matching copy** under `skills/magic-eye/scripts/` in the same change.
- When you change a tool's behaviour or flags, also update `skills/magic-eye/SKILL.md`
  and the relevant `skills/magic-eye/references/*.md` — the skill is documentation
  too, and the same mandate applies.
