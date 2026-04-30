import sqlite3
import sys
c = sqlite3.connect('data/amadeus.db')
print("Tables in data/amadeus.db:")
print([row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()])
