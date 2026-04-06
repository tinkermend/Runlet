# 模板槽位

仅列模板与必填槽位；槽位值由对话提取或补问获得。

| template_code | required_slots |
| --- | --- |
| has_data | none |
| no_data | none |
| field_equals_exists | field, operator, value |
| status_exists | status |
| count_gte | min_count |

说明：自然语言“至少 N 条”统一映射到 `min_count`。
