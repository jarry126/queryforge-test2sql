"""Schema 语料构建.

把数据库 schema（CSpider tables.json 格式）转成：
1. 可检索的 schema_doc 行（库级概览 + 每表一段，含列/类型/主外键）——灌进 pgvector；
2. 紧凑的 DDL 风格 schema 文本——喂给 LLM 生成 SQL。

CSpider tables.json 字段：db_id, table_names(_original), column_names(_original),
column_types, primary_keys, foreign_keys。
"""

from __future__ import annotations


def _split_identifier(name: str) -> str:
    """把下划线/驼峰标识符拆成更适合检索的词。"""
    import re

    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name.replace("_", " "))
    return " ".join(spaced.split()).lower()


def _columns_by_table(schema: dict) -> dict[int, list[tuple[str, str]]]:
    """返回 {table_idx: [(列原名, 类型), ...]}。"""
    out: dict[int, list[tuple[str, str]]] = {}
    cols_orig = schema["column_names_original"]
    types = schema.get("column_types", [])
    for i, (tbl_idx, col_name) in enumerate(cols_orig):
        if tbl_idx < 0:  # "*"
            continue
        col_type = types[i] if i < len(types) else "text"
        out.setdefault(tbl_idx, []).append((col_name, col_type))
    return out


def _column_labels(schema: dict, tbl_idx: int) -> list[tuple[str, str, str]]:
    """返回指定表的 [(列原名, 可读列名, 类型), ...]。"""
    cols_orig = schema["column_names_original"]
    cols_readable = schema.get("column_names", cols_orig)
    types = schema.get("column_types", [])
    out = []
    for i, (t_idx, col_name) in enumerate(cols_orig):
        if t_idx != tbl_idx:
            continue
        readable = cols_readable[i][1] if i < len(cols_readable) else col_name
        col_type = types[i] if i < len(types) else "text"
        out.append((col_name, readable, col_type))
    return out


def _field_phrase(columns: list[tuple[str, str, str]], limit: int = 8) -> str:
    labels = []
    for original, readable, _ctype in columns[:limit]:
        if readable and readable != original:
            labels.append(f"{original}（{readable}）")
        else:
            labels.append(original)
    if len(columns) > limit:
        labels.append("等")
    return "、".join(labels)


def _fallback_field_hint(columns: list[tuple[str, str, str]]) -> str:
    field_text = _field_phrase(columns)
    return f"字段别名：{field_text}。" if field_text else ""


def build_schema_docs(
    schema: dict,
    enriched: bool = False,
    descriptions: dict[str, str] | None = None,
) -> list[dict]:
    """构建该库的 schema_doc 行列表（库级 1 条 + 每表 1 条）。"""
    db_id = schema["db_id"]
    tables = schema["table_names_original"]
    tables_readable = schema.get("table_names", tables)
    cols_by_tbl = _columns_by_table(schema)

    # 主键 / 外键映射（基于全局列索引）
    cols_orig = schema["column_names_original"]
    pk_idx = set(schema.get("primary_keys", []))
    fk_pairs = schema.get("foreign_keys", [])

    docs: list[dict] = []

    # 库级概览
    overview = f"数据库 {db_id}，包含表：" + "、".join(
        f"{o}（{r}）" for o, r in zip(tables, tables_readable, strict=False)
    )
    if enriched:
        overview += "\n库语义：该数据库围绕这些实体及其关系组织，适合根据问题召回相关表、字段和 JOIN 路径。"
    docs.append({"db_id": db_id, "doc_type": "db", "table_name": None, "content": overview, "metadata": {}})

    # 每表一段
    for tbl_idx, tbl_name in enumerate(tables):
        cols = cols_by_tbl.get(tbl_idx, [])
        col_lines = []
        for gi, (t_idx, c_name) in enumerate(cols_orig):
            if t_idx != tbl_idx:
                continue
            ctype = schema.get("column_types", ["text"] * len(cols_orig))[gi]
            mark = " [主键]" if gi in pk_idx else ""
            col_lines.append(f"  - {c_name} ({ctype}){mark}")
        # 外键
        fk_lines = []
        for a, b in fk_pairs:
            if cols_orig[a][0] == tbl_idx:
                ref_tbl = tables[cols_orig[b][0]]
                fk_lines.append(f"  - {cols_orig[a][1]} -> {ref_tbl}.{cols_orig[b][1]}")
        content = f"表 {tbl_name}（{tables_readable[tbl_idx]}），列：\n" + "\n".join(col_lines)
        if fk_lines:
            content += "\n外键：\n" + "\n".join(fk_lines)
        if enriched and descriptions and descriptions.get(tbl_name):
            content += "\n表说明：" + descriptions[tbl_name].strip()
            field_hint = _fallback_field_hint(_column_labels(schema, tbl_idx))
            if field_hint:
                content += "\n" + field_hint
        docs.append(
            {
                "db_id": db_id,
                "doc_type": "table",
                "table_name": tbl_name,
                "content": content,
                "metadata": {"columns": [c for c, _ in cols], "enriched": enriched},
            }
        )
    return docs


def build_ddl_text(schema: dict) -> str:
    """构建紧凑 DDL 文本（CREATE TABLE 风格），用于 LLM 生成 SQL 的完整 schema 提示。"""
    tables = schema["table_names_original"]
    cols_orig = schema["column_names_original"]
    types = schema.get("column_types", ["text"] * len(cols_orig))
    pk_idx = set(schema.get("primary_keys", []))
    fk_pairs = schema.get("foreign_keys", [])

    lines: list[str] = []
    for tbl_idx, tbl_name in enumerate(tables):
        col_defs = []
        for gi, (t_idx, c_name) in enumerate(cols_orig):
            if t_idx != tbl_idx:
                continue
            pk = " PRIMARY KEY" if gi in pk_idx else ""
            col_defs.append(f"  {c_name} {types[gi]}{pk}")
        fk_defs = []
        for a, b in fk_pairs:
            if cols_orig[a][0] == tbl_idx:
                ref_tbl = tables[cols_orig[b][0]]
                fk_defs.append(f"  FOREIGN KEY ({cols_orig[a][1]}) REFERENCES {ref_tbl}({cols_orig[b][1]})")
        body = ",\n".join(col_defs + fk_defs)
        lines.append(f"CREATE TABLE {tbl_name} (\n{body}\n);")
    return "\n\n".join(lines)
