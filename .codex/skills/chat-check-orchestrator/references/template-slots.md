# 模板槽位

仅列模板与必填槽位；槽位值由对话提取或补问获得。

| template_code | required_slots |
| --- | --- |
| has_data | 无 |
| no_data | 无 |
| field_equals_exists | field, operator, value |
| status_exists | status |
| count_gte | min_count |

说明：自然语言“至少 N 条”统一映射到 `min_count`。

`field_equals_exists` 的 `operator` 仅在用户明确表达比较方式时再归一填写；若语义未明确，应先补问，或统一按默认等值 token `equals` 处理，不要省略 `operator`，也不要引入新的操作符词汇。
