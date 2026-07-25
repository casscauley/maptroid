import os
import sys
import re
import socket

pwd = os.path.dirname(__file__)
sys.path.append(os.path.join(pwd, ".."))
machine_name = re.sub("[^A-z0-9._]", "_", socket.gethostname())

# Load secrets from a gitignored .env at the REPO root — three levels up from
# here (main/settings -> main -> server -> repo). Real environment variables win
# over the file, via setdefault. This mirrors the loader txrx, tempo and
# stream-recorder use, so secrets live in one kind of place across the box
# instead of as literals in local.py.
#
# Note the absolute path: the exec loop below resolves its files relative to the
# CWD, which only works because the service sets WorkingDirectory=<repo>/server.
# Deriving this one from __file__ instead means it keeps working from anywhere.
_ENV_PATH = os.path.abspath(os.path.join(pwd, "..", "..", "..", ".env"))
if os.path.exists(_ENV_PATH):
    for _line in open(_ENV_PATH):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

settings_files = [
    "00-base",
    "local",
    # after local, so it can read the credentials .env put into os.environ
    "spaces",
]

for s_file in settings_files:
    f = "main/settings/{}.py".format(s_file)
    try:
        with open(os.path.abspath(f)) as file:
            exec(compile(file.read(), f, "exec"), globals(), locals())
    except IOError:
        pass

from unrest.settings import get_secret_key
SECRET_KEY = get_secret_key(BASE_DIR)
