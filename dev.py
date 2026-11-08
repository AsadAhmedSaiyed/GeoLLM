"""Cross-platform launcher for GeoLLM (Backend + Modern Frontend).

Usage:
    python dev.py            # Starts FastAPI serving both Backend & React UI on http://127.0.0.1:8000
    python dev.py --dev      # Starts FastAPI (8000) AND Vite hot-reload dev server (5173) concurrently
"""
import os
import sys
import subprocess
import signal

# Ensure UTF-8 mode
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, "frontend")
DIST_HTML = os.path.join(ROOT, "static", "dist", "index.html")

def build_frontend_if_needed():
    if not os.path.exists(DIST_HTML):
        print("[GeoLLM] Building modern React frontend...")
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run([npm_cmd, "run", "build"], cwd=FRONTEND_DIR, check=True)

def main():
    dev_mode = "--dev" in sys.argv
    build_frontend_if_needed()

    processes = []
    
    # Start Backend (FastAPI on port 8000)
    print("\n" + "="*60)
    print(" 🌍 GeoLLM — Autonomous Geospatial Workbench")
    print("="*60)
    print(" Backend + React UI: http://127.0.0.1:8000")
    if dev_mode:
        print(" Vite Hot-Reload UI: http://localhost:5173")
    print(" Press Ctrl+C to stop all services.")
    print("="*60 + "\n")

    backend_proc = subprocess.Popen(
        [sys.executable, "web_app.py"],
        cwd=ROOT,
        env=os.environ,
    )
    processes.append(backend_proc)

    if dev_mode:
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        vite_proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=FRONTEND_DIR,
            env=os.environ,
        )
        processes.append(vite_proc)

    def cleanup(*_):
        for p in processes:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        backend_proc.wait()
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()

