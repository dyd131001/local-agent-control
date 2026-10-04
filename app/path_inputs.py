"""Validated, relative file selections from a Work's linked project."""
import fnmatch
import os
import stat
from pathlib import Path

READ_SCOPE_ENFORCED = False  # Codex Runtime has no per-path read allowlist.


def validate_ignore_pattern(value):
    if (not isinstance(value, str) or not value or len(value) > 500 or
            value.startswith('/') or '\\' in value or '\x00' in value or
            '..' in value.split('/') or any(ord(char) < 32 for char in value)):
        raise ValueError('Ignore 규칙은 상대 경로 패턴이어야 합니다.')
    return value


def _ignore_rules(root=None, directory='.', custom=()):
    from .config import ROOT
    from .workspace import safe_read
    rules = []
    sources = [(ROOT / '.gitignore', '')]
    if root is not None:
        parents = ['']
        if directory != '.':
            parts = directory.split('/')
            parents += ['/'.join(parts[:index]) for index in range(1, len(parts) + 1)]
        for parent in parents:
            relative = f'{parent}/.gitignore' if parent else '.gitignore'
            try:
                content = safe_read(root, relative, 1024 * 1024).decode('utf-8', 'replace')
            except (FileNotFoundError, ValueError, OSError):
                continue
            sources.append((content, parent))
    for value in custom:
        validate_ignore_pattern(value)
        sources.append((value, ''))
    for source, base in sources:
        if isinstance(source, Path):
            try:
                lines = source.read_text(encoding='utf-8').splitlines()
            except FileNotFoundError:
                lines = []
        else:
            lines = source.splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            negated = line.startswith('!')
            pattern = line[1:] if negated else line
            directory_only = pattern.endswith('/')
            pattern = pattern.strip('/')
            if pattern:
                rules.append((pattern, directory_only, negated, base))
    return rules


def _ignored(relative: str, is_directory: bool, rules, root=None) -> bool:
    from .config import DATA_DIR, STATE_DIR, RUNTIME_DIR
    if any(part in {'.git', '.dbstore', '.control-center-state'} for part in relative.split('/')):
        return True
    if root is not None:
        target = root / relative
        if any(target == managed or target.is_relative_to(managed) for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR)):
            return True
    ignored = False
    for pattern, directory_only, negated, base in rules:
        if base and not relative.startswith(base + '/'):
            continue
        scoped = relative[len(base)+1:] if base else relative
        parts = scoped.split('/')
        if '/' in pattern:
            matched = fnmatch.fnmatchcase(scoped, pattern) or (directory_only and scoped.startswith(pattern + '/'))
        else:
            candidates = parts if not directory_only or is_directory else parts[:-1]
            matched = any(fnmatch.fnmatchcase(part, pattern) for part in candidates)
        if matched:
            ignored = not negated
    return ignored


def _directory_names(fd: int) -> list[str]:
    """List names from an open directory; macOS Python lacks listdir(fd)."""
    if os.listdir in os.supports_fd:
        return os.listdir(fd)
    import ctypes
    class Dirent(ctypes.Structure):
        _fields_ = [('ino', ctypes.c_uint32), ('reclen', ctypes.c_uint16),
                    ('type', ctypes.c_uint8), ('namlen', ctypes.c_uint8),
                    ('name', ctypes.c_char * 1024)]
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fdopendir.argtypes = [ctypes.c_int]
    libc.fdopendir.restype = ctypes.c_void_p
    libc.readdir.argtypes = [ctypes.c_void_p]
    libc.readdir.restype = ctypes.POINTER(Dirent)
    libc.closedir.argtypes = [ctypes.c_void_p]
    owned_fd = os.dup(fd)
    stream = libc.fdopendir(owned_fd)
    if not stream:
        error = ctypes.get_errno()
        os.close(owned_fd)
        raise OSError(error, os.strerror(error))
    names = []
    try:
        while True:
            ctypes.set_errno(0)
            entry = libc.readdir(stream)
            if not entry:
                error = ctypes.get_errno()
                if error:
                    raise OSError(error, os.strerror(error))
                break
            name = os.fsdecode(entry.contents.name[:entry.contents.namlen])
            if name not in ('.', '..'):
                names.append(name)
    finally:
        libc.closedir(stream)
    return names


def _open_child(fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if os.open in os.supports_dir_fd:
        return os.open(name, flags, dir_fd=fd)
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.openat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    libc.openat.restype = ctypes.c_int
    child = libc.openat(fd, os.fsencode(name), flags)
    if child < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), name)
    return child


def _child_mode(fd: int, name: str) -> int:
    if os.stat in os.supports_dir_fd:
        return os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fstatat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int]
    libc.fstatat.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if libc.fstatat(fd, os.fsencode(name), buffer, 0x20) < 0:  # AT_SYMLINK_NOFOLLOW
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), name)
    return ctypes.c_uint16.from_buffer_copy(buffer.raw, 8).value  # Darwin stat.st_mode


def validate_selection(value: str) -> str:
    """A picker selection is an exact project-relative file/folder, or . for root."""
    if value == '.':
        return value
    if (not isinstance(value, str) or not value or len(value) > 500 or
            value.startswith('/') or '\\' in value or '\x00' in value or
            any(ord(ch) < 32 for ch in value)):
        raise ValueError('Project selection must be relative to the linked project')
    if any(part in {'', '.', '..'} or ':' in part for part in value.split('/')):
        raise ValueError('Project selection contains an invalid path component')
    return value


def _project_root(root: Path) -> Path:
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError('Linked project root is unavailable or is a symbolic link')
    return root


def validate_external_root(value: str) -> Path:
    if (not isinstance(value, str) or len(value) > 1000 or not value.startswith('/') or
            '\x00' in value or any(ord(ch) < 32 for ch in value) or '..' in Path(value).parts):
        raise ValueError('External folder must be an absolute directory without parent traversal')
    root = _project_root(Path(value))
    from .config import DATA_DIR, STATE_DIR, RUNTIME_DIR
    if any(root == managed or root.is_relative_to(managed) or managed.is_relative_to(root)
           for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR)):
        raise ValueError('Internal application storage cannot be an external folder')
    return root


def _directory_fd(root: Path, relative: str):
    _project_root(root)
    validate_selection(relative)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if relative != '.':
            for part in relative.split('/'):
                child = _open_child(fd, part)
                os.close(fd)
                fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def selection_kind(root: Path, relative: str, custom=()) -> str:
    validate_selection(relative)
    if relative == '.':
        _project_root(root)
        return 'DIRECTORY'
    parent, _, name = relative.rpartition('/')
    try:
        fd = _directory_fd(root, parent or '.')
        try:
            mode = _child_mode(fd, name)
        finally:
            os.close(fd)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise ValueError(f'Project selection is unavailable: {relative}') from exc
    if _ignored(relative, stat.S_ISDIR(mode), _ignore_rules(root, parent or '.', custom), root):
        raise ValueError(f'Project selection is ignored: {relative}')
    if stat.S_ISLNK(mode):
        raise ValueError(f'Symbolic links cannot be selected: {relative}')
    if stat.S_ISDIR(mode):
        return 'DIRECTORY'
    if stat.S_ISREG(mode):
        return 'FILE'
    raise ValueError(f'Only regular files and folders can be selected: {relative}')


def browse_directory(root: Path, relative: str = '.', offset: int = 0, limit: int = 100, custom=()):
    """List one directory page. Never descend through a symbolic link."""
    parent = relative.rpartition('/')[0] if relative != '.' else '.'
    rules = _ignore_rules(root, relative, custom)
    if relative != '.' and _ignored(relative, True, _ignore_rules(root, parent or '.', custom), root):
        raise ValueError(f'Project folder is ignored: {relative}')
    try:
        fd = _directory_fd(root, relative)
    except OSError as exc:
        raise ValueError(f'Project folder is unavailable: {relative}') from exc
    try:
        entries = []
        for name in _directory_names(fd):
            mode = _child_mode(fd, name)
            kind = 'SYMLINK' if stat.S_ISLNK(mode) else 'DIRECTORY' if stat.S_ISDIR(mode) else 'FILE' if stat.S_ISREG(mode) else 'OTHER'
            path = name if relative == '.' else f'{relative}/{name}'
            if _ignored(path, kind == 'DIRECTORY', rules, root):
                continue
            entries.append({'name': name, 'path': path, 'kind': kind})
    except OSError as exc:
        raise ValueError(f'Project folder cannot be read: {relative}') from exc
    finally:
        os.close(fd)
    entries.sort(key=lambda item: (item['kind'] != 'DIRECTORY', item['name'].lower(), item['name']))
    parts = [] if relative == '.' else relative.split('/')
    breadcrumbs = [{'name': '프로젝트', 'path': '.'}]
    for index, part in enumerate(parts):
        breadcrumbs.append({'name': part, 'path': '/'.join(parts[:index + 1])})
    return {'directory': relative, 'breadcrumbs': breadcrumbs, 'total': len(entries),
            'entries': entries[offset:offset + limit], 'offset': offset,
            'has_more': offset + limit < len(entries)}


def _covers(selection: str, path: str, kind: str) -> bool:
    return selection == '.' or path == selection or (kind == 'DIRECTORY' and path.startswith(selection + '/'))


def _project_entries(root: Path, custom=()):
    """Enumerate names through directory handles, refusing links at every step."""
    fd = _directory_fd(root, '.')
    def visit(directory_fd, prefix):
        rules = _ignore_rules(root, prefix or '.', custom)
        names = sorted(_directory_names(directory_fd))
        for name in names:
            relative = f'{prefix}/{name}' if prefix else name
            mode = _child_mode(directory_fd, name)
            if _ignored(relative, stat.S_ISDIR(mode), rules, root):
                yield relative, 'IGNORED'
                continue
            if stat.S_ISLNK(mode):
                yield relative, 'SYMLINK'
            elif stat.S_ISDIR(mode):
                child_fd = _open_child(directory_fd, name)
                try:
                    yield from visit(child_fd, relative)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(mode):
                yield relative, 'FILE'
    try:
        yield from visit(fd, '')
    finally:
        os.close(fd)


def scope_preview(root: Path, read_paths: list[str], search_paths: list[str], legacy_patterns=(), custom=()):
    """Count selected files and excluded files without reading file content."""
    if read_paths and legacy_patterns:
        raise ValueError('Choose folder selections or legacy patterns, not both')
    read_kinds = {path: selection_kind(root, path, custom) for path in read_paths}
    search_kinds = {path: selection_kind(root, path, custom) for path in search_paths}
    if search_paths and not (read_paths or legacy_patterns):
        raise ValueError('Choose a read scope before a search scope')
    if read_paths:
        for path in search_paths:
            if not any(_covers(read, path, kind) for read, kind in read_kinds.items()):
                raise ValueError(f'Search scope must stay within read scope: {path}')
    for pattern in legacy_patterns:
        validate_pattern(pattern)
    read_files, search_files, excluded_files, symlinks, ignored_locations = [], [], [], [], []
    try:
        for relative, kind in _project_entries(root, custom):
            if kind == 'IGNORED':
                ignored_locations.append(relative)
                continue
            if kind == 'SYMLINK':
                symlinks.append(relative)
                continue
            readable = (any(_covers(choice, relative, kind) for choice, kind in read_kinds.items())
                        if read_paths else any(matches(pattern, relative) for pattern in legacy_patterns))
            if not readable:
                if legacy_patterns and any(_covers(choice, relative, kind) for choice, kind in search_kinds.items()):
                    raise ValueError(f'Search scope must stay within read scope: {relative}')
                excluded_files.append(relative)
                continue
            read_files.append(relative)
            if not search_paths or any(_covers(choice, relative, kind) for choice, kind in search_kinds.items()):
                search_files.append(relative)
    except OSError as exc:
        raise ValueError(f'Project tree changed or cannot be read: {exc.strerror or exc}') from exc
    return {'read_files': read_files, 'search_files': search_files,
            'excluded_files': excluded_files, 'ignored_locations': ignored_locations, 'symlinks': symlinks}


def validate_pattern(pattern: str) -> str:
    if (not isinstance(pattern, str) or not pattern or len(pattern) > 500 or
            pattern.startswith('/') or '\\' in pattern or '\x00' in pattern or
            any(ord(ch) < 32 for ch in pattern)):
        raise ValueError('Project input must be a relative path pattern')
    parts = pattern.split('/')
    if any(part in {'', '.', '..'} or ':' in part for part in parts):
        raise ValueError('Project input contains an invalid path component')
    return pattern


def matches(pattern: str, relative: str) -> bool:
    """** matches zero or more directories; * and ? match within one component."""
    parts, path = validate_pattern(pattern).split('/'), relative.split('/')
    def visit(i, j):
        if i == len(parts):
            return j == len(path)
        if parts[i] == '**':
            return visit(i + 1, j) or (j < len(path) and visit(i, j + 1))
        return j < len(path) and fnmatch.fnmatchcase(path[j], parts[i]) and visit(i + 1, j + 1)
    return visit(0, 0)


def selected_files(root: Path, patterns: list[str]):
    """Enumerate regular files without following links or leaving the linked root."""
    _project_root(root)
    for pattern in patterns:
        validate_pattern(pattern)
    found = []
    try:
        for relative, kind in _project_entries(root):
            if kind == 'FILE' and any(matches(pattern, relative) for pattern in patterns):
                found.append(relative)
    except OSError as exc:
        raise ValueError(f'Project tree changed or cannot be read: {exc.strerror or exc}') from exc
    return found
