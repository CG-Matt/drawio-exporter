#!.venv/bin/python
import argparse
import math
import shutil
import subprocess
import tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import unquote, urlparse

try:
    from playwright.sync_api import sync_playwright
except Exception:
    raise SystemExit(
        "Python Playwright is required. Install in .venv with: "
        ".venv/bin/python -m pip install playwright && "
        ".venv/bin/python -m playwright install chromium"
    )

REPO_DIR = Path(__file__).resolve().parent.parent
TARGET_ROOT = REPO_DIR / ".webapp"

FULL_COPY_LIST = [
    "export3.html",
    "export-fonts.css",
    "js/app.min.js",
    "js/export-init.js",
    "js/export.js",
    "js/extensions.min.js",
    "js/stencils.min.js",
    "js/shapes-14-6-5.min.js",
    "js/math-print.js",
    "mxgraph/css/common.css",
    "math4/es5",
    "resources",
    "styles/fonts",
    "shapes",
    "stencils",
    "img",
]

SEED_FILES = [
    "export3.html",
    "export-fonts.css",
    "js/app.min.js",
    "js/export-init.js",
    "js/export.js",
    "mxgraph/css/common.css",
    "stencils/electrical/logic_gates.xml",
    "stencils/electrical/iec_logic_gates.xml",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Vendor draw.io webapp files into .webapp/. "
            "Use --source-root for local source or --github for remote."
        )
    )
    parser.add_argument("--full", action="store_true", help="Copy broad fallback webapp asset set")
    parser.add_argument("--input", action="append", default=[], help="Input diagram file for dependency discovery")
    parser.add_argument("--github", "--from-github", dest="github", action="store_true", help="Pull draw.io source from GitHub via shallow sparse clone")
    parser.add_argument("--ref", default=None, help="Git branch/tag/commit when using --github")
    parser.add_argument("--source-root", default=None, help="Path to draw.io repository root (required unless --github)")
    parser.add_argument("--chrome", default=None, help="Optional Chromium executable path override")
    return parser.parse_args()


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=False,
    )


def get_default_inputs(source_root: Path) -> list[Path]:
    return [
        source_root / "templates" / "other" / "block.xml",
        source_root / "templates" / "network" / "enterprise_1.xml",
        source_root / "templates" / "engineering" / "electrical_1.xml",
        source_root / "templates" / "flowcharts" / "epc.xml",
    ]


def prepare_source_root(opts: argparse.Namespace) -> tuple[Path, callable]:
    if not opts.github:
        if not opts.source_root:
            raise RuntimeError("Missing required --source-root for local mode")

        repo_root = Path(opts.source_root).expanduser().resolve()
        source_root = repo_root / "src" / "main" / "webapp"

        if not source_root.exists():
            raise RuntimeError(
                f"Could not find webapp at {source_root}. "
                "Pass the draw.io repository root to --source-root."
            )

        return source_root, (lambda: None)

    temp_base = Path(tempfile.mkdtemp(prefix="drawio-vendorize-"))
    clone_root = temp_base / "drawio"
    github_url = "https://github.com/jgraph/drawio.git"

    clone_cmd = ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse"]

    if opts.ref:
        clone_cmd += ["--branch", opts.ref]

    clone_cmd += [github_url, str(clone_root)]

    print(f"Cloning draw.io from GitHub{f' (ref: {opts.ref})' if opts.ref else ''}...")
    run(clone_cmd)
    run(["git", "-C", str(clone_root), "sparse-checkout", "set", "src/main/webapp"])

    source_root = clone_root / "src" / "main" / "webapp"

    def cleanup() -> None:
        shutil.rmtree(temp_base, ignore_errors=True)

    return source_root, cleanup


def reset_target_root() -> None:
    shutil.rmtree(TARGET_ROOT, ignore_errors=True)
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)


def copy_entry(source_root: Path, rel_path: str) -> bool:
    src = source_root / rel_path
    dst = TARGET_ROOT / rel_path

    if not src.exists():
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)

    return True


def copy_full(source_root: Path) -> None:
    reset_target_root()

    for rel_path in FULL_COPY_LIST:
        if not copy_entry(source_root, rel_path):
            raise RuntimeError(f"Missing source path: {source_root / rel_path}")

        print(f"Copied {rel_path}")

    print(f"Vendored full webapp asset set to {TARGET_ROOT}")


def make_handler(web_root: Path):
    class StaticHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            req_path = unquote(urlparse(self.path).path or "/")
            normalized = req_path.lstrip("/")

            if not normalized:
                normalized = "index.html"

            full_path = (web_root / normalized).resolve()

            if web_root not in full_path.parents and full_path != web_root:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Forbidden")
                return

            if full_path.is_dir():
                full_path = full_path / "index.html"

            if not full_path.exists() or not full_path.is_file():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            content_type = {
                ".html": "text/html; charset=UTF-8",
                ".js": "application/javascript; charset=UTF-8",
                ".css": "text/css; charset=UTF-8",
                ".json": "application/json; charset=UTF-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".gif": "image/gif",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".xml": "application/xml; charset=UTF-8",
                ".txt": "text/plain; charset=UTF-8",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".ttf": "font/ttf",
            }.get(full_path.suffix.lower(), "application/octet-stream")

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(full_path.read_bytes())

        def log_message(self, *_):
            return

    return StaticHandler


def to_local_rel_path(url: str, port: int) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if parsed.hostname != "127.0.0.1" or parsed.port != port:
        return None

    rel = unquote(parsed.path or "/")

    if rel == "/":
        rel = "/index.html"

    rel = rel.lstrip("/")

    if not rel or ".." in rel:
        return None

    return rel


def discover_required_files(source_root: Path, input_files: list[Path], chrome_path: str | None) -> list[str]:
    requested = set(SEED_FILES)

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(source_root))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as p:
            launch_opts = {"headless": True}
            if chrome_path:
                launch_opts["executable_path"] = chrome_path

            browser = p.chromium.launch(**launch_opts)
            try:
                for input_file in input_files:
                    xml = input_file.read_text(encoding="utf-8")
                    page = browser.new_page(viewport={"width": 1920, "height": 1080})

                    def on_request(req):
                        rel = to_local_rel_path(req.url, port)
                        if rel:
                            requested.add(rel)

                    page.on("request", on_request)

                    page.goto(f"http://127.0.0.1:{port}/export3.html", wait_until="load", timeout=120000)
                    page.wait_for_function("() => typeof window.render === 'function'", timeout=120000)

                    page.evaluate(
                        """
                        (renderData) => {
                          window.render(renderData);
                        }
                        """,
                        {
                            "format": "png",
                            "xml": xml,
                            "scale": "1",
                            "border": "0",
                            "w": "0",
                            "h": "0",
                            "allPages": "0",
                        },
                    )

                    page.wait_for_selector("#LoadingComplete", state="attached", timeout=120000)
                    page.close()
                    print(f"Scanned dependencies from {input_file}")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    return sorted(requested)


def copy_discovered_files(source_root: Path, file_set: list[str]) -> None:
    reset_target_root()

    copied: list[str] = []
    missing: list[str] = []

    for rel_path in sorted(file_set):
        if copy_entry(source_root, rel_path):
            copied.append(rel_path)
        else:
            missing.append(rel_path)

    if missing:
        preview = ", ".join(missing[:3])
        print(f"Skipped {len(missing)} missing references (example: {preview})")

    total_size = 0

    for rel_path in copied:
        p = TARGET_ROOT / rel_path
        if p.exists() and p.is_file():
            total_size += p.stat().st_size

    print(f"Copied {len(copied)} files, total {total_size / (1024 * 1024):.2f} MiB")
    print(f"Vendored minimal discovered webapp set to {TARGET_ROOT}")


def main() -> int:
    opts = parse_args()
    source_root, cleanup = prepare_source_root(opts)

    try:
        if not source_root.exists():
            raise RuntimeError(f"Cannot find source webapp root: {source_root}")

        if opts.full:
            copy_full(source_root)
            return 0

        inputs = [Path(p).expanduser().resolve() for p in opts.input] if opts.input else get_default_inputs(source_root)
        inputs = [p for p in inputs if p.exists()]

        if not inputs:
            raise RuntimeError("No valid input diagrams found for dependency discovery")

        file_set = discover_required_files(source_root, inputs, opts.chrome)
        copy_discovered_files(source_root, file_set)
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
