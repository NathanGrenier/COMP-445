# Lab 2
## Development Setup

We use **[uv](https://docs.astral.sh/uv/)** for dependency management.

### Install uv

**MacOS / Linux:** [Follow this Guide](https://docs.astral.sh/uv/getting-started/installation/#__tabbed_1_1)

**Windows:** [Follow this Guide](https://docs.astral.sh/uv/getting-started/installation/#__tabbed_1_2)

### Create & Sync Environment

To create your local virtual environment (`.venv`) and install all dependencies locked in `uv.lock`:

```bash
uv sync
```

### Enter the Environment

You can activate the environment in your terminal:

**MacOS / Linux:**
```bash
source .venv/bin/activate
```

**Windows:**
```powershell
.venv\Scripts\activate
```

*Alternatively, you can run commands without activating by prefixing them with `uv run` (e.g., `uv run jupyter lab`).*

### Managing Packages

**Add a package:**
```bash
uv add <package_name>
# Example: uv add scipy
```

**Remove a package:**
```bash
uv remove <package_name>
```

**Sync with team changes:**
If someone else pushed changes to `uv.lock`, update your local environment:
```bash
uv sync
```

### Formatting & Linting

We use **Ruff** for linting and formatting.

**Check for errors (Lint):**
```bash
uv run ruff check .
```

**Auto-format code:**
```bash
uv run ruff format .
```

> **VS Code Tip:** Install the `Ruff` extension. It will use the settings in `pyproject.toml` to format your code automatically on save.