"""Launch the viewer: python -m lexarena.ui [--port 8501]"""
import subprocess
import sys
from pathlib import Path


def main() -> int:
    port = sys.argv[sys.argv.index("--port") + 1] if "--port" in sys.argv else "8501"
    app = Path(__file__).with_name("app.py")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", port,
                            "--server.address", "localhost", "--browser.gatherUsageStats", "false"])


if __name__ == "__main__":
    sys.exit(main())
