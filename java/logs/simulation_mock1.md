
# IFRS 17 BBA 生命周期仿真器 - 初始化

**保单号**: mock1
❌ 仿真过程发生错误: 
### Error querying database.  Cause: org.postgresql.util.PSQLException: ERROR: relation "zh.t_pp_jl_contract" does not exist
  位置：132
### The error may exist in com/bba/mapper/PolicyContractMapper.java (best guess)
### The error may involve defaultParameterMap
### The error occurred while setting parameters
### SQL: SELECT  policy_no,certi_no,premium_cny,under_write_date,start_date,end_date,warranty_end_date,class_code,run_date,val_method  FROM zh.t_pp_jl_contract     WHERE (policy_no = ? AND val_method = ? AND run_date = ? AND (certi_no IS NULL OR certi_no = ?)) LIMIT 1
### Cause: org.postgresql.util.PSQLException: ERROR: relation "zh.t_pp_jl_contract" does not exist
  位置：132
; bad SQL grammar []; nested exception is org.postgresql.util.PSQLException: ERROR: relation "zh.t_pp_jl_contract" does not exist
  位置：132
