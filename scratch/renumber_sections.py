"""Renumber duplicate and downstream sections in README.md."""
from pathlib import Path

FILE = Path("README.md")
content = FILE.read_text(encoding="utf-8")

replacements = [
    ("## 10. Project Structure", "## 11. Project Structure"),
    ("## 11. Testing",           "## 12. Testing"),
    ("## 12. Deployment Instructions", "## 13. Deployment Instructions"),
    ("## 13. Known Limitations", "## 14. Known Limitations"),
    ("## 14. Future Improvements", "## 15. Future Improvements"),
    ("## 15. License",           "## 16. License"),
    ("## 16. Author",            "## 17. Author"),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new, 1)
        print(f"  Replaced: {old!r} -> {new!r}")
    else:
        print(f"  NOT FOUND: {old!r}")

FILE.write_text(content, encoding="utf-8")
print("Done.")
