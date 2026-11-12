import os, json
from datetime import datetime, timezone
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from contextlib import contextmanager

database_url=os.getenv('DATABASE_URL','sqlite:///tradeomatic.db')
if database_url.startswith(('postgres://','postgresql://')):database_url='postgresql+psycopg://'+database_url.split('://',1)[1]
engine=create_engine(database_url,pool_pre_ping=True)
meta=MetaData()
records=Table('records',meta,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('payload',Text,nullable=False))
def init():
    if engine.dialect.name=='postgresql':
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(88412093)'));meta.create_all(c)
    else:meta.create_all(engine)
def put(kind,id,payload):
    ins=pg_insert if engine.dialect.name=='postgresql' else sqlite_insert
    stmt=ins(records).values(kind=kind,id=id,payload=json.dumps(payload))
    with engine.begin() as c: c.execute(stmt.on_conflict_do_update(index_elements=['kind','id'],set_={'payload':stmt.excluded.payload}))
def get(kind,id,default=None):
    with engine.connect() as c: row=c.execute(select(records.c.payload).where(records.c.kind==kind,records.c.id==id)).first()
    return json.loads(row[0]) if row else default
def listing(kind):
    with engine.connect() as c: rows=c.execute(select(records.c.payload).where(records.c.kind==kind)).all()
    return [json.loads(r[0]) for r in rows]
def audit(action,details=''):
    now=datetime.now(timezone.utc).isoformat()
    put('audit',now,{'time':now,'action':action,'details':details})

def put_once(kind,id,payload):
    """Immutable event insert, unique across processes and scanner retries."""
    ins=pg_insert if engine.dialect.name=='postgresql' else sqlite_insert
    with engine.begin() as c:
        result=c.execute(ins(records).values(kind=kind,id=id,payload=json.dumps(payload,allow_nan=False)).on_conflict_do_nothing(index_elements=['kind','id']))
        return result.rowcount==1

class Transaction:
    def __init__(self,connection): self.c=connection
    def get(self,kind,id,default=None):
        row=self.c.execute(select(records.c.payload).where(records.c.kind==kind,records.c.id==id)).first()
        return json.loads(row[0]) if row else default
    def listing(self,kind):
        return [json.loads(r[0]) for r in self.c.execute(select(records.c.payload).where(records.c.kind==kind)).all()]
    def put(self,kind,id,payload):
        ins=pg_insert if engine.dialect.name=='postgresql' else sqlite_insert
        stmt=ins(records).values(kind=kind,id=id,payload=json.dumps(payload,allow_nan=False))
        self.c.execute(stmt.on_conflict_do_update(index_elements=['kind','id'],set_={'payload':stmt.excluded.payload}))

@contextmanager
def atomic():
    """Serialize paper allocations/config changes across API and scanner."""
    from sqlalchemy import text
    with engine.connect() as c:
        if engine.dialect.name=='sqlite': c.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            c.begin(); c.execute(text('SELECT pg_advisory_xact_lock(88412092)'))
        try:
            yield Transaction(c); c.commit()
        except BaseException:
            c.rollback(); raise
