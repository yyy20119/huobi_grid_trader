import pymysql


class DatabaseManager:
    def __init__(self, host, user, password, database):
        self.db = pymysql.connect(host=host, user=user, password=password, database=database)
        self.cursor = self.db.cursor()

    def search_result(self, sql):
        self.cursor.execute(sql)
        return self.cursor.fetchall()

    def record_order(self, sql):
        self.cursor.execute(sql)
        self.db.commit()


class Trader:
    def __init__(self):
        self.ccxt_exchange = None
        self.db_manager = None

    def connect_db(self, host, user, password, database):
        self.db_manager = DatabaseManager(host, user, password, database)

    @property
    def balance(self):
        return self.ccxt_exchange.fetch_balance()

    def order_status(self, order_id, order_symbol):
        return self.ccxt_exchange.fetch_order_status(order_id, order_symbol)

    def last_price(self, order_symbol):
        return self.ccxt_exchange.fetch_ticker(order_symbol)['last']

    def create_order(self, order_symbol, order_type, buy_side, order_amount, buy_price):
        return self.ccxt_exchange.create_order(order_symbol, order_type, buy_side, order_amount, buy_price)

    def cancel_order(self, order_id, order_symbol):
        return self.ccxt_exchange.cancel_order(order_id, order_symbol)
