"""Fill bundled/libs with deckcheck and pygls (all pure Python) so the extension runs with any Python 3.11+ and no
pip install (M2 spec §4.1, §9). Run from editors/vscode: python scripts/bundle_libs.py"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
LIBS = HERE / "bundled" / "libs"

if __name__ == "__main__":
    shutil.rmtree(LIBS, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", str(LIBS), "--no-compile",
                    f"{REPO}[lsp]"], check=True)
    for junk in LIBS.glob("*.dist-info/RECORD"):
        junk.unlink()
    print(f"bundled into {LIBS}: {sorted(p.name for p in LIBS.iterdir() if p.is_dir())}")
