from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.services.trade_alerts import notify_trade_alert


def test_trade_alert_no_config():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        assert notify_trade_alert(session, "test") is False
    finally:
        session.close()
