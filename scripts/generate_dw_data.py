"""扩充数据仓库（dw）的订单数据

用法（项目根目录）：
  python -m scripts.generate_dw_data --dry-run          # 只打印将要写入的规模，不落库
  python -m scripts.generate_dw_data --reset            # 重建：清空 5 张表后写入完整数据集（默认 5 万单）
  python -m scripts.generate_dw_data --reset --orders 200000

为什么要这个脚本：
  dw.sql 里的种子数据只有 2025 年 Q1、115 笔订单、20 个客户、15 个商品、6 个省份，
  导致「TopN 排名」「各大区对比」「同比环比」这类问句没有区分度（Top3 是在 15 个商品里排）。
  本脚本按同一套业务口径把数据放大，**不改表结构、不改取值域**，
  因此元数据知识库、prompt、eval/dataset.jsonl 都无需改写。

与 dw.sql 的关系：
  - dw.sql 负责建表 + 写入原始种子数据（115 单，保留不动）
  - 本脚本在种子数据之上追加生成数据；--reset 会先清空再重建「种子 + 生成」的完整集
  - 生成的 ID 与种子数据不冲突（见 _legacy_* 的划分规则）

生成数据的真实性约束（不是随机撒点）：
  - 时间：2024-01-01 ~ 2025-12-31，含周末效应、逐年增长、618/双11/双12 脉冲
  - 客户：会员等级呈金字塔（青铜 > 白银 > 黄金 > 铂金），下单频次服从长尾（少数客户贡献多数订单）
  - 商品：单价按品类分档（手机数码 5k~10k，休闲零食 5~99），销量服从长尾
  - 订单：order_amount = 数量 × 单价 × 折扣，保证与 order_quantity 自洽

固定随机种子，同样的参数每次生成同一份数据，便于复现评测结果。
"""

import argparse
import asyncio
import random
from datetime import date, timedelta

from sqlalchemy import text

from server.clients.mysql_client_manager import dw_mysql_client_manager

# 固定种子：换种子等于换一份数据集，评测结果不可比
SEED = 20260901

# 生成的 ID 与种子数据的划分边界（种子：R001-R006 / C001-C020 / P001-P015）
LEGACY_REGION_MAX = 6
LEGACY_CUSTOMER_MAX = 20
LEGACY_PRODUCT_MAX = 15
# 种子 order_id 形如 ORD20250101001（"ORD" + 8 位日期 + 3 位序号 = 14 字符）；
# 生成数据的序号用 4 位（ORD202501011000，15 字符），据此把两者区分开。
# 这个边界必须精确：若写成 <= 15，重复执行 --reset 时会把上次生成的订单也当成种子读进来。
LEGACY_ORDER_ID_LEN = 14

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)

# -----------------------------------------------------------------------------
# 维度取值域：在原种子基础上扩充，原值全部保留
# -----------------------------------------------------------------------------
# 省份 → 大区。前 6 条与 dw.sql 的 R001-R006 完全一致（含各自的大区归属）
PROVINCES = [
    ("广东省", "华南"), ("浙江省", "华东"), ("四川省", "西南"),
    ("北京市", "华北"), ("上海市", "华东"), ("湖北省", "华中"),
    ("江苏省", "华东"), ("山东省", "华东"), ("福建省", "华东"),
    ("安徽省", "华东"), ("江西省", "华东"), ("广西壮族自治区", "华南"),
    ("海南省", "华南"), ("湖南省", "华中"), ("河南省", "华中"),
    ("天津市", "华北"), ("河北省", "华北"), ("山西省", "华北"),
    ("内蒙古自治区", "华北"), ("重庆市", "西南"), ("贵州省", "西南"),
    ("云南省", "西南"), ("西藏自治区", "西南"), ("陕西省", "西北"),
    ("甘肃省", "西北"), ("青海省", "西北"), ("宁夏回族自治区", "西北"),
    ("新疆维吾尔自治区", "西北"), ("辽宁省", "东北"), ("吉林省", "东北"),
    ("黑龙江省", "东北"),
]

# 省份下单权重：人口与经济体量近似，用于让「各省销售额」有真实的高低之分
PROVINCE_WEIGHT = {
    "广东省": 13.0, "江苏省": 9.5, "山东省": 8.5, "浙江省": 8.5, "河南省": 7.0,
    "四川省": 6.0, "湖北省": 4.8, "湖南省": 4.5, "河北省": 4.5, "福建省": 4.2,
    "上海市": 4.0, "北京市": 4.0, "安徽省": 3.6, "辽宁省": 2.8, "陕西省": 2.6,
    "江西省": 2.4, "重庆市": 2.4, "广西壮族自治区": 2.2, "云南省": 2.2,
    "山西省": 2.0, "贵州省": 1.6, "天津市": 1.5, "黑龙江省": 1.5, "吉林省": 1.2,
    "内蒙古自治区": 1.1, "新疆维吾尔自治区": 1.0, "甘肃省": 0.9,
    "海南省": 0.6, "宁夏回族自治区": 0.4, "青海省": 0.3, "西藏自治区": 0.2,
}

# 会员等级金字塔：越大越稀有
MEMBER_LEVELS = [("青铜", 46), ("白银", 30), ("黄金", 18), ("铂金", 6)]

SURNAMES = (
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛段雷侯龙史陶黎贺顾毛郝龚邵万钱严武戴莫孔向汤"
)

MALE_GIVEN = [
    "伟", "强", "磊", "军", "洋", "勇", "杰", "涛", "明", "超", "刚", "平", "辉",
    "健", "鹏", "飞", "斌", "宇", "浩", "峰", "建国", "建军", "晓东", "文博",
    "嘉伟", "子轩", "浩然", "俊杰", "志强", "海涛", "天宇", "一鸣", "振华",
]
FEMALE_GIVEN = [
    "芳", "娜", "敏", "静", "丽", "艳", "娟", "霞", "燕", "玲", "婷", "雪", "梅",
    "萍", "红", "英", "华", "慧", "美", "秀英", "淑珍", "婉婷", "思琪", "雅静",
    "梦瑶", "雨欣", "诗涵", "佳怡", "晓燕", "丽娜", "春梅", "静怡", "语彤",
]

# 品类 → (单价区间, [(品牌, 型号), ...])
#
# 品牌与型号成对定义、而不是分两个池子各自随机取：分开取会造出
# 「华为 iPhone 16 Pro」「美的 V15 吸尘器」这种错配，而这套数据的问句
# 大量围绕品牌展开（「华为品牌商品的销售数量」「鞋靴品类中耐克品牌的销售额」），
# 名称错配会直接污染演示与评测。原种子里的品牌全部保留，货架格局不变。
CATEGORY_SPEC = {
    "手机数码": (
        (499, 9999),
        [("苹果", "iPhone 16 Pro"), ("苹果", "iPhone 16"), ("苹果", "iPad Air"),
         ("三星", "Galaxy S25 Ultra"), ("三星", "Galaxy Z Flip6"),
         ("华为", "Mate 70 Pro"), ("华为", "Pura 70"), ("华为", "MatePad 11"),
         ("小米", "小米15 Pro"), ("小米", "红米 K80"), ("小米", "小米手环 9代"),
         ("OPPO", "Find X8"), ("OPPO", "Reno13"),
         ("vivo", "X100 Pro"), ("vivo", "iQOO 13"),
         ("荣耀", "Magic7 Pro"), ("荣耀", "荣耀手环 9"),
         ("一加", "一加 13"), ("亚马逊", "Kindle Paperwhite 电子书")],
    ),
    "家用电器": (
        (299, 5999),
        [("美的", "变频空调 1.5匹"), ("美的", "变频微波炉"), ("美的", "电饭煲 4L"),
         ("格力", "云锦空调 3匹"), ("格力", "空气循环扇"),
         ("海尔", "对开门冰箱 550L"), ("海尔", "滚筒洗衣机 10kg"),
         ("戴森", "V15 无线吸尘器"), ("戴森", "Supersonic 吹风机"),
         ("西门子", "洗碗机 13套"), ("西门子", "嵌入式烤箱"),
         ("松下", "空气净化器"), ("九阳", "破壁料理机"), ("九阳", "豆浆机"),
         ("Instant Pot", "多功能电压力锅"), ("小米", "扫地机器人"), ("小米", "智能空气炸锅")],
    ),
    "鞋靴": (
        (199, 1499),
        [("耐克", "Air Max 270 运动鞋"), ("耐克", "Air Force 1 板鞋"),
         ("耐克", "Zoom 缓震跑鞋"), ("阿迪达斯", "Ultraboost 跑鞋"),
         ("阿迪达斯", "Superstar 贝壳头"), ("安踏", "氢跑鞋 5代"),
         ("安踏", "高帮篮球鞋"), ("李宁", "䨻 轻质跑鞋"), ("李宁", "悟道 休闲鞋"),
         ("彪马", "复古板鞋"), ("彪马", "足球训练鞋"),
         ("新百伦", "574 复古慢跑鞋"), ("新百伦", "990 系列"),
         ("斯凯奇", "厚底老爹鞋"), ("斯凯奇", "一脚蹬健步鞋")],
    ),
    "服饰": (
        (89, 899),
        [("优衣库", "Heattech 保暖夹克"), ("优衣库", "纯棉圆领T恤"),
         ("优衣库", "摇粒绒外套"), ("李维斯", "501 牛仔裤"),
         ("李维斯", "牛仔夹克"), ("海澜之家", "休闲西装外套"),
         ("海澜之家", "羊毛针织衫"), ("太平鸟", "中长款羽绒服"),
         ("太平鸟", "短款棉服"), ("森马", "亚麻长袖衬衫"),
         ("森马", "工装长裤"), ("杰克琼斯", "纯色卫衣"),
         ("杰克琼斯", "修身休闲裤"), ("GAP", "经典连帽卫衣"), ("GAP", "条纹polo衫")],
    ),
    "食品饮料": (
        (15, 299),
        [("雀巢", "金牌速溶咖啡"), ("雀巢", "全脂奶粉 900g"),
         ("蒙牛", "纯牛奶 250ml*12"), ("蒙牛", "特仑苏 250ml*12"),
         ("伊利", "安慕希酸奶 205g*12"), ("伊利", "金典有机奶"),
         ("农夫山泉", "天然矿泉水 550ml*24"), ("农夫山泉", "东方树叶 500ml*15"),
         ("康师傅", "红烧牛肉面 五连包"), ("康师傅", "冰红茶 1L*12"),
         ("统一", "老坛酸菜面 五连包"), ("统一", "阿萨姆奶茶"),
         ("星巴克", "挂耳咖啡 10袋"), ("星巴克", "星冰乐 玻璃瓶装")],
    ),
    "休闲零食": (
        (5, 99),
        [("乐事", "原味薯片 150g"), ("乐事", "黄瓜味薯片 150g"),
         ("奥利奥", "巧克力夹心饼干"), ("奥利奥", "巧脆卷 分享装"),
         ("三只松鼠", "每日坚果 750g"), ("三只松鼠", "手撕面包 1kg"),
         ("良品铺子", "肉松饼 500g"), ("良品铺子", "混合果干 500g"),
         ("百草味", "果冻布丁 综合装"), ("百草味", "坚果炒货 礼盒装"),
         ("旺旺", "雪饼 大礼包"), ("旺旺", "旺仔牛奶 245ml*12")],
    ),
    "美妆个护": (
        (39, 899),
        [("兰蔻", "小黑瓶精华 30ml"), ("兰蔻", "清滢柔肤水 400ml"),
         ("雅诗兰黛", "小棕瓶精华 50ml"), ("雅诗兰黛", "DW 粉底液"),
         ("欧莱雅", "紫熨斗眼霜"), ("欧莱雅", "氨基酸洗面奶"),
         ("珀莱雅", "红宝石精华 30ml"), ("珀莱雅", "双抗面膜 30片"),
         ("完美日记", "丝绒哑光口红"), ("完美日记", "动物眼影盘"),
         ("花西子", "雕花口红"), ("花西子", "空气蜜粉"),
         ("资生堂", "防晒霜 SPF50+"), ("资生堂", "护发精油 100ml")],
    ),
    "家居家装": (
        (49, 2999),
        [("宜家", "北欧落地灯"), ("宜家", "实木餐桌 1.4m"),
         ("宜家", "布艺沙发 三人位"), ("全友", "乳胶床垫 1.8m"),
         ("全友", "四门收纳衣柜"), ("顾家", "真皮沙发 组合"),
         ("顾家", "岩板茶几"), ("林氏木业", "简约书桌 1.2m"),
         ("林氏木业", "床架 1.8m"), ("源氏木语", "实木斗柜"),
         ("源氏木语", "遮光窗帘 定制")],
    ),
    "运动户外": (
        (99, 1999),
        [("迪卡侬", "速干运动T恤"), ("迪卡侬", "加厚瑜伽垫"),
         ("迪卡侬", "家用跑步机"), ("哥伦比亚", "三合一冲锋衣"),
         ("哥伦比亚", "抓绒保暖内胆"), ("探路者", "户外帐篷 3-4人"),
         ("探路者", "碳纤维登山杖"), ("骆驼", "防风中长款冲锋衣"),
         ("骆驼", "徒步登山鞋"), ("凯乐石", "轻量羽绒服"),
         ("凯乐石", "攀岩安全带")],
    ),
    "母婴玩具": (
        (29, 899),
        [("好孩子", "轻便婴儿推车"), ("好孩子", "儿童安全座椅"),
         ("好孩子", "婴儿床 实木"), ("巴拉巴拉", "儿童羽绒服"),
         ("巴拉巴拉", "男童运动套装"), ("帮宝适", "婴儿纸尿裤 L码"),
         ("帮宝适", "拉拉裤 XL码"), ("乐高", "积木拼装玩具"),
         ("乐高", "城市系列 消防车"), ("费雪", "安抚毛绒玩具"),
         ("费雪", "儿童绘本套装")],
    ),
}

# 商品型号池取尽时用来区分同名商品的规格后缀
VARIANTS = ["标准版", "尊享版", "升级款", "套装"]

# 月份销售脉冲：618 / 双11 / 双12 / 年货节
MONTH_FACTOR = {
    1: 0.82, 2: 0.72, 3: 0.92, 4: 0.95, 5: 1.02, 6: 1.58,
    7: 0.98, 8: 1.00, 9: 1.05, 10: 1.12, 11: 2.10, 12: 1.42,
}

# 星期效应：周一=0 ... 周日=6
WEEKDAY_FACTOR = [0.92, 0.95, 0.97, 1.00, 1.12, 1.32, 1.28]

# 相对 2024-01 的逐月增长（电商自然增长 + 大促逐年加码）
GROWTH_PER_MONTH = 0.012


# =============================================================================
# 读取种子数据（保证可与 dw.sql 的原始数据共存、可对照）
# =============================================================================
async def load_legacy(session):
    """读取 dw 中属于种子范围的行；已在库的生成数据不会被当作种子"""
    regions = (await session.execute(text(
        "SELECT region_id, province, region_name, country FROM dim_region "
        f"WHERE CAST(SUBSTRING(region_id, 2) AS UNSIGNED) <= {LEGACY_REGION_MAX} "
        "ORDER BY region_id"
    ))).mappings().all()

    customers = (await session.execute(text(
        "SELECT customer_id, customer_name, gender, member_level FROM dim_customer "
        f"WHERE CAST(SUBSTRING(customer_id, 2) AS UNSIGNED) <= {LEGACY_CUSTOMER_MAX} "
        "ORDER BY customer_id"
    ))).mappings().all()

    products = (await session.execute(text(
        "SELECT product_id, product_name, category, brand FROM dim_product "
        f"WHERE CAST(SUBSTRING(product_id, 2) AS UNSIGNED) <= {LEGACY_PRODUCT_MAX} "
        "ORDER BY product_id"
    ))).mappings().all()

    orders = (await session.execute(text(
        "SELECT order_id, customer_id, product_id, date_id, region_id, "
        "order_quantity, order_amount FROM fact_order "
        f"WHERE CHAR_LENGTH(order_id) <= {LEGACY_ORDER_ID_LEN} ORDER BY order_id"
    ))).mappings().all()

    return list(regions), list(customers), list(products), list(orders)


# =============================================================================
# 维度生成
# =============================================================================
def build_regions(legacy_regions):
    """省份维度：种子 6 条原样保留，其余按 PROVINCES 补齐"""
    existing = {r["region_id"] for r in legacy_regions}
    existing_provinces = {r["province"] for r in legacy_regions}

    rows = [
        {"region_id": r["region_id"], "province": r["province"],
         "region_name": r["region_name"], "country": r["country"] or "中国"}
        for r in legacy_regions
    ]

    next_index = 1
    for province, region_name in PROVINCES:
        if province in existing_provinces:
            continue
        while f"R{next_index:03d}" in existing:
            next_index += 1
        rows.append({
            "region_id": f"R{next_index:03d}",
            "province": province,
            "region_name": region_name,
            "country": "中国",
        })
        next_index += 1

    return rows


def build_customers(legacy_customers, rng, target):
    """客户维度：种子 20 条保留，扩充到 target 个"""
    rows = [
        {"customer_id": c["customer_id"], "customer_name": c["customer_name"],
         "gender": c["gender"], "member_level": c["member_level"]}
        for c in legacy_customers
    ]

    levels = [level for level, _ in MEMBER_LEVELS]
    weights = [weight for _, weight in MEMBER_LEVELS]

    for index in range(len(rows) + 1, target + 1):
        gender = rng.choice(["男", "女"])
        given_pool = MALE_GIVEN if gender == "男" else FEMALE_GIVEN
        name = rng.choice(SURNAMES) + rng.choice(given_pool)
        rows.append({
            "customer_id": f"C{index:03d}",
            "customer_name": name,
            "gender": gender,
            "member_level": rng.choices(levels, weights=weights, k=1)[0],
        })

    return rows


def build_products(legacy_products, legacy_orders, rng, target):
    """商品维度：种子 15 条保留，扩充到 target 个

    返回 (商品行, 单价表)。dim_product 没有价格列，单价由脚本内部维护，
    仅用于计算 fact_order.order_amount，保证金额与数量自洽且符合品类价位。
    """
    rows = [
        {"product_id": p["product_id"], "product_name": p["product_name"],
         "category": p["category"], "brand": p["brand"]}
        for p in legacy_products
    ]
    price_of = {}

    # 种子商品的单价从它的既有订单反推（order_amount / order_quantity），
    # 比在品类区间里随机取值更贴合原数据——否则会出现「iPhone 15 Pro 卖 512 元」这种失真
    samples = {}
    for order in legacy_orders:
        quantity = order["order_quantity"] or 1
        samples.setdefault(order["product_id"], []).append(
            float(order["order_amount"]) / quantity)

    for item in rows:
        values = sorted(samples.get(item["product_id"], []))
        if values:
            price_of[item["product_id"]] = round(values[len(values) // 2], 2)
        else:
            # 种子订单里没出现过该商品，退回品类区间的中位价位
            low, high = CATEGORY_SPEC[item["category"]][0]
            price_of[item["product_id"]] = round(rng.uniform(low, high), 2)

    categories = list(CATEGORY_SPEC)
    used_names = {item["product_name"] for item in rows}

    for index in range(len(rows) + 1, target + 1):
        category = rng.choice(categories)
        (low, high), pairs = CATEGORY_SPEC[category]
        brand, model = rng.choice(pairs)
        name = f"{brand} {model}"

        # 池子被取尽时补一个规格后缀，保证商品名唯一。
        # 同名不同 ID 会让「销售额前5的商品」这类排名问句出现重复条目，很不像真实数据。
        if name in used_names:
            for variant in VARIANTS:
                if f"{name} {variant}" not in used_names:
                    name = f"{name} {variant}"
                    break
            else:
                # 规格后缀也被占满（品类型号池偏小），退到序号兜底，唯一性必须保证
                suffix = 2
                while f"{name} 第{suffix}批" in used_names:
                    suffix += 1
                name = f"{name} 第{suffix}批"
        used_names.add(name)

        product_id = f"P{index:03d}"
        rows.append({
            "product_id": product_id,
            "product_name": name,
            "category": category,
            "brand": brand,
        })
        price_of[product_id] = round(rng.uniform(low, high), 2)

    return rows, price_of


def build_dates():
    """时间维度：2024-01-01 ~ 2025-12-31，date_id 为 yyyyMMdd"""
    rows = []
    current = START_DATE
    while current <= END_DATE:
        rows.append({
            "date_id": int(current.strftime("%Y%m%d")),
            "year": current.year,
            "quarter": f"Q{(current.month - 1) // 3 + 1}",
            "month": current.month,
            "day": current.day,
        })
        current += timedelta(days=1)
    return rows


# =============================================================================
# 事实表生成
# =============================================================================
def _daily_factor(day: date) -> float:
    """某一天的相对订单热度：月份脉冲 × 星期效应 × 逐月增长"""
    months_since_start = (day.year - START_DATE.year) * 12 + (day.month - START_DATE.month)
    growth = 1.0 + GROWTH_PER_MONTH * months_since_start
    return MONTH_FACTOR[day.month] * WEEKDAY_FACTOR[day.weekday()] * growth


def build_orders(legacy_orders, rng, customers, products, price_of, regions, total_target):
    """订单事实表：种子 115 单保留，其余按时间/客户/商品的长尾分布生成"""
    rows = [
        {"order_id": o["order_id"], "customer_id": o["customer_id"],
         "product_id": o["product_id"], "date_id": o["date_id"],
         "region_id": o["region_id"], "order_quantity": o["order_quantity"],
         "order_amount": float(o["order_amount"])}
        for o in legacy_orders
    ]

    # 客户下单频次长尾：少数高活跃客户贡献大部分订单。
    # 指数取 0.45 而非更陡的值——0.72 会让头号客户两年下近 2000 单（每天 2.6 单），
    # 那是批发商的行为，不是零售客户。权重同样要打乱，否则种子客户永远霸榜。
    customer_ids = [c["customer_id"] for c in customers]
    customer_weights = [1.0 / (i ** 0.45) for i in range(1, len(customer_ids) + 1)]
    rng.shuffle(customer_weights)
    # 地区按省份体量加权；一个客户固定归属一个省份，保证「客户-地区」关系自洽
    province_pool = [r["province"] for r in regions]
    province_weights = [PROVINCE_WEIGHT.get(p, 0.5) for p in province_pool]
    region_of_province = {r["province"]: r["region_id"] for r in regions}
    # 商品销量长尾。权重必须打乱后再分配：
    # 若按表内顺序直接对齐，种子商品（P001-P015）会永远占据销量榜首，
    # 热度就成了"商品在 dw.sql 里的书写顺序"，而不是市场表现。
    product_ids = [p["product_id"] for p in products]
    product_weights = [1.0 / (i ** 0.55) for i in range(1, len(product_ids) + 1)]
    rng.shuffle(product_weights)

    # 为每个客户分配常住地区（同一客户的所有订单落在同一地区，符合真实业务）。
    # 种子客户在 dw.sql 里已经用既有订单固定了地区，必须沿用——
    # 否则同一个客户会横跨多个大区，"按客户数分组"和"按订单数分组"对不上。
    customer_region = {}
    for order in legacy_orders:
        customer_region.setdefault(order["customer_id"], order["region_id"])

    for customer_id, province in zip(customer_ids, rng.choices(
            province_pool, weights=province_weights, k=len(customer_ids))):
        customer_region.setdefault(customer_id, region_of_province[province])

    # 先生成每天的订单数，再归一化到目标总量
    days = []
    current = START_DATE
    while current <= END_DATE:
        days.append(current)
        current += timedelta(days=1)

    weights = [_daily_factor(d) for d in days]
    weight_sum = sum(weights)
    target_new = max(total_target - len(rows), 0)

    counts = []
    for weight in weights:
        expected = target_new * weight / weight_sum
        # 泊松近似：均值 expected 的抖动，避免每天订单数一模一样
        counts.append(max(0, int(rng.gauss(expected, expected ** 0.5))))

    # 生成过程中数量会在整数取整处产生偏差，按比例回补到最热的那天
    drift = target_new - sum(counts)
    if counts:
        counts[weights.index(max(weights))] += drift

    sequence = 1000  # 4 位序号，与种子的 3 位序号天然区分
    for day, count in zip(days, counts):
        date_id = int(day.strftime("%Y%m%d"))
        for _ in range(count):
            product_id = rng.choices(product_ids, weights=product_weights, k=1)[0]

            # 价格越高买得越少：高价商品 1~2 件，低价商品可成批采购
            price = price_of[product_id]
            if price >= 3000:
                quantity = rng.choices([1, 2], weights=[92, 8], k=1)[0]
            elif price >= 500:
                quantity = rng.choices([1, 2, 3], weights=[70, 22, 8], k=1)[0]
            elif price >= 100:
                quantity = rng.randint(1, 5)
            else:
                quantity = rng.randint(3, 30)

            discount = rng.uniform(0.82, 1.0)  # 大促期间折扣更深
            if MONTH_FACTOR[day.month] >= 1.4:
                discount = rng.uniform(0.70, 0.98)

            customer_id = rng.choices(customer_ids, weights=customer_weights, k=1)[0]

            rows.append({
                "order_id": f"ORD{date_id}{sequence:04d}",
                "customer_id": customer_id,
                "product_id": product_id,
                "date_id": date_id,
                # 地区必须跟随客户，不能独立抽样，否则同一订单的客户与地区对不上
                "region_id": customer_region[customer_id],
                "order_quantity": quantity,
                "order_amount": round(quantity * price * discount, 2),
            })
            sequence += 1

    return rows


# =============================================================================
# 落库
# =============================================================================
async def insert_rows(session, table: str, rows: list, columns: list, batch: int = 5000):
    """分批 executemany 写入，避免单条 SQL 过大"""
    if not rows:
        return
    placeholders = ", ".join(f":{c}" for c in columns)
    statement = text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})")
    for start in range(0, len(rows), batch):
        await session.execute(statement, rows[start:start + batch])


async def ensure_indexes(session):
    """给事实表外键补索引

    种子数据只有 115 行，全表扫描没有代价，所以 dw.sql 里没建索引；
    扩到几万行后 JOIN 会明显变慢，这里补上（幂等，已存在则跳过）。
    """
    wanted = [
        ("fact_order", "idx_fact_order_customer", "customer_id"),
        ("fact_order", "idx_fact_order_product", "product_id"),
        ("fact_order", "idx_fact_order_date", "date_id"),
        ("fact_order", "idx_fact_order_region", "region_id"),
    ]
    for table, index_name, column in wanted:
        exists = (await session.execute(text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
        ), {"t": table, "i": index_name})).scalar()
        if not exists:
            await session.execute(text(f"CREATE INDEX {index_name} ON {table} ({column})"))
            print(f"  已建索引 {index_name}")


async def main():
    parser = argparse.ArgumentParser(description="扩充数据仓库（dw）的维度与订单数据")
    parser.add_argument("--orders", type=int, default=50000, help="订单总数目标（默认 50000）")
    parser.add_argument("--customers", type=int, default=2000, help="客户总数目标（默认 2000）")
    parser.add_argument("--products", type=int, default=200, help="商品总数目标（默认 200）")
    parser.add_argument("--reset", action="store_true",
                        help="先清空 5 张表再写入「种子 + 生成」的完整数据集")
    parser.add_argument("--dry-run", action="store_true", help="只打印规模，不写库")
    args = parser.parse_args()

    rng = random.Random(SEED)

    dw_mysql_client_manager.init()
    try:
        async with dw_mysql_client_manager.session_factory() as session:
            legacy_regions, legacy_customers, legacy_products, legacy_orders = \
                await load_legacy(session)

            print(f"读到种子数据：地区 {len(legacy_regions)} / 客户 {len(legacy_customers)} / "
                  f"商品 {len(legacy_products)} / 订单 {len(legacy_orders)}")

            # 种子数据的规模是已知的（dw.sql：6 / 20 / 15 / 115）。
            # 若读出来远多于这个数，说明 ID 边界规则失效、把生成数据当成了种子——
            # 那样继续跑会重复累加，所以这里直接拦下来。
            expected = (LEGACY_REGION_MAX, LEGACY_CUSTOMER_MAX, LEGACY_PRODUCT_MAX)
            actual = (len(legacy_regions), len(legacy_customers), len(legacy_products))
            if any(a > e for a, e in zip(actual, expected)) or len(legacy_orders) > 200:
                raise SystemExit(
                    f"种子数据规模异常（期望不超过 {expected} 和 115 单，实际 {actual} 和 "
                    f"{len(legacy_orders)} 单）。ID 划分边界可能已失效，请先检查 dw 表内容。"
                )

            regions = build_regions(legacy_regions)
            customers = build_customers(legacy_customers, rng, args.customers)
            products, price_of = build_products(legacy_products, legacy_orders, rng, args.products)
            dates = build_dates()
            orders = build_orders(legacy_orders, rng, customers, products, price_of,
                                  regions, args.orders)

            print(f"生成完整数据集：地区 {len(regions)} / 客户 {len(customers)} / "
                  f"商品 {len(products)} / 日期 {len(dates)} / 订单 {len(orders)}")

            total_amount = sum(o["order_amount"] for o in orders)
            print(f"  订单总额 {total_amount:,.2f}，单均 {total_amount / len(orders):,.2f}")
            print(f"  时间范围 {dates[0]['date_id']} ~ {dates[-1]['date_id']}")

            if args.dry_run:
                print("dry-run：未写库")
                return

            if args.reset:
                # 外键无约束，直接清空 5 张表即可
                for table in ("fact_order", "dim_date", "dim_product", "dim_customer", "dim_region"):
                    await session.execute(text(f"DELETE FROM {table}"))
                # 完整数据集里已包含种子行，直接全量写回
                await insert_rows(session, "dim_region", regions,
                                  ["region_id", "province", "region_name", "country"])
                await insert_rows(session, "dim_customer", customers,
                                  ["customer_id", "customer_name", "gender", "member_level"])
                await insert_rows(session, "dim_product", products,
                                  ["product_id", "product_name", "category", "brand"])
                await insert_rows(session, "dim_date", dates,
                                  ["date_id", "year", "quarter", "month", "day"])
                await insert_rows(session, "fact_order", orders,
                                  ["order_id", "customer_id", "product_id", "date_id",
                                   "region_id", "order_quantity", "order_amount"])
            else:
                # 追加模式：只补种子里没有的部分
                await insert_rows(session, "dim_region", regions[len(legacy_regions):],
                                  ["region_id", "province", "region_name", "country"])
                await insert_rows(session, "dim_customer", customers[len(legacy_customers):],
                                  ["customer_id", "customer_name", "gender", "member_level"])
                await insert_rows(session, "dim_product", products[len(legacy_products):],
                                  ["product_id", "product_name", "category", "brand"])
                existing_dates = {row[0] for row in (await session.execute(
                    text("SELECT date_id FROM dim_date"))).fetchall()}
                await insert_rows(session, "dim_date",
                                  [d for d in dates if d["date_id"] not in existing_dates],
                                  ["date_id", "year", "quarter", "month", "day"])
                await insert_rows(session, "fact_order", orders[len(legacy_orders):],
                                  ["order_id", "customer_id", "product_id", "date_id",
                                   "region_id", "order_quantity", "order_amount"])

            await ensure_indexes(session)
            await session.commit()

            print("\n写入完成，当前表行数：")
            for table in ("dim_region", "dim_customer", "dim_product", "dim_date", "fact_order"):
                count = (await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
                print(f"  {table:14s} {count:>8,}")
    finally:
        await dw_mysql_client_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
