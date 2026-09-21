# =============================================================================
# 【服务层】元知识构建服务（MetaKnowledgeService）
#
# 作用：将「静态配置文件（meta_config.yaml）」中声明式定义的表/字段/指标，
#       结合「数据仓库（DW）实时查询到的实际字段类型/取值」，构建出 NL2SQL
#       系统运行时所需的全部「元知识」，并同步到三大存储引擎：
#         1. Meta MySQL（元数据库）    —— 结构化存储表/字段/指标定义
#         2. Qdrant（向量数据库）      —— 存储字段/指标的 Embedding 向量索引
#         3. Elasticsearch（全文检索） —— 存储字段取值的倒排索引
#
# 上下文传递（组合关系，见 docs/architecture-06-meta-knowledge-build 图6）：
#   - 上游调用方：meta_builder/scripts/build_meta_knowledge.py（命令行独立构建，脚本入口）
#   - 下游依赖（6 个 Repository/客户端）：
#     * meta_mysql_repository   —— 写入表/字段/指标定义到 Meta MySQL
#     * dw_mysql_repository     —— 查询 DW 的字段类型、示例值、去重取值
#     * column_qdrant_repository—— 写入字段向量到 Qdrant
#     * metric_qdrant_repository—— 写入指标向量到 Qdrant
#     * value_es_repository     —— 写入字段取值到 Elasticsearch
#     * embedding_client        —— 将文本转为向量（Embedding）
#
# 构建完成后的数据流向（运行时消费）：
#   Meta MySQL   ← merge_retrieved_info 节点查询补全元数据
#   Qdrant       ← recall_column / recall_metric 节点向量召回
#   Elasticsearch← recall_value 节点全文召回取值
# =============================================================================

import uuid
from pathlib import Path

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from omegaconf import OmegaConf

from server.conf.meta_config import MetaConfig
from server.core.log import logger
from server.entities.column_info import ColumnInfo
from server.entities.column_metric import ColumnMetric
from server.entities.metric_info import MetricInfo
from server.entities.table_info import TableInfo
from server.entities.value_info import ValueInfo
from server.repositories.es.value_es_repository import ValueESRepository
from server.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from server.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from server.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from server.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    """元知识构建服务

    职责：将配置文件中的表/字段/指标定义同步到三个存储引擎

    完整构建流程（build 方法，详见 build() 的注释）：
      1. 加载配置文件（meta_config.yaml）→ 反序列化为 MetaConfig
      2. 处理表信息：
         a. 从 DW 查询字段类型和示例值 → 保存表/字段定义到 Meta MySQL
         b. 为字段名/描述/别名生成 Embedding → 写入 Qdrant（多维度覆盖）
         c. 为 sync=true 字段的取值建立倒排索引 → 写入 Elasticsearch
      3. 处理指标信息：
         a. 保存指标定义及「指标-字段」关联到 Meta MySQL
         b. 为指标名/描述/别名生成 Embedding → 写入 Qdrant

    设计要点：
    - 该服务是「离线构建」逻辑，通常在应用启动前一次性执行，而非每次查询时执行
    - 每个私有方法（_xxx）对应一个存储引擎的一次写入，职责单一、顺序清晰
    """

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,          # 元数据库仓库（写表/字段/指标定义）
        dw_mysql_repository: DWMySQLRepository,              # 数据仓库仓库（读字段类型/取值）
        column_qdrant_repository: ColumnQdrantRepository,    # 字段向量库仓库（写字段向量）
        embedding_client: HuggingFaceEndpointEmbeddings,     # Embedding 客户端（文本→向量）
        value_es_repository: ValueESRepository,              # 取值全文检索仓库（写取值索引）
        metric_qdrant_repository: MetricQdrantRepository,    # 指标向量库仓库（写指标向量）
    ):
        """初始化构建服务，注入六大基础设施依赖

        说明：所有依赖均由调用方（脚本或 lifespan）装配后传入，
        本类不负责创建连接，只负责编排构建流程（依赖注入原则）。
        """
        self.meta_mysql_repository = meta_mysql_repository      # 元数据库仓库
        self.dw_mysql_repository = dw_mysql_repository          # 数据仓库仓库
        self.column_qdrant_repository = column_qdrant_repository  # 字段向量库仓库
        self.embedding_client = embedding_client                # Embedding 客户端
        self.value_es_repository = value_es_repository          # 取值全文检索仓库
        self.metric_qdrant_repository = metric_qdrant_repository  # 指标向量库仓库

    async def _save_tables_to_meta_db(self, meta_config: MetaConfig) -> list[ColumnInfo]:
        """【步骤2a】将配置中的表/字段定义同步到元数据库（Meta MySQL）

        参数：
        - meta_config: 已加载的元知识配置（含表/字段声明式定义）

        返回：
        - list[ColumnInfo]  所有字段的 ColumnInfo 实体列表，
                            供后续 _save_column_info_to_qdrant（向量化）和
                            _save_value_info_to_es（取值索引）复用，避免重复查询

        详细流程：
        1. 遍历 meta_config.tables 中的每张表定义
        2. 对每张表：
           a. 构造 TableInfo 实体（表 ID = 表名）
           b. 从数据仓库查询该表所有字段的实际数据类型（get_column_types）
           c. 对表中每个字段：查询前 10 个去重示例值（get_column_values），
              结合配置中的 role/description/alias 构造 ColumnInfo 实体
        3. 在同一个事务中批量写入表定义与字段定义

        关键设计：
        - 字段 ID 采用「{表名}.{字段名}」格式（如 "fact_order.order_amount"），
          作为全局唯一标识贯穿整个系统（Qdrant payload、ES 索引、召回去重）
        - 字段类型（type）从 DW 实时查询，而非配置声明——保证与真实库结构一致
        - 示例值（examples）取前 10 条去重值，用于后续给 LLM 展示数据分布
        """
        # 累积待写入的表定义列表
        table_infos: list[TableInfo] = []
        # 累积待写入的字段定义列表（同时作为返回值供后续步骤复用）
        column_infos: list[ColumnInfo] = []

        # 遍历配置文件中的每张表
        for table in meta_config.tables:
            # ---- 构造 TableInfo 实体（表 ID 直接复用表名）----
            table_info = TableInfo(
                id=table.name,            # 表 ID（= 表名，作为全局唯一标识）
                name=table.name,          # 表名
                role=table.role,          # 表角色：fact（事实表）/ dim（维度表）
                description=table.description,  # 表业务描述
            )
            table_infos.append(table_info)  # 加入待写入列表

            # 从数据仓库查询该表所有字段的「实际数据类型」
            # 返回 dict：{字段名: 字段类型}，如 {"order_amount": "decimal(10,2)", ...}
            column_types: dict[str, str] = await self.dw_mysql_repository.get_column_types(table.name)

            # 遍历该表配置中的每个字段
            for column in table.columns:
                # 查询该字段的前 10 个去重示例值（用于给 LLM 展示数据分布）
                column_values: list = await self.dw_mysql_repository.get_column_values(
                    table.name, column.name, 10
                )

                # ---- 构造 ColumnInfo 实体（融合配置声明 + DW 实际元数据）----
                column_info = ColumnInfo(
                    id=f"{table.name}.{column.name}",   # 字段全局 ID：{表名}.{字段名}
                    name=column.name,                    # 字段名（来自配置）
                    type=column_types[column.name],      # 字段类型（来自 DW 实时查询）
                    role=column.role,                    # 字段角色（来自配置）
                    examples=column_values,              # 示例值（来自 DW 实时查询）
                    description=column.description,      # 字段描述（来自配置）
                    alias=column.alias,                  # 字段别名（来自配置）
                    table_id=table.name,                 # 所属表 ID（= 表名）
                )
                column_infos.append(column_info)  # 加入待写入列表

        # ---- 在同一事务中批量写入表与字段定义 ----
        # session.begin() 显式开启事务：save_table_infos 与 save_column_infos
        # 要么全部成功、要么全部回滚，保证元数据库的一致性
        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_table_infos(table_infos)    # 批量写表定义
            await self.meta_mysql_repository.save_column_infos(column_infos)  # 批量写字段定义

        # 返回字段列表，供后续向量化与 ES 索引步骤复用
        return column_infos

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfo]):
        """【步骤2b】将字段信息向量化并写入 Qdrant 向量库

        参数：
        - column_infos: 上一步（_save_tables_to_meta_db）返回的字段实体列表

        向量化策略（多维度覆盖，见 docs/architecture-08-embedding-strategy 图8）：
        每个字段会生成 N 条向量记录（N = 1 名称 + 1 描述 + len(别名)）：
          1. 字段名（如 "order_amount"）        → 覆盖「精确字段名匹配」场景
          2. 字段描述（如 "订单金额"）            → 覆盖「语义描述匹配」场景
          3. 每个字段别名（如 "销售额"、"成交额"）→ 覆盖「同义词/别名匹配」场景

        设计意图：
        - 用户查询可能是"卖了多少钱"（匹配描述）、"成交额排行"（匹配别名）、
          或 "order_amount 统计"（匹配字段名），多维度覆盖可显著提高召回率
        - 每条向量记录都携带「完整的 ColumnInfo payload」，命中任意一条即可
          还原出完整字段信息（id/name/type/role/examples/description/alias）

        Embedding 批处理：
        - 分批（batch_size=10）调用 aembed_documents，避免单次请求文本过多
          导致超时或内存溢出
        """
        # 确保 Qdrant 中字段 Collection 存在（不存在则自动创建）
        await self.column_qdrant_repository.ensure_collection()

        # ---- 构造待向量化的 points 列表 ----
        # 每个 point 结构：{id: uuid, embedding_text: 待向量化文本, payload: 完整字段实体}
        points: list[dict] = []
        for column_info in column_infos:
            # 向量维度1：字段名（精确匹配）
            points.append(
                {
                    "id": uuid.uuid4(),                     # 每条向量记录独立 UUID（随机，保证唯一）
                    "embedding_text": column_info.name,     # 待向量化的文本 = 字段名
                    "payload": column_info,                 # 附带的完整字段实体（命中后还原）
                }
            )
            # 向量维度2：字段描述（语义匹配）
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": column_info.description,  # 待向量化的文本 = 字段描述
                    "payload": column_info,
                }
            )
            # 向量维度3~N：每个字段别名各一条（别名覆盖）
            for alia in column_info.alias:
                points.append(
                    {"id": uuid.uuid4(), "embedding_text": alia, "payload": column_info}
                )

        # ---- 分批生成 Embedding 向量 ----
        embedding_texts = [point["embedding_text"] for point in points]  # 提取所有待向量化文本
        embedding_batch_size = 10                       # 每批处理 10 条文本
        embeddings = []                                 # 累积全部向量
        for i in range(0, len(embedding_texts), embedding_batch_size):
            # 切出当前批次的文本切片
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            # 调用 Embedding 服务批量转向量（一次请求处理一批）
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            embeddings.extend(batch_embeddings)         # 追加到总向量列表

        # ---- 提取写入所需的 id 与 payload 列表 ----
        ids = [point["id"] for point in points]          # 每条记录的唯一 ID
        payloads = [point["payload"] for point in points]  # 每条记录的完整字段实体

        # 批量写入 Qdrant（内部按 batch_size=20 分片上传）
        await self.column_qdrant_repository.upsert(ids, embeddings, payloads)

    async def _save_value_info_to_es(
        self, meta_config: MetaConfig, column_infos: list[ColumnInfo]
    ):
        """【步骤2c】将字段取值写入 Elasticsearch 建立全文索引

        参数：
        - meta_config:   元知识配置（用于读取每个字段的 sync 开关）
        - column_infos:  字段实体列表（用于定位哪些字段需要同步取值）

        索引策略：
        - 只对配置中 sync=true 的字段建立取值索引（非所有字段）
        - 每个字段最多取 100000 个去重值（distinct）
        - ES 端使用 IK 分词器（ik_max_word）做中文分词

        设计意图：
        - 字段取值（如"北京"、"在职"、"已转正"）是离散的枚举值或实体名，
          适合用 ES 倒排索引做精确匹配，而非 Qdrant 向量语义匹配
        - 通过 sync 开关精细化控制：只有「低基数的枚举字段」才值得建全文索引，
          高基数字段（如金额、时间戳）取值无穷多，建索引无意义
        """
        # 确保 ES 中取值索引存在（不存在则自动创建，含 mapping 定义）
        await self.value_es_repository.ensure_index()

        # ---- 构建「字段ID → 是否同步」映射表 ----
        # 遍历配置中所有表/字段，记录每个字段的 sync 开关，
        # 键为「{表名}.{字段名}」，与 ColumnInfo.id 保持一致
        column2sync: dict[str, bool] = {}
        for table in meta_config.tables:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = column.sync

        # ---- 构造 ValueInfo 列表（仅对 sync=true 的字段）----
        value_infos: list[ValueInfo] = []
        for column_info in column_infos:
            # 查该字段是否需要同步取值（sync 开关）
            sync = column2sync[column_info.id]
            if sync:
                # 从数据仓库查询该字段的去重取值（最多 100000 条）
                table_name = column_info.table_id          # 所属表名
                column_name = column_info.name             # 字段名
                values = await self.dw_mysql_repository.get_column_values(
                    table_name, column_name, 100000
                )

                # 将每个取值包装为 ValueInfo 实体
                # 取值 ID 格式：「{字段ID}.{取值}」（如 "dim_intern.转正状态.已转正"），
                # 保证同字段下不同取值 ID 唯一，且可反推所属字段
                current_value_infos = [
                    ValueInfo(
                        id=f"{column_info.id}.{value}",     # 取值唯一 ID
                        value=value,                        # 具体取值内容
                        column_id=column_info.id,           # 所属字段 ID
                    )
                    for value in values
                ]
                value_infos.extend(current_value_infos)     # 合并到总列表

        # 批量写入 Elasticsearch（内部按 batch_size=20 分片，走 bulk API）
        await self.value_es_repository.index(value_infos)

    async def _save_metrics_to_meta_db(self, meta_config: MetaConfig) -> list[MetricInfo]:
        """【步骤3a】将指标定义保存到元数据库（Meta MySQL）

        参数：
        - meta_config: 元知识配置（含指标声明式定义）

        返回：
        - list[MetricInfo]  所有指标的 MetricInfo 实体列表，
                            供后续 _save_metric_info_to_qdrant 向量化复用

        说明：
        - 除了保存指标本身（MetricInfo），还保存「指标↔字段」关联关系（ColumnMetric）
        - 关联关系用于后续 SQL 生成：召回某指标后，通过 relevant_columns 自动
          带出其计算所需的全部字段，保证 SQL 可正确生成（见 merge 节点步骤1）
        """
        # 累积待写入的指标定义列表
        metric_infos: list[MetricInfo] = []
        # 累积待写入的「指标-字段」关联列表
        column_metrics: list[ColumnMetric] = []

        for metric in meta_config.metrics:
            # ---- 构造 MetricInfo 实体（指标 ID = 指标名）----
            metric_info = MetricInfo(
                id=metric.name,                          # 指标 ID（= 指标名，全局唯一）
                name=metric.name,                        # 指标名
                description=metric.description,          # 指标描述（用于语义召回）
                relevant_columns=metric.relevant_columns,  # 指标依赖的字段 ID 列表
                alias=metric.alias,                      # 指标别名（用于别名覆盖召回）
            )
            metric_infos.append(metric_info)  # 加入待写入列表

            # ---- 为指标的每个依赖字段构造「指标-字段」关联 ----
            for relevant_column in metric.relevant_columns:
                column_metric = ColumnMetric(
                    column_id=relevant_column,  # 依赖的字段 ID
                    metric_id=metric.name,      # 指标 ID（= 指标名）
                )
                column_metrics.append(column_metric)  # 加入待写入列表

        # ---- 在同一事务中批量写入指标定义与关联关系 ----
        async with self.meta_mysql_repository.session.begin():
            await self.meta_mysql_repository.save_metric_infos(metric_infos)      # 批量写指标定义
            await self.meta_mysql_repository.save_column_metrics(column_metrics)  # 批量写指标-字段关联

        return metric_infos

    async def _save_metric_info_to_qdrant(self, metric_infos: list[MetricInfo]):
        """【步骤3b】将指标信息向量化并写入 Qdrant 向量库

        参数：
        - metric_infos: 上一步（_save_metrics_to_meta_db）返回的指标实体列表

        向量化策略（多维度覆盖，同字段向量化策略）：
        每个指标生成 N 条向量记录（N = 1 名称 + 1 描述 + len(别名)）：
          1. 指标名（如 "转正率"）              → 覆盖「精确指标名匹配」
          2. 指标描述（如 "实习生转正通过率"）    → 覆盖「语义描述匹配」
          3. 每个指标别名（如 "转正比例"）        → 覆盖「同义词/别名匹配」

        每条向量记录携带完整 MetricInfo payload，命中任意一条即可还原完整指标定义
        """
        # 确保 Qdrant 中指标 Collection 存在（不存在则自动创建）
        await self.metric_qdrant_repository.ensure_collection()

        # ---- 构造待向量化的 points 列表 ----
        points: list[dict] = []
        for metric_info in metric_infos:
            # 向量维度1：指标名（精确匹配）
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": metric_info.name,
                    "payload": metric_info,
                }
            )
            # 向量维度2：指标描述（语义匹配）
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": metric_info.description,
                    "payload": metric_info,
                }
            )
            # 向量维度3~N：每个指标别名各一条（别名覆盖）
            for alia in metric_info.alias:
                points.append(
                    {"id": uuid.uuid4(), "embedding_text": alia, "payload": metric_info}
                )

        # ---- 分批生成 Embedding 向量 ----
        ids = [point["id"] for point in points]                      # 记录 ID 列表
        embeddings = []                                              # 累积向量
        embedding_texts = [point["embedding_text"] for point in points]  # 待向量化文本
        embedding_batch_size = 10                                    # 批大小
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            embeddings.extend(batch_embeddings)
        payloads = [point["payload"] for point in points]            # payload 列表

        # 批量写入 Qdrant
        await self.metric_qdrant_repository.upsert(ids, embeddings, payloads)

    async def build(self, config_path: Path):
        """构建元知识库的主入口（编排整个构建流程）

        参数：
        - config_path: 元知识配置文件（meta_config.yaml）的路径

        完整构建流程（对应 docs/architecture-06 图6）：
          1. 加载配置文件 → 反序列化为 MetaConfig 对象
          2. 处理表信息（若配置了 tables）：
             a. _save_tables_to_meta_db   —— 保存表/字段定义到 Meta MySQL
             b. _save_column_info_to_qdrant —— 字段向量化写入 Qdrant
             c. _save_value_info_to_es    —— 字段取值建立 ES 全文索引
          3. 处理指标信息（若配置了 metrics）：
             a. _save_metrics_to_meta_db  —— 保存指标定义及关联到 Meta MySQL
             b. _save_metric_info_to_qdrant —— 指标向量化写入 Qdrant

        说明：
        - 表与指标的处理相互独立（分别用 if 判断），允许只配置其中一种
        - 每个子步骤之间通过返回值传递中间结果（column_infos / metric_infos），
          避免重复查询 DW，提高构建效率
        """
        # ========== 步骤1：加载并反序列化配置文件 ==========
        # OmegaConf.load 读取 yaml 原始内容
        context = OmegaConf.load(config_path)
        # OmegaConf.structured 依据 MetaConfig 的 dataclass 生成 schema，
        # 用于校验 yaml 字段完整性、类型匹配，并为缺失字段填充默认值
        schema = OmegaConf.structured(MetaConfig)
        # 合并 schema 与 yaml 内容，再反序列化为 MetaConfig 实例
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))
        logger.info("加载配置文件")

        # ========== 步骤2：处理表信息 ==========
        if meta_config.tables:
            # 2.1 保存表/字段定义到 Meta MySQL（返回字段列表供后续复用）
            column_infos = await self._save_tables_to_meta_db(meta_config)
            logger.info("保存表信息到meta数据库")

            # 2.2 字段向量化写入 Qdrant（复用上一步的 column_infos）
            await self._save_column_info_to_qdrant(column_infos)
            logger.info("为字段信息建立向量索引")

            # 2.3 字段取值建立 ES 全文索引（复用 column_infos + 配置的 sync 开关）
            await self._save_value_info_to_es(meta_config, column_infos)
            logger.info("为字段取值建立全文索引")

        # ========== 步骤3：处理指标信息 ==========
        if meta_config.metrics:
            # 3.1 保存指标定义及关联到 Meta MySQL（返回指标列表供后续复用）
            metric_infos = await self._save_metrics_to_meta_db(meta_config)
            logger.info("保存指标信息到meta数据库")

            # 3.2 指标向量化写入 Qdrant（复用上一步的 metric_infos）
            await self._save_metric_info_to_qdrant(metric_infos)
            logger.info("为指标信息建立向量索引")

        logger.info("元数据知识库构建完成")
