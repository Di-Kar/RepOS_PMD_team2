"""analytics_etl package - adds parent directory to sys.path for tests."""
import sys
from pathlib import Path

# Get the project root (parent of analytics_etl/)
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
