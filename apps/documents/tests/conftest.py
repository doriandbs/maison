import pytest


@pytest.fixture(autouse=True)
def medias(settings, tmp_path):
    """Chaque test dépose ses fichiers dans un dossier temporaire jetable."""
    settings.MEDIA_ROOT = tmp_path
    return tmp_path
