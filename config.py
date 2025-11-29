# config.py
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    DEBUG: bool = True
    DATA_PATH = BASE_DIR / "data" / "materials.json"

def get_config() -> Config:
    return Config()
