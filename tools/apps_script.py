"""Copy the Apps Script web app's files to the clipboard, one at a time, for pasting
into the Sheet's Apps Script editor (see README, "Dashboard on your phone").

  python tools/apps_script.py code       Code.gs
  python tools/apps_script.py index      Index.html (built from spending_tracker/dashboard.html)
  python tools/apps_script.py manifest   appsscript.json

Add --print to write it to stdout instead. None of these files contain your data.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def index_html() -> str:
    # Apps Script fills <?!= data ?> with the Sheet's data when the page is opened.
    html = (ROOT / "spending_tracker" / "dashboard.html").read_text()
    assert "/*DATA*/null" in html
    return html.replace("/*DATA*/null", "<?!= data ?>")


def main():
    args = [a for a in sys.argv[1:] if a != "--print"]
    files = {"code": lambda: (ROOT / "apps_script" / "Code.gs").read_text(),
             "index": index_html,
             "manifest": lambda: (ROOT / "apps_script" / "appsscript.json").read_text()}
    if len(args) != 1 or args[0] not in files:
        raise SystemExit(__doc__)
    text = files[args[0]]()
    if "--print" in sys.argv:
        print(text)
    else:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        print(f"Copied {args[0]} ({len(text):,} characters) to the clipboard.")


if __name__ == "__main__":
    main()
