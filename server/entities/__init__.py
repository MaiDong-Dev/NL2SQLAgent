# =============================================================================
# 【实体层】包级导出
# 作用：把领域实体收敛到一处，调用方写 `from server.entities import ColumnInfo`
#       即可，不必记住每个实体在哪个文件里。
#
# 为什么这个包最适合做 re-export：实体层是纯 dataclass，**不依赖任何其它内部模块**，
# 因此在这里导入它们既不会引入循环依赖，也不会拖慢任何 import。
# =============================================================================

from server.entities.column_info import ColumnInfo
from server.entities.column_metric import ColumnMetric
from server.entities.metric_info import MetricInfo
from server.entities.table_info import TableInfo
from server.entities.value_info import ValueInfo

__all__ = [
    "ColumnInfo",
    "ColumnMetric",
    "MetricInfo",
    "TableInfo",
    "ValueInfo",
]
