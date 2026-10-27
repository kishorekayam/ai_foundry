"""Approved, read-only metadata queries.

Each query returns exactly ONE row with ONE text column (`metadata`) holding the whole schema as JSON.
The same SQL is configured in the Boomi Database connector (Process A) and used by the Python adapter
when running without Boomi. No query reads table rows.
"""

PG_METADATA_SQL = """
SELECT json_build_object('tables', COALESCE(json_agg(t ORDER BY t.name), '[]'::json))::text AS metadata
FROM (
  SELECT c.relname AS name,
    (SELECT json_agg(json_build_object(
        'name', a.attname,
        'type', format_type(a.atttypid, a.atttypmod),
        'udt', ty.typname,
        'typeKind', ty.typtype,
        'maxLength', CASE WHEN a.atttypmod > 0 AND ty.typname IN ('varchar','bpchar') THEN a.atttypmod - 4 END,
        'nullable', NOT a.attnotnull,
        'default', pg_get_expr(d.adbin, d.adrelid),
        'identity', a.attidentity <> '',
        'identityKind', a.attidentity,
        'generated', a.attgenerated <> '',
        'enumValues', (SELECT json_agg(e.enumlabel ORDER BY e.enumsortorder) FROM pg_enum e WHERE e.enumtypid = a.atttypid)
      ) ORDER BY a.attnum)
     FROM pg_attribute a
     JOIN pg_type ty ON ty.oid = a.atttypid
     LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS columns,
    (SELECT json_agg(json_build_object(
        'type', con.contype,
        'name', con.conname,
        'columns', (SELECT json_agg(att.attname ORDER BY k.ord)
                    FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.attnum),
        'refTable', rc.relname,
        'refSchema', rn.nspname,
        'refColumns', (SELECT json_agg(att.attname ORDER BY k.ord)
                       FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute att ON att.attrelid = con.confrelid AND att.attnum = k.attnum),
        'definition', CASE WHEN con.contype = 'c' THEN pg_get_constraintdef(con.oid) END
      ))
     FROM pg_constraint con
     LEFT JOIN pg_class rc ON rc.oid = con.confrelid
     LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
     WHERE con.conrelid = c.oid AND con.contype IN ('p','u','f','c')) AS constraints,
    (SELECT json_agg(json_build_object(
        'name', ic.relname,
        'columns', (SELECT json_agg(att.attname ORDER BY k.ord)
                    FROM unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute att ON att.attrelid = i.indrelid AND att.attnum = k.attnum
                    WHERE k.attnum > 0),
        'hasExpression', EXISTS (SELECT 1 FROM unnest(i.indkey::int2[]) AS x(n) WHERE x.n = 0),
        'expression', pg_get_expr(i.indexprs, i.indrelid),
        'partial', i.indpred IS NOT NULL))
     FROM pg_index i
     JOIN pg_class ic ON ic.oid = i.indexrelid
     WHERE i.indrelid = c.oid AND i.indisunique AND NOT i.indisprimary
       AND NOT EXISTS (SELECT 1 FROM pg_constraint cc WHERE cc.conindid = i.indexrelid AND cc.contype IN ('u','p'))) AS "uniqueIndexes"
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = :schema AND c.relkind IN ('r','p')
) t
"""

MYSQL_METADATA_SQL = """
SELECT JSON_OBJECT('tables', COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
  'name', t.TABLE_NAME,
  'columns', (SELECT JSON_ARRAYAGG(JSON_OBJECT(
      'name', c.COLUMN_NAME, 'type', c.COLUMN_TYPE, 'udt', c.DATA_TYPE,
      'maxLength', c.CHARACTER_MAXIMUM_LENGTH, 'nullable', c.IS_NULLABLE = 'YES',
      'default', c.COLUMN_DEFAULT, 'identity', c.EXTRA LIKE '%auto_increment%'))
    FROM information_schema.COLUMNS c
    WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME),
  'constraints', (SELECT JSON_ARRAYAGG(JSON_OBJECT(
      'type', CASE tc.CONSTRAINT_TYPE WHEN 'PRIMARY KEY' THEN 'p' WHEN 'UNIQUE' THEN 'u' WHEN 'FOREIGN KEY' THEN 'f' END,
      'name', tc.CONSTRAINT_NAME,
      'columns', (SELECT JSON_ARRAYAGG(k.COLUMN_NAME) FROM information_schema.KEY_COLUMN_USAGE k
                  WHERE k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND k.TABLE_NAME = tc.TABLE_NAME AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME),
      'refTable', (SELECT MAX(k.REFERENCED_TABLE_NAME) FROM information_schema.KEY_COLUMN_USAGE k
                  WHERE k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND k.TABLE_NAME = tc.TABLE_NAME AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME),
      'refColumns', (SELECT JSON_ARRAYAGG(k.REFERENCED_COLUMN_NAME) FROM information_schema.KEY_COLUMN_USAGE k
                  WHERE k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND k.TABLE_NAME = tc.TABLE_NAME AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME)))
    FROM information_schema.TABLE_CONSTRAINTS tc
    WHERE tc.TABLE_SCHEMA = t.TABLE_SCHEMA AND tc.TABLE_NAME = t.TABLE_NAME AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY','UNIQUE','FOREIGN KEY'))
)), JSON_ARRAY())) AS metadata
FROM information_schema.TABLES t
WHERE t.TABLE_SCHEMA = DATABASE() AND t.TABLE_TYPE = 'BASE TABLE'
"""
