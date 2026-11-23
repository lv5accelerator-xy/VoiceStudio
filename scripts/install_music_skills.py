"""Install the pinned text-only music skills into the current checkout.

Uses git objects from fixed GitHub sources. No remote scripts, checkout hooks,
package installs, or user-level writes are involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
SOURCES = {"jtydhr88/lyric-writing-skills", "jtydhr88/music-composition-skills"}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], timeout=90)


def files_at(repo: Path, ref: str, skill_path: str) -> dict[str, bytes]:
    directory = skill_path.removesuffix("/SKILL.md")
    files = {}
    tree = git(repo, "ls-tree", "-rz", ref, "--", directory)
    for line in tree.decode("utf-8").rstrip("\x00").split("\x00"):
        metadata, _, path = line.partition("\t")
        name = path.removeprefix(directory + "/")
        if (
            not metadata.startswith("100644 blob ")
            or path != f"{directory}/{name}"
            or len(Path(name).parts) != 1
            or Path(name).suffix not in {".md", ".yaml"}
        ):
            raise ValueError(f"Unexpected file in pinned skill: {path}")
        files[name] = git(repo, "show", f"{ref}:{path}")
    for name in ("LICENSE", "NOTICE"):
        files[name] = git(repo, "show", f"{ref}:{name}")
    if "SKILL.md" not in files:
        raise ValueError(f"Missing skill entry: {skill_path}")
    return files


def digest(files: dict[str, bytes]) -> str:
    result = hashlib.sha256()
    for name, content in sorted(files.items()):
        result.update(name.encode("utf-8") + b"\0")
        result.update(hashlib.sha256(content).digest())
    return result.hexdigest()


def matches(destination: Path, files: dict[str, bytes]) -> bool:
    return destination.is_dir() and not destination.is_symlink() and {
        path.name for path in destination.iterdir()
    } == files.keys() and all(
        file.is_file() and not file.is_symlink() and file.read_bytes() == content
        for name, content in files.items()
        for file in [destination / name]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify already installed files without network access.")
    check = parser.parse_args().check
    lock = json.loads((ROOT / "skills-lock.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for name, item in lock["skills"].items():
        if item["source"] in SOURCES:
            groups[(item["source"], item["ref"])].append((name, item))
    if not groups:
        raise SystemExit("No pinned music skills configured.")
    for (source, ref), items in groups.items():
        with TemporaryDirectory(prefix="voicestudio-skills-") as temp:
            repo = Path(temp)
            if not check:
                git(repo, "init", "-q")
                git(repo, "-c", "protocol.file.allow=never", "fetch", "-q", "--depth=1",
                    f"https://github.com/{source}.git", ref)
                if git(repo, "rev-parse", "FETCH_HEAD").decode().strip() != ref:
                    raise SystemExit(f"Unexpected revision for {source}")
            for name, item in items:
                if Path(name).name != name or name in {".", ".."}:
                    raise SystemExit(f"Invalid locked skill name: {name}")
                destination = SKILLS / name
                if check:
                    entries = list(destination.iterdir()) if destination.is_dir() and not destination.is_symlink() else []
                    files = {path.name: path.read_bytes() for path in entries if path.is_file() and not path.is_symlink()}
                    if len(files) != len(entries) or digest(files) != item["computedHash"]:
                        raise SystemExit(f"Missing or modified pinned skill: {name}")
                    print(f"Verified {name}")
                    continue
                files = files_at(repo, ref, item["skillPath"])
                if digest(files) != item["computedHash"]:
                    raise SystemExit(f"Skill content does not match the lock: {name}")
                if destination.exists() or destination.is_symlink():
                    if not matches(destination, files):
                        raise SystemExit(f"Existing skill differs: {destination}. Move it aside before installing.")
                else:
                    destination.mkdir()
                    for filename, content in files.items():
                        (destination / filename).write_bytes(content)
                print(f"Installed {name}")


if __name__ == "__main__":
    main()
