"""Experimental disk-backed manifest selector; not wired into production restore."""
import csv
import sqlite3
import tempfile
from pathlib import Path


class ManifestIndex:
    def __init__(self, package_root, directory=None):
        self._temp = tempfile.TemporaryDirectory(prefix='lifeboat-index-', dir=directory)
        self.connection = None
        self.rows_read = 0
        try:
            self.connection = sqlite3.connect(str(Path(self._temp.name) / 'index.sqlite'))
            self.connection.execute('PRAGMA cache_size=-8192')
            # Disposable derived data, never a restore journal or a source database.
            self.connection.execute('PRAGMA journal_mode=OFF')
            self.connection.execute('PRAGMA synchronous=OFF')
            self.connection.execute('CREATE TABLE entries(path TEXT PRIMARY KEY, size TEXT, hash TEXT) WITHOUT ROWID')
            with (Path(package_root) / 'manifest' / 'sha256.csv').open(encoding='utf-8', newline='') as handle:
                batch = []
                for row in csv.DictReader(handle):
                    batch.append((str(row['relative_path']), row['size'], str(row['sha256'])))
                    self.rows_read += 1
                    if len(batch) == 4096:
                        self.connection.executemany('INSERT OR REPLACE INTO entries VALUES(?,?,?)', batch)
                        batch.clear()
                self.connection.executemany('INSERT OR REPLACE INTO entries VALUES(?,?,?)', batch)
            self.connection.commit()
        except BaseException:
            self.close()
            raise

    def select(self, project):
        prefix = str(project['backupRelativePath']).rstrip('/') + '/'
        # '/' immediately precedes '0' in SQLite BINARY collation.
        upper = prefix[:-1] + '0'
        return {path[len(prefix):]: (int(size), digest.lower())
                for path, size, digest in self.connection.execute(
                    'SELECT path,size,hash FROM entries WHERE path >= ? AND path < ?',
                    (prefix, upper))}

    @property
    def disk_bytes(self):
        return (Path(self._temp.name) / 'index.sqlite').stat().st_size

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self._temp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
