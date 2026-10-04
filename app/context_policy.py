"""Small, explicit context delivery policy shared by Run, Pack and Queue."""
from pathlib import Path
import io
from fastapi import HTTPException

FULL_LIMIT = 8192
MODES = {'REFERENCE', 'RETRIEVE', 'FULL'}


def policy(kind, item, requested=None):
    mime = (getattr(item, 'content_type', '') or '').split(';')[0].lower()
    name = getattr(item, 'name', getattr(item, 'title', ''))
    suffix = Path(name).suffix.lower()
    size = len(item.content.encode()) if kind == 'RESOURCE' else item.size
    small_text = size <= FULL_LIMIT and (kind == 'RESOURCE' or mime in {'text/plain', 'text/markdown'} or suffix in {'.txt', '.md'})
    document = mime == 'application/pdf' or suffix in {'.pdf', '.docx', '.odt', '.rtf'}
    workspace_source = kind == 'SOURCE' and getattr(item, 'location_type', '') in {'WORKSPACE','EXTERNAL'}
    default = ('FULL' if kind == 'RESOURCE' and small_text else
               'RETRIEVE' if document or (size > FULL_LIMIT and not workspace_source) else
               'REFERENCE')
    mode = requested or default
    if mode not in MODES:
        raise HTTPException(422, 'Invalid Context policy')
    if mode == 'FULL' and not small_text:
        raise HTTPException(422, 'FULL is available only for small text or markdown')
    return mode


def prompt_cost(item):
    # Content bytes are charged only when they are actually inserted into the prompt.
    return len(item.get('data', '').encode()) * 3 // 4 if item.get('include_mode') == 'FULL' else 0


def short_summary(name, mime, data):
    suffix=Path(name).suffix.lower()
    if mime=='application/pdf' or suffix=='.pdf':
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data),strict=False)
            title=(reader.metadata.title or '').strip() if reader.metadata else ''
            if title:return title[:200]
            first=(reader.pages[0].extract_text() or '').strip() if reader.pages else ''
            if first:return ' '.join(first.split())[:200]
        except Exception:pass
    if mime.startswith('text/') or suffix in {'.md','.txt','.json','.csv','.py','.js'}:
        preview=' '.join(data[:800].decode('utf-8',errors='replace').split())
        if preview:return preview[:200]
    return f'{name} · {mime or "file"} · {len(data)} bytes'
