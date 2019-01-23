import functools
from sqlalchemy.sql import select, and_, func, between, distinct, text
from .util import str2hump
from .db_util import MysqlDB


class Transaction():
    def __init__(self, db: MysqlDB):
        self._db = db
        self._transaction = None
        self._connect = None

    async def __aenter__(self):
        self._connect = await self._db.engine().connect()
        self._transaction = await self._connect.begin()
        return self._connect

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await self._transaction.commit()
        except Exception as e:
            await self._transaction.rollback()
            raise e


def get_tx(db: MysqlDB):
    return Transaction(db)


class DaoMetaClass(type):
    """
        dao的元类 读取 db 和 table信息 生成
    """

    def __new__(cls, name, bases, attrs):
        """

        :param name:
        :param bases:
        :param attrs:
        :return:
        """
        if name == "BaseDao":
            return type.__new__(cls, name, bases, attrs)
        if attrs.get('__db__') is None:
            raise NotImplementedError("Should have __db__ value.")

        attrs['__tablename__'] = attrs.get('__tablename__') or str2hump(name[:-3]) + 's'
        return type.__new__(cls, name, bases, attrs)

    def reformatter(cls, data: dict):
        """
        将model数据转换成dao数据
        :param data:
        :return:
        """
        return data

    def formatter(cls, data: dict):
        """
        将dao数据转换成model数据
        :param data:
        :return:
        """
        return dict(data)

    async def query(cls, ctx: dict = None, query: dict = None, pager: dict = None, sorter: dict = None):
        """
        通用查询
        :param query:
        :param pager:
        :param sorter:
        :return:
        """
        await cls.__db__.connect()
        table = cls.__db__[cls.__tablename__]
        sql = select([table])
        if query:
            for k, values in query.items():
                if not values:
                    continue
                if k.startswith('_gt_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[4:]) > v)
                elif k.startswith('_gte_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[5:]) >= v)
                elif k.startswith('_lt_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[4:]) < v)
                elif k.startswith('_lte_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[5:]) <= v)
                elif k.startswith('_like_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[6:]).like(v))
                else:
                    sql = sql.where(getattr(table.c, k).in_(values))

        if pager is not None:
            per_page = pager.get('_per_page')
            page = pager.get('_page')
            if per_page:
                sql = sql.limit(per_page)
            if page:
                if per_page is None:
                    sql = sql.offset((page - 1) * 30).limit(30)
                else:
                    sql = sql.offset((page - 1) * per_page)
        if sorter is None:
            sorter = {}
        order_by = sorter.get('_order_by', 'id')
        desc = sorter.get('_desc', True)
        if desc:
            sql = sql.order_by(getattr(table.c, order_by, table.c.id).desc())
        else:
            sql = sql.order_by(getattr(table.c, order_by, table.c.id))
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        data = await res.fetchall()
        return list(map(cls.formatter, data))

    async def insert(cls, ctx: dict = None, data: dict = None):
        """
        通用插入
        :param tx:
        :param args:
        :return:
        """
        table = cls.__db__[cls.tablename]
        sql = table.insert().value(**data)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res

    async def count(cls, query: dict = None):
        """
        计数
        :param query:
        :return:
        """
        table = cls.__db__[cls.__tablename__]
        sql = select([func.count('*')], from_obj=table)
        if query:
            for k, values in query.items():
                if not values:
                    continue
                if k.startswith('_gt_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[4:]) > v)
                elif k.startswith('_gte_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[5:]) >= v)
                elif k.startswith('_lt_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[4:]) < v)
                elif k.startswith('_lte_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[5:]) <= v)
                elif k.startswith('_like_'):
                    for v in values:
                        sql = sql.where(getattr(table.c, k[6:]).like("%" + v))
                else:
                    sql = sql.where(getattr(table.c, k).in_(values))
        res = await cls.__db__.execute(sql=sql)
        return await res.scalar()

    async def update(cls, ctx: dict = None, where_dict: dict = None, data: dict = None):
        """
        通用修改
        :param ctx:
        :param primay_key:
        :param data:
        :return:
        """
        table = cls.__db__[cls.tablename]
        sql = table.update()
        if where_dict is not None:
            for key, value in where_dict.items():
                if hasattr(table.c, key):
                    sql = sql.where(getattr(table.c, key) == value)
        sql = sql.value(**data)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res

    async def delete(cls, ctx: dict, where_dict: dict = None, data: dict = None):
        """
        通用删除
        :param ctx:
        :param where_didt:
        :param data:
        :return:
        """
        table = cls.__db__[cls.tablename]
        sql = table.delete()
        if where_dict is not None:
            for key, value in where_dict.items():
                if hasattr(table.c, key):
                    sql = sql.where(getattr(table.c, key) == value)
        sql = sql.value(**data)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res


class BaseDao(metaclass=DaoMetaClass):
    pass