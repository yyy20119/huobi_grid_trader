import logging
import time
from functools import wraps
import ccxt
from grid_trader import Trader

class HuobiTrader(Trader):
    def __init__(self, apikey, secretkey):
        super().__init__()
        self.ccxt_exchange = ccxt.huobipro({
            'apiKey': apikey,
            'secret': secretkey,
        })

    def db_connected(self):
        return False if not self.db_manager else True

    def require_db_connected(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self.db_connected():
                raise RuntimeError('Please connect the db first!')
            return func(self, *args, **kwargs)

        return wrapper

    @require_db_connected
    def create_table(self, new_table=True):
        if not new_table:
            return
        self.db_manager.cursor.execute("DROP TABLE IF EXISTS order_info")
        sql = """CREATE TABLE order_info (
                 order_id VARCHAR(100) NOT NULL,
                 side VARCHAR(10),
                 price FLOAT,  
                 amount FLOAT,
                 related_id VARCHAR(100))"""
        self.db_manager.cursor.execute(sql)

    @property
    @require_db_connected
    def all_orders(self):
        sql = 'SELECT * FROM order_info ORDER BY price'
        return self.db_manager.search_result(sql)

    def start_logging(self):
        tm = time.strftime('%Y%m%d%H%M', time.localtime(time.time()))
        log_name = tm + '_huobi.log'
        logging.basicConfig(filename=log_name, level=logging.INFO,
                            format='%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s')

    # strategy here
    @require_db_connected
    def trade_forerver(self, order_symbol, order_amount, base_usdt, new_table=True):
        self.start_logging()
        self.create_table(new_table)

        # 先下第一笔买单
        order_type = 'limit'
        order_side = 'buy'
        order_price = self.last_price(order_symbol) - 0.2
        take_order = self.create_order(order_symbol, order_type, order_side, order_amount, order_price)
        order_id = take_order['id']
        sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{order_id}', '{order_side}', {order_price}, {order_amount}, '{order_id}')"""
        self.db_manager.record_order(sql)
        logging.info(f"下买单成功:\n'{order_id}', '{order_side}', {order_price}, {order_amount}, '{order_id}")

        def delete_low_price_order():
            # 删除未成交的买单及db记录
            sql = "SELECT * FROM order_info where side='buy'"
            total = self.db_manager.search_result(sql)
            for row in total:
                self.cancel_order(row[0], order_symbol)
            sql = f"DELETE FROM order_info WHERE side='buy'"
            self.db_manager.record_order(sql)
            logging.info('成功撤销所有买单！')

        while True:
            results = self.all_orders
            for index, row in enumerate(results):
                order_id = row[0]
                side = row[1]
                price = row[2]
                amount = row[3]
                related_id = row[4]
                # 防止服务器请求异常
                while True:
                    try:
                        order_status = self.order_status(order_id, order_symbol)
                        last_price = self.last_price(order_symbol)
                        balance = self.balance
                        # 可用余额的监控与交易量的调整
                        if balance['USDT']['free'] >= 1.1 * base_usdt:
                            base_usdt = 1.1 * base_usdt
                            order_amount = round(1.1 * order_amount, 3)
                        break
                    except:
                        logging.warning('请求异常，1秒后重试')
                        time.sleep(1)
                        continue

                if side == 'buy':
                    # 当买单成交时
                    if order_status == 'closed':
                        logging.info('买单成交！')
                        # 删除已成交的db记录
                        sql = f"DELETE FROM order_info WHERE order_id='{order_id}'"
                        self.db_manager.record_order(sql)

                        # 在止盈处下卖单
                        sell_side = 'sell'
                        sell_price = price + 10
                        take_sell_order = self.create_order(order_symbol, order_type, sell_side, 0.998 * amount,
                                                            sell_price)
                        takeorder_id = take_sell_order['id']
                        sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{sell_side}', {sell_price}, {0.998 * amount}, '{takeorder_id}')"""
                        related_id = takeorder_id
                        self.db_manager.record_order(sql)
                        logging.info(
                            f"在止盈处下卖单成功:\n'{takeorder_id}', '{sell_side}', {sell_price}, {0.998 * amount}, '{takeorder_id}'")

                        # 在低一档的价格下买单
                        buy_side = 'buy'
                        buy_price = price - 10
                        available_usdt = balance['USDT']['free']
                        if available_usdt < buy_price * order_amount:
                            logging.info('可用余额不足，无法下新的买单')
                            continue
                        take_buy_order = self.create_order(order_symbol, order_type, buy_side, order_amount, buy_price)
                        takeorder_id = take_buy_order['id']
                        sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{related_id}')"""
                        self.db_manager.record_order(sql)
                        logging.info(
                            f"在低一档的价格下买单成功:\n'{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{related_id}")



                    # 当前价格远大于所挂买单时，撤销原有的买单并重新根据当前价格下新的买单
                    elif order_status == 'open' and len(results) == 1:
                        if last_price - price >= 20:
                            logging.info('当前价格远大于所挂买单，撤销原有的买单！')
                            # 删除未成交的买单及db记录
                            try:
                                delete_low_price_order()
                            except:
                                logging.warning('无法撤销已成交的买单')
                                continue

                            # 在略低于当前价格的地方下买单
                            buy_side = 'buy'
                            buy_price = last_price - 0.2
                            take_buy_order = self.create_order(order_symbol, order_type, buy_side, order_amount,
                                                               buy_price)
                            takeorder_id = take_buy_order['id']
                            sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}')"""
                            self.db_manager.record_order(sql)
                            logging.info(
                                f"在略低于当前价格的地方下买单成功:\n'{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}'")



                elif side == 'sell':
                    # 当卖单成交时
                    if order_status == 'closed':
                        logging.info('卖单成交！')

                        # 删除已成交的db记录
                        sql = f"DELETE FROM order_info WHERE order_id='{order_id}'"
                        self.db_manager.record_order(sql)

                        # 删除未成交的买单及db记录
                        try:
                            delete_low_price_order()
                        except:
                            logging.warning('无法撤销已成交的买单')
                            continue

                        # 在回调的地方下买单
                        buy_side = 'buy'
                        buy_price = last_price - 10
                        take_buy_order = self.create_order(order_symbol, order_type, buy_side, order_amount, buy_price)
                        takeorder_id = take_buy_order['id']
                        sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}')"""
                        self.db_manager.record_order(sql)
                        logging.info(
                            f"在回调的地方下买单成功:\n'{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}'")

                    # 若价格低的卖单还未成交，则价格高的不可能成交
                    else:
                        time.sleep(1)
                        break

                time.sleep(1)


if __name__ == '__main__':
    huobi_trader = HuobiTrader(apikey='', secretkey='')
    huobi_trader.connect_db(host='127.0.0.1', user='root', password='123456', database='huobi')
    huobi_trader.trade_forerver(order_symbol='ETH/USDT', order_amount=0.02, base_usdt=1000)
