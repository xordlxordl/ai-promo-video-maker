"""Sync generic files improved in template into this project (run when updating or revising an existing project).

python3 scripts/sync_template.py            List generic files that differ from template (does not modify anything)
python3 scripts/sync_template.py --diff     Print diffs simultaneously
python3 scripts/sync_template.py --apply    Overwrite these files with template version (first confirm diffs do not contain project-specific changes)

Compares only style-independent generic files: scripts in scripts/ except mix.py, and player logic in web/.
mix.py, timing.json, scenes, theme, fonts.json, web/config.ts, and web/style.css are project-specific and left untouched.

Template location search order: environment variable PROMO_TEMPLATE -> clone mode <repo>/template (this project in outputs/<project>/build)
-> promo-video-maker installed in AI tools' skills directories under workspace and home directory (Skill mode).
"""
import argparse
import filecmp
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = "promo-video-maker"
SKILL_DIRS = [".claude/skills", ".cursor/skills", ".agents/skills", ".codex/skills", ".config/agents/skills"]
OWN = {"scripts/mix.py"}


def find_template():
    if os.environ.get("PROMO_TEMPLATE"):
        return os.path.abspath(os.environ["PROMO_TEMPLATE"])
    workspace = os.path.normpath(os.path.join(ROOT, "..", "..", ".."))
    if os.path.isfile(os.path.join(workspace, "template", "scripts", "sync_template.py")):
        return os.path.join(workspace, "template")
    for base in (workspace, os.path.expanduser("~")):
        for d in SKILL_DIRS:
            for skill_md in glob.glob(os.path.join(base, d, "*", "SKILL.md")):
                if f"name: {SKILL}" in open(skill_md, encoding="utf-8").read():
                    return os.path.join(os.path.dirname(skill_md), "template")
    return None


TEMPLATE = find_template()
GENERIC = ["scripts", "web/App.tsx", "web/main.tsx", "web/vite.config.ts"]


def generic_files():
    for g in GENERIC:
        base = os.path.join(TEMPLATE, g)
        if os.path.isfile(base):
            yield g
            continue
        for name in sorted(os.listdir(base)):
            rel = f"{g}/{name}"
            if rel not in OWN and name.endswith((".py", ".js", ".mjs", ".ts", ".tsx")):
                yield rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not TEMPLATE or not os.path.isdir(TEMPLATE) or os.path.samefile(TEMPLATE, ROOT):
        sys.exit("Cannot find template: This script must be run under <output_dir>/<project>/build/; if template is not in the default location, specify it with PROMO_TEMPLATE=<tool_dir>/template")
    print(f"Comparing against {TEMPLATE}")
    css = os.path.join(ROOT, "src", "index.css")
    if os.path.exists(css) and "max-width: none" not in open(css, encoding="utf-8").read():
        print("NOTE: src/index.css is missing 'img { max-width: none; }': enlarged screenshots will be squished horizontally; add it as in template/src/index.css")
    changed = []
    for rel in generic_files():
        t, p = os.path.join(TEMPLATE, rel), os.path.join(ROOT, rel)
        if not os.path.exists(p):
            changed.append(rel)
            print(f"Missing  {rel}")
        elif not filecmp.cmp(t, p, shallow=False):
            changed.append(rel)
            print(f"Different  {rel}")
            if a.diff:
                subprocess.run(["diff", "-u", p, t])
    if not changed:
        print("All generic files match template")
        return
    if a.apply:
        for rel in changed:
            shutil.copy2(os.path.join(TEMPLATE, rel), os.path.join(ROOT, rel))
        print(f"Overwrote {len(changed)} file(s) with template version; now run npm run lint and npm run mix to ensure nothing is broken")
    else:
        print("After confirming differences are template improvements (not project-specific changes), add --apply")


if __name__ == "__main__":
    main()
