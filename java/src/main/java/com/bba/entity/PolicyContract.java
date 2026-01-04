package com.bba.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDate;

@Data
@TableName(value = "zh.t_pp_jl_contract", autoResultMap = true)
public class PolicyContract {
    
    @TableField("policy_no")
    private String policyNo;
    
    @TableField("certi_no")
    private String certiNo;
    
    @TableField("premium_cny")
    private BigDecimal sumPremiumNoTax;
    
    @TableField("under_write_date")
    private LocalDate underWriteDate;
    
    @TableField("start_date")
    private LocalDate startDate;
    
    @TableField("end_date")
    private LocalDate endDate;
    
    @TableField("warranty_end_date")
    private LocalDate warrantyEndDate;
    
    @TableField("class_code")
    private String classCode;
    
    @TableField("run_date")
    private String runDate;
    
    @TableField("val_method")
    private String valMethod;

    @TableField(exist = false)
    private BigDecimal iacfAmount;
}
