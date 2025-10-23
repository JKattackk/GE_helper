import sqlite3
import pynufft
import requests
import json


headers = {
    'User-Agent': 'GE price trend tracking wip discord @kat6541'
}
itemID = '2'
priceHistory5mURL = url = "https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=1h&id=" + itemID
[om, Nd, Kd, Jd] = [[-1,1], 300, 600, 5]


""" try:
    command = "SELECT timeStamp from " + tableName + " ORDER BY timeStamp DESC LIMIT 1"
    lastEntryTime = int(cursor.execute(command).fetchone()[0])
    command = "SELECT timeStamp from " + tableName + " ORDER BY timeStamp ASC LIMIT 1"
    firstEntryTime = int(cursor.execute(command).fetchone()[0])
    dataSpan = lastEntryTime - firstEntryTime
    print("data spans ", dataSpan, " s, or ", dataSpan/86400, " days")
    command = "SELECT timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume FROM " + tableName
    response = cursor.execute(command).fetchall()


    ##NufftObj = NUFFT()
    ##NufftObj.plan(om, Nd, Kd, Jd)
    
    print('test')
    
except:
    print("invalid price history")
 """



