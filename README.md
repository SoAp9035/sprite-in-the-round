# sprite-in-the-round

Give an agent a pixel-art sprite, an object turnaround or a directional character sheet. It builds a static coloured mesh and delivers a **GLB** and an **OBJ** you can open in Blender or import into a game, with a PNG preview. For objects, top, side, front and back at the same scale give the agent the most information. For characters, use matching poses from several directions. A single front sprite also works, with inferred depth and back details.

The agent builds the shape as horizontal pixel layers. The same layers support 2D sprite-stack turning and solid mesh export. See [references/sprite-stacking-guide.md](references/sprite-stacking-guide.md) for the bundled sprite-stacking and pixel-perfect integration guide (adapted from SpriteCook).

## Install

Copy or symlink this folder (keep the name `sprite-in-the-round`) into your agent's skills directory:

- **Claude Code:** `~/.claude/skills/sprite-in-the-round` (or `<project>/.claude/skills/`)
- **Clients following the cross-client convention:** `~/.agents/skills/sprite-in-the-round` (or `<project>/.agents/skills/`)
- **Other agents:** check where they load skills from, or point them at `SKILL.md`.

The helper scripts need Python 3.9+ with NumPy and Pillow. Grid recovery also uses SciPy and headless OpenCV. With [uv](https://docs.astral.sh/uv/) installed, `uv run scripts/<name>.py` sets them up automatically.

The damaged-grid detector is vendored under `scripts/pixelfixer/` with its MIT license. [Pixel Art Fixer source](https://github.com/Retro-Diffusion/pixel-art-fixer/tree/ef376e57e1c272633ca2dbf5f29ec3fcf6596465/python/pixelfixer)

## Layout

```
SKILL.md                      technique, workflow, gotchas (loaded when the skill triggers)
references/                   loaded on demand: sprite-stacking & pixel-perfect guide, input cleanup, building, characters, views, engines
scripts/pixel_grid.py         screenshot / upscale / JPEG → native pixel art
scripts/voxlib.py             building blocks the agent imports (stack_views, carve, sculpt, decal, lathe, paint, ...)
scripts/stack.py              static GLB + OBJ and preview from a slice sheet, plus optional 2D exports
scripts/glb.py                GLB and OBJ mesh writers used by stack.py
assets/viewer.html            standalone viewer (3D normal/AO lighting, slice scan, exploded, 16-dir export)
evals/evals.json              test prompts (agentskills.io eval format)
evals/test_*.py               regression tests: uv run --with numpy --with pillow --with scipy --with opencv-python-headless python -m unittest discover -s evals
```
