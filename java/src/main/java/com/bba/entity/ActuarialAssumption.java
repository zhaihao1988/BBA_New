package com.bba.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import lombok.Data;
import java.math.BigDecimal;

@Data
@TableName(value = "zh.conf_measure_actuarial_assumption", autoResultMap = true)
public class ActuarialAssumption {
    
    @TableField("class_code")
    private String classCode;
    
    @TableField("val_month")
    private String valMonth;
    
    @TableField("val_method")
    private String valMethod;
    
    @TableField("loss_ratio")
    private BigDecimal lossRatio;
    
    @TableField("indirect_claims_expense_ratio")
    private BigDecimal indirectClaimsExpenseRatio;
    
    @TableField("maintenance_expense_ratio")
    private BigDecimal maintenanceExpenseRatio;
    
    @TableField("ra")
    private BigDecimal raRatio;
    
    @TableField("acquisition_expense_ratio")
    private BigDecimal acquisitionExpenseRatio;
}
