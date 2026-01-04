drop table if exists measure_platform.measure_cf_basic_data;
create table if not exists measure_platform.measure_cf_basic_data
(
  id                    bigint          not null
    constraint pk_measure_cf_basic_data
      primary key,
  val_month             varchar(8)      not null,
  unit_id               varchar(128)    not null,
  political_flag        varchar(4),
  present_flag          varchar(4)      not null,
  biz_type              varchar(6)      not null,
  risk_code             varchar(32)     not null,
  pay_freq              varchar(4),
  start_date            varchar(10)     not null,
  rein_prem_ratio       numeric(38, 10),
  surplus_ratio         numeric(38, 10),
  period_adj_ratio      numeric(38, 10) default 0,
  rein_part_ratio       numeric(38, 10) default 0,
  rein_prem             numeric(38, 10),
  ceded_out_premium_cny numeric(38, 10),
  premium_cny           numeric(38, 10) not null,
  currency              varchar(4)      not null,
  init_prem_fcy         numeric(38, 10),
  foreign_currency      varchar(4),
  acc_prem              numeric(38, 10),
  iacf_fol_cny          numeric(38, 10),
  curr_iacf_fcy         numeric(38, 10),
  end_date              varchar(10),
  term                  bigint,
  term_unit             varchar(2),
  invest_prop           numeric(12, 10),
  group_id              varchar(32)     not null,
  portfolio_id          varchar(32)     not null,
  val_method            varchar(6)      not null,
  version               integer,
  create_by             varchar(64),
  update_by             varchar(64),
  create_time           timestamp(6),
  update_time           timestamp(6),
  is_status             varchar(1),
  remark                varchar(255),
  com_code              varchar(50),
  business_nature       varchar(50),
  car_kind_code         varchar(25),
  use_nature_code       varchar(25),
  coverage_segment      varchar(255),
  last_val_month        varchar(8),
  under_write_date      varchar(8),
  warranty_period       varchar(16),
  evaluate_date         varchar(8),
  whether_cur_policy    varchar(1),
  plan_date             varchar(10),
  valid_date             varchar(10)
);

comment on table measure_platform.measure_cf_basic_data is '保单现金流计量基础数据';

comment on column measure_platform.measure_cf_basic_data.id is '主键id';

comment on column measure_platform.measure_cf_basic_data.val_month is '当期评估时点(yyyyMM)';

comment on column measure_platform.measure_cf_basic_data.unit_id is '计量层级编号';

comment on column measure_platform.measure_cf_basic_data.political_flag is '政保单标记';

comment on column measure_platform.measure_cf_basic_data.present_flag is '赠险标签(1-是 0-否)';

comment on column measure_platform.measure_cf_basic_data.biz_type is '业务类型';

comment on column measure_platform.measure_cf_basic_data.risk_code is 'I17险种代码';

comment on column measure_platform.measure_cf_basic_data.pay_freq is '交费频率';

comment on column measure_platform.measure_cf_basic_data.start_date is '保险责任起期';

comment on column measure_platform.measure_cf_basic_data.rein_prem_ratio is '净分出保费比例';

comment on column measure_platform.measure_cf_basic_data.surplus_ratio is '盈余比例';

comment on column measure_platform.measure_cf_basic_data.period_adj_ratio is '期调整因子';

comment on column measure_platform.measure_cf_basic_data.rein_part_ratio is '再保互助比例';

comment on column measure_platform.measure_cf_basic_data.rein_prem is '净分出保费本币';

comment on column measure_platform.measure_cf_basic_data.ceded_out_premium_cny is '分出保费';

comment on column measure_platform.measure_cf_basic_data.premium_cny is '保费-本币';

comment on column measure_platform.measure_cf_basic_data.currency is '本币币种';

comment on column measure_platform.measure_cf_basic_data.init_prem_fcy is '保费总额原币';

comment on column measure_platform.measure_cf_basic_data.foreign_currency is '原币币种';

comment on column measure_platform.measure_cf_basic_data.acc_prem is '累积已收保费本币';

comment on column measure_platform.measure_cf_basic_data.iacf_fol_cny is '保险获取现金流_本币';

comment on column measure_platform.measure_cf_basic_data.curr_iacf_fcy is '当月预期获取费用原币';

comment on column measure_platform.measure_cf_basic_data.end_date is '保险责任止期';

comment on column measure_platform.measure_cf_basic_data.term is '保障期限';

comment on column measure_platform.measure_cf_basic_data.term_unit is '保障期限单位(D,W,M,Y)';

comment on column measure_platform.measure_cf_basic_data.invest_prop is '投资成分占比';

comment on column measure_platform.measure_cf_basic_data.group_id is '合同分组编号(长)';

comment on column measure_platform.measure_cf_basic_data.portfolio_id is '合同组合编号(短)';

comment on column measure_platform.measure_cf_basic_data.val_method is '评估方法';

comment on column measure_platform.measure_cf_basic_data.version is '版本号';

comment on column measure_platform.measure_cf_basic_data.create_by is '创建人';

comment on column measure_platform.measure_cf_basic_data.update_by is '更新人';

comment on column measure_platform.measure_cf_basic_data.create_time is '创建时间';

comment on column measure_platform.measure_cf_basic_data.update_time is '更新时间';

comment on column measure_platform.measure_cf_basic_data.is_status is '状态（0待处理 1处理中 2已处理 3异常）';

comment on column measure_platform.measure_cf_basic_data.remark is '备注';

comment on column measure_platform.measure_cf_basic_data.com_code is '归属机构';

comment on column measure_platform.measure_cf_basic_data.business_nature is '业务渠道';

comment on column measure_platform.measure_cf_basic_data.car_kind_code is '车辆种类';

comment on column measure_platform.measure_cf_basic_data.use_nature_code is '使用性质';

comment on column measure_platform.measure_cf_basic_data.coverage_segment is '险别条款段';

comment on column measure_platform.measure_cf_basic_data.last_val_month is '上期评估时点yyyyMM';

comment on column measure_platform.measure_cf_basic_data.under_write_date is '签单日期';

comment on column measure_platform.measure_cf_basic_data.warranty_period is '保修期';

comment on column measure_platform.measure_cf_basic_data.evaluate_date is '保险评估起期';

comment on column measure_platform.measure_cf_basic_data.whether_cur_policy is '是否当期新单';

comment on column measure_platform.measure_cf_basic_data.plan_date is '缴费日期';
comment on column measure_platform.measure_cf_basic_data.valid_date is '批单生效日';

alter table measure_platform.measure_cf_basic_data
  owner to cas25_dev;

create unique index if not exists uk_measure_cf_basic_data
  on measure_platform.measure_cf_basic_data (val_month, unit_id, group_id);

grant delete, insert, select, truncate, update on measure_platform.measure_cf_basic_data to cas25_role_test;

