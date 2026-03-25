#!/usr/bin/env python3
"""Fix the truncated dashboard HTML in main.py"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Read gen_dashboard.py to get the HTML
with open('gen_dashboard.py', 'r', encoding='utf-8') as f:
    gen_content = f.read()

# Extract the HTML between triple quotes
start_marker = "DASHBOARD_HTML = '''"
end_marker = "'''"

start_idx = gen_content.index(start_marker) + len(start_marker)
end_idx = gen_content.index(end_marker, start_idx)
html = gen_content[start_idx:end_idx]

# Read main.py
with open('main.py', 'r', encoding='utf-8') as f:
    main_content = f.read()

# Find the truncated section
trunc_marker = '长内容已截断'
trunc_idx = main_content.index(trunc_marker)

# Find the line start before the truncation marker (the "极" character)
# Go back to find the start of the line with the truncation marker
line_start = main_content.rfind('\n', 0, trunc_idx) + 1

# Find where the next route definition starts
next_route = main_content.index('@app.delete', trunc_idx)

# Replace: from the truncated line to just before @app.delete
# with the complete HTML + closing triple quote + return
replacement = html.rstrip() + '\n    """\n    return html_content\n\n'

new_content = main_content[:line_start] + replacement + main_content[next_route:]

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Done! Replaced truncated HTML with complete version')
print(f'HTML lines: {len(html.splitlines())}')
