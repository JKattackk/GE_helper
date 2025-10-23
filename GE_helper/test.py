import os.path
import json
import sqlite3
import time
import requests
import plotly.express as px

def plotPrep(itemID):
    database = sqlite3.connect('itemData.db')
    cursor = database.cursor()
    cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
    command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + itemID + "';"
    query = cursor.execute(command)
    if not query.fetchone() == None:
        tableName = "priceHistory5m.itemID" + itemID
        command = "SELECT timestamp, avgHighPrice FROM " + tableName + " WHERE avgHighPrice IS NOT NULL"
        query = cursor.execute(command)
        dat = query.fetchall()
        fig = px.line(dat, x=0, y=1)
        fig.show()
    else:
        print(f"no table for {itemID}")

plotPrep("2")