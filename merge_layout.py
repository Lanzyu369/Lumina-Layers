with open('ui/layout.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('ui/layout_final.py', 'r', encoding='utf-8') as f:
    final_part = f.read()

# Lines 1-439 are index 0 to 438
with open('ui/layout.py', 'w', encoding='utf-8') as f:
    f.writelines(lines[:439])
    f.write('\n')
    f.write(final_part)
