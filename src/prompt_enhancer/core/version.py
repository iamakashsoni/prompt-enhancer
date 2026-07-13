import os

__version__ = "1.0.0"

GITHUB_REPO = "iamakashsoni/prompt-enhancer"
PORTFOLIO_URL = "https://akashsoni.vercel.app/projects/prompt-enhancer"

UPDATE_MANIFEST_URL = os.environ.get(
    "PE_UPDATE_URL",
    f"https://github.com/{GITHUB_REPO}/releases/latest/download/version.json",
)
