"""Build an ephemeral core-only wheel projection for architecture tests.

The output is a CI artifact, not a public GEODE distribution.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _record_row(path: str, data: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return path, f"sha256={digest.decode('ascii')}", str(len(data))


def _dist_info_root(names: list[str]) -> str:
    roots = {
        name.split("/", 1)[0]
        for name in names
        if "/" in name and name.split("/", 1)[0].endswith(".dist-info")
    }
    if len(roots) != 1:
        raise ValueError(f"expected one .dist-info directory, found {len(roots)}")
    return roots.pop()


def _keep(path: str, dist_info: str) -> bool:
    if path.startswith("core/"):
        return not path.startswith("core/self_improving/")
    return path in {f"{dist_info}/METADATA", f"{dist_info}/WHEEL"} or path.startswith(
        f"{dist_info}/licenses/"
    )


def _validate_paths(input_wheel: Path, output_wheel: Path) -> None:
    if input_wheel.resolve() == output_wheel.resolve():
        raise ValueError("input and output wheel paths must differ")
    if output_wheel.resolve().is_relative_to((REPO_ROOT / "dist").resolve()):
        raise ValueError("kernel probe output must not be written under the repository dist/")


def build_kernel_probe(input_wheel: Path, output_wheel: Path) -> None:
    """Project *input_wheel* into a non-publishable core-only test wheel."""
    _validate_paths(input_wheel, output_wheel)

    with zipfile.ZipFile(input_wheel) as source:
        infos = [info for info in source.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("input wheel contains duplicate file names")
        dist_info = _dist_info_root(names)
        required = {f"{dist_info}/METADATA", f"{dist_info}/WHEEL"}
        missing = required - set(names)
        if missing:
            raise ValueError(f"input wheel is missing: {', '.join(sorted(missing))}")
        files = [(info, source.read(info)) for info in infos if _keep(info.filename, dist_info)]

    record_path = f"{dist_info}/RECORD"
    rows = [_record_row(info.filename, data) for info, data in files]
    rows.append((record_path, "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(rows)

    output_wheel.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_wheel, "w") as target:
        for info, data in files:
            target.writestr(info, data)
        target.writestr(record_path, record.getvalue().encode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-wheel", required=True, type=Path)
    parser.add_argument("--output-wheel", required=True, type=Path)
    args = parser.parse_args()
    build_kernel_probe(args.input_wheel, args.output_wheel)
    print(args.output_wheel)


if __name__ == "__main__":
    main()
