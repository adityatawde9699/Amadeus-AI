"""Wrap each op.create_table() block in if _should_create() guard."""
from pathlib import Path
import re

FILE = Path("alembic/versions/ed7c7f360b09_add_core_tables_users_tasks_notes_.py")
content = FILE.read_text(encoding="utf-8")

# Table names in order
tables = [
    "users", "tasks", "notes", "reminders", "calendar_events",
    "interaction_logs", "messages", "graph_entities", "graph_relationships",
]

for table in tables:
    # Find the comment line and wrap in if block
    marker = f'    # ── {table} '
    if marker not in content:
        # Some tables use shorter markers
        marker = f'    # ── {table}'
    
    if marker not in content:
        print(f"WARNING: could not find marker for {table}")
        continue
    
    # Add "if _should_create" before the marker
    content = content.replace(
        marker,
        f'    if _should_create("{table}"):\n    {marker}',
        1,
    )

# Now indent every line between "if _should_create" and the next "if _should_create" (or downgrade)
# Easier approach: just indent all op.create_table and op.create_index lines that follow each guard
lines = content.split("\n")
new_lines = []
inside_guard = False
for i, line in enumerate(lines):
    if '    if _should_create(' in line:
        inside_guard = True
        new_lines.append(line)
        continue
    
    # Check if this line starts a new guard or the downgrade function
    if inside_guard and (line.startswith('    if _should_create(') or line.startswith('def downgrade')):
        inside_guard = line.startswith('    if _should_create(')
        new_lines.append(line)
        continue
    
    if inside_guard and line.strip() and not line.startswith('    #') and not line.strip().startswith('#'):
        # Indent op calls by 4 more spaces
        if line.startswith('    op.') or line.startswith('        ') or line.startswith('    sa.'):
            new_lines.append('    ' + line)
        elif line.startswith('    # ──'):
            new_lines.append('    ' + line)
        else:
            new_lines.append(line)
    else:
        new_lines.append(line)

content = "\n".join(new_lines)
FILE.write_text(content, encoding="utf-8")
print("Done - wrapped all tables in _should_create guards.")
