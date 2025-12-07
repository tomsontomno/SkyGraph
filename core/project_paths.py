from pathlib import Path
from dotenv import load_dotenv

# Root directory of the project (e.g., where main.py is located)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Load .env from root
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

# Main folders
DATA_DIR = PROJECT_ROOT / "data"
CURRENT_DIR = DATA_DIR / "current"
LOGS_DIR = DATA_DIR / "logs"
STATIC_DIR = PROJECT_ROOT / "static"

ARCHIVE_FLIGHTGRAPH_DIR = DATA_DIR / "archives" / "flight_graph"
GRAPH_PKL_FILE = CURRENT_DIR / "graph.pkl"

# Optional helpers
PROXIES_FILE = CURRENT_DIR / "proxies.txt"
EDGES_FILE = CURRENT_DIR / "edges.json"
CURL_REQUEST_FILE = CURRENT_DIR / "curl_request_data.json"
SUCCESS_SOUND = STATIC_DIR / "success.wav"
WAKEUP_SOUND = STATIC_DIR / "wake_up.wav"


# Optional helpers
def path_in_data(*parts):
    return DATA_DIR.joinpath(*parts)


def path_in_logs(filename):
    return LOGS_DIR / filename


def path_in_current(filename):
    return CURRENT_DIR / filename


def path_in_static(filename):
    return STATIC_DIR / filename


def path_in_archive_flightgraph(filename):
    return ARCHIVE_FLIGHTGRAPH_DIR / filename