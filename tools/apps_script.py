"""Copy the Apps Script web app's files to the clipboard, one at a time, for pasting
into the Sheet's Apps Script editor (see docs/SETUP.md, step 7).

  python tools/apps_script.py code       Code.gs
  python tools/apps_script.py index      Index.html (built from spending_tracker/dashboard.html)
  python tools/apps_script.py manifest   appsscript.json

Add --print to write it to stdout instead. None of these files contain your data.
Add --demo for the public demo's versions (docs/DEMO.md): Code.gs never writes, and
the manifest runs as the owner for anyone, signed in or not. Only use --demo on a
Sheet that holds nothing but fake data.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def index_html() -> str:
    # Apps Script fills <?!= data ?> with the Sheet's data when the page is opened.
    html = (ROOT / "spending_tracker" / "dashboard.html").read_text()
    assert "/*DATA*/null" in html
    return html.replace("/*DATA*/null", "<?!= data ?>")


def code(demo: bool) -> str:
    text = (ROOT / "apps_script" / "Code.gs").read_text()
    if demo:
        assert "const DEMO = false;" in text
        text = text.replace("const DEMO = false;", "const DEMO = true;")
    return text


def manifest(demo: bool) -> str:
    text = (ROOT / "apps_script" / "appsscript.json").read_text()
    if not demo:
        return text
    m = json.loads(text)
    m["webapp"] = {"executeAs": "USER_DEPLOYING", "access": "ANYONE_ANONYMOUS"}
    return json.dumps(m, indent=2) + "\n"


def main():
    demo = "--demo" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--print", "--demo")]
    files = {"code": lambda: code(demo), "index": index_html, "manifest": lambda: manifest(demo)}
    if len(args) != 1 or args[0] not in files:
        raise SystemExit(__doc__)
    text = files[args[0]]()
    if "--print" in sys.argv:
        print(text)
    else:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        print(f"Copied {args[0]}{' (demo)' if demo else ''} ({len(text):,} characters) to the clipboard.")


if __name__ == "__main__":
    main()
