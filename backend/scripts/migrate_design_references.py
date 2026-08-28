import logging

from app import models
from app.database import SessionLocal
from app.integrations.cloudinary_storage import CloudinaryStorage


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def migrate() -> int:
    db = SessionLocal()
    storage = CloudinaryStorage(folder="turan/design-references")
    migrated = 0
    try:
        rows = db.query(models.DesignReference).filter(~models.DesignReference.file_path.like("http%://%"))
        for reference in rows.order_by(models.DesignReference.id).all():
            public_url = storage.upload_file(reference.file_path, prefix=f"design_{reference.id}")
            if not public_url:
                logger.error("Skipping reference %s: upload failed (%s)", reference.id, reference.file_path)
                continue
            reference.file_path = public_url
            migrated += 1
            logger.info("Migrated reference %s", reference.id)
        db.commit()
        return migrated
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("Migrated %s design references", migrate())
