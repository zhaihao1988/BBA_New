# IFIE计量板块差异分析报告
## OCI选择权=1（拆分模式）对比

### 一、IFIE_P&C部分（计入损益）

#### ✅ 符合文档要求的部分：

1. **年初有效合同_预期现金流 IFIE_P&C（13.2）**
   - ✅ 公式：当年年末期末现值 - 当年年初期初现值
   - ✅ 使用Beg_Lcu字段（年初现值-上年期末利率）
   - ✅ 包含预期未来和预期当期
   - ✅ 使用锁定利率（Wlk）

2. **新增合同/有效合同_预期现金流 IFIE_P&C（13.3）**
   - ✅ 公式：期末现值（锁定利率）- 初始现值
   - ✅ 区分新增合同和有效合同
   - ✅ 包含预期未来和预期当期
   - ✅ 使用锁定利率（Wlk）

3. **年初有效合同_非金融风险调整 IFIE_P&C（13.5）**
   - ✅ 公式：当年年末RA期末现值 - 当年年初RA期初现值
   - ✅ 使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）
   - ✅ 使用Beg_Lcu字段
   - ✅ 使用锁定利率（Wlk）

4. **新增合同/有效合同_非金融风险调整 IFIE_P&C（13.6）**
   - ✅ 公式：期末RA现值（锁定利率）- 初始RA现值
   - ✅ 使用Rad字段
   - ✅ 区分新增合同和有效合同
   - ✅ 使用锁定利率（Wlk）

5. **IFIE_CSM（13.8）**
   - ✅ 公式：-CSM计息
   - ✅ 来自Part 5的计算结果

6. **IFIE_P&C合计（13.9）**
   - ✅ 公式：IFIE_CF + IFIE_RA + IFIE_CSM

7. **亏损分摊（13.10-13.13）**
   - ✅ 使用LC_Ratio进行分摊
   - ✅ 区分IFIE_P&C和IFIE_OCI的亏损分摊

---

### 二、IFIE_OCI部分（计入其他综合收益）

#### ❌ 不符合文档要求的部分：

### 1. **年初有效合同_预期现金流 IFIE_OCI（14.2）**

**文档要求：**
```
IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - (Eff.F_{beg_prev_curr}^{CF} - Eff.F_{beg_prev}^{CF})
```

**文档说明：**
- `Eff.F_{end_curr}^{CF}`：有效合同-期末预期-预期未来-预期现金流-期末现值（期末利率）
- `Eff.F_{end}^{CF}`：有效合同-期末预期-预期未来-预期现金流-期末现值（加权初始确认利率）
- `Eff.F_{beg_prev_curr}^{CF}`：有效合同-年初预期-预期未来-预期现金流-年初现值（上年期末利率）
- `Eff.F_{beg_prev}^{CF}`：有效合同-年初预期-预期未来-预期现金流-年初现值（上年加权初始确认利率）

**当前代码实现：**
```python
ifie_oci_if_cf = Decimal('0')  # 简化：假设无期初余额
```

**差异：**
- ❌ **严重错误**：年初有效合同的IFIE_OCI被简化为0，完全不符合文档要求
- ❌ 缺少年初利率差异的计算：`(Eff.F_{beg_prev_curr}^{CF} - Eff.F_{beg_prev}^{CF})`
- ❌ 缺少期末利率差异的计算：`(Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF})`
- ❌ 文档要求使用**预期未来（Cfa）**，但代码中未实现

**需要的PV字段：**
- `Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt` + `Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt`（期末-期末利率）
- `Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt` + `Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt`（期末-锁定利率）
- `Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt` + `Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt`（年初-上年期末利率）
- `Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt` + `Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt`（年初-上年加权初始确认利率）**⚠️ 此字段可能不存在**

---

### 2. **年初有效合同_非金融风险调整 IFIE_OCI（14.5）**

**文档要求：**
```
IFIE_{OCI_IF}^{RA} = (Eff.F_{end_curr}^{RA} - Eff.F_{end}^{RA}) - (Eff.F_{beg_prev_curr}^{RA} - Eff.F_{beg_prev}^{RA})
```

**文档说明：**
- `Eff.F_{end_curr}^{RA}`：有效合同-期末预期-预期未来-预期非金融风险调整-期末现值（期末利率）
- `Eff.F_{end}^{RA}`：有效合同-期末预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）
- `Eff.F_{beg_prev_curr}^{RA}`：有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年期末利率）
- `Eff.F_{beg_prev}^{RA}`：有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年加权初始确认利率）

**当前代码实现：**
```python
ifie_oci_if_ra = Decimal('0')
ra_end_current = (pv_end_claims_current + pv_end_maint_current) * ra_ratio
ra_end_locked = (pv_end_claims_locked + pv_end_maint_locked) * ra_ratio
ifie_oci_nb_ra = ra_end_current - ra_end_locked
```

**差异：**
- ❌ **严重错误**：年初有效合同的IFIE_OCI被简化为0，完全不符合文档要求
- ❌ 缺少年初利率差异的计算：`(Eff.F_{beg_prev_curr}^{RA} - Eff.F_{beg_prev}^{RA})`
- ❌ 缺少期末利率差异的计算：`(Eff.F_{end_curr}^{RA} - Eff.F_{end}^{RA})`
- ❌ 文档要求使用**Rad字段**，但代码中使用了`(Cla+Mtn)×RA_Ratio`计算（仅针对新增合同部分）
- ❌ 文档要求使用**预期未来（Cfa）**，但代码中未实现

**需要的PV字段：**
- `Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt`（期末-期末利率）**⚠️ 此字段可能不存在**
- `Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt`（期末-锁定利率）
- `Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt`（年初-上年期末利率）
- `Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt`（年初-上年加权初始确认利率）**⚠️ 此字段可能不存在**

---

### 3. **新增合同_预期现金流 IFIE_OCI（14.3）**

**文档要求：**
```
IFIE_{OCI_NB}^{CF} = New.F_{end_curr}^{CF} - New.F_{end}^{CF}
```

**文档说明：**
- `New.F_{end_curr}^{CF}`：新增合同-期末预期-预期未来-预期现金流-期末现值（期末利率）
- `New.F_{end}^{CF}`：新增合同-期末预期-预期未来-预期现金流-期末现值（加权初始确认利率）

**当前代码实现：**
```python
pv_field_end_claims_current = 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt'
pv_field_end_maint_current = 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt'
pv_field_end_claims_locked = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt'
pv_field_end_maint_locked = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt'
ifie_oci_nb_cf = (pv_end_claims_current + pv_end_maint_current) - (pv_end_claims_locked + pv_end_maint_locked)
```

**差异：**
- ✅ 公式基本正确：期末利率 - 锁定利率
- ✅ 使用预期未来（Cfa）字段
- ✅ 区分新增合同和有效合同
- ⚠️ **潜在问题**：文档要求只使用**预期未来（Cfa）**，代码中确实使用了Cfa字段，这部分是正确的

---

### 4. **新增合同_非金融风险调整 IFIE_OCI（14.6）**

**文档要求：**
```
IFIE_{OCI_NB}^{RA} = New.F_{end_curr}^{RA} - New.F_{end}^{RA}
```

**文档说明：**
- `New.F_{end_curr}^{RA}`：新增合同-期末预期-预期未来-预期非金融风险调整-期末现值（期末利率）
- `New.F_{end}^{RA}`：新增合同-期末预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）

**当前代码实现：**
```python
ra_end_current = (pv_end_claims_current + pv_end_maint_current) * ra_ratio
ra_end_locked = (pv_end_claims_locked + pv_end_maint_locked) * ra_ratio
ifie_oci_nb_ra = ra_end_current - ra_end_locked
```

**差异：**
- ❌ **不符合文档要求**：文档要求使用**Rad字段**，但代码中使用了`(Cla+Mtn)×RA_Ratio`计算
- ❌ 应该使用：`Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt` - `Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt`
- ⚠️ **潜在问题**：文档要求只使用**预期未来（Cfa）**，代码中使用了Cfa字段，这部分是正确的

---

### 5. **IFIE_OCI合计（14.8）**

**文档要求：**
```
IFIE_{OCI_Total} = IFIE_{OCI_CF} + IFIE_{OCI_RA}
```

**当前代码实现：**
```python
ifie_oci_total = ifie_oci_cf + ifie_oci_ra
```

**差异：**
- ⚠️ **部分正确**：公式正确，但由于年初有效合同的IFIE_OCI被简化为0，合计结果不准确

---

### 6. **IFIE_OCI亏损分摊（14.9-14.12）**

**文档要求：**
- 14.9: `IFIE_{OCI_CF_LC} = LC_{IFIE_CF} - IFIE_{CF_LC}`
- 14.10: `IFIE_{OCI_CF_nonLC} = IFIE_{OCI_CF} - IFIE_{OCI_CF_LC}`
- 14.11: `IFIE_{OCI_RA_LC} = LC_{IFIE_RA} - IFIE_{RA_LC}`
- 14.12: `IFIE_{OCI_RA_nonLC} = IFIE_{OCI_RA} - IFIE_{OCI_RA_LC}`

**当前代码实现：**
```python
context.ifie_oci_lc = ifie_oci_total * context.nb_lc_ratio
context.ifie_oci_non_lc = ifie_oci_total - context.ifie_oci_lc
```

**差异：**
- ❌ **不符合文档要求**：文档要求使用减法公式（LC分摊IFIE - IFIE_P&C亏损），但代码中使用了简单的比例分摊
- ❌ 缺少`LC_{IFIE_CF}`和`LC_{IFIE_RA}`的计算（来自第7章）
- ❌ 缺少`IFIE_{CF_LC}`和`IFIE_{RA_LC}`的计算（来自第13.10-13.13节）

---

## 三、总结

### 严重问题（必须修复）：

1. **年初有效合同_预期现金流 IFIE_OCI（14.2）**：完全未实现，被简化为0
2. **年初有效合同_非金融风险调整 IFIE_OCI（14.5）**：完全未实现，被简化为0
3. **新增合同_非金融风险调整 IFIE_OCI（14.6）**：未使用Rad字段，使用了(Cla+Mtn)×RA_Ratio计算
4. **IFIE_OCI亏损分摊（14.9-14.12）**：公式不符合文档要求，使用了简单的比例分摊

### 潜在问题（需要确认）：

1. **年初有效合同IFIE_OCI**：需要确认是否存在`Pvfl_If_Bop_Cfa_Beg_Wlk_*`字段（年初-上年加权初始确认利率）
2. **新增合同IFIE_OCI**：需要确认是否存在`Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt`字段（期末-期末利率的Rad字段）

### 符合要求的部分：

1. IFIE_P&C部分基本符合文档要求
2. 新增合同_预期现金流 IFIE_OCI（14.3）基本正确
3. IFIE_OCI合计（14.8）公式正确（但结果不准确，因为年初有效合同部分缺失）

---

## 四、修复建议

### 优先级1（必须修复）：

1. **实现年初有效合同_预期现金流 IFIE_OCI（14.2）**
   - 需要计算：`(期末利率差异) - (年初利率差异)`
   - 需要确认PV字段是否存在

2. **实现年初有效合同_非金融风险调整 IFIE_OCI（14.5）**
   - 需要计算：`(期末利率差异) - (年初利率差异)`
   - 需要使用Rad字段，不能使用(Cla+Mtn)×RA_Ratio

3. **修复新增合同_非金融风险调整 IFIE_OCI（14.6）**
   - 改为使用Rad字段：`Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt` - `Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt`

4. **修复IFIE_OCI亏损分摊（14.9-14.12）**
   - 改为使用减法公式：`LC_{IFIE_CF} - IFIE_{CF_LC}`
   - 需要从第7章获取`LC_{IFIE_CF}`和`LC_{IFIE_RA}`
   - 需要从第13.10-13.13节获取`IFIE_{CF_LC}`和`IFIE_{RA_LC}`

### 优先级2（需要确认）：

1. **确认PV字段是否存在**：
   - ✅ `Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt`（期末-期末利率的Rad字段）**已存在**
   - ✅ `Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt`（新增合同-期末-期末利率的Rad字段）**已存在**
   - ❌ `Pvfl_If_Bop_Cfa_Beg_Wlk_*`（年初-上年加权初始确认利率）**不存在**

2. **如果字段不存在，需要修改pv_calculator.py生成这些字段**
   - 需要生成：`Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt`
   - 需要生成：`Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt`
   - 需要生成：`Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt`

---

## 五、代码位置

- **IFIE_P&C部分**：`BBA_dev/logic/ifie.py` 第124-463行
- **IFIE_OCI部分**：`BBA_dev/logic/ifie.py` 第468-565行
- **亏损分摊部分**：`BBA_dev/logic/ifie.py` 第581-628行

