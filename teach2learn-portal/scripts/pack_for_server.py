"""Emit a single self-contained program for the GPU host, on stdout.

The deployed portal on the GPU host predates the multilingual work: its
app/services/ has inference.py but no translation.py. Everything else
check_languages.py needs is there and API-identical -- training_contract_messages,
generate_detailed, GenerationResult, DEFAULT_SUBJECT_MODELS, topics.py.

So rather than splitting the run across two machines, this packs what is missing
into the piped bytes. The emitted program registers an embedded copy of
translation.py as `app.services.translation` in sys.modules before
check_languages.py imports it, then runs check_languages.py.

lessons.json is embedded the same way and for the same reason: the harness reads
its teacher scripts from the repo root, and nothing of ours exists on the host's
filesystem. The stderr line reports the bank version and how many of its lessons
nobody has reviewed yet, so an unreviewed run cannot be started by accident.

Nothing is written on the server: the program arrives on stdin, and the module
only ever exists in that process's memory.

    python3 scripts/pack_for_server.py | ssh HOST \\
      'cd ~/scratch/teach2learn-portal && set -a && . ./.env && set +a && \\
       CUDA_VISIBLE_DEVICES=0 $APP_PYTHON - --baseline'

The host's own .venv is a web-serving environment with no torch/transformers, so
it raises "Real inference requires the server inference dependencies". The live
portal runs under a different interpreter, named by APP_PYTHON in run.sh:

    /data/scratch/sanyam_jain_2022/mistral_finetune/.qwendt/bin/python

APP_PYTHON is set in the service's process environment rather than .env, so it
has to be spelled out in the ssh command.

--with-key additionally embeds SARVAM_API_KEY from .env.local, since the host's
.env has no Sarvam key. Embedding it keeps the secret out of `ps` on a shared
host, which an env var on the ssh command line would not. Pipe this straight into
ssh -- do not write the output to a file, or the key lands on disk.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATION = ROOT / "app" / "services" / "translation.py"
HARNESS = ROOT / "scripts" / "check_languages.py"
# The lesson bank sits at the repo root, one level above the portal, because the RAG
# tool's harness reads the same file.
LESSONS = ROOT.parent / "lessons.json"

# check_languages.py opens with `from __future__ import annotations`, which the
# compiler requires to be the first statement in the file. The prelude has to run
# before its imports, so the future import is hoisted here and stripped below.
PRELUDE = '''\
from __future__ import annotations
# --- packed by scripts/pack_for_server.py; nothing here touches the filesystem ---
import base64 as _pack_b64, os as _pack_os, sys as _pack_sys, types as _pack_types

_pack_sys.path.insert(0, _pack_os.getcwd())
import app.services as _pack_pkg  # the host's real package

_pack_mod = _pack_types.ModuleType("app.services.translation")
_pack_mod.__package__ = "app.services"
exec(compile(_pack_b64.b64decode("{translation}").decode("utf-8"),
             "app/services/translation.py", "exec"), _pack_mod.__dict__)
_pack_sys.modules["app.services.translation"] = _pack_mod
_pack_pkg.translation = _pack_mod

{env}
for _pack_name in [n for n in dir() if n.startswith("_pack_")]:
    del globals()[_pack_name]
# --- end prelude ---

'''


def read_env_local(names: list[str]) -> dict[str, str]:
    """Pull specific values out of .env.local without importing dotenv."""
    path = ROOT / ".env.local"
    if not path.exists():
        sys.exit(f"{path} not found; cannot source a Sarvam key")
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if match and match.group(1) in names:
            found[match.group(1)] = match.group(2).strip("\"'")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-key",
        action="store_true",
        help="embed SARVAM_API_KEY from .env.local (needed for --sweep, not for --baseline)",
    )
    args = parser.parse_args()

    if sys.stdout.isatty():
        sys.exit(
            "refusing to print the packed program to a terminal -- it may contain a key.\n"
            "Pipe it into ssh instead; see this file's docstring."
        )

    env_lines = ""
    if args.with_key:
        values = read_env_local(["SARVAM_API_KEY", "T2L_TRANSLATION_BACKEND"])
        key = values.get("SARVAM_API_KEY", "")
        if not key:
            sys.exit("no SARVAM_API_KEY in .env.local; --sweep needs one to translate")
        backend = values.get("T2L_TRANSLATION_BACKEND") or "sarvam"
        env_lines = (
            f'_pack_os.environ["SARVAM_API_KEY"] = '
            f'_pack_b64.b64decode("{base64.b64encode(key.encode()).decode()}").decode()\n'
            f'_pack_os.environ["T2L_TRANSLATION_BACKEND"] = "{backend}"'
        )
        print(f"packed with SARVAM_API_KEY (…{key[-4:]}) and backend={backend}", file=sys.stderr)
    else:
        # The host has no Sarvam key, so translate() would silently pass text
        # through untranslated and every language would look like a clean
        # round-trip. Fail instead.
        env_lines = '_pack_os.environ.setdefault("T2L_TRANSLATION_BACKEND", "off")'
        print("packed without a Sarvam key (--baseline only)", file=sys.stderr)

    if not LESSONS.exists():
        sys.exit(f"{LESSONS} not found; the harness has no teacher scripts without it")
    bank = json.loads(LESSONS.read_text())
    lessons = bank.get("lessons") or []
    unreviewed = [item["id"] for item in lessons if not item.get("reviewed")]
    print(
        f"packed lesson bank v{bank.get('version')}: {len(lessons)} lessons, "
        f"{len(unreviewed)} unreviewed",
        file=sys.stderr,
    )
    if unreviewed:
        print(
            "  the run will need --allow-unreviewed and its results are stamped unreviewed",
            file=sys.stderr,
        )

    encoded = base64.b64encode(TRANSLATION.read_bytes()).decode()
    sys.stdout.write(PRELUDE.format(translation=encoded, env=env_lines))
    harness = HARNESS.read_text().replace("from __future__ import annotations\n", "", 1)

    # The harness declares this at module level, so setting it from the prelude would
    # be overwritten a moment later. Replacing the declaration is ordering-proof; the
    # assert stops the pack silently shipping a lessonless harness if it is renamed.
    declaration = "PACKED_LESSONS: dict[str, Any] | None = None"
    if harness.count(declaration) != 1:
        sys.exit(f"check_languages.py no longer declares {declaration!r}; update this packer")
    packed_bank = base64.b64encode(LESSONS.read_bytes()).decode()
    harness = harness.replace(
        declaration,
        "PACKED_LESSONS: dict[str, Any] | None = __import__('json').loads(\n"
        f'    __import__("base64").b64decode("{packed_bank}").decode("utf-8")\n'
        ")",
        1,
    )
    sys.stdout.write(harness)


if __name__ == "__main__":
    main()
