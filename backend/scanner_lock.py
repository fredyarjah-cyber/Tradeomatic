"""Session-level scanner ownership, kept out of idle transactions."""
from sqlalchemy import text
from . import db

LOCK_ID = 88412091


class OwnershipLost(RuntimeError):
    pass


class ScannerLock:
    def __init__(self):
        self.connection = None
        self.backend_pid = None
        self.local = db.engine.dialect.name != 'postgresql'

    def acquire(self):
        if self.local:
            return True
        connection = db.engine.connect()
        try:
            acquired = connection.execute(text('SELECT pg_try_advisory_lock(:lock)'), {'lock':LOCK_ID}).scalar()
            if acquired:
                self.backend_pid = connection.execute(text('SELECT pg_backend_pid()')).scalar()
                # Session locks survive commit; avoid an idle-in-transaction session.
                connection.commit()
                self.connection = connection
                return True
            connection.commit()
        except Exception:
            connection.invalidate()
            connection.close()
            raise
        connection.close()
        return False

    def check(self):
        if self.local:
            return
        try:
            if self.connection is None or self.connection.invalidated:
                raise OwnershipLost()
            pid = self.connection.execute(text('SELECT pg_backend_pid()')).scalar()
            self.connection.commit()
            if pid != self.backend_pid:
                raise OwnershipLost()
        except Exception:
            raise OwnershipLost('Scanner database ownership lost; stopping this cycle') from None

    def close(self):
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            if not connection.invalidated:
                connection.execute(text('SELECT pg_advisory_unlock(:lock)'), {'lock':LOCK_ID})
                connection.commit()
        except Exception:
            # Do not return a possibly locked session to the connection pool.
            connection.invalidate()
        finally:
            connection.close()
