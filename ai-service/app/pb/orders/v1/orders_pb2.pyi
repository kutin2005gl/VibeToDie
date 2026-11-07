from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GetOrderRequest(_message.Message):
    __slots__ = ("order_id",)
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    def __init__(self, order_id: _Optional[str] = ...) -> None: ...

class Order(_message.Message):
    __slots__ = ("order_id", "customer_name", "product_id", "product_name", "quantity", "unit_price", "discount", "paid_amount", "payment_method", "installment_months", "order_date", "delivered_date", "status", "store", "customer_email")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    CUSTOMER_NAME_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_NAME_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    UNIT_PRICE_FIELD_NUMBER: _ClassVar[int]
    DISCOUNT_FIELD_NUMBER: _ClassVar[int]
    PAID_AMOUNT_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_METHOD_FIELD_NUMBER: _ClassVar[int]
    INSTALLMENT_MONTHS_FIELD_NUMBER: _ClassVar[int]
    ORDER_DATE_FIELD_NUMBER: _ClassVar[int]
    DELIVERED_DATE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STORE_FIELD_NUMBER: _ClassVar[int]
    CUSTOMER_EMAIL_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    customer_name: str
    product_id: str
    product_name: str
    quantity: int
    unit_price: int
    discount: int
    paid_amount: int
    payment_method: str
    installment_months: int
    order_date: str
    delivered_date: str
    status: str
    store: str
    customer_email: str
    def __init__(self, order_id: _Optional[str] = ..., customer_name: _Optional[str] = ..., product_id: _Optional[str] = ..., product_name: _Optional[str] = ..., quantity: _Optional[int] = ..., unit_price: _Optional[int] = ..., discount: _Optional[int] = ..., paid_amount: _Optional[int] = ..., payment_method: _Optional[str] = ..., installment_months: _Optional[int] = ..., order_date: _Optional[str] = ..., delivered_date: _Optional[str] = ..., status: _Optional[str] = ..., store: _Optional[str] = ..., customer_email: _Optional[str] = ...) -> None: ...

class GetProductRequest(_message.Message):
    __slots__ = ("product_id",)
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    def __init__(self, product_id: _Optional[str] = ...) -> None: ...

class Product(_message.Message):
    __slots__ = ("product_id", "name", "price", "warranty_months", "stock_total")
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PRICE_FIELD_NUMBER: _ClassVar[int]
    WARRANTY_MONTHS_FIELD_NUMBER: _ClassVar[int]
    STOCK_TOTAL_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    name: str
    price: int
    warranty_months: int
    stock_total: int
    def __init__(self, product_id: _Optional[str] = ..., name: _Optional[str] = ..., price: _Optional[int] = ..., warranty_months: _Optional[int] = ..., stock_total: _Optional[int] = ...) -> None: ...

class SearchProductsRequest(_message.Message):
    __slots__ = ("query", "limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    limit: int
    def __init__(self, query: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ProductSummary(_message.Message):
    __slots__ = ("product_id", "name", "price")
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PRICE_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    name: str
    price: int
    def __init__(self, product_id: _Optional[str] = ..., name: _Optional[str] = ..., price: _Optional[int] = ...) -> None: ...

class SearchProductsResponse(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[ProductSummary]
    def __init__(self, items: _Optional[_Iterable[_Union[ProductSummary, _Mapping]]] = ...) -> None: ...

class GetStockRequest(_message.Message):
    __slots__ = ("product_id",)
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    def __init__(self, product_id: _Optional[str] = ...) -> None: ...

class Stock(_message.Message):
    __slots__ = ("product_id", "stock_total", "by_store")
    class ByStoreEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    STOCK_TOTAL_FIELD_NUMBER: _ClassVar[int]
    BY_STORE_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    stock_total: int
    by_store: _containers.ScalarMap[str, int]
    def __init__(self, product_id: _Optional[str] = ..., stock_total: _Optional[int] = ..., by_store: _Optional[_Mapping[str, int]] = ...) -> None: ...
