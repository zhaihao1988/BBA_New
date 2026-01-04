-- 删除表结构
DROP TABLE IF EXISTS "conf_measure_common_pad";
-- auto-generated definition
create table conf_measure_common_pad
(
  id              bigint          not null
    constraint pk_conf_measure_common_pad
      primary key,
  evaluate_method varchar(4)      not null,
  val_month       varchar(6)      not null,
  i17_risk_code   varchar(32)     not null,
  pad_key         varchar(32)     not null,
  pad_value       numeric(12, 10) not null,
  version         integer         not null,
  create_by       varchar(64)     not null,
  update_by       varchar(64)     not null,
  create_time     timestamp(6)    not null,
  update_time     timestamp(6)    not null,
  is_status       varchar(1)      not null,
  remark          varchar(255)
);

comment on table conf_measure_common_pad is '计量通用非金融风险调整系数配置表';

comment on column conf_measure_common_pad.id is '主键id';

comment on column conf_measure_common_pad.evaluate_method is '评估方法(见字典)';

comment on column conf_measure_common_pad.val_month is '评估月(YYYYmm)';

comment on column conf_measure_common_pad.i17_risk_code is 'I17险种代码';

comment on column conf_measure_common_pad.pad_key is '非金融风险调整系数key';

comment on column conf_measure_common_pad.pad_value is '非金融风险调整系数value';

comment on column conf_measure_common_pad.version is '版本号';

comment on column conf_measure_common_pad.create_by is '创建人';

comment on column conf_measure_common_pad.update_by is '更新人';

comment on column conf_measure_common_pad.create_time is '创建时间';

comment on column conf_measure_common_pad.update_time is '更新时间';

comment on column conf_measure_common_pad.is_status is '状态（0待处理 1处理中 2已处理 3异常）';

comment on column conf_measure_common_pad.remark is '备注';

create unique index uk_conf_measure_common_pad
  on conf_measure_common_pad (evaluate_method, val_month, i17_risk_code, pad_key);


-- ----------------------------
-- Records of conf_measure_common_pad
-- 070004 产品 非金融风险调整系数 数据
-- ----------------------------
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (1, '1', '2021', 'NA', '1', '1.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (4, '1', '2021', 'NA', '2', '1.1000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (7, '1', '2021', 'NA', '3', '0.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (2, '1', '2022', 'NA', '1', '1.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (5, '1', '2022', 'NA', '2', '1.1000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (8, '1', '2022', 'NA', '3', '0.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (3, '1', '2023', 'NA', '1', '1.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (6, '1', '2023', 'NA', '2', '1.1000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (9, '1', '2023', 'NA', '3', '0.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (10, '3', '2022', 'NA', '1', '1.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (13, '3', '2022', 'NA', '2', '1.1000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (16, '3', '2022', 'NA', '3', '0.9000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (11, '3', '2023', 'NA', '1', '1.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (14, '3', '2023', 'NA', '2', '1.1000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (17, '3', '2023', 'NA', '3', '0.9000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (12, '3', '2024', 'NA', '1', '1.0000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (15, '3', '2024', 'NA', '2', '1.1000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (18, '3', '2024', 'NA', '3', '0.9000000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (21, '4', '2023', '070004', '1', '0.0200000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (20, '4', '2022', '070004', '1', '0.0200000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (22, '4', '2024', '070004', '1', '0.0200000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (19, '4', '2021', '070004', '1', '0.0200000000', 1, 'test', 'test', '2024-01-24 04:08:10', '2024-01-24 04:08:10', '2', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (23, '4', '2022', 'ACCX01', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (24, '8', '2022', '0105', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (25, '8', '2022', '0511', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (26, '8', '2022', '260001', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (27, '8', '2022', '31DXZN', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (28, '8', '2022', '3241ZN', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (29, '8', '2022', '3320ZN', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (30, '8', '2022', '3441ZN', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
INSERT INTO "measure_platform"."conf_measure_common_pad" ("id", "evaluate_method", "val_month", "i17_risk_code", "pad_key", "pad_value", "version", "create_by", "update_by", "create_time", "update_time", "is_status", "remark")
VALUES (31, '10', '2022', 'NA', '1', '0.0350000000', 1, 'test', 'test', '2024-03-08 04:08:10', '2024-03-08 04:08:10', '3', '测试数据');
drop table if exists "measure_platform"."conf_measure_common_pad";
