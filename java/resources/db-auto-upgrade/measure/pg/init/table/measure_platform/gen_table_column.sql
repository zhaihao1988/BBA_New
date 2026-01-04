-- ----------------------------
-- Table structure for gen_table_column
-- ----------------------------
DROP TABLE IF EXISTS "gen_table_column";
CREATE TABLE "gen_table_column"
(
  "column_id"      int8 NOT NULL
    constraint pk_gen_table_column
      primary key,
  "table_id"       int8,
  "column_name"    varchar(200) COLLATE "pg_catalog"."default",
  "column_comment" varchar(500) COLLATE "pg_catalog"."default",
  "column_type"    varchar(100) COLLATE "pg_catalog"."default",
  "java_type"      varchar(500) COLLATE "pg_catalog"."default",
  "java_field"     varchar(200) COLLATE "pg_catalog"."default",
  "is_pk"          char(1) COLLATE "pg_catalog"."default",
  "is_increment"   char(1) COLLATE "pg_catalog"."default",
  "is_required"    char(1) COLLATE "pg_catalog"."default",
  "is_insert"      char(1) COLLATE "pg_catalog"."default",
  "is_edit"        char(1) COLLATE "pg_catalog"."default",
  "is_list"        char(1) COLLATE "pg_catalog"."default",
  "is_query"       char(1) COLLATE "pg_catalog"."default",
  "query_type"     varchar(200) COLLATE "pg_catalog"."default",
  "html_type"      varchar(200) COLLATE "pg_catalog"."default",
  "dict_type"      varchar(200) COLLATE "pg_catalog"."default",
  "sort"           int4,
  "create_by"      varchar(64) COLLATE "pg_catalog"."default",
  "create_time"    timestamp(6),
  "update_by"      varchar(64) COLLATE "pg_catalog"."default",
  "update_time"    timestamp(6),
  "version"        int8 NOT NULL
)
;
COMMENT
ON COLUMN "gen_table_column"."column_id" IS '编号';
COMMENT
ON COLUMN "gen_table_column"."table_id" IS '归属表编号';
COMMENT
ON COLUMN "gen_table_column"."column_name" IS '列名称';
COMMENT
ON COLUMN "gen_table_column"."column_comment" IS '列描述';
COMMENT
ON COLUMN "gen_table_column"."column_type" IS '列类型';
COMMENT
ON COLUMN "gen_table_column"."java_type" IS 'JAVA类型';
COMMENT
ON COLUMN "gen_table_column"."java_field" IS 'JAVA字段名';
COMMENT
ON COLUMN "gen_table_column"."is_pk" IS '是否主键（1是）';
COMMENT
ON COLUMN "gen_table_column"."is_increment" IS '是否自增（1是）';
COMMENT
ON COLUMN "gen_table_column"."is_required" IS '是否必填（1是）';
COMMENT
ON COLUMN "gen_table_column"."is_insert" IS '是否为插入字段（1是）';
COMMENT
ON COLUMN "gen_table_column"."is_edit" IS '是否编辑字段（1是）';
COMMENT
ON COLUMN "gen_table_column"."is_list" IS '是否列表字段（1是）';
COMMENT
ON COLUMN "gen_table_column"."is_query" IS '是否查询字段（1是）';
COMMENT
ON COLUMN "gen_table_column"."query_type" IS '查询方式（等于、不等于、大于、小于、范围）';
COMMENT
ON COLUMN "gen_table_column"."html_type" IS '显示类型（文本框、文本域、下拉框、复选框、单选框、日期控件）';
COMMENT
ON COLUMN "gen_table_column"."dict_type" IS '字典类型';
COMMENT
ON COLUMN "gen_table_column"."sort" IS '排序';
COMMENT
ON COLUMN "gen_table_column"."create_by" IS '创建者';
COMMENT
ON COLUMN "gen_table_column"."create_time" IS '创建时间';
COMMENT
ON COLUMN "gen_table_column"."update_by" IS '更新者';
COMMENT
ON COLUMN "gen_table_column"."update_time" IS '更新时间';
COMMENT
ON COLUMN "gen_table_column"."version" IS '版本';
COMMENT
ON TABLE "gen_table_column" IS '代码生成业务表字段';
