"""Focused offline acceptance: large PDF registration, Run references and lazy excerpts."""
import io
import json
import subprocess
import sys
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_phase1 import Phase1Tests
from app.context_reader import retrieve
from app.db import Artifact,ContextPackItem,Session
from app.workspace import ident


def pdf(index):
    writer=PdfWriter()
    font=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),
        NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')}))
    for page_number in range(25):
        page=writer.add_blank_page(612,792)
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        marker=' PROJECT_DELTA_KEY 731 ' if index==2 and page_number==16 else ''
        body=(f'Document {index} section {page_number}. '+'ordinary background information '*150+marker).replace('(', '').replace(')', '')
        content=DecodedStreamObject()
        content.set_data(f'BT /F1 10 Tf 72 720 Td ({body}) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(content)
    output=io.BytesIO();writer.write(output)
    return output.getvalue()


def run():
    Phase1Tests.setUpClass()
    case=Phase1Tests('test_full_flow_and_resume')
    try:
        case.setUp()
        sources=[]
        for index in range(3):
            body=pdf(index)
            response=case.client.post(f"/api/works/{case.work['id']}/sources",files={'file':(f'large-{index}.pdf',body,'application/pdf')})
            assert response.status_code<300,response.text
            sources.append(response.json())
        detail=case.wait(case.start('Find PROJECT_DELTA_KEY',context_ids=[s['id'] for s in sources])['id'])
        assert detail['run']['status']=='COMPLETED',detail['run']['error']
        manifest=json.loads(detail['run']['manifest'])
        assert len(manifest['files'])==3
        assert all(f['include_mode']=='RETRIEVE' and f['delivery']=='reference' for f in manifest['files'])
        assert len(manifest['prompt'])<10000
        assert manifest['context_budget']['estimate']<sum(s['size'] for s in sources)//4
        assert not list((Path(case.work['path'])/'runs'/detail['run']['id']/'inputs').rglob('*.pdf'))
        context=detail['run']['context_config']
        assert not any('data' in item for item in context.get('snapshots',[]))
        reference=Path(case.work['path'])/'runs'/detail['run']['id']/'context-inputs.json'
        excerpts=retrieve(json.loads(reference.read_text()),sources[2]['id'],'PROJECT_DELTA_KEY')
        assert excerpts and 'PROJECT_DELTA_KEY 731' in excerpts[0]['text'] and excerpts[0]['location']=='page 17'
        command=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'app'/'context_reader.py'),
            '--manifest',str(reference),'--id',sources[2]['id'],'--query','PROJECT_DELTA_KEY'],
            capture_output=True,text=True,check=True)
        assert 'PROJECT_DELTA_KEY 731' in command.stdout
        # The same bytes selected through Material, Artifact and Pack occupy one
        # reference in the final Run manifest, without a Pack base64 copy.
        artifact_path='artifacts/reference-duplicate.pdf'
        (Path(case.work['path'])/artifact_path).write_bytes(pdf(2))
        with Session() as db:
            db.add(Artifact(id=ident('art'),work_id=case.work['id'],run_id=detail['run']['id'],
                name='reference-duplicate.pdf',candidate_path=artifact_path,relative_path=artifact_path,
                location_type='LEGACY',content_type='application/pdf',size=sources[2]['size'],
                sha256=sources[2]['sha256'],partial=False,availability='AVAILABLE'))
            db.commit()
            artifact_id=db.query(Artifact).filter_by(relative_path=artifact_path).one().id
        pack_response=case.client.post(f"/api/works/{case.work['id']}/context-packs",
            json={'name':'Reference bundle','source_ids':[sources[2]['id']]})
        assert pack_response.status_code==201,pack_response.text
        pack=pack_response.json()
        assert 'data' not in pack['items'][0]['snapshot']
        with Session() as db:
            assert 'data' not in json.loads(db.query(ContextPackItem).filter_by(context_pack_id=pack['id']).one().snapshot)
        confirmed=case.client.post('/api/context-packs/'+pack['id']+'/confirm',json={'confirmed':True})
        assert confirmed.status_code==200,confirmed.text
        duplicate=case.wait(case.start('Use selected references',context_ids=[sources[2]['id']],
            artifact_ids=[artifact_id],pack_id=pack['id'])['id'])
        assert duplicate['run']['status']=='COMPLETED',duplicate['run']['error']
        duplicate_manifest=json.loads(duplicate['run']['manifest'])
        assert len(duplicate_manifest['files'])==1
        assert len(duplicate_manifest['context_aliases'])==2
        assert duplicate_manifest['context_budget']['estimate']<sources[2]['size']//4
        small=case.client.post(f"/api/works/{case.work['id']}/sources",
            files={'file':('brief.md',b'SHORT_INLINE_FOLLOWUP','text/markdown')}).json()
        inline=case.wait(case.start('Use brief note',context_ids=[small['id']],
            context_policies={'SOURCE:'+small['id']:'FULL'})['id'])
        assert inline['run']['status']=='COMPLETED',inline['run']['error']
        assert 'SHORT_INLINE_FOLLOWUP' in json.loads(inline['run']['manifest'])['prompt']
        print(f"PASS: 3 PDFs ({sum(s['size'] for s in sources):,} bytes) reference-only; "
              f"initial Context estimate {manifest['context_budget']['estimate']:,} tokens; page 17 retrieved")
    finally:
        Phase1Tests.tearDownClass()


if __name__=='__main__':run()
