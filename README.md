本文利用ccxt实现简单的一个网格交易策略，只要价格一直在某一范围内波动就会有盈利产生。此外，在价格超出网格后增加了重新下单的功能，并在此基础上添加了可用余额的监控，从而在盈利足够多的情况下自动增加交易量。

# 用到的包
```
import os
import ccxt
import time
import pymysql
import logging
```
# 日志管理

```
tm = time.strftime('%Y%m%d%H%M', time.localtime(time.time()))
log_name = tm + '_huobi.log'
logging.basicConfig(filename=log_name, level=logging.INFO,format='%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s')
```
# 数据库
事先在mysql里建好名字为‘huobi’的数据库（create database huobi default charset utf8;）
```
# 连接database
db = pymysql.connect(
    host='127.0.0.1',
    user ='这里输用户名',
    password ='这里输密码',
    database ='huobi',)

# 使用 cursor() 方法创建一个游标对象 cursor
cursor = db.cursor()

#在数据库中创建新的订单信息表
cursor.execute("DROP TABLE IF EXISTS order_info")
sql = """CREATE TABLE order_info (
         order_id VARCHAR(100) NOT NULL,
         side VARCHAR(10),
         price FLOAT,  
         amount FLOAT,
         related_id VARCHAR(100))"""
cursor.execute(sql)
```

# 关联火币账户

```
# huobi
apikey = ‘这里输火币账户的apikey’
secretkey = ‘这里输火币账户的secretkey’

huobi=ccxt.huobipro({
    'apiKey':apikey,
    'secret':secretkey,
})
```

# 第一笔买单
以ETH/USDT为例，先下第一笔买单
```
order_symbol='ETH/USDT'
order_type='limit'
order_side='buy'
order_amount=0.04

ETH_Last=huobi.fetch_ticker(order_symbol)['last']
logging.info('ETH 最新价格:'+str(ETH_Last))

order_price=ETH_Last-0.3

take_order=huobi.create_order(order_symbol,order_type,order_side,order_amount,order_price)
logging.info(take_order)

takeorder_id=take_order['id']
logging.info(takeorder_id)

order_status=huobi.fetch_order(takeorder_id,order_symbol)
logging.info(order_status)

takeorder_side=order_status['side']
logging.info(takeorder_side)

takeorder_price=order_status['price']
logging.info(takeorder_price)

sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{takeorder_side}', {takeorder_price}, {order_amount}, '{takeorder_id}')"""
cursor.execute(sql)
db.commit()
```

# 设置基础余额
这一变量需根据实际账户余额设置，之后会不断根据可用余额和这个基础余额进行比较，从而决定是否增加交易量。
```
base_usdt=500
```
# 开始网格交易
这里的策略是每当价格下降2usdt，则买入0.04个eth。当价格上涨2usdt时，就卖出。实际可根据投入的资金自行决定并设置价格下降和上涨的范围。但由于要给火币平台一定的交易手续费，所以要提前减去这部分的成本，使得每笔的收益为正。
```
while True:
    #价格低的优先查找（先买单后卖单）
    sql = 'SELECT * FROM order_info ORDER BY price'
    # 执行SQL语句
    cursor.execute(sql)
    # 获取所有记录列表
    results = cursor.fetchall()
    for index,row in enumerate(results):
        order_id = row[0]
        side = row[1]
        price = row[2]
        amount = row[3]
        related_id = row[4]
        
        #防止服务器请求异常
        while True:
            try:
                order_status = huobi.fetch_order_status(order_id, order_symbol)
                last_price = huobi.fetch_ticker(order_symbol)['last']
                balance = huobi.fetch_balance()
                #可用余额的监控与交易量的调整
                if balance['USDT']['free']>=1.1*base_usdt:
                    base_usdt=1.1*base_usdt
                    order_amount=round(1.1*order_amount,3)
                break
            except:
                logging.warning('请求异常，1秒后重试')
                time.sleep(1)
                continue

        
        if  side=='buy':
        	#当买单成交时
            if order_status == 'closed':
                logging.info('买单成交！')
                # 删除已成交的db记录
                sql = f"DELETE FROM order_info WHERE order_id='{order_id}'"
                cursor.execute(sql)
                db.commit()

                #在止盈处下卖单
                sell_side='sell'
                sell_price=price+2
                take_sell_order = huobi.create_order(order_symbol, order_type, sell_side, 0.998*amount, sell_price)
                takeorder_id=take_sell_order['id']
                sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{sell_side}', {sell_price}, {0.999*amount}, '{takeorder_id}')"""
                related_id=takeorder_id
                cursor.execute(sql)
                db.commit()
                logging.info(f"在止盈处下卖单成功:\n'{takeorder_id}', '{sell_side}', {sell_price}, {0.998*amount}, '{takeorder_id}'")

                #在低一档的价格下买单
                buy_side='buy'
                buy_price=price-2
                available_usdt = balance['USDT']['free']
                if available_usdt < buy_price*order_amount:
                    logging.info('可用余额不足，无法下新的买单')
                    continue
                take_buy_order = huobi.create_order(order_symbol, order_type, buy_side, order_amount, buy_price)
                takeorder_id = take_buy_order['id']
                sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{related_id}')"""
                cursor.execute(sql)
                db.commit()
                logging.info(f"在低一档的价格下买单成功:\n'{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{related_id}")



            # 当前价格远大于所挂买单时，撤销原有的买单并重新根据当前价格下新的买单
            elif order_status=='open' and len(results)==1:
                if last_price-price>=4:
                    logging.info('当前价格远大于所挂买单，撤销原有的买单！')
                    # 删除未成交的买单及db记录
                    sql = "SELECT * FROM order_info where side='buy'"
                    cursor.execute(sql)
                    total = cursor.fetchall()
                    try:
                        for row in total:
                            huobi.cancel_order(row[0], order_symbol)
                    except:
                        logging.warning('无法撤销已成交的买单')
                        continue
                    sql = f"DELETE FROM order_info WHERE side='buy'"
                    cursor.execute(sql)
                    db.commit()
                    logging.info('成功撤销所有买单！')

                    # 在略低于当前价格的地方下买单
                    buy_side = 'buy'
                    buy_price = last_price - 0.3
                    take_buy_order = huobi.create_order(order_symbol, order_type, buy_side, order_amount, buy_price)
                    takeorder_id = take_buy_order['id']
                    sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}')"""
                    cursor.execute(sql)
                    db.commit()
                    logging.info(f"在略低于当前价格的地方下买单成功:\n'{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}'")



        elif side=='sell':
        	#当卖单成交时
            if order_status=='closed':
                logging.info('卖单成交！')

                # 删除已成交的db记录
                sql = f"DELETE FROM order_info WHERE order_id='{order_id}'"
                cursor.execute(sql)
                db.commit()

                # 删除未成交的买单及db记录
                sql = "SELECT * FROM order_info where side='buy'"
                cursor.execute(sql)
                total = cursor.fetchall()
                try:
                    for row in total:
                        huobi.cancel_order(row[0],order_symbol)
                except:
                    logging.warning('无法撤销已成交的买单')
                    continue
                sql = f"DELETE FROM order_info WHERE side='buy'"
                cursor.execute(sql)
                db.commit()
                logging.info('成功撤销所有买单！')

                #在回调的地方下买单
                buy_side='buy'
                buy_price=last_price-2
                take_buy_order = huobi.create_order(order_symbol, order_type, buy_side, order_amount, buy_price)
                takeorder_id = take_buy_order['id']
                sql = f"""INSERT INTO order_info(order_id,side, price, amount, related_id) VALUES ('{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}')"""
                cursor.execute(sql)
                db.commit()
                logging.info(f"在回调的地方下买单成功:\n'{takeorder_id}', '{buy_side}', {buy_price}, {order_amount}, '{takeorder_id}'")

            #若价格低的卖单还未成交，则价格高的不可能成交
            else:
                time.sleep(1)
                break

        time.sleep(1)
```

# 运行结果
下图为最新的部分log，目前已运行了一周的时间，暂无异常发生。（之前是在okex平台已成功运行了一个多月，但现在okex无法提币，所以本文以火币为例）
![在这里插入图片描述](https://img-blog.csdnimg.cn/2020103116285057.png?x-oss-process=image/watermark,type_ZmFuZ3poZW5naGVpdGk,shadow_10,text_aHR0cHM6Ly9ibG9nLmNzZG4ubmV0L3FxXzQzNDM1Mjc0,size_16,color_FFFFFF,t_70#pic_center)


# 更新
2020/11/25

以上是十月份的时候写的一篇博客，后面发现火币手续费要比okex贵一点，所以网格区间最好大于或等于2.5，封装了一下代码并已上传至github，但还没有测试过:)

2020/12/17

测试后修复了一处bug，目前可以在服务器上成功运行。开启脚本命令如下：

```shell
(python3 run.py > error_huobi.txt 2>&1 &)
```

2021/1/7

由于最近eth价格已超过1000，所以更新了网格区间，建议大于或等于10是安全的。

