from backend.models.rag import Material
from backend.services.material_service import material_stats


def test_statistics_are_scoped_to_material_source(session_factory):
    with session_factory() as db:
        for index, (source, status) in enumerate([
            ("builtin", "ready"), ("builtin", "ready"),
            ("user", "ready"), ("user", "pending"),
        ]):
            db.add(Material(title=f"scope-{index}", source_type=source,
                            status=status, stored_path=f"scope-{index}.md"))
        db.flush()
        assert material_stats(db, source_type="user") == {
            "ready": 1, "pending": 1, "indexing": 0, "failed": 0, "total": 2,
        }
        assert material_stats(db, source_type="builtin")["total"] == 2
        assert material_stats(db)["total"] == 4
        db.rollback()
