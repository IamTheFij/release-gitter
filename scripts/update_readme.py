from __future__ import annotations

import subprocess
import sys
from pathlib import Path

COMMAND = ["./venv/bin/release-gitter", "--help"]


def get_usage() -> str:
    process_result = subprocess.run(COMMAND, capture_output=True, text=True)
    return process_result.stdout.strip()


def update_usage(readme_path: Path, usage: str):
    if not readme_path.exists():
        raise ValueError("Readme file does not exist.")

    new_content: list[str] = []
    usage_content = [f"    {line}\n" for line in usage.split("\n")]

    with open(readme_path, "r") as file:
        content_lines = file.readlines()

    in_usage_block = False
    for line in content_lines:
        if "USAGE_END" in line:
            in_usage_block = False

        if in_usage_block:
            continue

        new_content.append(line)

        if "USAGE_BEGIN" in line:
            in_usage_block = True
            new_content.extend(usage_content)

    print(new_content)

    with open(readme_path, "w") as file:
        file.writelines(new_content)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        readme_path = Path(sys.argv[1])
    else:
        readme_path = Path(__file__).parent.parent / "README.md"

    if not readme_path.exists():
        raise ValueError("Readme file does not exist.")

    usage = get_usage()
    update_usage(readme_path, usage)
