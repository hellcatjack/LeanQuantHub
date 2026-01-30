from sqlalchemy import select
from sqlalchemy.dialects import mysql, sqlite

from app.models import LeanExecutorPool
from app.services import ib_client_id_pool


def _compile_sql(dialect):
    clauses = ib_client_id_pool._build_worker_order_by("mysql" if dialect.name == "mysql" else None)
    stmt = select(LeanExecutorPool).order_by(*clauses)
    return str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_worker_order_by_mysql_avoids_nulls_first():
    sql = _compile_sql(mysql.dialect())
    assert "NULLS FIRST" not in sql.upper()


def test_worker_order_by_sqlite_keeps_nulls_first():
    sql = _compile_sql(sqlite.dialect())
    assert "NULLS FIRST" in sql.upper()
