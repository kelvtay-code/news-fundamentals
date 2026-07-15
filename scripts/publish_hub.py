"""
Regenerate the Optionx Hub and publish it (git commit + push) to GitHub Pages.

Designed to be dropped into the ProKai pipeline as a final step. Never
raises on "nothing to commit" -- that's a normal no-op outcome, not a
failure, since not every pipeline run changes the source data.
"""
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_hub  # noqa: E402


def run(cmd):
    return subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True)


def main():
    generate_hub.build()

    run(["git", "add", "-A"])
    diff = run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("[INFO] No changes to publish (data unchanged since last run).")
        return

    commit = run(["git", "commit", "-m", "Auto-update hub data"])
    if commit.returncode != 0:
        print(f"[ERROR] git commit failed:\n{commit.stdout}\n{commit.stderr}")
        sys.exit(1)

    push = run(["git", "push"])
    if push.returncode != 0:
        print(f"[ERROR] git push failed:\n{push.stdout}\n{push.stderr}")
        sys.exit(1)

    print("[OK] Optionx Hub published.")


if __name__ == "__main__":
    main()
