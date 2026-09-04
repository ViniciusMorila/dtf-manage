import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, UnidentifiedImageError

from dtf_manager.models.automatic_link import ArtCandidate
from dtf_manager.utils.art_matching import matching_tokens, normalize_for_matching


SUPPORTED_ART_EXTENSIONS = frozenset((".png", ".jpg", ".jpeg", ".webp"))
IGNORED_FILE_NAMES = frozenset(("thumbs.db", "desktop.ini"))


class ArtDirectoryError(OSError):
    pass


def _has_hidden_attribute(path: Path) -> bool:
    hidden_flag = getattr(os, "FILE_ATTRIBUTE_HIDDEN", 0)
    try:
        return bool(hidden_flag and path.stat().st_file_attributes & hidden_flag)
    except (OSError, AttributeError):
        return False


def scan_art_directory(folder: Path) -> tuple[ArtCandidate, ...]:
    if not folder.is_dir():
        raise ArtDirectoryError("Não foi possível acessar a pasta de artes.")
    candidates: list[ArtCandidate] = []
    try:
        def raise_walk_error(error: OSError) -> None:
            raise error

        for root, directory_names, file_names in os.walk(
            folder, followlinks=False, onerror=raise_walk_error
        ):
            directory_names[:] = [
                name for name in directory_names
                if not name.startswith(".") and not (Path(root) / name).is_symlink()
            ]
            for file_name in file_names:
                path = Path(root) / file_name
                if (
                    file_name.casefold() in IGNORED_FILE_NAMES
                    or file_name.startswith(".")
                    or file_name.startswith("~")
                    or _has_hidden_attribute(path)
                    or path.is_symlink()
                    or path.suffix.casefold() not in SUPPORTED_ART_EXTENSIONS
                ):
                    continue
                try:
                    with Image.open(path) as image:
                        image.verify()
                except (OSError, UnidentifiedImageError, ValueError):
                    continue
                resolved = path.resolve()
                relative = path.relative_to(folder)
                normalized = normalize_for_matching(path.name, remove_extension=True)
                candidates.append(ArtCandidate(
                    id=str(uuid5(NAMESPACE_URL, str(resolved))),
                    file_name=path.name,
                    base_name=path.stem,
                    normalized_name=normalized,
                    extension=path.suffix.casefold(),
                    file_reference=str(resolved),
                    relative_path=str(relative),
                    tokens=matching_tokens(path.name, remove_extension=True),
                ))
    except (OSError, PermissionError) as error:
        raise ArtDirectoryError("Não foi possível acessar a pasta de artes.") from error
    return tuple(candidates)
