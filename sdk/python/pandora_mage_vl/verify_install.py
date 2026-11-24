"""Explicit install/update integrity check. Never called by model initialization."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(directory):
    root = Path(directory).resolve(strict=True)

    def resource(name):
        relative = Path(name)
        if not name or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe resource path")
        path = root / relative
        # Reject symlink components even when they point within the package.
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Symlink resource: " + name)
        path = path.resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Resource escapes package")
        return path

    config_path = resource("models.json")
    if config_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Oversized model metadata")
    config = json.loads(config_path.read_text())
    version = config.get("format_version")
    if type(version) is not int or version not in (1, 2) or config.get("model") != "Mage-VL":
        raise ValueError("Unsupported Mage-VL package")
    if config.get("profile") != {"context_tokens": 4096, "prefill_alignment_tokens": 128,
                                 "visual_tokens_per_canvas": 144, "embedding_elements": 2560}:
        raise ValueError("Unsupported model profile")
    expected = {}
    for line in resource("SHA256SUMS").read_text().splitlines():
        if len(line) <= 66 or line[64:66] not in ("  ", " *"):
            raise ValueError("Malformed checksum line")
        digest, name = line[:64], line[66:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) or name in expected:
            raise ValueError("Invalid or duplicate checksum")
        resource(name)
        expected[name] = digest
    common = config["resources"]
    required = {"models.json", common["tokenizer"], common["token_vectors"]["path"]}
    if any(Path(name).suffix in (".pdm", ".aidem") for name in required):
        raise ValueError("Invalid ordinary resource role")
    targets = []
    missing = []
    directories = set()
    for target in config["targets"]:
        files = target["files"]
        if target["qnn_version"] != "2.48" or set(files) != {"vision", "contexts"} or len(files["contexts"]) != 3:
            raise ValueError("Unsupported target roles")
        if version == 2:
            if target.get("formats") != {
                "vision": "aidem-v2.0.2-qnn-single",
                "contexts": "aidem-v2.0.2-genie-group",
            }:
                raise ValueError("Unsupported Mage-VL graph formats")
        elif "formats" in target:
            raise ValueError("Format declarations require the mixed model manifest")
        names = [files["vision"], *files["contexts"]]
        if len(set(names)) != 4:
            raise ValueError("Duplicate graph role")
        scope = resource(target["directory"])
        if scope in directories or scope == root / "targets" or not scope.is_relative_to(root / "targets"):
            raise ValueError("Invalid or duplicate target directory")
        directories.add(scope)
        graph_paths = [resource(name) for name in names]
        if len(set(graph_paths)) != len(names):
            raise ValueError("Duplicate graph path")
        for path in graph_paths:
            if path.suffix != ".aidem" or not path.is_relative_to(scope) or path == scope:
                raise ValueError("Invalid graph path")
        absent = [(role, name) for role, name, path in
                  zip(("vision", "language context", "language context", "language context"), names, graph_paths)
                  if not path.is_file()]
        if absent:
            missing.extend(f"[{target['soc']} {role}: {name}]" for role, name in absent)
        else:
            targets.append((target["soc"], names, target["directory"]))
    if not targets:
        detail = " ".join(missing) if missing else "no targets declared"
        raise ValueError("No complete model target; missing files: " + detail)
    if len(targets) > 1:
        raise ValueError("Multiple complete model targets: " +
                         " ".join(f"[{soc}: {directory}]" for soc, _, directory in targets))
    required.update(targets[0][1])
    if not required.issubset(expected):
        raise ValueError("Checksum manifest omits required resources")
    tensor = common["token_vectors"]
    if tensor["dtype"] != "float32-le" or tensor["shape"] != [151936, 2560] or tensor["layout"] != "row-major":
        raise ValueError("Unsupported token tensor")
    if resource(tensor["path"]).stat().st_size != 151936 * 2560 * 4:
        raise ValueError("Token tensor byte count mismatch")
    # Check the required closure AND every additional installed declared resource.
    checked = 0
    for name, digest in expected.items():
        path = resource(name)
        if not path.is_file():
            if name in required:
                raise ValueError("Missing resource: " + name)
            continue
        actual = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                actual.update(block)
        if actual.hexdigest() != digest:
            raise ValueError("SHA256 mismatch: " + name)
        checked += 1
    return {"target": targets[0][0], "checked_files": checked, "required_files": len(required)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir")
    args = parser.parse_args()
    print(json.dumps(verify(args.model_dir)))


if __name__ == "__main__":
    main()
