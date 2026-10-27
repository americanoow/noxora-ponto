"""Baixa os modelos do motor facial OpenCV para BIOMETRIC_MODEL_DIR e confere o SHA-256."""

import hashlib
import tempfile
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.biometrics import engines_opencv


class Command(BaseCommand):
    help = "Baixa e confere (SHA-256) os modelos YuNet e SFace do OpenCV Zoo."

    def handle(self, *args, **options):
        target = engines_opencv.model_dir()
        target.mkdir(parents=True, exist_ok=True)
        for filename, expected, url in engines_opencv.MODELS.values():
            path = target / filename
            if path.is_file() and engines_opencv._sha256(path) == expected:
                self.stdout.write(f"ok (já existe): {filename}")
                continue
            with tempfile.NamedTemporaryFile(dir=target, delete=False) as tmp:
                with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (URL fixa https)
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: response.read(1 << 20), b""):
                        digest.update(chunk)
                        tmp.write(chunk)
            if digest.hexdigest() != expected:
                Path(tmp.name).unlink(missing_ok=True)
                raise CommandError(f"SHA-256 não confere para {filename}; arquivo descartado.")
            Path(tmp.name).replace(path)
            self.stdout.write(f"baixado e conferido: {filename}")
