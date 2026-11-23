# Local runtime and one-button setup

People who have never opened a terminal set up Replicants with one button on Home. Setup:

1. **Checks the computer** (`replicants/desktop/hardware.py`): system memory and, on NVIDIA machines, graphics memory. It answers in plain words: it can host a replicant, a lighter one, or not yet (under 8 GB RAM).
2. **Gets thought running.** With the runtime on `auto`, an Ollama the person already runs is used as-is. Otherwise the app installs its own private runtime (`replicants/desktop/local_runtime.py`):
   - one exact Ollama release, pinned by version, size and SHA-256 at release build time (`scripts/pin_local_runtime.py`),
   - downloaded and verified before anything is unpacked; unsafe archive paths are refused,
   - unpacked under the app's data folder (`runtime/ollama-<version>/`), with its own model folder (`models/`),
   - run on a private localhost port (11535), never the system Ollama's port,
   - stopped when the app quits; the app stops only a process it started from its own runtime folder.
3. **Picks a mind that fits**, unless the person already chose one: `gemma4:26b` with 16 GB+ of graphics memory, `gemma4:e4b` with 8 GB+ of graphics memory or 16 GB+ of RAM, `gemma4:e2b` with 8 GB+ of RAM. These tiers are provisional until the model evaluation scores the smaller models.
4. **Downloads what's missing**, with progress: "Preparing a place for thought…", "Downloading a mind…", "Downloading memory…".

`replicants/desktop/runtime_pin.json` pins Ollama 0.40.15 by version, download URL, size and SHA-256. A build without a complete pin refuses to download a runtime at all: it falls back to an Ollama the person installs. Settings offers the choice explicitly: automatic, built into Replicants, or an Ollama I installed.

## Signing

The workflow signs the installer when the repository has `WINDOWS_SIGNING_CERT_BASE64` (a base64 PFX) and `WINDOWS_SIGNING_CERT_PASSWORD` secrets. Without them it stays unsigned, as before. Only the installer is signed today; signing the bundled executables needs Tauri's `signCommand`.

## Limits

- The built-in runtime is Windows x64 only. Other platforms use an Ollama the person installs.
- Graphics memory is sensed on NVIDIA only; other machines are judged by system memory.
- The Ollama Windows archive is large (it carries GPU libraries), so first setup is a big download on top of the model.
