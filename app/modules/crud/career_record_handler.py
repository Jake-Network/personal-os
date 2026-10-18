from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.database.model.career import CareerRecord


class CareerRecordHandler:
    def list(self, session: Session) -> list[CareerRecord]:
        return list(session.scalars(select(CareerRecord).order_by(CareerRecord.id.desc())))

    def get(self, session: Session, record_id: int) -> CareerRecord:
        record = session.get(CareerRecord, record_id)
        if record is None:
            raise LookupError("커리어 기록을 찾을 수 없습니다")
        return record

    def has_children(self, session: Session, record_id: int) -> bool:
        return session.scalar(select(CareerRecord.id).where(CareerRecord.parent_id == record_id).limit(1)) is not None


career_record_handler = CareerRecordHandler()
