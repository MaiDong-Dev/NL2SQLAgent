# =============================================================================
# 【数据库交互模块】字段取值 ES 全文检索 Repository
# 作用：封装 Elasticsearch 的索引与查询操作，为「字段取值」建立倒排索引
#       （全文检索），支持通过关键词匹配召回字段的具体取值。
# 上下文传递：被 DataAgentContext 携带，在 recall_value 节点中注入使用。
# =============================================================================

from dataclasses import asdict

from elasticsearch import AsyncElasticsearch

from app.entities.value_info import ValueInfo


class ValueESRepository:
    """字段取值全文检索仓库
    
    职责：
    - 管理名为 'data-agent-value' 的 ES 索引
    - 将字段的具体取值写入 ES，建立倒排索引
    - 提供全文检索接口，通过关键词匹配召回相关字段取值
    
    为什么用 ES 而不是向量库？
    字段取值（如 "北京"、"在职"、"实习生"）是离散的枚举值或实体名，
    更适合用全文检索（倒排索引）来精确匹配，而不是语义向量检索。
    向量检索更适合字段名/指标名这类抽象概念。
    
    分词策略：
    - 使用 IK 分词器（ik_max_word），对中文做细粒度分词
    - 例如 "在职实习生" 会被切分为 ["在职", "实习生", "实习", "生"]
    - 搜索时同样使用 ik_max_word，确保召回率
    """

    # ES 索引名称
    index_name = 'data-agent-value'

    # ES 索引映射定义
    index_mappings = {
        "dynamic": False,  # 关闭动态映射，严格按定义存储
        "properties": {
            "id": {"type": "keyword"},       # 唯一标识，不分词
            "value": {
                "type": "text",
                "analyzer": "ik_max_word",       # 写入时用 IK 细粒度分词
                "search_analyzer": "ik_max_word"  # 搜索时同样用 IK 分词
            },
            "column_id": {"type": "keyword"}  # 关联的字段 ID，不分词
        }
    }

    def __init__(self, client: AsyncElasticsearch):
        self.client = client

    async def ensure_index(self):
        """确保索引存在，不存在则自动创建"""
        if not await self.client.indices.exists(index=self.index_name):
            await self.client.indices.create(index=self.index_name, mappings=self.index_mappings)

    async def index(self, value_infos: list[ValueInfo], batch_size=20):
        """批量写入字段取值（使用 ES bulk API 提高写入效率）
        
        参数：
        - value_infos: 待写入的字段取值列表
        - batch_size: 每批写入的数据量
        """
        for i in range(0, len(value_infos), batch_size):
            batch = value_infos[i:i + batch_size]
            operations = []
            for value_info in batch:
                # ES bulk API 格式：{action}\n{document}\n
                operations.append({"index": {"_index": self.index_name, "_id": value_info.id}})
                operations.append(asdict(value_info))
            await self.client.bulk(operations=operations)

    async def search(self, keyword: str, score_threshold: float = 0.6, limit: int = 5) -> list[ValueInfo]:
        """全文检索——根据关键词匹配召回字段取值
        
        参数：
        - keyword: 搜索关键词（如 "在职"、"北京"）
        - score_threshold: 相关性分数阈值（0.6），低于此分数的结果丢弃
        - limit: 返回的最大结果数（Top-5）
        
        检索方式：
        - 使用 match 查询，ES 会对 keyword 做 IK 分词后再匹配
        - 例如搜索 "在职" 能匹配到 "在职实习生"、"在职员工" 等
        """
        result = await self.client.search(index=self.index_name,
                                          query={
                                              "match": {
                                                  "value": keyword
                                              }
                                          },
                                          min_score=score_threshold,
                                          size=limit)
        return [ValueInfo(**hit['_source']) for hit in result['hits']['hits']]