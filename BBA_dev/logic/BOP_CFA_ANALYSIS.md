# 年初预期未来现金流（BOP_Cfa）计算逻辑分析

## 用户理解

**有效合同 - 年初预期 - 预期未来 - 期末现值 - 加权初始确认利率 - 赔付现金流**

应该是在**评估月底**，根据**年初预期（上年底精算假设）**，计算的**评估月之后的现金流现值**。

## 系统现有逻辑

### 代码位置
`BBA_dev/pv_calculator.py` 第755-758行

```python
# 年初预期未来现金流（BOP_Cfa）：评估期末之后发生的现金流，折现到评估月底
res_bop_cfa = calc_all(cf_bop_future, val_month_end, uw_date, rate_val_locked_df, "")
for k, v in res_bop_cfa.items():
    results[f"Pvfl_If_Bop_Cfa_Rep_Wlk{k}"] = v
```

### 关键变量

1. **`cf_bop_future`**：年初预期的未来现金流
   - 来源：第698行 `cf_bop_future = cf_bop[cf_bop['Date_Obj'] > val_month_end]`
   - `cf_bop`的来源：第686-690行
     ```python
     if val_month_date.year in bop_cf_by_year:
         cf_bop = bop_cf_by_year[val_month_date.year]
     else:
         # 如果没有年初现金流，使用当前现金流（fallback）
         cf_bop = cf_for_calc
     ```

2. **`bop_cf_by_year`**：存储年初现金流的字典
   - 初始化：第478行 `bop_cf_by_year = {}`
   - **问题**：代码中**没有找到赋值语句**，所以`bop_cf_by_year`始终为空！

3. **`cf_for_calc`**：当前评估月的现金流
   - 来源：第527行 `cf_for_calc = cf_val`
   - `cf_val`的来源：第518行 `cf_val = projector.project_policy_flows(policy_row, assump_val)`
   - `assump_val`：当前评估月的精算假设（第505行）

4. **`cf_prev_ye`**：基于上年末假设的现金流
   - 来源：第514行 `cf_prev_ye = projector.project_policy_flows(policy_row, assump_prev_ye)`
   - `assump_prev_ye`：上年末的精算假设（第502行）
   - **问题**：这个现金流被生成了，但**没有被使用**！

### 折现逻辑

- **折现时点**：`val_month_end`（评估月底）✅ 正确
- **折现利率**：`rate_val_locked_df`（基于签单日的锁定利率，即加权初始确认利率Wlk）✅ 正确
- **现金流来源**：`cf_bop_future`（评估月之后的现金流）✅ 正确
- **现金流假设**：❌ **问题**：实际使用的是`cf_val`（当前评估月假设），而不是`cf_prev_ye`（上年末假设）

## 差异分析

### 系统现有逻辑的问题

1. **`bop_cf_by_year`没有被赋值**
   - 代码中生成了`cf_prev_ye`（基于上年末假设），但没有存储到`bop_cf_by_year`中
   - 导致`bop_cf_by_year`始终为空，走fallback逻辑

2. **Fallback逻辑错误**
   - 当`bop_cf_by_year`为空时，使用`cf_for_calc`（即`cf_val`）
   - `cf_val`是基于**当前评估月假设**（`assump_val`）生成的
   - 而不是基于**上年末假设**（`assump_prev_ye`）生成的

3. **结果**
   - 系统实际使用的是**当前评估月假设**的现金流
   - 而不是**上年末假设**的现金流
   - 这不符合IFRS 17的要求

### 正确的逻辑应该是

1. **使用`cf_prev_ye`作为年初现金流**
   - `cf_prev_ye`是基于上年末假设（`assump_prev_ye`）生成的
   - 应该存储到`bop_cf_by_year[val_month_date.year]`中

2. **从`cf_prev_ye`中提取未来现金流**
   - `cf_bop_future = cf_prev_ye[cf_prev_ye['Date_Obj'] > val_month_end]`

3. **折现到评估月底**
   - 使用加权初始确认利率（Wlk）折现

## 修复建议

在`pv_calculator.py`中，需要：

1. **保存年初现金流到`bop_cf_by_year`**
   ```python
   # 在生成cf_prev_ye之后，保存到bop_cf_by_year
   if not is_new_business:
       bop_cf_by_year[val_month_date.year] = cf_prev_ye
   ```

2. **确保使用正确的现金流**
   - 确保`cf_bop`来自`bop_cf_by_year`，而不是fallback到`cf_for_calc`

3. **添加注释说明**
   - 明确说明年初预期现金流应该基于上年末假设

