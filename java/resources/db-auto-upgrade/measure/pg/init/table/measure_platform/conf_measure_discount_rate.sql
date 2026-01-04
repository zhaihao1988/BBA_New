-- auto-generated definition
create table conf_measure_discount_rate
(
  id            integer not null
    primary key,
  val_month     varchar(6),
  month_id      integer,
  discount_rate numeric(38, 10),
  create_by     varchar(64),
  update_by     varchar(64),
  create_time   timestamp,
  update_time   timestamp,
  remark        varchar(255)
);

comment on table conf_measure_discount_rate is '折现率配置表';

comment on column conf_measure_discount_rate.id is '主键';

comment on column conf_measure_discount_rate.val_month is '评估年月';

comment on column conf_measure_discount_rate.month_id is '月数序号';

comment on column conf_measure_discount_rate.discount_rate is '折现率';

comment on column conf_measure_discount_rate.create_by is '创建人';

comment on column conf_measure_discount_rate.update_by is '更新人';

comment on column conf_measure_discount_rate.create_time is '创建时间';

comment on column conf_measure_discount_rate.update_time is '更新时间';

comment on column conf_measure_discount_rate.remark is '备注';

alter table conf_measure_discount_rate
  owner to cas25_dev;

