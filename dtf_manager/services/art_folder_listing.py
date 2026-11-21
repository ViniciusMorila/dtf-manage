"""Light listing of the art folder for the art-stock tab.

Same file rules as scan_art_directory (recursive; png/jpg/jpeg/webp; no hidden files, links,
Thumbs.db) but WITHOUT decoding each image: with hundreds of files that would make the tab slow.
A corrupted image simply has no thumbnail. scan_art_directory itself stays untouched for the
automatic linking."""
import os
from pathlib import Path

from dtf_manager.models.art_stock import ArtFile
from dtf_manager.services.art_directory_scanner import (
    IGNORED_FILE_NAMES, SUPPORTED_ART_EXTENSIONS, ArtDirectoryError, _has_hidden_attribute,
)


def list_art_files(folder: Path) -> tuple[ArtFile, ...]:
    if not folder.is_dir():
        raise ArtDirectoryError("Não foi possível acessar a pasta de artes.")
    files: list[ArtFile] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    try:
        for root, directories, names in os.walk(folder, followlinks=False,
                                                onerror=raise_walk_error):
            directories[:] = [d for d in directories
                              if not d.startswith(".") and not (Path(root) / d).is_symlink()]
            for name in names:
                path = Path(root) / name
                if (name.casefold() in IGNORED_FILE_NAMES or name.startswith((".", "~"))
                        or path.suffix.casefold() not in SUPPORTED_ART_EXTENSIONS
                        or path.is_symlink() or _has_hidden_attribute(path)):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append(ArtFile(path.relative_to(folder).as_posix(), str(path.resolve()),
                                     name, stat.st_size, stat.st_mtime))
    except OSError as error:
        raise ArtDirectoryError("Não foi possível acessar a pasta de artes.") from error
    return tuple(sorted(files, key=lambda f: f.relative_path.casefold()))
