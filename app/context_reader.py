"""Read a small relevant excerpt from an explicitly selected Run input.

The Runtime calls this only when it needs source text. Selection alone never
adds a whole document to the model prompt.
"""
import argparse
import hashlib
import io
import json
import mimetypes
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.workspace import safe_read


def _text(data, name):
    suffix=Path(name).suffix.lower()
    if suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data))
        return ((f'page {index+1}', page.extract_text() or '') for index,page in enumerate(reader.pages))
    if suffix in {'.docx','.odt'}:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            member='word/document.xml' if suffix=='.docx' else 'content.xml'
            info=archive.getinfo(member)
            if info.file_size>20*1024*1024:raise ValueError('Document XML exceeds retrieval limit')
            document=ElementTree.fromstring(archive.read(info))
            if suffix=='.docx':
                content=' '.join(node.text or '' for node in document.iter() if node.tag.endswith('}t'))
            else:content=' '.join(document.itertext())
            return iter([('document',content)])
    if suffix=='.rtf':
        content=re.sub(r'\\[a-zA-Z]+-?\d* ?', '', data.decode('latin-1',errors='replace'))
        return iter([('document',content)])
    mime=mimetypes.guess_type(name)[0] or ''
    if not (mime.startswith('text/') or suffix in {'.md','.json','.ipynb','.yaml','.yml','.toml'}):
        raise ValueError('No built-in text extractor for this file type; use a read-only viewer for the selected path')
    return iter([('text',data.decode('utf-8',errors='replace'))])


def retrieve(manifest, source_id, query, page=None):
    item=next((f for f in manifest.get('files',[]) if source_id in {f.get('source_id'),f.get('artifact_id')}),None)
    resource=next((f for f in manifest.get('references',[]) if f.get('source_type')=='RESOURCE' and f.get('source_id')==source_id),None)
    if item:
        data=safe_read(Path(item['snapshot_root']),item['snapshot_path'],256*1024*1024)
        name=item.get('name') or item['snapshot_path']
        digest=item['sha256']
    elif resource:
        from app.db import Resource,Session
        with Session() as db:
            row=db.get(Resource,source_id)
            if not row:raise ValueError('Selected Resource no longer exists')
            data=row.content.encode()
        name=resource['name'];digest=resource['sha256']
    else:raise ValueError('ID is not selected for this Run')
    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Selected input changed since registration')
    sections=_text(data,name)
    terms=[term.lower() for term in re.findall(r'[^\s,;:?!]{2,}',query)[:12]]
    chunks=[]
    for location,content in sections:
        if page is not None and location!=f'page {page}':continue
        for start in range(0,len(content),1400):
            excerpt=content[start:start+1400]
            score=sum(excerpt.lower().count(term) for term in terms)
            if len(chunks)<3 or score>chunks[-1][0]:
                chunks.append((score,location,start,excerpt))
                chunks.sort(key=lambda chunk:(-chunk[0],chunk[1],chunk[2]))
                del chunks[3:]
    return [{'location':location,'offset':start,'score':score,'text':excerpt} for score,location,start,excerpt in chunks]


def main():
    parser=argparse.ArgumentParser(description='Retrieve up to three short excerpts from a selected Run input')
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--id',required=True)
    parser.add_argument('--query',required=True)
    parser.add_argument('--page',type=int)
    args=parser.parse_args()
    print(json.dumps(retrieve(json.loads(Path(args.manifest).read_text()),args.id,args.query,args.page),ensure_ascii=False))


if __name__=='__main__':main()
