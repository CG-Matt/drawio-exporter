#!.venv/bin/python
import argparse
import html
import json
import math
import re
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from playwright.sync_api import sync_playwright
except Exception:
    print(
        "Python Playwright is required. Install with: pip install playwright && python -m playwright install chromium",
        file=sys.stderr,
    )
    raise


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export .drawio files to PNG/SVG using draw.io export3 renderer")
    parser.add_argument("input_positional", nargs="?", default=None, help="Input .drawio/.xml file")
    parser.add_argument("-i", "--input", dest="input_opt", default=None, help="Input .drawio/.xml file")
    parser.add_argument("-o", "--output", default=None, help="Output file path")
    parser.add_argument("-f", "--format", default=None, help="Output format: png or svg")
    parser.add_argument("-s", "--scale", type=float, default=10, help="Export scale (default 10)")
    parser.add_argument("--border", type=float, default=0, help="Border in pixels")
    parser.add_argument("--width", type=float, default=0, help="Fit width")
    parser.add_argument("--height", type=float, default=0, help="Fit height")
    parser.add_argument("--page-id", default=None, help="Export specific page id")
    parser.add_argument("--from", dest="from_idx", default=None, help="Export from page index")
    parser.add_argument("--to", dest="to_idx", default=None, help="Export to page index")
    parser.add_argument("--all-pages", action="store_true", help="Export all pages")
    parser.add_argument("--chrome", default=None, help="Optional Chromium executable path override")
    args = parser.parse_args()

    args.input = args.input_opt or args.input_positional

    if not args.input:
        fail("Missing input file. Use --input <file.drawio>.")

    args.input = str(Path(args.input).expanduser().resolve())
    input_path = Path(args.input)

    if not input_path.exists():
        fail(f"Input file not found: {args.input}")

    if not args.format:
        ext = Path(args.output).suffix.lower() if args.output else ""
        args.format = "svg" if ext == ".svg" else "png"

    args.format = args.format.lower()

    if args.format not in ("png", "svg"):
        fail("Format must be png or svg.")

    if not args.output:
        args.output = str(input_path.with_suffix(f".{args.format}"))

    args.output = str(Path(args.output).expanduser().resolve())

    if not math.isfinite(args.scale) or args.scale <= 0:
        fail("--scale must be a positive number.")

    return args


def slugify_name(name: str) -> str:
    value = re.sub(r"[^\w\s-]", "", name or "").strip().lower()
    value = re.sub(r"[\s_-]+", "-", value).strip("-")
    return value or "page"


def extract_drawio_pages(xml_text: str) -> list[dict]:
    if not re.search(r"<mxfile[\s>]", xml_text, re.IGNORECASE):
        return []

    pages: list[dict] = []

    for m in re.finditer(r"<diagram\b([^>]*)>", xml_text, re.IGNORECASE):
        attrs = m.group(1) or ""
        id_m = re.search(r'\bid="([^"]+)"', attrs, re.IGNORECASE)

        if not id_m:
            continue

        name_m = re.search(r'\bname="([^"]*)"', attrs, re.IGNORECASE)
        pages.append(
            {
                "id": html.unescape(id_m.group(1)),
                "name": html.unescape(name_m.group(1) if name_m else ""),
            }
        )

    return pages


def select_pages(args: argparse.Namespace, pages: list[dict]) -> list[dict]:
    if not pages:
        return []

    if args.page_id:
        for i, p in enumerate(pages):
            if p["id"] == args.page_id:
                return [{**p, "index": i}]

        fail(f"Page id not found: {args.page_id}")

    if args.from_idx is not None or args.to_idx is not None:
        from_i = int(args.from_idx or 0)
        from_i = max(0, min(from_i, len(pages) - 1))
        raw_to = int(args.to_idx) if args.to_idx is not None else from_i
        to_i = max(from_i, min(raw_to, len(pages) - 1))
        return [{**pages[i], "index": i} for i in range(from_i, to_i + 1)]

    if len(pages) > 1 or args.all_pages:
        return [{**p, "index": i} for i, p in enumerate(pages)]

    return [{**pages[0], "index": 0}]


def build_output_path(base_output: Path, fmt: str, page: dict, multi: bool) -> Path:
    if not multi:
        return base_output

    suffix = f"-p{page['index'] + 1:02d}-{slugify_name(page.get('name') or f'page-{page['index'] + 1}') }"
    return base_output.with_name(f"{base_output.stem}{suffix}{base_output.suffix or ('.' + fmt)}")


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


def export_with_playwright(args: argparse.Namespace, xml_text: str) -> list[Path]:
    repo_dir = Path(__file__).resolve().parent.parent
    web_root = repo_dir / ".webapp"

    if not (web_root / "export3.html").exists():
        fail(f"Vendored webapp not found at {web_root}. Run: .venv/bin/python vendorize.py --github")

    pages = extract_drawio_pages(xml_text)
    selected_pages = select_pages(args, pages)
    multi_output = len(selected_pages) > 1
    targets = selected_pages if selected_pages else [{"id": None, "name": "", "index": 0}]

    output_base = Path(args.output)
    output_base.parent.mkdir(parents=True, exist_ok=True)

    handler = make_handler(web_root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    written: list[Path] = []

    try:
        with sync_playwright() as p:
            launch_opts = {"headless": True}
            executable = args.chrome or None
            if executable:
                launch_opts["executable_path"] = executable

            browser = p.chromium.launch(**launch_opts)
            try:
                for target in targets:
                    out_path = build_output_path(output_base, args.format, target, multi_output)
                    page = browser.new_page(viewport={"width": 1920, "height": 1080})
                    try:
                        page.goto(f"http://127.0.0.1:{port}/export3.html", wait_until="load", timeout=120000)
                        page.wait_for_function("() => typeof window.render === 'function'", timeout=120000)

                        render_data = {
                            "format": args.format,
                            "xml": xml_text,
                            "scale": str(args.scale),
                            "border": str(int(args.border) if float(args.border).is_integer() else args.border),
                            "w": str(int(args.width) if float(args.width).is_integer() else args.width),
                            "h": str(int(args.height) if float(args.height).is_integer() else args.height),
                            "pageId": target.get("id") or None,
                            "from": None,
                            "to": None,
                            "allPages": "0",
                        }

                        page.evaluate(
                            """
                            (renderData) => {
                              window.__renderData = renderData;
                              window.__graph = window.render(renderData);
                            }
                            """,
                            render_data,
                        )

                        page.wait_for_selector("#LoadingComplete", state="attached", timeout=120000)

                        export_info = page.evaluate(
                            """
                            () => {
                              const done = document.getElementById('LoadingComplete');
                              const bounds = JSON.parse(done.getAttribute('bounds') || '{}');
                              const scale = Number(done.getAttribute('scale') || '1');
                              return { bounds, scale };
                            }
                            """
                        )

                        if args.format == "png":
                            bounds = export_info.get("bounds") or {}
                            clip = {
                                "x": max(0, float(bounds.get("x", 0) or 0)),
                                "y": max(0, float(bounds.get("y", 0) or 0)),
                                "width": max(1, math.ceil(float(bounds.get("width", 1) or 1))),
                                "height": max(1, math.ceil(float(bounds.get("height", 1) or 1))),
                            }

                            page.set_viewport_size(
                                {
                                    "width": max(1920, math.ceil(clip["x"] + clip["width"] + 16)),
                                    "height": max(1080, math.ceil(clip["y"] + clip["height"] + 16)),
                                }
                            )

                            page.screenshot(path=str(out_path), clip=clip, type="png", omit_background=True)
                        else:
                            svg_text = page.evaluate(
                                """
                                () => {
                                  const graph = window.__graph;
                                  const data = window.__renderData;
                                  const done = document.getElementById('LoadingComplete');
                                  const expScale = Number(done.getAttribute('scale') || '1');
                                  let bg = graph.background;

                                  if (bg === mxConstants.NONE)
                                  {
                                    bg = null;
                                  }

                                  const svgRoot = graph.getSvg(bg, expScale, parseInt(data.border || '0', 10) || 0,
                                    false, null, true);

                                  if (graph.shadowVisible)
                                  {
                                    graph.addSvgShadow(svgRoot);
                                  }

                                  if (graph.mathEnabled)
                                  {
                                    Editor.prototype.addMathCss(svgRoot);
                                  }

                                  return Graph.xmlDeclaration + '\\n' + Graph.svgDoctype + '\\n' + mxUtils.getXml(svgRoot);
                                }
                                """
                            )

                            out_path.write_text(svg_text, encoding="utf-8")

                        written.append(out_path)
                    finally:
                        page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    return written


def main() -> int:
    args = parse_args()
    xml_text = Path(args.input).read_text(encoding="utf-8")
    written = export_with_playwright(args, xml_text)

    for file in written:
        print(f"Exported {args.format.upper()} to {file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
