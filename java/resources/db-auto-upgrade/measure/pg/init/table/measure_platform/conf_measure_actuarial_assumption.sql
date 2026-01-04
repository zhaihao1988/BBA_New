-- auto-generated definition
create table conf_measure_actuarial_assumption
(
  id                            integer default nextval('measure_platform.pk_seq'::regclass) not null
    constraint conf_measure_actuarial_assumption_pkey1
      primary key,
  val_month                     varchar(6)                                                   not null,
  risk_code                     varchar(64)                                                  not null,
  car_kind_code                 varchar(64)                                                  not null,
  use_nature_code               varchar(64)                                                  not null,
  val_method                    varchar(4)                                                   not null,
  loss_ratio                    numeric(38, 10),
  indirect_claims_expense_ratio numeric(38, 10),
  acquisition_expense_ratio     numeric(38, 10),
  maintenance_expense_ratio     numeric(38, 10),
  ra                            numeric(38, 10),
  ibnr_ra_factor                numeric(38, 10),
  rbnp_ra_factor                numeric(38, 10),
  cer_ra_factor                 numeric(38, 10),
  create_by                     varchar(64),
  update_by                     varchar(64),
  create_time                   timestamp,
  update_time                   timestamp,
  remark                        varchar(255)
);

comment on table conf_measure_actuarial_assumption is '精算假设配置表';

comment on column conf_measure_actuarial_assumption.id is '主键';

comment on column conf_measure_actuarial_assumption.val_month is '当前评估月';

comment on column conf_measure_actuarial_assumption.risk_code is '险种代码';

comment on column conf_measure_actuarial_assumption.car_kind_code is '车辆种类';

comment on column conf_measure_actuarial_assumption.use_nature_code is '使用性质代码';

comment on column conf_measure_actuarial_assumption.val_method is '评估方法';

comment on column conf_measure_actuarial_assumption.loss_ratio is '赔付率';

comment on column conf_measure_actuarial_assumption.indirect_claims_expense_ratio is '间接理赔费用率';

comment on column conf_measure_actuarial_assumption.acquisition_expense_ratio is '获取费用率';

comment on column conf_measure_actuarial_assumption.maintenance_expense_ratio is '维持费用率';

comment on column conf_measure_actuarial_assumption.ra is '非金融风险调整';

comment on column conf_measure_actuarial_assumption.ibnr_ra_factor is 'IBNR的ra因子';

comment on column conf_measure_actuarial_assumption.rbnp_ra_factor is 'RBNP的ra因子';

comment on column conf_measure_actuarial_assumption.cer_ra_factor is 'CER的ra因子';

comment on column conf_measure_actuarial_assumption.create_by is '创建人';

comment on column conf_measure_actuarial_assumption.update_by is '更新人';

comment on column conf_measure_actuarial_assumption.create_time is '创建时间';

comment on column conf_measure_actuarial_assumption.update_time is '更新时间';

comment on column conf_measure_actuarial_assumption.remark is '备注';

alter table conf_measure_actuarial_assumption
  owner to cas25_dev;

