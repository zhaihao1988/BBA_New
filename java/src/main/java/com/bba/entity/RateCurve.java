package com.bba.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import lombok.Data;
import java.math.BigDecimal;

@Data
@TableName(value = "measure_platform.conf_measure_month_disrate", autoResultMap = true)
public class RateCurve {
    
    @TableField("val_month")
    private String valMonth;
    
    @TableField("term_month")
    private Integer termMonth;
    
    @TableField("forward_disrate_value")
    private BigDecimal forwardDisrateValue;
}
