# Utils 说明

## 数据库连接配置

`diagnose_db.py` 支持以下环境：

- test：`10.128.21.148:5431/cas25_test`，用户 `readonly_cas25_test`
- qa：`10.128.21.134:5432/cas25_test_qa`，用户 `cas25_qa`

运行示例：

```bash
python BBA_dev/utils/diagnose_db.py            # 默认 test
python -c "from BBA_dev.utils.diagnose_db import diagnose_database_connection; diagnose_database_connection('qa')"
```
