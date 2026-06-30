"""schema 语料构建单测。"""

from app.core.rag.schema_corpus import build_ddl_text, build_schema_docs

SCHEMA = {
    "db_id": "concert_singer",
    "table_names_original": ["singer", "concert"],
    "table_names": ["歌手", "演唱会"],
    "column_names_original": [
        [-1, "*"],
        [0, "Singer_ID"],
        [0, "Name"],
        [1, "Concert_ID"],
        [1, "Singer_ID"],
    ],
    "column_names": [[-1, "*"], [0, "id"], [0, "名字"], [1, "音乐会id"], [1, "歌手id"]],
    "column_types": ["text", "number", "text", "number", "number"],
    "primary_keys": [1, 3],
    "foreign_keys": [[4, 1]],
}


def test_build_schema_docs_structure():
    docs = build_schema_docs(SCHEMA)
    types = {d["doc_type"] for d in docs}
    assert "db" in types and "table" in types
    table_docs = [d for d in docs if d["doc_type"] == "table"]
    assert {d["table_name"] for d in table_docs} == {"singer", "concert"}


def test_ddl_contains_tables_and_fk():
    ddl = build_ddl_text(SCHEMA)
    assert "CREATE TABLE singer" in ddl
    assert "CREATE TABLE concert" in ddl
    assert "FOREIGN KEY" in ddl
    assert "PRIMARY KEY" in ddl


def test_enriched_schema_docs_add_table_description():
    docs = build_schema_docs(
        SCHEMA,
        enriched=True,
        descriptions={"singer": "歌手表，用于记录歌手姓名、编号等基础信息。"},
    )
    singer = next(d for d in docs if d["table_name"] == "singer")
    assert "表说明" in singer["content"]
    assert "用于记录歌手姓名" in singer["content"]
    assert "Singer_ID（id）" in singer["content"]
    assert singer["metadata"]["enriched"] is True


def test_enriched_without_description_does_not_add_fake_semantics():
    docs = build_schema_docs(SCHEMA, enriched=True)
    singer = next(d for d in docs if d["table_name"] == "singer")
    assert "表说明" not in singer["content"]
