drop table if exists measure_platform.conf_measure_common_claim;
create table if not exists measure_platform.conf_measure_common_claim
(
  id                  bigint                    not null
    constraint pk_conf_measure_common_claim
      primary key,
  val_month           varchar(6)                not null,
  last_val_month      varchar(6),
  unit_id             varchar(128)              not null,
  present_flag        varchar(4)                not null,
  risk_code           varchar(32)               not null,
  under_write_date    varchar(8),
  guarantee_period    varchar(16),
  start_date          varchar(8)                not null,
  evaluate_date       varchar(8),
  premium_cny         numeric(38, 10)           not null,
  invest_prop         numeric(12, 10),
  portfolio_id        varchar(32)               not null,
  iacf_fol_cny        numeric(38, 10),
  currency            varchar(4)                not null,
  group_id            varchar(32)               not null,
  whether_cur_policy  varchar(1),
  end_date            varchar(8),
  term                varchar(30),
  com_code            varchar(50),
  business_nature     varchar(50),
  coverage_segment    varchar(255),
  car_kind_code       varchar(25),
  use_nature_code     varchar(25),
  val_method          varchar(6)                not null,
  curr_serv_amt       numeric(38, 10) default 0 not null,
  other_serv_amt      numeric(38, 10) default 0 not null,
  cur_rec_pct         numeric(38, 10) default 0 not null,
  prem_bop_un_rec_amt numeric(38, 10) default 0 not null,
  prem_interest_amt numeric(38, 10) default 0 not null,
  prem_cur_rec_amt numeric(38, 10) default 0 not null,
  prem_eop_un_rec_amt numeric(38, 10) default 0 not null,
  un_rec_prem_amt     numeric(38, 10) default 0 not null,
  ultimate_paid_loss  numeric(38, 10) default 0 not null,
  pv_paid_loss        numeric(38, 10) default 0 not null,
  create_by           varchar(64),
  update_by           varchar(64),
  create_time         timestamp(6),
  update_time         timestamp(6),
  remark              varchar(255)
);

comment on table measure_platform.conf_measure_common_claim is '理赔配置表';

comment on column measure_platform.conf_measure_common_claim.id is '主键id';

comment on column measure_platform.conf_measure_common_claim.val_month is '当期评估月(YYYYmm)';

comment on column measure_platform.conf_measure_common_claim.last_val_month is '上期评估时点';

comment on column measure_platform.conf_measure_common_claim.unit_id is '计量层级编号';

comment on column measure_platform.conf_measure_common_claim.present_flag is '赠险标签(1-是 0-否)';

comment on column measure_platform.conf_measure_common_claim.risk_code is 'I17险种代码';

comment on column measure_platform.conf_measure_common_claim.under_write_date is '签单日期';

comment on column measure_platform.conf_measure_common_claim.guarantee_period is '保修期';

comment on column measure_platform.conf_measure_common_claim.start_date is '保险责任起期';

comment on column measure_platform.conf_measure_common_claim.evaluate_date is '保险评估起期';

comment on column measure_platform.conf_measure_common_claim.premium_cny is '保费-本币';

comment on column measure_platform.conf_measure_common_claim.invest_prop is '投资成分占比';

comment on column measure_platform.conf_measure_common_claim.portfolio_id is '合同组合编号(短)';

comment on column measure_platform.conf_measure_common_claim.iacf_fol_cny is '保险获取现金流_本币';

comment on column measure_platform.conf_measure_common_claim.currency is '本币币种';

comment on column measure_platform.conf_measure_common_claim.group_id is '合同分组编号(长)';

comment on column measure_platform.conf_measure_common_claim.whether_cur_policy is '是否当期新单';

comment on column measure_platform.conf_measure_common_claim.end_date is '保险责任止期';

comment on column measure_platform.conf_measure_common_claim.term is '保障期限';

comment on column measure_platform.conf_measure_common_claim.com_code is '归属机构';

comment on column measure_platform.conf_measure_common_claim.business_nature is '业务渠道';

comment on column measure_platform.conf_measure_common_claim.coverage_segment is '险别条款段';

comment on column measure_platform.conf_measure_common_claim.car_kind_code is '车辆种类';

comment on column measure_platform.conf_measure_common_claim.use_nature_code is '使用性质';

comment on column measure_platform.conf_measure_common_claim.val_method is '评估方法';

comment on column measure_platform.conf_measure_common_claim.curr_serv_amt is '当期服务量';

comment on column measure_platform.conf_measure_common_claim.other_serv_amt is '当期及未来服务量';

comment on column measure_platform.conf_measure_common_claim.cur_rec_pct is '当期确认比例';

comment on column measure_platform.conf_measure_common_claim.prem_bop_un_rec_amt is '期初未确认的保费';
comment on column measure_platform.conf_measure_common_claim.prem_interest_amt is '期初保费计息';
comment on column measure_platform.conf_measure_common_claim.prem_cur_rec_amt is '当期确认的保费';
comment on column measure_platform.conf_measure_common_claim.prem_eop_un_rec_amt is '期末未确认的保费';

comment on column measure_platform.conf_measure_common_claim.un_rec_prem_amt is '未经过保费';

comment on column measure_platform.conf_measure_common_claim.ultimate_paid_loss is '终极赔付金额';

comment on column measure_platform.conf_measure_common_claim.pv_paid_loss is '预期赔付金额';

comment on column measure_platform.conf_measure_common_claim.create_by is '创建人';

comment on column measure_platform.conf_measure_common_claim.update_by is '更新人';

comment on column measure_platform.conf_measure_common_claim.create_time is '创建时间';

comment on column measure_platform.conf_measure_common_claim.update_time is '更新时间';

comment on column measure_platform.conf_measure_common_claim.remark is '备注';

alter table measure_platform.conf_measure_common_claim
  owner to cas25_dev;

create unique index if not exists uk_conf_measure_common_claim
  on measure_platform.conf_measure_common_claim (val_month, unit_id, group_id);

grant delete, insert, select, truncate, update on measure_platform.conf_measure_common_claim to cas25_role_test;

