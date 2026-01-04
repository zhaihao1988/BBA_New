-- ----------------------------
-- Table structure for measure_result_core
-- ----------------------------
DROP TABLE IF EXISTS "measure_result_core";
CREATE TABLE "measure_result_core" (
  "id" int8 NOT NULL
      constraint pk_measure_result_core
          primary key,
  "val_month" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "group_id"     varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "portfolio_id"     varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "val_method"  varchar(6) COLLATE "pg_catalog"."default"  NOT NULL,
  "var" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "var_amt" numeric(38,10) NOT NULL,
  "profit_level" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "currency" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "is_status" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "version" int8 NOT NULL,
  "create_by" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "update_by" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "create_time" timestamp(6) NOT NULL,
  "update_time" timestamp(6) NOT NULL,
  "com_code"         varchar(32) COLLATE "pg_catalog"."default",
  "business_nature"  varchar(32) COLLATE "pg_catalog"."default",
  "car_kind_code"    varchar(32) COLLATE "pg_catalog"."default",
  "use_nature_code"  varchar(32) COLLATE "pg_catalog"."default",
  "coverage_segment" varchar(32) COLLATE "pg_catalog"."default",
  "remark" varchar(1024) COLLATE "pg_catalog"."default"
)
;
COMMENT ON COLUMN "measure_result_core"."id" IS '主键ID';
COMMENT ON COLUMN "measure_result_core"."val_month" IS '当期评估月(yyyymm)';
COMMENT ON COLUMN "measure_result_core"."group_id" IS '合同分组编号(长)';
COMMENT ON COLUMN "measure_result_core"."portfolio_id" IS '合同组合编号(短)';
COMMENT ON COLUMN "measure_result_core"."val_method" IS '评估方法';
COMMENT ON COLUMN "measure_result_core"."var" IS '变量';
COMMENT ON COLUMN "measure_result_core"."var_amt" IS '变量值';
COMMENT ON COLUMN "measure_result_core"."profit_level" IS '盈亏水平';
COMMENT ON COLUMN "measure_result_core"."currency" IS '币种';
COMMENT ON COLUMN "measure_result_core"."is_status" IS '状态';
COMMENT ON COLUMN "measure_result_core"."version" IS '版本号';
COMMENT ON COLUMN "measure_result_core"."create_by" IS '创建人';
COMMENT ON COLUMN "measure_result_core"."update_by" IS '更新人';
COMMENT ON COLUMN "measure_result_core"."create_time" IS '创建时间';
COMMENT ON COLUMN "measure_result_core"."update_time" IS '更新时间';
COMMENT ON COLUMN "measure_result_core"."remark" IS '备注';
COMMENT ON COLUMN "measure_result_core"."com_code" IS '归属机构';
COMMENT ON COLUMN "measure_result_core"."business_nature" IS '业务渠道';
COMMENT ON COLUMN "measure_result_core"."car_kind_code" IS '车辆种类';
COMMENT ON COLUMN "measure_result_core"."use_nature_code" IS '使用性质';
COMMENT ON COLUMN "measure_result_core"."coverage_segment" IS '险别条款段';
COMMENT ON TABLE "measure_result_core" IS '计量通用核心计量结果';

-- ----------------------------
-- Indexes structure for table measure_result_core
-- ----------------------------
CREATE UNIQUE INDEX "uk_measure_result_core" ON "measure_result_core" USING btree (
  "val_month" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "group_id" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "val_method" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "var" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
