#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""临时脚本：将LC分摊IFIE函数添加到group_csm_lc_measurement.py"""

# 读取LC分摊IFIE函数
with open('BBA_group/logic/csm_lc_measurement.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    lc_ifie_func = ''.join(lines[701-1:1330])

# 修改函数名（从_calculate_lc_ifie_allocation改为calculate_lc_ifie_allocation）
lc_ifie_func = lc_ifie_func.replace('def _calculate_lc_ifie_allocation', 'def calculate_lc_ifie_allocation')

# 检查是否已存在
with open('BBA_group/logic/group_csm_lc_measurement.py', 'r', encoding='utf-8') as f:
    existing = f.read()
    if 'def calculate_lc_ifie_allocation' not in existing:
        # 添加到文件末尾
        with open('BBA_group/logic/group_csm_lc_measurement.py', 'a', encoding='utf-8') as f2:
            f2.write('\n\n')
            f2.write(lc_ifie_func)
        print('✅ LC IFIE函数已添加')
    else:
        print('⚠️ LC IFIE函数已存在')



