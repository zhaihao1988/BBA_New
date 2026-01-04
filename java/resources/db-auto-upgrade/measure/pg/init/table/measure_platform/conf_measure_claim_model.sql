drop table if exists measure_platform.conf_measure_claim_model;
create table measure_platform.conf_measure_claim_model
(
  id          integer not null
    constraint conf_measure_actuarial_assumption_pkey
      primary key,
  val_year    varchar(4),
  month_id    integer,
  risk_code   varchar(6),
  paid_ratio  numeric(38, 10),
  create_by   varchar(64),
  update_by   varchar(64),
  create_time timestamp,
  update_time timestamp,
  remark      varchar(255)
);

alter table measure_platform.conf_measure_claim_model
  owner to cas25_dev;
comment on table measure_platform.conf_measure_claim_model is '赔付模式配置表';
comment on column measure_platform.conf_measure_claim_model.id is '主键';
comment on column measure_platform.conf_measure_claim_model.val_year    is '评估年';
comment on column measure_platform.conf_measure_claim_model.month_id    is '月数序号';
comment on column measure_platform.conf_measure_claim_model.risk_code   is '险种代码';
comment on column measure_platform.conf_measure_claim_model.paid_ratio  is '赔付率';
comment on column measure_platform.conf_measure_claim_model.create_by   is '创建人';
comment on column measure_platform.conf_measure_claim_model.update_by   is '更新人';
comment on column measure_platform.conf_measure_claim_model.create_time is '创建时间';
comment on column measure_platform.conf_measure_claim_model.update_time is '更新时间';
comment on column measure_platform.conf_measure_claim_model.remark is '备注';
