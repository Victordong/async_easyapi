import functools
from sqlalchemy.sql import select, and_, func, between, distinct, text
from easyapi_tools.util import str2hump, type_to_json
from .db_util import MysqlDB
from sqlalchemy.exc import NoSuchColumnError
import datetime


class Transaction():
    def __init__(self, db: MysqlDB):
        self._db = db
        self._transaction = None
        self._connect = None

    async def __aenter__(self):
        self._connect = await self._db._engine.acquire()
        self._transaction = await self._connect.begin()
        return self._connect

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await self._transaction.commit()
        except Exception as e:
            await self._transaction.rollback()
            raise e
        finally:
            await self._connect.close()


def get_tx(db: MysqlDB):
    return Transaction(db)


def search_sql(sql, query: dict, table):
    for k in query.keys():
        if type(query[k]) is not list:
            # 兼容处理
            values = [query[k]]
        else:
            values = query[k]
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
                sql = sql.where(getattr(table.c, k[6:]).like(v + '%'))
        elif k.startswith('_in_'):
            sql = sql.where(getattr(table.c, k[4:]).in_(values))
        else:
            sql = sql.where(getattr(table.c, k) == values[0])
    return sql


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
        if "BaseDao" in name:
            return type.__new__(cls, name, bases, attrs)
        if attrs.get('__db__') is None:
            raise NotImplementedError("Should have __db__ value.")

        attrs['__tablename__'] = attrs.get('__tablename__') or str2hump(name[:-3]) + 's'
        return type.__new__(cls, name, bases, attrs)


class BaseDao(metaclass=DaoMetaClass):
    @classmethod
    def reformatter(cls, data: dict, *args, **kwargs):
        """
        将model数据转换成dao数据
        :param data:
        :return:
        """
        return data

    @classmethod
    def formatter(cls, data: dict, *args, **kwargs):
        """
        将dao数据转换成model数据
        :param data:
        :return:
        """
        return type_to_json(data)

    @classmethod
    async def first(cls, ctx: dict = None, query=None, sorter_key: str = 'id', *args, **kwargs):
        """
        获取根据sorter_key倒叙第一个资源 sorter_key 默认id
        :param ctx:
        :param query:
        :return:
        """
        if query is None:
            query = {}
        query = cls.reformatter(query, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        sql = select([table])
        if query:
            sql = search_sql(sql, query, table)
        sql = sql.order_by(getattr(table.c, sorter_key, table.c.id).desc())
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        data = await res.first()
        if not data:
            return None
        return cls.formatter(data, *args, **kwargs)

    @classmethod
    async def last(cls, ctx: dict = None, query=None, sorter_key: str = 'id', *args, **kwargs):
        """
        获取根据sorter_key倒叙最后一个资源 sorter_key 默认id
        :param ctx:
        :param query:
        :param sorter_key:
        :return:
        """
        if query is None:
            query = {}
        query = cls.reformatter(query, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        sql = select([table])
        if query:
            sql = search_sql(sql, query, table)
        sql = sql.order_by(getattr(table.c, sorter_key, table.c.id))
        res = await cls.__db__.execute(ctx=ctx, sql=sql)

        data = await res.first()
        if not data:
            return None
        return cls.formatter(data, *args, **kwargs)

    @classmethod
    async def get(cls, ctx: dict = None, query=None, *args, **kwargs):
        """
        获取单个资源 通常给予unique使用
        :param query:
        :return:
        """
        if query is None:
            query = {}
        query = cls.reformatter(query, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        sql = select([table])
        if query:
            sql = search_sql(sql, query, table)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        data = await res.first()
        if not data:
            return None
        return cls.formatter(data, *args, **kwargs)

    @classmethod
    async def query(cls, ctx: dict = None, query: dict = None, pager: dict = None, sorter: dict = None, *args,
                    **kwargs):
        """
        通用查询
        :param query:
        :param pager:
        :param sorter:
        :return:
        """
        if query is None:
            query = {}
        query = cls.reformatter(query, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        sql = select([table])
        if query:
            sql = search_sql(sql, query, table)
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
        return list(map(functools.partial(cls.formatter, *args, **kwargs), data))

    @classmethod
    async def insert(cls, data: dict, ctx: dict = None, *args, **kwargs):
        """
        通用插入
        :param tx:
        :param args:
        :return:
        """
        if data is None:
            return None
        table = cls.__db__[cls.__tablename__]
        data = cls.reformatter(data, *args, **kwargs)
        sql = table.insert().values(**data)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res.lastrowid

    @classmethod
    async def count(cls, ctx: dict = None, query: dict = None, *args, **kwargs):
        """
        计数
        :param query:
        :return:
        """
        if query is None:
            query = {}
        query = cls.reformatter(query, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        sql = select([func.count('*')], from_obj=table)
        if query:
            sql = search_sql(sql, query, table)

        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return await res.scalar()

    @classmethod
    async def execute(cls, ctx: dict = None, sql: str = ""):
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res

    @classmethod
    async def update(cls, ctx: dict = None, where_dict: dict = None, data: dict = None, *args, **kwargs):
        """
        通用修改
        :param ctx:
        :param primay_key:
        :param data:
        :return:
        """
        if where_dict is None:
            where_dict = {}
        where_dict = cls.reformatter(where_dict, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        data = cls.reformatter(data, *args, **kwargs)
        sql = table.update()
        for key, value in where_dict.items():
            if hasattr(table.c, key):
                sql = sql.where(getattr(table.c, key) == value)
        sql = sql.values(**data)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res

    @classmethod
    async def delete(cls, ctx: dict = None, where_dict: dict = None, *args, **kwargs):
        """
        通用删除
        :param ctx:
        :param where_didt:
        :param data:
        :return:
        """
        if where_dict is None:
            where_dict = {}
        where_dict = cls.reformatter(where_dict, *args, **kwargs)
        table = cls.__db__[cls.__tablename__]
        sql = table.delete()
        for key, value in where_dict.items():
            if hasattr(table.c, key):
                sql = sql.where(getattr(table.c, key) == value)
        res = await cls.__db__.execute(ctx=ctx, sql=sql)
        return res


class BusinessBaseDao(BaseDao):

    @classmethod
    def formatter(cls, data: dict, *args, **kwargs):
        """
        将dao数据转换成model数据
        :param data:
        :return:
        """
        return super().formatter(data)

    @classmethod
    def reformatter(cls, data: dict, *args, **kwargs):
        """
        将model数据转换成dao数据
        :param data:
            unscoped: 是否处理软删除
        :return:
        """
        new_data = dict()
        for key, value in data.items():
            new_data[key] = value
        if not kwargs.get('unscoped', False) and 'deleted_at' not in data:
            new_data['deleted_at'] = None
        return super().reformatter(new_data)

    @classmethod
    async def update(cls, ctx: dict = None, where_dict: dict = None, data: dict = None, unscoped=False,
                     modify_by: str = ''):
        """
        业务修改
        :param ctx:
        :param where_dict: 修改数据的条件
        :param data: 修改的数据
        :param modify_by: 修改用户
        :return:
        """
        data['updated_at'] = datetime.datetime.now()
        data['updated_by'] = modify_by
        return await super().update(ctx=ctx, where_dict=where_dict, data=data, unscoped=unscoped)

    @classmethod
    async def delete(cls, ctx: dict = None, where_dict: dict = None, unscoped=False, modify_by: str = ''):
        """
        业务删除
        :param ctx:
        :param where_dict:
        :param modify_by:
        :return:
        """
        if where_dict is None:
            where_dict = {}
        data = dict()
        data['deleted_at'] = datetime.datetime.now()
        data['updated_by'] = modify_by
        return await super().update(ctx=ctx, where_dict=where_dict, data=data, unscoped=unscoped)

    @classmethod
    async def insert(cls, ctx: dict = None, data: dict = None, modify_by='', unscoped=False):
        if data is None:
            data = {}
        data['created_at'] = datetime.datetime.now()
        data['created_by'] = modify_by
        return await super().insert(ctx=ctx, data=data, unscoped=unscoped)
