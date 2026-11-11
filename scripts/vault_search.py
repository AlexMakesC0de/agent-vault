"""Ranked full-text search over the central profile and registered project vaults.

The Markdown files stay the source of truth. This module keeps a machine-local SQLite FTS5
index derived from them: every search re-reads only files whose size or modification time
changed, drops files that disappeared, and rebuilds from scratch when the index is missing,
damaged or from an older layout. Deleting the index file is always safe.
"""
import os
from pathlib import Path
import re
import sqlite3

INDEX_NAME = 'search.sqlite'
LAYOUT = 1  # Bump when the schema or tokenizer changes; older indexes are rebuilt.
KNOWLEDGE_FOLDERS = ('docs/knowledge', 'notes')
WORD = re.compile(r'\w+', re.UNICODE)
HEADING = re.compile(r'^#\s+(.+?)\s*#*\s*$', re.MULTILINE)


def stores(profile_root, projects):
    """Searchable stores as (id, name, root). The central profile is 'profile'."""
    result = []
    if profile_root:
        result.append(('profile', 'Central profile', Path(profile_root)))
    result += [(p['id'], p['name'], Path(p['root'])) for p in projects]
    return result


def store_files(root):
    """Root-level Markdown plus the knowledge folders; hidden folders are skipped.

    An in-repo vault's root is the whole project checkout, so only these locations are read,
    never source trees or dependencies.
    """
    if not root.is_dir():
        return []
    found = [path for path in root.glob('*.md') if path.is_file()]
    for folder in KNOWLEDGE_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for directory, subfolders, names in os.walk(base):
            subfolders[:] = sorted(d for d in subfolders if not d.startswith('.'))
            found += [Path(directory) / name for name in names if name.lower().endswith('.md')]
    return sorted(set(found))


def title_of(path, text):
    match = HEADING.search(text)
    return match.group(1).strip() if match else path.stem.replace('-', ' ')


def connect(index):
    """Open the index, rebuilding it when it is damaged or from another layout."""
    for attempt in range(2):
        try:
            db = sqlite3.connect(str(index))
            if db.execute('PRAGMA user_version').fetchone()[0] != LAYOUT:
                db.executescript('DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS notes;')
                db.executescript(
                    'CREATE TABLE files(path TEXT PRIMARY KEY, store TEXT NOT NULL, mtime_ns INTEGER, size INTEGER);'
                    "CREATE VIRTUAL TABLE notes USING fts5(path UNINDEXED, store UNINDEXED, title, body,"
                    " tokenize='porter unicode61 remove_diacritics 2');"
                    f'PRAGMA user_version={LAYOUT};')
            db.execute('SELECT count(*) FROM notes').fetchone()
            return db
        except sqlite3.DatabaseError:
            try:
                db.close()
            except Exception:
                pass
            if attempt:
                raise
            index.unlink(missing_ok=True)


def refresh(db, all_stores):
    """Bring the index in line with the files on disk; return counts for the caller."""
    seen, changed = set(), 0
    known = {row[0]: (row[1], row[2], row[3]) for row in db.execute('SELECT path, store, mtime_ns, size FROM files')}
    with db:
        for key, _, root in all_stores:
            for path in store_files(root):
                name = str(path)
                if name in seen:
                    continue  # A nested store claims a file once, under the first store listed.
                seen.add(name)
                info = path.stat()
                if known.get(name) == (key, info.st_mtime_ns, info.st_size):
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                db.execute('DELETE FROM notes WHERE path = ?', (name,))
                db.execute('INSERT INTO notes(path, store, title, body) VALUES (?, ?, ?, ?)',
                           (name, key, title_of(path, text), text))
                db.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)', (name, key, info.st_mtime_ns, info.st_size))
                changed += 1
        gone = [name for name in known if name not in seen]
        for name in gone:
            db.execute('DELETE FROM notes WHERE path = ?', (name,))
            db.execute('DELETE FROM files WHERE path = ?', (name,))
    return {'notes': len(seen), 'reindexed': changed, 'removed': len(gone)}


def match_expression(query, joiner):
    words = WORD.findall(query)
    return f' {joiner} '.join('"' + word + '"' for word in words)


def search(directory, profile_root, projects, query, store=None, limit=8, rebuild=False):
    """Search every store, or one store chosen by id, name or alias ('profile' for the central one)."""
    all_stores = stores(profile_root, projects)
    if store:
        wanted = store.casefold()
        names = {key: {key.casefold(), name.casefold()} for key, name, _ in all_stores}
        for project in projects:
            names[project['id']].update(alias.casefold() for alias in project.get('aliases', []))
        chosen = [key for key, folded in names.items() if wanted in folded]
        if not chosen:
            raise ValueError(f'Unknown store {store!r}; use "profile" or a registered project id or alias')
    if not WORD.search(query or ''):
        raise ValueError('Give at least one search word')
    index = Path(directory) / INDEX_NAME
    if rebuild:
        index.unlink(missing_ok=True)
    db = connect(index)
    try:
        counts = refresh(db, all_stores)
        where, parameters = 'notes MATCH ?', []
        if store:
            where += ' AND store = ?'
            parameters.append(chosen[0])
        rows, mode = [], None
        for mode, joiner in [('all words', 'AND'), ('any word', 'OR')]:
            rows = db.execute(
                'SELECT store, path, title, snippet(notes, 3, \'[\', \']\', \' ... \', 16), bm25(notes, 0, 0, 4.0, 1.0)'
                f' FROM notes WHERE {where} ORDER BY 5 LIMIT ?',
                [match_expression(query, joiner), *parameters, max(1, limit)]).fetchall()
            if rows:
                break
        return {'query': query, 'matched': mode if rows else 'nothing', 'index': str(index), **counts,
                'results': [{'store': s, 'path': p, 'title': t, 'snippet': ' '.join(snippet.split()), 'score': round(-score, 3)}
                            for s, p, t, snippet, score in rows]}
    finally:
        db.close()
