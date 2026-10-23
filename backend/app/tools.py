"""
工具定义模块
定义AI Agent可以调用的各种工具
使用LangChain的@tool装饰器定义工具

当前版本：
- 天气：Open-Meteo真实API
- 订单查询：MySQL
- 订单取消：MySQL
- 其他业务工具：暂时使用模拟数据
"""

import ast
import json
import logging
import math
import os
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Optional, Union

import requests
import mysql.connector
from dotenv import load_dotenv
from langchain_core.tools import tool


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted request metadata supplied by the application, never by the LLM."""

    conversation_id: str
    user_message: str
    request_id: str
    user_id: str


_TOOL_EXECUTION_CONTEXT: ContextVar[Optional[ToolExecutionContext]] = ContextVar(
    "tool_execution_context",
    default=None,
)


@contextmanager
def tool_execution_context(
    conversation_id: str,
    user_message: str,
    request_id: Optional[str] = None,
    *,
    user_id: str,
) -> Iterator[ToolExecutionContext]:
    """Bind server-controlled metadata for tools executed during one Agent turn."""

    context = ToolExecutionContext(
        conversation_id=conversation_id,
        user_message=user_message,
        request_id=request_id or str(uuid.uuid4()),
        user_id=user_id,
    )
    token = _TOOL_EXECUTION_CONTEXT.set(context)
    try:
        yield context
    finally:
        _TOOL_EXECUTION_CONTEXT.reset(token)


def _current_tool_context() -> ToolExecutionContext:
    context = _TOOL_EXECUTION_CONTEXT.get()
    if context is None:
        raise RuntimeError("Tool execution context is unavailable.")
    return context


_CONFIRMATION_PATTERNS = {
    "create_order": re.compile(
        r"^(确认购买|确定购买|确认下单|确定下单|是的[，, ]?确认(?:购买|下单))$"
    ),
    "cancel_order": re.compile(r"^(确认取消|确定取消|是的[，, ]?确认取消)$"),
    "create_ticket": re.compile(
        r"^(确认创建工单|确定创建工单|是的[，, ]?确认创建工单)$"
    ),
}


def _has_explicit_confirmation(message: str, action_type: str) -> bool:
    """Accept only a full-turn confirmation for the requested action type."""

    pattern = _CONFIRMATION_PATTERNS.get(action_type)
    if pattern is None:
        return False
    normalized = re.sub(r"[。.!！?？\s]+$", "", message.strip())
    return bool(pattern.fullmatch(normalized))


# ============================================
# 加载环境变量
# ============================================

load_dotenv()


# ============================================
# 计算器安全限制
# ============================================

MAX_EXPRESSION_LENGTH = 200
MAX_EXPRESSION_NODES = 64
MAX_ABSOLUTE_VALUE = 10**100


class UnsafeExpressionError(ValueError):
    """Raised when an expression is outside the calculator's small grammar."""


def safe_calculate(expression: str) -> Union[int, float]:
    """
    Evaluate a deliberately small arithmetic grammar
    without executing arbitrary Python code.
    """

    if not isinstance(expression, str) or not expression.strip():
        raise UnsafeExpressionError("Expression must not be empty.")

    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise UnsafeExpressionError("Expression is too long.")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(
            "Expression syntax is invalid."
        ) from exc

    nodes_seen = 0

    def is_supported_number(value: Union[int, float]) -> bool:
        return (
            abs(value) <= MAX_ABSOLUTE_VALUE
            and (
                isinstance(value, int)
                or math.isfinite(value)
            )
        )

    def evaluate(node: ast.AST) -> Union[int, float]:
        nonlocal nodes_seen

        nodes_seen += 1

        if nodes_seen > MAX_EXPRESSION_NODES:
            raise UnsafeExpressionError(
                "Expression is too complex."
            )

        # Expression
        if isinstance(node, ast.Expression):
            return evaluate(node.body)

        # 数字
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            if not is_supported_number(node.value):
                raise UnsafeExpressionError(
                    "Number is outside the supported range."
                )

            return node.value

        # 一元运算 + / -
        if isinstance(node, ast.UnaryOp) and isinstance(
            node.op,
            (ast.UAdd, ast.USub)
        ):
            value = evaluate(node.operand)

            if isinstance(node.op, ast.UAdd):
                return value

            return -value

        # 二元运算
        if isinstance(node, ast.BinOp) and isinstance(
            node.op,
            (
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
            )
        ):
            left = evaluate(node.left)
            right = evaluate(node.right)

            if isinstance(node.op, ast.Add):
                result = left + right

            elif isinstance(node.op, ast.Sub):
                result = left - right

            elif isinstance(node.op, ast.Mult):
                result = left * right

            else:
                result = left / right

            if not is_supported_number(result):
                raise UnsafeExpressionError(
                    "Result is outside the supported range."
                )

            return result

        raise UnsafeExpressionError(
            "Only +, -, *, /, parentheses, "
            "and numeric literals are supported."
        )

    return evaluate(tree)


# ============================================
# MySQL数据库配置
# ============================================

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ai_agent")


def _get_mysql_connection():
    """
    创建MySQL数据库连接。

    数据库配置从.env读取：

    MYSQL_HOST=localhost
    MYSQL_PORT=3306
    MYSQL_USER=root
    MYSQL_PASSWORD=你的密码
    MYSQL_DATABASE=ai_agent
    """

    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        connection_timeout=5,
    )


def check_database_readiness() -> bool:
    """Return whether the configured business database accepts a simple query."""

    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        return cursor.fetchone() == (1,)
    except Exception:
        logger.warning("Database readiness check failed", exc_info=True)
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================
# 知识库数据（暂时模拟）
# ============================================

KNOWLEDGE_BASE = {
    "退款政策": (
        "我们的退款政策如下：\n"
        "1. 订单完成后7天内可申请全额退款\n"
        "2. 7-30天内可申请部分退款（扣除20%手续费）\n"
        "3. 30天后不支持退款\n"
        "4. 退款将在1-3个工作日内原路返回"
    ),

    "配送时间": (
        "配送时间说明：\n"
        "1. 标准配送：3-5个工作日\n"
        "2. 加急配送：1-2个工作日（额外收取10元）\n"
        "3. 当日达：仅限部分城市，需在中午12点前下单\n"
        "4. 偏远地区可能延长1-2天"
    ),

    "会员权益": (
        "会员权益说明：\n"
        "1. 普通会员：享受9.9折优惠\n"
        "2. 银卡会员：享受9折优惠，免运费\n"
        "3. 金卡会员：享受8.5折优惠，免运费，优先客服\n"
        "4. 钻石会员：享受8折优惠，免运费，优先客服，专属礼品"
    ),

    "如何注册": (
        "注册流程：\n"
        "1. 点击首页右上角「注册」按钮\n"
        "2. 输入手机号并获取验证码\n"
        "3. 设置登录密码\n"
        "4. 填写基本信息完成注册\n"
        "注册成功后即可享受新人礼包！"
    ),

    "支付方式": (
        "支持的支付方式：\n"
        "1. 支付宝\n"
        "2. 微信支付\n"
        "3. 银行卡支付\n"
        "4. 花呗/信用支付\n"
        "5. 货到付款（部分商品支持）"
    ),

    "优惠券使用": (
        "优惠券使用规则：\n"
        "1. 每笔订单限用一张优惠券\n"
        "2. 优惠券不可叠加使用\n"
        "3. 部分商品不可使用优惠券\n"
        "4. 优惠券需在有效期内使用"
    ),

    "积分规则": (
        "积分规则：\n"
        "1. 每消费1元累积1积分\n"
        "2. 100积分可抵扣1元\n"
        "3. 积分不可提现\n"
        "4. 积分有效期为获得后12个月"
    ),

    "客服时间": (
        "客服工作时间：\n"
        "1. 在线客服：9:00-22:00\n"
        "2. 电话客服：9:00-21:00\n"
        "3. 周末及节假日照常服务\n"
        "4. 紧急问题可拨打24小时热线"
    ),
}


# ============================================
# FAQ数据
# ============================================

FAQ_DATA = {
    "如何修改密码": (
        "修改密码步骤：\n"
        "1. 登录后进入「个人中心」\n"
        "2. 点击「账号安全」\n"
        "3. 选择「修改密码」\n"
        "4. 输入原密码和新密码\n"
        "5. 点击确认完成修改"
    ),

    "如何更换手机号": (
        "更换手机号步骤：\n"
        "1. 进入「个人中心」-「账号安全」\n"
        "2. 点击「更换手机号」\n"
        "3. 输入新的手机号并验证\n"
        "4. 完成更换"
    ),

    "如何联系人工客服": (
        "联系人工客服的方式：\n"
        "1. 点击右下角在线客服图标\n"
        "2. 输入「人工」转人工服务\n"
        "3. 或拨打客服热线：400-888-8888\n"
        "4. 服务时间：9:00-21:00"
    ),

    "订单如何取消": (
        "取消订单说明：\n"
        "1. 未发货订单可自助取消\n"
        "2. 进入「我的订单」-「待发货」\n"
        "3. 点击「取消订单」并选择原因\n"
        "4. 已发货订单需等收货后申请退款"
    ),

    "商品坏了怎么办": (
        "商品问题处理：\n"
        "1. 签收7天内可申请退换货\n"
        "2. 进入订单详情点击「申请售后」\n"
        "3. 上传商品照片并描述问题\n"
        "4. 审核通过后免费退货或换货"
    ),
}

# ============================================
# 商品目录
# ============================================

PRODUCT_CATALOG = {
    "无线蓝牙耳机": {
        "price": 299.00,
        "description": "高品质无线蓝牙耳机",
    },
    "智能手环": {
        "price": 199.00,
        "description": "智能健康运动手环",
    },
    "移动电源": {
        "price": 129.00,
        "description": "便携式大容量移动电源",
    },
}


@tool
def get_product_catalog() -> str:
    """返回服务端当前可售商品与价格；商品和金额必须以此结果为准。"""

    products = "\n".join(
        f"• {name}：¥{float(info['price']):.2f}（{info['description']}）"
        for name, info in PRODUCT_CATALOG.items()
    )
    return f"🛍️ 当前可售商品\n\n{products}"

# ============================================
# 天气相关内部函数
# ============================================

def _get_weather_emoji(condition: str) -> str:
    """根据天气状况返回对应的表情符号。"""

    weather_emojis = {
        "晴": "☀️",
        "阴": "☁️",
        "雨": "🌧️",
        "雪": "❄️",
        "雾": "🌫️",
        "雷": "⛈️",
        "多云": "⛅",
    }

    return weather_emojis.get(condition, "🌤️")


def _weather_code_to_text(weather_code: int) -> str:
    """将Open-Meteo天气代码转换成中文天气描述。"""

    weather_code_map = {
        0: "晴",
        1: "大致晴朗",
        2: "多云",
        3: "阴",
        45: "雾",
        48: "雾",
        51: "小雨",
        53: "小雨",
        55: "小雨",
        56: "冻雨",
        57: "冻雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "阵雨",
        81: "阵雨",
        82: "强阵雨",
        85: "阵雪",
        86: "强阵雪",
        95: "雷雨",
        96: "雷雨伴冰雹",
        99: "雷雨伴冰雹",
    }

    return weather_code_map.get(
        weather_code,
        "未知天气"
    )


def _get_city_coordinates(city: str) -> dict:
    """使用Open-Meteo地理编码API查询城市经纬度。"""

    url = "https://geocoding-api.open-meteo.com/v1/search"

    params = {
        "name": city,
        "count": 1,
        "language": "zh",
        "format": "json",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("results"):
        raise ValueError(f"未找到城市：{city}")

    location = data["results"][0]

    return {
        "name": location.get("name", city),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "country": location.get("country", ""),
        "admin1": location.get("admin1", ""),
    }


def _get_real_weather(city: str) -> dict:
    """从Open-Meteo获取真实天气数据。"""

    location = _get_city_coordinates(city)

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "weather_code,"
            "wind_speed_10m"
        ),
        "timezone": "auto",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    current = data.get("current")

    if not current:
        raise ValueError(
            "天气 API 没有返回当前天气数据"
        )

    weather_code = current.get("weather_code")

    condition = _weather_code_to_text(
        weather_code
    )

    return {
        "city": location["name"],
        "condition": condition,
        "temperature": current.get("temperature_2m"),
        "humidity": current.get(
            "relative_humidity_2m"
        ),
        "wind": current.get(
            "wind_speed_10m"
        ),
        "update_time": current.get("time"),
    }


# ============================================
# 天气工具
# ============================================

@tool
def get_weather(city: str) -> str:
    """
    获取指定城市的实时天气信息。

    Args:
        city: 城市名称，例如 "北京"、"上海"、"广州"

    Returns:
        str: 从天气API获取的实时天气信息
    """

    try:
        weather = _get_real_weather(city)

        emoji = _get_weather_emoji(
            weather["condition"]
        )

        return f"""📍 {weather['city']}实时天气

🌡️ 温度: {weather['temperature']}°C
{emoji} 天气: {weather['condition']}
💧 湿度: {weather['humidity']}%
🌬️ 风速: {weather['wind']} km/h

🕐 更新时间: {weather['update_time']}"""

    except requests.exceptions.Timeout:
        return "⚠️ 天气服务请求超时，请稍后再试。"

    except requests.exceptions.RequestException:
        logger.exception("Weather provider request failed")
        return "⚠️ 天气服务暂时不可用，请稍后再试。"

    except Exception:
        logger.exception("Weather lookup failed")
        return "⚠️ 查询天气失败，请检查城市名称是否正确。"


# ============================================
# 计算工具
# ============================================

@tool
def calculate(expression: str) -> str:
    """
    执行数学计算。

    Args:
        expression: 数学表达式，例如 "2+3*4"

    Returns:
        str: 计算结果
    """

    try:
        allowed_chars = set(
            "0123456789+-*/.() "
        )

        if not all(
            c in allowed_chars
            for c in expression
        ):
            return (
                "⚠️ 表达式包含非法字符，"
                "仅支持数字和基本运算符"
            )

        result = safe_calculate(expression)

        if isinstance(result, float):
            if result.is_integer():
                result = int(result)
            else:
                result = round(result, 8)

        return (
            f"📐 计算结果\n\n"
            f"expression = {expression}\n\n"
            f"✅ 结果: {result}"
        )

    except ZeroDivisionError:
        return "⚠️ 错误：除数不能为零"

    except Exception:
        logger.exception("Calculator rejected an expression")
        return "⚠️ 计算错误，请检查表达式是否正确。"


# ============================================
# 当前时间工具
# ============================================

@tool
def get_current_time() -> str:
    """
    获取当前时间。

    Returns:
        str: 当前日期和时间
    """

    now = datetime.now()

    weekday_names = [
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    ]

    weekday = weekday_names[
        now.weekday()
    ]

    return f"""🕐 当前时间

📅 日期: {now.strftime('%Y年%m月%d日')}
⏰ 时间: {now.strftime('%H:%M:%S')}
📆 {weekday}

祝您有美好的一天！"""


# ============================================
# 知识库搜索工具
# ============================================

@tool
def search_knowledge(query: str) -> str:
    """
    搜索知识库中的相关信息。

    Args:
        query: 搜索关键词，例如 "退款政策"

    Returns:
        str: 搜索到的相关信息
    """

    query_lower = query.lower()

    results = []

    for key, value in KNOWLEDGE_BASE.items():

        if (
            query_lower in key.lower()
            or query_lower in value.lower()
        ):
            results.append(
                f"📖 {key}\n{value}"
            )

    if results:
        return "\n\n---\n\n".join(
            results[:3]
        )

    return (
        f"抱歉，暂未找到与「{query}」"
        "相关的知识库内容。\n"
        "您可以尝试以下关键词：\n"
        "• 退款政策\n"
        "• 配送时间\n"
        "• 会员权益\n"
        "• 支付方式\n"
        "• 优惠券使用"
    )

# ============================================
# 创建订单工具
# ============================================

# 用户身份由登录会话注入 ContextVar，不作为工具参数暴露给模型，
# 防止提示词诱导模型以他人身份操作（越权）。


def _pending_action_ttl_minutes() -> int:
    try:
        return max(1, min(60, int(os.getenv("PENDING_ACTION_TTL_MINUTES", "10"))))
    except ValueError:
        return 10


def _create_pending_action(action_type: str, payload: dict) -> str:
    """Persist a one-time action that must be confirmed in a later user turn."""

    context = _current_tool_context()
    action_token = str(uuid.uuid4())
    now = datetime.now()
    expires_at = now + timedelta(minutes=_pending_action_ttl_minutes())
    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            UPDATE pending_actions
            SET status = 'superseded'
            WHERE conversation_id = %s
              AND user_id = %s
              AND action_type = %s
              AND status = 'pending'
            """,
            (context.conversation_id, context.user_id, action_type),
        )
        cursor.execute(
            """
            INSERT INTO pending_actions (
                action_token,
                conversation_id,
                user_id,
                action_type,
                payload_json,
                status,
                created_request_id,
                created_at,
                expires_at,
                result_ref
            ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, NULL)
            """,
            (
                action_token,
                context.conversation_id,
                context.user_id,
                action_type,
                json.dumps(payload, ensure_ascii=False),
                context.request_id,
                now,
                expires_at,
            ),
        )
        connection.commit()
        return action_token
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to create pending %s action", action_type)
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def _decode_action_payload(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    raise ValueError("Pending action payload has an unsupported format.")


@tool
def prepare_order(product_name: str, quantity: int = 1) -> str:
    """Prepare an order preview. This never creates an order or charges the user."""

    product_name = product_name.strip()
    if quantity < 1 or quantity > 99:
        return "❌ 购买数量必须在1到99之间。"

    product = PRODUCT_CATALOG.get(product_name)
    if not product:
        available_products = "\n".join(
            f"• {name}：¥{info['price']:.2f}"
            for name, info in PRODUCT_CATALOG.items()
        )
        return f"❌ 暂未找到商品：{product_name}\n\n当前支持的商品：\n{available_products}"

    unit_price = float(product["price"])
    total_amount = unit_price * quantity
    try:
        action_token = _create_pending_action(
            "create_order",
            {
                "product_name": product_name,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_amount": total_amount,
            },
        )
    except Exception:
        return "⚠️ 暂时无法生成订单确认单，请稍后重试。"

    return f"""🧾 订单待确认

📦 商品：{product_name}
🔢 数量：{quantity}
💰 单价：¥{unit_price:.2f}
💵 总价：¥{total_amount:.2f}
⏳ 有效期：{_pending_action_ttl_minutes()} 分钟
🔐 确认编号：{action_token}

本步骤尚未创建订单。请让用户在下一条消息中单独回复“确认购买”后，再调用 create_order。"""


@tool
def create_order() -> str:
    """Commit the latest prepared order after a separate, explicit user confirmation."""

    context = _current_tool_context()
    if not _has_explicit_confirmation(context.user_message, "create_order"):
        return "❌ 未检测到独立且明确的确认消息，订单没有创建。请让用户单独回复“确认购买”。"

    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT action_token, payload_json, status, created_request_id,
                   expires_at, result_ref
            FROM pending_actions
            WHERE conversation_id = %s
              AND user_id = %s
              AND action_type = 'create_order'
              AND status IN ('pending', 'completed')
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (context.conversation_id, context.user_id),
        )
        action = cursor.fetchone()
        if not action:
            connection.rollback()
            return "❌ 没有待确认订单，请先告诉我商品和数量。"
        if action["status"] == "completed":
            connection.rollback()
            return f"✅ 该确认操作已经完成，订单号：{action['result_ref']}。无需重复下单。"
        if action["created_request_id"] == context.request_id:
            connection.rollback()
            return "❌ 预览和确认不能在同一轮完成。请让用户查看订单信息后，在下一条消息中确认。"
        if action["expires_at"] <= datetime.now():
            cursor.execute(
                "UPDATE pending_actions SET status = 'expired' WHERE action_token = %s",
                (action["action_token"],),
            )
            connection.commit()
            return "⌛ 订单确认已过期，请重新生成订单预览。"

        payload = _decode_action_payload(action["payload_json"])
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        cursor.execute(
            """
            INSERT INTO orders (
                order_id, user_id, product_name, quantity, amount, status,
                create_time, delivery_time, express_company, tracking_number,
                idempotency_key
            ) VALUES (%s, %s, %s, %s, %s, '处理中', %s, NULL, NULL, NULL, %s)
            """,
            (
                order_id,
                context.user_id,
                payload["product_name"],
                int(payload["quantity"]),
                float(payload["total_amount"]),
                datetime.now(),
                action["action_token"],
            ),
        )
        cursor.execute(
            """
            UPDATE pending_actions
            SET status = 'completed', result_ref = %s
            WHERE action_token = %s AND status = 'pending'
            """,
            (order_id, action["action_token"]),
        )
        connection.commit()
        return f"""✅ 订单创建成功

🆔 订单号：{order_id}
📦 商品：{payload['product_name']}
🔢 数量：{int(payload['quantity'])}
💰 单价：¥{float(payload['unit_price']):.2f}
💵 订单金额：¥{float(payload['total_amount']):.2f}
📋 当前状态：处理中"""
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to commit prepared order")
        return "⚠️ 创建订单失败，服务暂时不可用。确认操作可安全重试。"
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# ============================================
# 订单查询工具
# ============================================

@tool
def get_order_status(order_id: str) -> str:
    """
    查询MySQL中的订单状态。

    Args:
        order_id: 订单号，例如 "ORD2026001"

    Returns:
        str: 订单详细信息
    """

    context = _current_tool_context()
    order_id = order_id.strip().upper()

    connection = None
    cursor = None

    try:
        # ----------------------------------------
        # 1. 连接数据库
        # ----------------------------------------

        connection = _get_mysql_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        # ----------------------------------------
        # 2. 查询订单
        # ----------------------------------------

        sql = """
        SELECT
            order_id,
            user_id,
            product_name,
            quantity,
            amount,
            status,
            create_time,
            delivery_time,
            express_company,
            tracking_number
        FROM orders
        WHERE order_id = %s
          AND user_id = %s
        """

        cursor.execute(
            sql,
            (order_id, context.user_id)
        )

        order = cursor.fetchone()

        # ----------------------------------------
        # 3. 订单不存在
        # ----------------------------------------

        if not order:

            return f"""🔍 未找到订单 {order_id}

可能的原因：
• 订单号输入错误
• 订单尚未生成
• 订单已超过保留期限

💡 提示：请检查订单号是否正确，格式如：ORD2026001"""

        # ----------------------------------------
        # 4. 状态对应表情
        # ----------------------------------------

        status_emoji = {
            "已发货": "📦",
            "处理中": "⏳",
            "运输中": "🚚",
            "派送中": "🏃",
            "已完成": "✅",
            "已取消": "❌",
        }

        emoji = status_emoji.get(
            order["status"],
            "📋"
        )

        # ----------------------------------------
        # 5. 基础订单信息
        # ----------------------------------------

        result = f"""{emoji} 订单信息 - {order['status']}

🆔 订单号: {order['order_id']}
🛍️ 商品: {order['product_name']}
🔢 数量: {order['quantity']}
💰 金额: ¥{float(order['amount']):.2f}
📅 下单时间: {order['create_time']}
"""

        # ----------------------------------------
        # 6. 如果存在物流信息，就显示物流信息
        # ----------------------------------------

        if order["tracking_number"]:

            result += f"""
🚚 快递公司: {order['express_company']}
📮 运单号: {order['tracking_number']}
"""

            if order["delivery_time"]:

                result += f"""📍 送达时间: {order['delivery_time']}
"""

            result += """
💡 该订单存在物流单号，如需查询详细物流轨迹，可以继续查询物流信息。
"""

        # ----------------------------------------
        # 7. 处理中订单
        # ----------------------------------------

        elif order["status"] == "处理中":

            result += """
⏳ 当前状态：订单正在处理中，暂未发货
📦 当前暂无物流单号
"""

        # ----------------------------------------
        # 8. 已取消订单
        # ----------------------------------------

        elif order["status"] == "已取消":

            result += """
❌ 当前订单已经取消
"""

        # ----------------------------------------
        # 9. 没有物流单号的其他订单
        # ----------------------------------------

        else:

            result += """
📦 当前订单暂未提供物流单号
"""

        return result

    except mysql.connector.Error:
        logger.exception("Order lookup failed")
        return "⚠️ 查询订单失败，数据库服务暂时不可用。"

    except Exception:
        logger.exception("Unexpected order lookup failure")
        return "⚠️ 查询订单时发生异常，请稍后重试。"

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()

# ============================================
# 物流轨迹查询工具
# ============================================

@tool
def get_logistics_tracking(tracking_number: str) -> str:
    """
    查询指定物流单号的物流轨迹。

    Args:
        tracking_number: 物流运单号，例如 "SF1234567890"

    Returns:
        str: 物流轨迹信息
    """

    context = _current_tool_context()
    tracking_number = tracking_number.strip().upper()

    connection = None
    cursor = None

    try:
        # ----------------------------------------
        # 1. 连接MySQL
        # ----------------------------------------

        connection = _get_mysql_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        # ----------------------------------------
        # 2. 查询该物流单号对应的订单
        # ----------------------------------------

        order_sql = """
        SELECT
            order_id,
            product_name,
            status,
            express_company
        FROM orders
        WHERE tracking_number = %s
          AND user_id = %s
        """

        cursor.execute(
            order_sql,
            (tracking_number, context.user_id)
        )

        order = cursor.fetchone()

        # Missing and non-owned tracking numbers intentionally share one
        # response so the endpoint cannot be used to enumerate other users'
        # shipments.
        if not order:
            return f"""❌ 未找到可访问的物流信息

📮 物流单号：{tracking_number}

请检查物流单号是否正确。"""

        # ----------------------------------------
        # 3. 查询物流轨迹
        # ----------------------------------------

        tracking_sql = """
        SELECT
            tracking_time,
            location,
            status,
            description
        FROM logistics_tracking
        WHERE tracking_number = %s
        ORDER BY tracking_time ASC
        """

        cursor.execute(
            tracking_sql,
            (tracking_number,)
        )

        tracking_records = cursor.fetchall()

        # ----------------------------------------
        # 4. 物流单号不存在
        # ----------------------------------------

        if not order and not tracking_records:

            return f"""❌ 未找到物流信息

📮 物流单号：{tracking_number}

请检查物流单号是否正确。
例如：SF1234567890"""

        # ----------------------------------------
        # 5. 有订单，但暂时没有物流轨迹
        # ----------------------------------------

        if not tracking_records:

            if order:

                return f"""📦 暂无物流轨迹

🆔 订单号：{order['order_id']}
📦 商品：{order['product_name']}
🚚 快递公司：{order['express_company']}
📮 物流单号：{tracking_number}
📋 订单状态：{order['status']}

目前暂未查询到该物流单号的轨迹信息，请稍后再试。"""

            return f"""📦 暂无物流轨迹

📮 物流单号：{tracking_number}

目前暂未查询到该物流单号的物流轨迹。"""

        # ----------------------------------------
        # 6. 组织物流轨迹结果
        # ----------------------------------------

        result = "🚚 物流轨迹\n\n"

        # 如果能够找到对应订单，则同时显示订单信息
        if order:

            result += f"""🆔 订单号：{order['order_id']}
📦 商品：{order['product_name']}
🚚 快递公司：{order['express_company']}
📮 物流单号：{tracking_number}
📋 订单状态：{order['status']}

━━━━━━━━━━━━━━━━━━
"""

        else:

            result += f"""📮 物流单号：{tracking_number}

━━━━━━━━━━━━━━━━━━
"""

        # ----------------------------------------
        # 7. 按时间顺序输出物流轨迹
        # ----------------------------------------

        for index, record in enumerate(
            tracking_records
        ):

            # 最后一条记录标记为最新位置
            if index == len(tracking_records) - 1:
                marker = "📍"
            else:
                marker = "○"

            result += f"""
{marker} {record['tracking_time']}
   📍 {record['location']}
   📋 {record['status']}
   💬 {record['description']}
"""

            # 非最后一条记录增加连接符
            if index != len(tracking_records) - 1:

                result += """   │
   ↓
"""

        # ----------------------------------------
        # 8. 显示最新物流状态
        # ----------------------------------------

        latest = tracking_records[-1]

        result += f"""
━━━━━━━━━━━━━━━━━━

📍 最新状态：{latest['status']}
📍 最新位置：{latest['location']}
🕐 更新时间：{latest['tracking_time']}
"""

        return result

    except mysql.connector.Error:
        logger.exception("Logistics lookup failed")
        return "⚠️ 查询物流失败，数据库服务暂时不可用。"

    except Exception:
        logger.exception("Unexpected logistics lookup failure")
        return "⚠️ 查询物流时发生异常，请稍后重试。"

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()

# ============================================
# 取消订单工具
# ============================================

@tool
def prepare_cancel_order(order_id: str) -> str:
    """Prepare a cancellation preview without changing the order."""

    context = _current_tool_context()
    order_id = order_id.strip().upper()
    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT order_id, product_name, quantity, amount, status
            FROM orders
            WHERE order_id = %s AND user_id = %s
            """,
            (order_id, context.user_id),
        )
        order = cursor.fetchone()
        if not order:
            return "❌ 未找到可访问的订单，请检查订单号。"
        if order["status"] == "已取消":
            return f"❌ 订单 {order_id} 已取消，无需重复操作。"
        if order["status"] != "处理中":
            return f"❌ 订单 {order_id} 当前状态为“{order['status']}”，不能直接取消。"
    except Exception:
        logger.exception("Failed to prepare order cancellation")
        return "⚠️ 暂时无法生成取消确认单，请稍后重试。"
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    try:
        action_token = _create_pending_action(
            "cancel_order",
            {
                "order_id": order["order_id"],
                "product_name": order["product_name"],
                "quantity": int(order["quantity"]),
                "amount": float(order["amount"]),
            },
        )
    except Exception:
        return "⚠️ 暂时无法生成取消确认单，请稍后重试。"

    return f"""⚠️ 订单取消待确认

🆔 订单号：{order['order_id']}
📦 商品：{order['product_name']}
🔢 数量：{int(order['quantity'])}
💰 金额：¥{float(order['amount']):.2f}
🔐 确认编号：{action_token}

本步骤尚未取消订单。请让用户在下一条消息中单独回复“确认取消”后，再调用 cancel_order。"""


@tool
def cancel_order() -> str:
    """Cancel the latest prepared order after a separate explicit confirmation."""

    context = _current_tool_context()
    if not _has_explicit_confirmation(context.user_message, "cancel_order"):
        return "❌ 未检测到独立且明确的确认消息，订单没有取消。请让用户单独回复“确认取消”。"

    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT action_token, payload_json, status, created_request_id,
                   expires_at, result_ref
            FROM pending_actions
            WHERE conversation_id = %s
              AND user_id = %s
              AND action_type = 'cancel_order'
              AND status IN ('pending', 'completed')
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (context.conversation_id, context.user_id),
        )
        action = cursor.fetchone()
        if not action:
            connection.rollback()
            return "❌ 没有待确认的取消操作，请先提供订单号。"
        if action["status"] == "completed":
            connection.rollback()
            return f"✅ 订单 {action['result_ref']} 已经取消，无需重复操作。"
        if action["created_request_id"] == context.request_id:
            connection.rollback()
            return "❌ 取消预览和确认不能在同一轮完成，请让用户在下一条消息中确认。"
        if action["expires_at"] <= datetime.now():
            cursor.execute(
                "UPDATE pending_actions SET status = 'expired' WHERE action_token = %s",
                (action["action_token"],),
            )
            connection.commit()
            return "⌛ 取消确认已过期，请重新发起取消操作。"

        payload = _decode_action_payload(action["payload_json"])
        cursor.execute(
            """
            UPDATE orders
            SET status = '已取消'
            WHERE order_id = %s AND user_id = %s AND status = '处理中'
            """,
            (payload["order_id"], context.user_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return "⚠️ 订单状态已经变化，取消未执行，请重新查询。"
        cursor.execute(
            """
            UPDATE pending_actions
            SET status = 'completed', result_ref = %s
            WHERE action_token = %s AND status = 'pending'
            """,
            (payload["order_id"], action["action_token"]),
        )
        connection.commit()
        return f"""✅ 订单取消成功

🆔 订单号：{payload['order_id']}
📦 商品：{payload['product_name']}
💰 金额：¥{float(payload['amount']):.2f}
📋 当前状态：已取消"""
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to commit prepared cancellation")
        return "⚠️ 取消订单失败，服务暂时不可用。确认操作可安全重试。"
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================
# FAQ工具
# ============================================

@tool
def FAQ_answer(question: str) -> str:
    """
    回答常见问题。

    Args:
        question: 问题内容

    Returns:
        str: 问题的解答
    """

    question_lower = question.lower()

    results = []

    # 精确匹配
    for key, value in FAQ_DATA.items():

        if question_lower in key.lower():

            results.append(
                f"❓ {key}\n\n{value}"
            )

    # 模糊匹配
    if not results:

        for key, value in FAQ_DATA.items():

            keywords = (
                key
                .replace("如何", "")
                .replace("？", "")
            )

            if any(
                kw in question_lower
                for kw in keywords.split("、")
            ):
                results.append(
                    f"❓ {key}\n\n{value}"
                )

    if results:

        return "\n\n---\n\n".join(
            results[:2]
        )

    suggestions = "\n".join(
        f"• {q}"
        for q in FAQ_DATA.keys()
    )

    return f"""🤔 抱歉，暂未找到「{question}」的明确解答。

您可能想了解：
{suggestions}

或者输入「人工」转接人工客服为您解答。"""


# ============================================
# 用户信息工具
# ============================================

@tool
def get_user_info() -> str:
    """获取当前登录用户的基本信息，不接受模型提供的用户ID。"""

    context = _current_tool_context()
    connection = _get_mysql_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT user_id, username, display_name, created_at FROM users WHERE user_id = %s",
            (context.user_id,),
        )
        user = cursor.fetchone()
        if not user:
            return "未找到当前用户信息。"
        return f"""👤 用户信息

🆔 用户ID: {user['user_id']}
📛 用户名: {user['username']}
🙂 昵称: {user['display_name']}
🕐 注册时间: {user['created_at']}"""
    finally:
        cursor.close()
        connection.close()


# ============================================
# 创建工单工具
# ============================================

@tool
def prepare_ticket(
    title: str,
    description: str,
    priority: str = "normal",
) -> str:
    """生成客服工单预览；本步骤不会创建工单。"""

    title = title.strip()
    description = description.strip()
    priority = priority.strip().lower()
    if not title or len(title) > 255:
        return "❌ 工单标题不能为空且不能超过255个字符。"
    if not description or len(description) > 2000:
        return "❌ 工单描述不能为空且不能超过2000个字符。"
    if priority not in {"low", "normal", "high", "urgent"}:
        return "❌ 工单优先级仅支持 low、normal、high、urgent。"

    try:
        action_token = _create_pending_action(
            "create_ticket",
            {"title": title, "description": description, "priority": priority},
        )
    except Exception:
        return "⚠️ 暂时无法生成工单确认单，请稍后重试。"

    priority_labels = {
        "low": "🟢 低",
        "normal": "🟡 中",
        "high": "🟠 高",
        "urgent": "🔴 紧急",
    }

    return f"""🧾 工单待确认

📌 标题: {title}
📝 描述: {description}
⚡ 优先级: {priority_labels[priority]}
🔐 确认编号: {action_token}

本步骤尚未创建工单。请让用户在下一条消息中单独回复“确认创建工单”后，再调用 create_ticket。"""


@tool
def create_ticket() -> str:
    """在用户另起一轮明确确认后，持久化最新的工单预览。"""

    context = _current_tool_context()
    if not _has_explicit_confirmation(context.user_message, "create_ticket"):
        return "❌ 未检测到独立且明确的确认消息，工单没有创建。"

    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()
        cursor.execute(
            """
            SELECT action_token, payload_json, status, created_request_id,
                   expires_at, result_ref
            FROM pending_actions
            WHERE conversation_id = %s
              AND user_id = %s
              AND action_type = 'create_ticket'
              AND status IN ('pending', 'completed')
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (context.conversation_id, context.user_id),
        )
        action = cursor.fetchone()
        if not action:
            connection.rollback()
            return "❌ 没有待确认工单，请先描述需要处理的问题。"
        if action["status"] == "completed":
            connection.rollback()
            return f"✅ 工单已经创建，工单号：{action['result_ref']}。"
        if action["created_request_id"] == context.request_id:
            connection.rollback()
            return "❌ 工单预览和确认不能在同一轮完成。"
        if action["expires_at"] <= datetime.now():
            cursor.execute(
                "UPDATE pending_actions SET status = 'expired' WHERE action_token = %s",
                (action["action_token"],),
            )
            connection.commit()
            return "⌛ 工单确认已过期，请重新生成工单预览。"

        payload = _decode_action_payload(action["payload_json"])
        ticket_id = f"TKT{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        cursor.execute(
            """
            INSERT INTO tickets (
                ticket_id, user_id, conversation_id, title, description,
                priority, status, create_time, update_time
            ) VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s)
            """,
            (
                ticket_id,
                context.user_id,
                context.conversation_id,
                payload["title"],
                payload["description"],
                payload["priority"],
                datetime.now(),
                datetime.now(),
            ),
        )
        cursor.execute(
            """
            UPDATE pending_actions
            SET status = 'completed', result_ref = %s
            WHERE action_token = %s AND status = 'pending'
            """,
            (ticket_id, action["action_token"]),
        )
        connection.commit()
        return f"""✅ 工单创建成功

🆔 工单号: {ticket_id}
📌 标题: {payload['title']}
⚡ 优先级: {payload['priority']}
📋 状态: open

📌 提示：
• 您可以随时输入「查询工单 {ticket_id}」查看进度
• 工作人员会尽快处理"""
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to create support ticket")
        return "⚠️ 创建工单失败，服务暂时不可用。确认操作可安全重试。"
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@tool
def get_ticket(ticket_id: str) -> str:
    """查询当前演示用户的客服工单。"""

    context = _current_tool_context()
    ticket_id = ticket_id.strip().upper()
    connection = None
    cursor = None
    try:
        connection = _get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ticket_id, title, description, priority, status,
                   create_time, update_time
            FROM tickets
            WHERE ticket_id = %s AND user_id = %s
            """,
            (ticket_id, context.user_id),
        )
        ticket = cursor.fetchone()
        if not ticket:
            return "❌ 未找到可访问的工单，请检查工单号。"
        return f"""🎫 工单信息

🆔 工单号: {ticket['ticket_id']}
📌 标题: {ticket['title']}
📝 描述: {ticket['description']}
⚡ 优先级: {ticket['priority']}
📋 状态: {ticket['status']}
🕐 创建时间: {ticket['create_time']}
🕐 更新时间: {ticket['update_time']}"""
    except Exception:
        logger.exception("Ticket lookup failed")
        return "⚠️ 查询工单失败，服务暂时不可用。"
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================
# 工具列表
# ============================================

TOOLS = [
    get_weather,
    calculate,
    get_current_time,
    search_knowledge,
    get_product_catalog,

    # 订单相关
    get_order_status,
    get_logistics_tracking,
    prepare_order,
    create_order,
    prepare_cancel_order,
    cancel_order,
    
    # 其他客服功能
    FAQ_answer,
    get_user_info,
    prepare_ticket,
    create_ticket,
    get_ticket,
]


def get_all_tools() -> list:
    """
    获取所有可用的工具。

    Returns:
        list: 工具列表
    """

    return TOOLS
