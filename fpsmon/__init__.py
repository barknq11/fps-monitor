"""FPS Monitor - a customisable FPS / GPU / CPU overlay for Windows."""

#: Single source of truth for the version. The build script and the update
#: check both read this, so a release cannot disagree with what the app
#: reports about itself.
__version__ = "1.1.0"

#: Where the update check looks. Owner/repo only, no credentials.
GITHUB_REPO = "barknq11/fps-monitor"
