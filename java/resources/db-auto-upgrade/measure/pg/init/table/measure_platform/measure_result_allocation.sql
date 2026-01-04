/*
 Navicat Premium Data Transfer

 Source Server         : 前海-dev
 Source Server Type    : PostgreSQL
 Source Server Version : 150006 (150006)
 Source Host           : 10.128.21.134:5432
 Source Catalog        : cas25_dev
 Source Schema         : measure_platform

 Target Server Type    : PostgreSQL
 Target Server Version : 150006 (150006)
 File Encoding         : 65001

 Date: 29/10/2024 15:10:47
*/


-- ----------------------------
-- Table structure for measure_result_allocation
-- ----------------------------
DROP TABLE IF EXISTS "measure_platform"."measure_result_allocation";
CREATE TABLE "measure_platform"."measure_result_allocation" (
  "id" int8 NOT NULL,
  "val_month" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "last_val_month" varchar(6) COLLATE "pg_catalog"."default",
  "unit_id" varchar(64) COLLATE "pg_catalog"."default" NOT NULL,
  "group_id" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "com_code" varchar(50) COLLATE "pg_catalog"."default",
  "business_nature" varchar(50) COLLATE "pg_catalog"."default",
  "coverage_segment" varchar(64) COLLATE "pg_catalog"."default",
  "car_kind_code" varchar(25) COLLATE "pg_catalog"."default",
  "use_nature_code" varchar(64) COLLATE "pg_catalog"."default",
  "val_method" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "un_rec_prem_amt" numeric(38,10) NOT NULL,
  "un_rec_prem_amt_group" numeric(38,10) NOT NULL,
  "lrc_lc_change_amt_group" numeric(38,10) NOT NULL,
  "lrc_lc_change_amt" numeric(38,10) NOT NULL,
  "currency" varchar(6) COLLATE "pg_catalog"."default" NOT NULL,
  "portfolio_id" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "create_by" varchar(32) COLLATE "pg_catalog"."default",
  "update_by" varchar(32) COLLATE "pg_catalog"."default",
  "create_time" timestamp(6),
  "update_time" timestamp(6)
)
;
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."val_month" IS '当期评估月(yyyymm)';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."last_val_month" IS '上期评估时点(yyyymm)';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."unit_id" IS '计量单元编号';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."group_id" IS '合同分组编码';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."com_code" IS '归属机构';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."business_nature" IS '业务渠道';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."coverage_segment" IS '条款险别段';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."car_kind_code" IS '车辆种类';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."use_nature_code" IS '使用性质代码';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."val_method" IS '评估方法';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."un_rec_prem_amt" IS '未经过保费';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."un_rec_prem_amt_group" IS '未经过保费(合同组）';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."lrc_lc_change_amt_group" IS '亏损部分(合同组）';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."lrc_lc_change_amt" IS '亏损部分';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."currency" IS '币种';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."portfolio_id" IS '合同组合编号(短)';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."create_by" IS '创建人';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."update_by" IS '更新人';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."create_time" IS '创建时间';
COMMENT ON COLUMN "measure_platform"."measure_result_allocation"."update_time" IS '更新时间';
COMMENT ON TABLE "measure_platform"."measure_result_allocation" IS '计量PAA分摊平台结果表';

-- ----------------------------
-- Primary Key structure for table measure_result_allocation
-- ----------------------------
ALTER TABLE "measure_platform"."measure_result_allocation" ADD CONSTRAINT "measure_result_allocation_pkey" PRIMARY KEY ("id");
