-- ----------------------------
-- Table structure for conf_measure_core
-- ----------------------------
DROP TABLE IF EXISTS "conf_measure_core";
CREATE TABLE "conf_measure_core" (
  "id" int8 NOT NULL
      constraint pk_conf_measure_core
          primary key,
  "val_method" varchar(4) COLLATE "pg_catalog"."default" NOT NULL,
  "var" varchar(64) COLLATE "pg_catalog"."default" NOT NULL,
  "var_name" varchar(64) COLLATE "pg_catalog"."default" NOT NULL,
  "order_operation" int4 NOT NULL,
  "take_var" varchar(64) COLLATE "pg_catalog"."default",
  "service_bean" varchar(64) COLLATE "pg_catalog"."default",
  "var_default_value" varchar(64) COLLATE "pg_catalog"."default",
  "var_function" varchar(1024) COLLATE "pg_catalog"."default",
  "version" int4 NOT NULL,
  "create_by" varchar(64) COLLATE "pg_catalog"."default" NOT NULL,
  "update_by" varchar(64) COLLATE "pg_catalog"."default" NOT NULL,
  "create_time" timestamp(6) NOT NULL,
  "update_time" timestamp(6) NOT NULL,
  "is_status" varchar(1) COLLATE "pg_catalog"."default" NOT NULL,
  "remark" varchar(255) COLLATE "pg_catalog"."default"
)
;
COMMENT ON COLUMN "conf_measure_core"."id" IS '主键id';
COMMENT ON COLUMN "conf_measure_core"."val_method" IS '评估方法';
COMMENT ON COLUMN "conf_measure_core"."var" IS '变量';
COMMENT ON COLUMN "conf_measure_core"."var_name" IS '变量名';
COMMENT ON COLUMN "conf_measure_core"."order_operation" IS '计算顺序';
COMMENT ON COLUMN "conf_measure_core"."take_var" IS '变量取值变量';
COMMENT ON COLUMN "conf_measure_core"."service_bean" IS '服务Bean';
COMMENT ON COLUMN "conf_measure_core"."var_default_value" IS '变量默认值';
COMMENT ON COLUMN "conf_measure_core"."var_function" IS '变量函数(记录用)';
COMMENT ON COLUMN "conf_measure_core"."version" IS '版本号';
COMMENT ON COLUMN "conf_measure_core"."create_by" IS '创建人';
COMMENT ON COLUMN "conf_measure_core"."update_by" IS '更新人';
COMMENT ON COLUMN "conf_measure_core"."create_time" IS '创建时间';
COMMENT ON COLUMN "conf_measure_core"."update_time" IS '更新时间';
COMMENT ON COLUMN "conf_measure_core"."is_status" IS '状态（0待处理 1处理中 2已处理 3异常）';
COMMENT ON COLUMN "conf_measure_core"."remark" IS '备注';
COMMENT ON TABLE "conf_measure_core" IS '计量通用核心配置表';


-- ----------------------------
-- Indexes structure for table conf_measure_core
-- ----------------------------
CREATE UNIQUE INDEX "uk_conf_measure_core" ON "conf_measure_core" USING btree (
  "val_method" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "var" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
    "order_operation" "pg_catalog"."int4_ops" ASC NULLS LAST
);


