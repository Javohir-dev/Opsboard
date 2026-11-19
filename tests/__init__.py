import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = tempfile.mkdtemp(prefix="opsboard-test-")
os.environ["OPS_DATA_DIR"] = DATA
os.environ["OPS_SECRET_STORE"] = "file"
os.environ["OPS_NO_OS_NOTIFY"] = "1"
os.environ["OPS_CLAUDE_CREDENTIALS"] = os.path.join(DATA, "no-credentials.json")
os.environ["OPS_CLAUDE_JSON"] = os.path.join(DATA, "no-claude.json")
os.environ["OPS_CLAUDE_SETTINGS"] = os.path.join(DATA, "claude-settings.json")
os.environ["OPS_ANTHROPIC_URL"] = "http://127.0.0.1:9"
for key in ("OPS_CONFIG", "OPS_NOTES", "OPS_TOKEN_FILE", "OPS_HIS_ROOT", "OPS_PORT"):
    os.environ.pop(key, None)
sys.path.insert(0, str(ROOT))
