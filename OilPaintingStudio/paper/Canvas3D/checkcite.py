import re, glob, os

KEYS = set()
FILES = sorted(glob.glob('sec/*.tex')) + ['main.tex']
for f in FILES:
    t = open(f, encoding='utf-8').read()
    for m in re.finditer(r'\\cite[a-zA-Z]*\{([^}]*)\}', t):
        for k in m.group(1).split(','):
            KEYS.add(k.strip())

bib = set()
bt = open('references.bib', encoding='utf-8').read()
for m in re.finditer(r'@\w+\{([^,]+),', bt):
    bib.add(m.group(1).strip())

print('=== CITED (%d) ===' % len(KEYS))
print('=== BIB (%d) ===' % len(bib))
print('\n-- cited but MISSING in bib --')
for k in sorted(KEYS - bib):
    print('  ', k)
print('\n-- in bib but never cited --')
for k in sorted(bib - KEYS):
    print('  ', k)
