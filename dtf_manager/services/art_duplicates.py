"""Finds art files with identical content under different names (only to warn; never merges).

Files are grouped by size first and only same-size files are hashed, so most folders need almost
no hashing. Hashes are cached by (path, size, modification time)."""
import hashlib
from collections import defaultdict


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_identical(files, cached: dict, save=None, should_stop=lambda: False) -> list[list[str]]:
    """files: iterable of ArtFile. cached: path -> (size, mtime, sha). save(rows) stores new
    hashes. Returns groups (lists of absolute paths) of files with the same content."""
    by_size = defaultdict(list)
    for file in files:
        by_size[file.size].append(file)
    by_hash = defaultdict(list)
    fresh = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        for file in same_size:
            if should_stop():
                return []
            known = cached.get(file.absolute_path)
            if known and known[0] == file.size and known[1] == file.mtime:
                sha = known[2]
            else:
                try:
                    sha = file_sha256(file.absolute_path)
                except OSError:
                    continue
                fresh.append((file.absolute_path, file.size, file.mtime, sha))
            by_hash[sha].append(file.absolute_path)
    if fresh and save is not None:
        save(fresh)
    return sorted(sorted(group) for group in by_hash.values() if len(group) > 1)
