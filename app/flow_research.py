"""Bounded Workspace discovery and independently verified research citations."""
import html
import http.client
import ipaddress
import io
import json
import os
import re
import socket
import ssl
import zipfile
from dataclasses import dataclass
from datetime import timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from pydantic import Field
from pypdf.errors import PdfReadError

from .config import DATA_DIR, RUNTIME_DIR, STATE_DIR
from .db import Resource, Source, now
from .storage import register_reference, workspace_root
from .workspace import safe_read, sha, ident, mime_type
from .workflow import StrictBody

EXTENSIONS = {'.md','.markdown','.txt','.json','.yaml','.yml','.csv','.py','.js','.ts','.tsx','.jsx','.html','.css'}
SKIP_DIRS = {'node_modules','.git','.venv','venv','dist','build','artifacts','runs','__pycache__'}


class ResearchFinding(StrictBody):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    path: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    excerpt: str = Field(min_length=12, max_length=1000)
    summary: str = Field(min_length=1, max_length=3000)
    rationale: str = Field(min_length=1, max_length=2000)
    relevance: float = Field(default=0.5, ge=0, le=1)
    location: str | None = Field(default=None, max_length=200)


class ResearchCandidate(StrictBody):
    title: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2048)
    path: str | None = Field(default=None, max_length=500)
    snippet: str = Field(default='', max_length=500)
    relevance: float = Field(default=0.5, ge=0, le=1)


class ResearchDocument(StrictBody):
    findings: list[ResearchFinding] = Field(default_factory=list, max_length=8)
    candidates: list[ResearchCandidate] = Field(default_factory=list, max_length=20)
    reason: str = Field(default='', max_length=2000)


@dataclass(frozen=True)
class ResearchBudget:
    files: int
    total_bytes: int
    per_file_bytes: int
    context_chars: int


def research_budget(level=0):
    """Settings remain conservative; one explicit extension adds one small step."""
    level=max(0,min(int(level),3))
    files=max(1,min(int(os.getenv('CC_RESEARCH_DOWNLOAD_FILES','3')),10))+2*level
    per_file=max(1,min(int(os.getenv('CC_RESEARCH_FILE_MB','5')),15))*1024*1024
    total=max(1,min(int(os.getenv('CC_RESEARCH_TOTAL_MB','15')),60))*1024*1024+10*1024*1024*level
    context=max(2000,min(int(os.getenv('CC_RESEARCH_CONTEXT_CHARS','12000')),30000))+8000*level
    return ResearchBudget(files,total,per_file,context)


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in {'script','style','nav','footer'}:self.hidden+=1
    def handle_endtag(self, tag):
        if tag in {'script','style','nav','footer'}:self.hidden=max(0,self.hidden-1)
    def handle_data(self, data):
        if not self.hidden:self.parts.append(data)


def clean_text(value, *, html_body=False):
    if html_body:
        parser=TextOnly();parser.feed(value);value=' '.join(parser.parts)
    return re.sub(r'\s+',' ',html.unescape(value)).strip()


def excerpt_in(text, excerpt):
    return clean_text(excerpt).casefold() in clean_text(text).casefold()


def search_workspace(work, goal):
    root=workspace_root(work).resolve()
    terms=[term.casefold() for term in re.findall(r'[\w가-힣]{2,}',goal) if len(term)>2][:15]
    found=[];seen=0
    for directory, dirs, files in os.walk(root,followlinks=False):
        folder=Path(directory)
        dirs[:]=[name for name in dirs if name not in SKIP_DIRS and not name.startswith('.') and
                 not (folder/name).is_symlink() and not any((folder/name).resolve().is_relative_to(p) for p in (STATE_DIR,RUNTIME_DIR,DATA_DIR) if not root.is_relative_to(p))]
        for name in files:
            seen+=1
            if seen>1000:break
            if name.startswith('.') or Path(name).suffix.lower() not in EXTENSIONS:continue
            relative=(folder/name).relative_to(root).as_posix()
            try:
                data=safe_read(root,relative,2*1024*1024)
                text=data.decode('utf-8')
            except (ValueError,OSError,UnicodeDecodeError):continue
            flat=clean_text(text)
            haystack=(relative+' '+flat[:30000]).casefold()
            hits=[term for term in terms if term in haystack]
            score=len(hits)*10+(5 if name.lower() in {'readme.md','requirements.md','agents.md'} else 0)
            if not score and terms:continue
            position=min((haystack.find(term) for term in hits),default=0)
            snippet=flat[max(0,position-150):position+950]
            found.append({'path':relative,'sha256':sha(data),'snippet':snippet,'score':score})
        if seen>1000:break
    found.sort(key=lambda x:(-x['score'],x['path']))
    return [{k:v for k,v in item.items() if k!='score'} for item in found[:12]]


def verified_url(value):
    parsed=urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None,80,443}:
        raise ValueError('Only public HTTP(S) source URLs are accepted')
    host=parsed.hostname.lower().rstrip('.')
    if host=='localhost' or host.endswith(('.local','.internal')) or len(host)>253:
        raise ValueError('Private source URL')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Source URL does not resolve to public addresses')
    return urlunsplit((parsed.scheme,parsed.netloc.lower(),parsed.path or '/',parsed.query,'')),addresses[0][4][0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,ip,port=443):
        super().__init__(host,port=port,timeout=8,context=ssl.create_default_context());self.ip=ip
    def connect(self):
        socket_address=socket.create_connection((self.ip,self.port),self.timeout)
        self.sock=self._context.wrap_socket(socket_address,server_hostname=self.host)


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self,host,ip,port=80):
        super().__init__(host,port=port,timeout=8);self.ip=ip
    def connect(self):
        self.sock=socket.create_connection((self.ip,self.port),self.timeout)


class DownloadBudgetExceeded(ValueError):
    def __init__(self, downloaded_bytes=0):
        super().__init__('Source exceeds the research download budget')
        self.downloaded_bytes=downloaded_bytes


def extract_document(body,kind):
    if kind=='application/pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(body),strict=False)
        parts=[];remaining=500000
        for page in reader.pages[:100]:
            if remaining<=0:break
            text=(page.extract_text() or '')[:min(remaining,20000)]
            parts.append(text);remaining-=len(text)
        return clean_text(' '.join(parts))
    if kind in {'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names=[name for name in archive.namelist() if name.startswith(('word/document.xml','xl/sharedStrings.xml','xl/worksheets/sheet'))]
            content=[];remaining=500000
            for name in names[:30]:
                if remaining<=0:break
                if archive.getinfo(name).file_size>2*1024*1024:continue
                text=clean_text(archive.read(name).decode('utf-8',errors='replace'),html_body=True)[:remaining]
                content.append(text);remaining-=len(text)
        return clean_text(' '.join(content))
    return clean_text(body.decode('utf-8',errors='replace'),html_body=kind=='text/html')[:500000]


def fetch_public_document(url, *, max_bytes=5*1024*1024, allow_file=True, redirects=0):
    """Fetch only a selected public source; keep the body in memory and return text."""
    canonical,ip=verified_url(url)
    parsed=urlsplit(canonical)
    if Path(parsed.path).suffix.lower() in {'.zip','.tar','.gz','.7z','.rar','.exe','.msi','.pkg','.dmg','.apk','.deb','.rpm','.whl','.jar','.bin'}:
        raise ValueError('Archive, executable, or installer downloads are not research sources')
    path=parsed.path+('?' + parsed.query if parsed.query else '')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    connection=(PinnedHTTPS if parsed.scheme=='https' else PinnedHTTP)(parsed.hostname,ip,port)
    try:
        connection.request('GET',path,headers={'Host':parsed.hostname,'Accept':'text/html,text/plain,application/json,application/pdf,*/*','User-Agent':'ControlCenterResearch/1.0'})
        response=connection.getresponse()
        if response.status in {301,302,303,307,308}:
            if redirects>=3:raise ValueError('Source redirects too many times')
            location=response.getheader('location')
            if not location:raise ValueError('Source redirect has no location')
            target=urljoin(canonical,location)
            verified_url(target)
            return fetch_public_document(target,max_bytes=max_bytes,allow_file=allow_file,redirects=redirects+1)
        if response.status!=200:raise ValueError('Source URL is not reachable')
        kind=response.getheader('content-type','').split(';')[0].strip().lower()
        text_kinds={'text/html','text/plain','application/json','text/markdown','text/csv','application/xml','text/xml'}
        file_kinds={'application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/octet-stream'}
        if kind not in text_kinds|file_kinds:
            raise ValueError('Source is not a verifiable text document')
        if kind=='application/octet-stream':
            suffix=Path(parsed.path).suffix.lower()
            kind={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                  '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}.get(suffix,'')
            if not kind:raise ValueError('Unsupported document type')
        is_file=kind in file_kinds
        if is_file and not allow_file:raise DownloadBudgetExceeded()
        limit=min(max_bytes,5*1024*1024) if is_file else 512*1024
        length=response.getheader('content-length')
        if length and int(length)>limit:raise DownloadBudgetExceeded()
        body=response.read(limit+1)
        if len(body)>limit:raise DownloadBudgetExceeded(len(body) if is_file else 0)
    finally:
        connection.close()
    return canonical,extract_document(body,kind),{'kind':kind,'bytes':len(body),'downloaded':is_file}


def fetch_web_text(url):
    canonical,text,_=fetch_public_document(url)
    return canonical,text


def ingest_findings(db, work, candidates, document, *, allow_web=False, budget=None, prior=None):
    """Only exact quoted text in a current local file or fetched page becomes material."""
    root=workspace_root(work).resolve()
    known={item['path']:item for item in candidates}
    accepted=list(prior or []);rejected=[];used=set();downloaded=0;download_bytes=0;pending=[];limits_hit=set()
    budget=budget or research_budget()
    context_used=sum(len(str(old.get(key,''))) for old in accepted for key in ('title','excerpt','summary','rationale'))
    for old in accepted:
        used.add((old['kind'],old.get('url') or old.get('path')))
    for item in sorted(document.findings,key=lambda x:-x.relevance):
        try:
            compressed_size=sum(len(getattr(item,key)) for key in ('title','excerpt','summary','rationale'))
            if context_used+compressed_size>budget.context_chars:
                pending.append({'title':item.title,'url':item.url,'path':item.path,'snippet':item.excerpt[:500],'relevance':item.relevance})
                limits_hit.add('context')
                continue
            if item.kind=='WORKSPACE':
                if not item.path or item.path not in known:raise ValueError('Workspace path was not among searched candidates')
                candidate=known[item.path]
                data=safe_read(root,item.path,2*1024*1024)
                if sha(data)!=candidate['sha256']:raise ValueError('Workspace file changed after search')
                content=data.decode('utf-8')
                if not excerpt_in(content,item.excerpt):raise ValueError('Quoted text is not in the Workspace file')
                marker=('WORKSPACE',item.path)
                if marker in used:continue
                used.add(marker)
                if root.is_relative_to(DATA_DIR):
                    material=next((s for s in db.query(Source).filter_by(work_id=work.id,relative_path=item.path,location_type='LEGACY') if s.sha256==sha(data)),None)
                    if material is None:
                        material=Source(id=ident('src'),work_id=work.id,name=Path(item.path).name,relative_path=item.path,
                                        location_type='LEGACY',content_type=mime_type(item.path),size=len(data),sha256=sha(data),is_context=True)
                        db.add(material)
                else:
                    material=register_reference(db,work,root,item.path,'WORKSPACE')
                db.flush()
                material_type='SOURCE'
            elif item.kind=='WEB':
                if not allow_web:raise ValueError('Web search was not enabled for this research Run')
                if not item.url:raise ValueError('Missing source URL')
                url,_=verified_url(item.url)
                if ('WEB',url) in used:continue
                file_hint=Path(urlsplit(url).path).suffix.lower() in {'.pdf','.docx','.xlsx'}
                if file_hint and (downloaded>=budget.files or download_bytes>=budget.total_bytes):
                    pending.append({'title':item.title,'url':item.url,'snippet':item.excerpt[:500],'relevance':item.relevance})
                    limits_hit.add('download')
                    continue
                try:
                    url,content,metadata=fetch_public_document(item.url,max_bytes=min(budget.per_file_bytes,budget.total_bytes-download_bytes),
                                                               allow_file=downloaded<budget.files)
                except DownloadBudgetExceeded as exc:
                    if exc.downloaded_bytes:downloaded+=1;download_bytes+=exc.downloaded_bytes
                    pending.append({'title':item.title,'url':item.url,'snippet':item.excerpt[:500],'relevance':item.relevance})
                    limits_hit.add('download')
                    continue
                if metadata['downloaded']:
                    if downloaded>=budget.files or download_bytes+metadata['bytes']>budget.total_bytes:
                        pending.append({'title':item.title,'url':url,'snippet':item.excerpt[:500],'relevance':item.relevance})
                        limits_hit.add('download')
                        continue
                    downloaded+=1;download_bytes+=metadata['bytes']
                if not excerpt_in(content,item.excerpt):raise ValueError('Quoted text is not on the source page')
                marker=('WEB',url)
                if marker in used:continue
                used.add(marker)
                def same_url(resource):
                    try:return json.loads(resource.content).get('url')==url
                    except (TypeError,ValueError):return False
                material=next((r for r in db.query(Resource).filter_by(work_id=work.id,scope='WORK',kind='KNOWLEDGE')
                               if same_url(r)),None)
                payload={'url':url,'title':item.title,'retrieved_at':now().isoformat(),
                         'excerpt':item.excerpt[:600],'summary':item.summary[:700],
                         'rationale':item.rationale[:400],'location':item.location,'media_type':metadata['kind']}
                if material is None:
                    text=json.dumps(payload,ensure_ascii=False)
                    material=Resource(id=ident('res'),work_id=work.id,category_id=work.category_id,kind='KNOWLEDGE',
                                      scope='WORK',title=item.title,content=text,sha256=sha(text.encode()),default_include=False)
                    db.add(material);db.flush()
                else:
                    text=json.dumps(payload,ensure_ascii=False)
                    if material.content!=text:
                        material.content=text;material.title=item.title;material.sha256=sha(text.encode())
                        material.version+=1;material.updated_at=now()
                material_type='RESOURCE'
            else:raise ValueError('Unsupported finding kind')
            accepted.append({'kind':item.kind,'title':item.title,'path':item.path if material_type=='SOURCE' else None,
                             'url':url if material_type=='RESOURCE' else None,'retrieved_at':now().isoformat(),
                             'excerpt':item.excerpt[:600],'summary':item.summary[:700],'rationale':item.rationale[:400],
                             'location':item.location,'relevance':item.relevance,
                             'media_type':metadata['kind'] if item.kind=='WEB' else mime_type(item.path),
                             'material_type':material_type,'material_id':material.id})
            context_used+=compressed_size
        except (ValueError,OSError,http.client.HTTPException,UnicodeDecodeError,ImportError,zipfile.BadZipFile,PdfReadError) as exc:
            rejected.append({'title':item.title,'reason':str(exc)[:350]})
    seen={(part.get('url'),part.get('path')) for part in accepted}
    for candidate in document.candidates:
        if (candidate.url,candidate.path) not in seen:
            pending.append(candidate.model_dump(exclude_none=True))
    unique={}
    for part in pending:
        unique[part.get('url') or part.get('path') or part['title']]=part
    report={'downloaded_files':downloaded,'downloaded_bytes':download_bytes,'pending_count':len(unique),
            'reason':(' · '.join(sorted(limits_hit))+' 한도에 도달했습니다.') if limits_hit else ('아직 확인하지 않은 후보가 있습니다.' if unique else None),
            'limits_hit':sorted(limits_hit),
            'limits':{'files':budget.files,'total_bytes':budget.total_bytes,'per_file_bytes':budget.per_file_bytes,'context_chars':budget.context_chars}}
    return accepted,rejected,list(unique.values()),report
