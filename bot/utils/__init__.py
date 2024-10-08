from .logger import logger
from . import launcher


import os

if not os.path.exists(path="../data/sessions"):
    os.mkdir(path="../data/sessions")
