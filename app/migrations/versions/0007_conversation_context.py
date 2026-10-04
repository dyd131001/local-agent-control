"""Add conversation context; do not backfill, move or delete existing data."""
from alembic import op
import sqlalchemy as sa
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

def upgrade():
    # Frozen schema definitions independent of application ORM.
    definitions = [
      ('conversation_threads', [('id','str',None),('work_id','str','works.id'),('codex_thread_id','nullable_str',None),('title','str',None),('status','str',None),('parent_thread_id','nullable_str','conversation_threads.id'),('relation_type','nullable_str',None),('turn_count','int',None),('usage','text',None),('compact_state','str',None),('created_at','date',None),('archived_at','nullable_date',None)]),
      ('context_resources', [('id','str',None),('work_id','str','works.id'),('category_id','str','categories.id'),('thread_id','nullable_str','conversation_threads.id'),('kind','str',None),('scope','str',None),('title','str',None),('content','text',None),('sha256','str',None),('version','int',None),('default_include','bool',None),('created_at','date',None),('updated_at','date',None)]),
      ('context_packs', [('id','str',None),('family_id','str',None),('work_id','str','works.id'),('thread_id','nullable_str','conversation_threads.id'),('name','str',None),('version','int',None),('status','str',None),('summary','text',None),('estimated_size','int',None),('budget','int',None),('created_at','date',None)]),
      ('context_pack_items', [('id','str',None),('context_pack_id','str','context_packs.id'),('source_type','str',None),('source_id','str',None),('source_hash','str',None),('source_version','nullable_int',None),('include_mode','str',None),('snapshot','text',None)]),
      ('conversation_handoffs', [('id','str',None),('source_thread_id','str','conversation_threads.id'),('target_thread_id','str','conversation_threads.id'),('context_pack_id','nullable_str','context_packs.id'),('run_id','str','runs.id'),('summary','text',None),('created_at','date',None)]),
      ('context_promotions', [('id','str',None),('source_thread_id','nullable_str','conversation_threads.id'),('source_run_id','str','runs.id'),('target_type','str',None),('target_id','str',None),('scope','str',None),('created_at','date',None)]),
      ('ephemeral_queries', [('id','str',None),('parent_thread_id','nullable_str','conversation_threads.id'),('thread_id','str','conversation_threads.id'),('run_id','str','runs.id'),('context_pack_id','nullable_str','context_packs.id'),('status','str',None),('result_action','nullable_str',None),('result','text',None),('created_at','date',None),('disposed_at','nullable_date',None)])]
    types={'str':sa.String,'text':sa.Text,'int':sa.Integer,'bool':sa.Boolean,'date':lambda:sa.DateTime(timezone=True)}
    for table, fields in definitions:
        columns=[]
        for name,kind,fk in fields:
            columns.append(sa.Column(name,types[kind.removeprefix('nullable_')](), *([sa.ForeignKey(fk)] if fk else []),primary_key=name=='id',nullable=kind.startswith('nullable_') if name!='id' else False))
        constraints=[]
        if table=='conversation_threads':
            constraints=[sa.UniqueConstraint('codex_thread_id'),sa.CheckConstraint("status IN ('ACTIVE','IDLE','ARCHIVED','CLOSED','EPHEMERAL','SUPERSEDED')",name='ck_conversation_status')]
        if table=='context_resources':constraints=[sa.CheckConstraint("scope IN ('THREAD','WORK','CATEGORY','GLOBAL')",name='ck_resource_scope')]
        if table=='context_packs':constraints=[sa.UniqueConstraint('family_id','version',name='uq_context_pack_version')]
        if table=='ephemeral_queries':constraints=[sa.UniqueConstraint('run_id')]
        op.create_table(table,*columns,*constraints)
        for name,_,_ in fields:
            if name in ('work_id','family_id','context_pack_id'):op.create_index('ix_'+table+'_'+name,table,[name])
    op.execute('ALTER TABLE runs ADD COLUMN conversation_id VARCHAR REFERENCES conversation_threads(id)')
    op.add_column('runs',sa.Column('context_config',sa.Text(),nullable=True))
    op.add_column('runs',sa.Column('is_query',sa.Boolean(),nullable=False,server_default='0'))
    op.create_index('ix_runs_conversation_id','runs',['conversation_id'])
    op.create_index('ix_runs_is_query','runs',['is_query'])

def downgrade():
    raise RuntimeError('Restore a backup; conversation history must remain intact')
