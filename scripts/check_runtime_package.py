"""Download the pinned official runtime for Windows integration tests only."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.environment import manifest
from app.services.installer import DependencyManager

root = Path(__file__).resolve().parents[1]
package = DependencyManager(root, root).download_runtime(manifest(root))
print(package)
