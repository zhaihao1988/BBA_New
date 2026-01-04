-- ----------------------------
-- Table structure for gen_table
-- ----------------------------
DROP TABLE IF EXISTS "ac_engine"."gen_table";
CREATE TABLE "ac_engine"."gen_table"
(
  "table_id"          int8 NOT NULL
    constraint pk_gen_table
      primary key,
  "table_name"        varchar(200) COLLATE "pg_catalog"."default",
  "table_comment"     varchar(500) COLLATE "pg_catalog"."default",
  "sub_table_name"    varchar(64) COLLATE "pg_catalog"."default",
  "sub_table_fk_name" varchar(64) COLLATE "pg_catalog"."default",
  "class_name"        varchar(100) COLLATE "pg_catalog"."default",
  "tpl_category"      varchar(200) COLLATE "pg_catalog"."default",
  "package_name"      varchar(100) COLLATE "pg_catalog"."default",
  "module_name"       varchar(60) COLLATE "pg_catalog"."default",
  "business_name"     varchar(60) COLLATE "pg_catalog"."default",
  "function_name"     varchar(50) COLLATE "pg_catalog"."default",
  "function_author"   varchar(50) COLLATE "pg_catalog"."default",
  "gen_type"          char(1) COLLATE "pg_catalog"."default",
  "gen_path"          varchar(200) COLLATE "pg_catalog"."default",
  "options"           varchar(1000) COLLATE "pg_catalog"."default",
  "create_by"         varchar(64) COLLATE "pg_catalog"."default",
  "create_time"       timestamp(6),
  "update_by"         varchar(64) COLLATE "pg_catalog"."default",
  "update_time"       timestamp(6),
  "remark"            varchar(500) COLLATE "pg_catalog"."default",
  "version"           int8 NOT NULL
)
;
ALTER TABLE "ac_engine"."gen_table" OWNER TO "biz";
COMMENT
ON COLUMN "ac_engine"."gen_table"."table_id" IS '编号';
COMMENT
ON COLUMN "ac_engine"."gen_table"."table_name" IS '表名称';
COMMENT
ON COLUMN "ac_engine"."gen_table"."table_comment" IS '表描述';
COMMENT
ON COLUMN "ac_engine"."gen_table"."sub_table_name" IS '关联子表的表名';
COMMENT
ON COLUMN "ac_engine"."gen_table"."sub_table_fk_name" IS '子表关联的外键名';
COMMENT
ON COLUMN "ac_engine"."gen_table"."class_name" IS '实体类名称';
COMMENT
ON COLUMN "ac_engine"."gen_table"."tpl_category" IS '使用的模板（crud单表操作 tree树表操作）';
COMMENT
ON COLUMN "ac_engine"."gen_table"."package_name" IS '生成包路径';
COMMENT
ON COLUMN "ac_engine"."gen_table"."module_name" IS '生成模块名';
COMMENT
ON COLUMN "ac_engine"."gen_table"."business_name" IS '生成业务名';
COMMENT
ON COLUMN "ac_engine"."gen_table"."function_name" IS '生成功能名';
COMMENT
ON COLUMN "ac_engine"."gen_table"."function_author" IS '生成功能作者';
COMMENT
ON COLUMN "ac_engine"."gen_table"."gen_type" IS '生成代码方式（0zip压缩包 1自定义路径）';
COMMENT
ON COLUMN "ac_engine"."gen_table"."gen_path" IS '生成路径（不填默认项目路径）';
COMMENT
ON COLUMN "ac_engine"."gen_table"."options" IS '其它生成选项';
COMMENT
ON COLUMN "ac_engine"."gen_table"."create_by" IS '创建者';
COMMENT
ON COLUMN "ac_engine"."gen_table"."create_time" IS '创建时间';
COMMENT
ON COLUMN "ac_engine"."gen_table"."update_by" IS '更新者';
COMMENT
ON COLUMN "ac_engine"."gen_table"."update_time" IS '更新时间';
COMMENT
ON COLUMN "ac_engine"."gen_table"."remark" IS '备注';
COMMENT
ON COLUMN "ac_engine"."gen_table"."version" IS '版本';
COMMENT
ON TABLE "ac_engine"."gen_table" IS '代码生成业务表';
