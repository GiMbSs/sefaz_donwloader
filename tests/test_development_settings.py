import json
import os
import subprocess
import sys
from pathlib import Path


def test_dev_mode_uses_the_local_sqlite_database():
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["DEV_MODE"] = "True"
    environment["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
    environment.pop("DJANGO_USE_SQLITE", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from django.conf import settings; "
                "print(json.dumps({'dev_mode': settings.DEV_MODE, "
                "'engine': settings.DATABASES['default']['ENGINE'], "
                "'name': str(settings.DATABASES['default']['NAME'])}))"
            ),
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "dev_mode": True,
        "engine": "django.db.backends.sqlite3",
        "name": str(project_root / "dev.sqlite3"),
    }
