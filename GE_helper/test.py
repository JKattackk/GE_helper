import os.path
import json
import sqlite3
import time
import requests
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import pandas as pd

def plotPrep(itemID):
    database = sqlite3.connect('itemData.db')
    cursor = database.cursor()
    cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
    command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + itemID + "';"
    query = cursor.execute(command)
    if not query.fetchone() == None:
        tableName = "priceHistory5m.itemID" + itemID
        command = "SELECT timestamp, avgHighPrice, avgLowPrice FROM " + tableName
        query = cursor.execute(command)
        dat = query.fetchall()
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                    vertical_spacing=0.05)
        time = [point[0] for point in dat]
        high = [point[1] for point in dat]
        low = [point[2] for point in dat]

        fig.add_trace(go.Scatter(x=time, y=high, mode='lines+markers',marker_color="orange"), row=1, col=1)
        fig.add_trace(go.Scatter(x=time, y=low, mode='lines+markers',marker_color="dodgerblue"), row=1, col=1)
        

        command = "SELECT lowPriceVolume, highPriceVolume FROM " + tableName
        query = cursor.execute(command)
        dat = query.fetchall()
        database.close()
        high = [point[0] for point in dat]
        low = [point[1] for point in dat]
        fig.add_trace(go.Histogram(histfunc="sum", x=time, y=high, marker_color="orange", xbins=dict(size=500)), row=2, col=1)
        fig.add_trace(go.Histogram(histfunc="sum", x=time, y=low, marker_color="dodgerblue", xbins=dict(size=500)), row=2, col=1)
        fig.update_layout(bargap=0.1, bargroupgap=0.05, showlegend = False)

        fig.show()
    else:
        print(f"no table for {itemID}")
        database.close()

plotPrep("2")