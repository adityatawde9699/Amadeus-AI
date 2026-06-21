import os
import psutil
import importlib
import time

process = psutil.Process(os.getpid())

def get_mem():
    return process.memory_info().rss / 1024 / 1024

baseline = get_mem()
print(f"Baseline: {baseline:.2f} MB")

modules_to_test = [
    ("requests", "requests"),
    ("aiohttp", "aiohttp"),
    ("beautifulsoup4", "bs4"),
    ("pandas", "pandas"),
    ("sqlalchemy", "sqlalchemy"),
    ("Amadeus base tools", "src.infra.tools.base"),
    ("Amadeus info_tools", "src.infra.tools.info_tools"),
    ("Amadeus system_tools", "src.infra.tools.system_tools"),
    ("torch", "torch"),
    ("sentence_transformers", "sentence_transformers"),
]

for name, mod in modules_to_test:
    try:
        start_mem = get_mem()
        importlib.import_module(mod)
        end_mem = get_mem()
        diff = end_mem - start_mem
        print(f"Import {name}: +{diff:.2f} MB (Total: {end_mem:.2f} MB)")
    except Exception as e:
        print(f"Import {name}: Failed ({e})")

