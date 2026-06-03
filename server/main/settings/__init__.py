import os
import sys
import re
import socket

pwd = os.path.dirname(__file__)
sys.path.append(os.path.join(pwd, ".."))
machine_name = re.sub("[^A-z0-9._]", "_", socket.gethostname())

settings_files = [
    "00-base",
    "local",
]

for s_file in settings_files:
    f = os.path.join(pwd, f"{s_file}.py")
    try:
        with open(f) as file:
            exec(compile(file.read(), f, "exec"), globals(), locals())
    except IOError:
        pass

from unrest.settings import get_secret_key
SECRET_KEY = get_secret_key(BASE_DIR)
