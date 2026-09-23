import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from pydantic import ValidationError
from app import models, schemas
from app.services.carousel_formats import (
    normalize_formats, enabled_formats, get_project_carousel_formats,
    filter_platform_accounts, missing_enabled_ctas,
)
from app.services.project_cta_settings import set_project_ctas


def test_legacy_defaults_preserve_supported_publications():
    assert enabled_formats(None, "telegram") == ("carousel", "story")
    assert enabled_formats(None, "tiktok") == ("carousel",)
    assert enabled_formats(None, "youtube") == ()
    assert enabled_formats({"tiktok": {"story": True}}, "tiktok") == ("carousel",)


def test_disabled_formats_do_not_require_cta():
    formats = {"telegram": {"story": False}, "vk": {"carousel": False, "story": False}}
    accounts = filter_platform_accounts({"telegram": [1], "vk": [2]}, formats)
    assert accounts == {"telegram": [1]}
    assert missing_enabled_ctas(accounts, formats, {"telegram": "Подпишись"}, {}) == []
    assert missing_enabled_ctas(accounts, formats, {}, {}) == ["telegram — карусель"]


def test_settings_persist_and_are_scoped_to_user_project():
    engine = create_engine("sqlite://")
    models.PostMyPostProjectSetting.__table__.create(engine)
    with Session(engine) as db:
        set_project_ctas(db, 1, 7, carousel_formats={"telegram": {"story": False}})
        db.commit()
        db.expire_all()
        assert get_project_carousel_formats(db, 1, 7)["telegram"] == {"carousel": True, "story": False}
        assert get_project_carousel_formats(db, 2, 7)["telegram"]["story"] is True
        assert get_project_carousel_formats(db, 1, 8)["telegram"]["story"] is True
        set_project_ctas(db, 1, 7, carousel_ctas={"telegram": "Подпишись"})
        set_project_ctas(db, 1, 7, carousel_formats={"telegram": {"carousel": False}})
        db.commit()
        db.expire_all()
        assert enabled_formats(get_project_carousel_formats(db, 1, 7), "telegram") == ()
        set_project_ctas(db, 1, 7, carousel_formats={"telegram": {"story": True}})
        db.commit()
        assert enabled_formats(get_project_carousel_formats(db, 1, 7), "telegram") == ("story",)


@pytest.mark.parametrize("value", [
    {"telegram": {"story": "false"}}, {"telegram": {"story": None}},
    {"telegram": {"unknown": True}}, {"unknown": {"story": True}},
])
def test_invalid_preferences_rejected(value):
    with pytest.raises(ValidationError):
        schemas.PostMyPostProjectUpdate(project_id=7, carousel_formats=value)
