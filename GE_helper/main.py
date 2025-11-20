import sys
import os.path
import json
import sqlite3
import time
import requests
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import pandas as pd
import traceback
from PyQt6.QtSql import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtWebEngineWidgets import QWebEngineView
from output import Ui_MainWindow
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFontDatabase, QMouseEvent, QPaintEvent, QEnterEvent
import numpy as np
import weakref
import threading
import difflib
from datetime import datetime

#pyuic6 -o .\GE_helper\output.py .\GE_helper\newUI.ui

itemListURL = "https://chisel.weirdgloop.org/gazproj/gazbot/os_dump.json"
priceHistory5mURL = url = "https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=5m&id="
itemLookupURL = "https://www.ge-tracker.com/item/"

headers = {
    'User-Agent': 'GE price trend tracking wip discord @kat6541'
}

filteredItemListValues = "(id INTEGER PRIMARY KEY, itemName, buyLimit, lowPrice, highPrice, value, highAlch, lowVolume, highVolume, lowPriceChange, highPriceChange, lowVolumeChange, highVolumeChange, timestamp, tracked)"
priceHistory5mValues = "(timeStamp INTEGER NOT NULL PRIMARY KEY, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume)"

alertConfigFile = "cfg/alertConfig.json"
filterConfigFile = "cfg/filterConfig.json"

## default item filter valuues
def_minBuyLimitValue = 2000000
def_minHourlyThroughput = 5000000
def_minHourlyVolume = 1000
def_maxPrice = 10000000
def_priceChangePercent = 10
def_volChangePercent = 100



# global registry of active Worker instances (weakrefs avoid leaks)
active_workers = weakref.WeakSet()
active_workers_lock = threading.Lock()

def textToInt(string):
    try:
        return int(string)
    except:
        endChar = string[-1].casefold()
        string = string[:-1]
        try:
            num = int(string)
        except Exception as e:
            print("invalid input: ")
            print(e)
            raise ValueError
        match endChar:
            case 'm':
                return(num * 10**6)
            case 'k':
                return(num * 10**3)
            case 'b':
                return(num * 10**9)
            case default:
                raise ValueError
            
class StatusIndicator(QWidget):
    PRESETS = {
        "initializing": QColor("#FFFFFF"),
        "ok": QColor("#41e968"),
        "working": QColor("#f3a033"),
        "error": QColor("#e53935"),
        "off": QColor("#808080")
    }
    def __init__(self, parent=None, diameter=14):
        super().__init__(parent)
        self._diameter = diameter
        self._color = self.PRESETS["initializing"]
        self.setFixedSize(self._diameter + 4, self._diameter + 4)
        # set a default tooltip; UI code can update later
        self.setToolTip("Status: unset")

    def set_status(self, name_or_color, tooltip: str | None = None):
        """Set named status (ok/warn/error/off/busy) or pass a QColor / hex string.
        Optionally update the tooltip text.
        """
        if isinstance(name_or_color, QColor):
            self._color = name_or_color
        else:
            # allow hex strings or preset names
            if isinstance(name_or_color, str) and name_or_color.startswith("#"):
                self._color = QColor(name_or_color)
            else:
                self._color = self.PRESETS.get(str(name_or_color).lower(), self.PRESETS["off"])
        if tooltip is not None:
            self.setToolTip(tooltip)
        self.update()

    def set_status_color(self, qcolor: QColor, tooltip: str | None = None):
        self.set_status(qcolor, tooltip)

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # draw subtle outer ring
        pen = QPen(QColor(0,0,0,60))
        pen.setWidth(1)
        p.setPen(pen)
        brush = QBrush(self._color)
        p.setBrush(brush)
        r = self.rect().adjusted(2, 2, -2, -2)
        p.drawEllipse(r)
        p.end()

    def enterEvent(self, event: QEnterEvent):
        # show tooltip immediately on hover for clearer UX
        tip = self.toolTip()
        if tip:
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), tip, self)
        super().enterEvent(event)
    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

class alert:
    def __init__(self, id, name, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp):
        self.id = str(id)
        self.name = str(name)
        self.lowPriceChange = f"{lowPriceChange:.2f}%"
        self.highPriceChange = f"{highPriceChange:.2f}%"
        self.lowVolChange = f"{lowVolChange:.2f}%"
        self.highVolChange = f"{highVolChange:.2f}%"
        self.timestamp = str(timestamp)
    
class signals(QObject):
    #indicates new price update. Includes unix timestamp of last update
    newUpdate = pyqtSignal(int)
    #indicates new alerts.  
    newAlerts = pyqtSignal(list, int)
    newItem = pyqtSignal(str)
    graphReady = pyqtSignal(object)
    #GUI updating requests
    progBarChange = pyqtSignal(int)
    loadTextChange = pyqtSignal(str)
    buildDBComplete = pyqtSignal()
    priceHistoryComplete = pyqtSignal()
    killPriceLoop = pyqtSignal()
    alertConfigSaved = pyqtSignal()

    newInProgressItem = pyqtSignal(object)
    newProgressUpdate = pyqtSignal(object)
    inProgressItemComplete = pyqtSignal(object)
    newUpdate = pyqtSignal(int)

class Worker(QRunnable):
    """Worker thread."""
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.is_killed = False
        self.statusString = ''

    @pyqtSlot()
    def run(self):
        """Initialise the runner function with passed args, kwargs."""
        try:
            # register self as active
            with active_workers_lock:
                active_workers.add(self)
            print(f"Worker starting: {self.fn.__name__}")
            self.is_killed = False
            self.fn(*self.args, **self.kwargs, worker= self)
            print(f"Worker completed: {self.fn.__name__}")
        except Exception as e:
            print(f"Error in worker thread: {e}")
            traceback.print_exc()
        finally:
            with active_workers_lock:
                try:
                    active_workers.discard(self)
                except Exception:
                    pass
    def kill(self):
        self.is_killed = True
    def getStatusString(self):
        return self.statusString
    def setStatusString(self, status):
        self.statusString = status

def get_active_workers_snapshot():
    with active_workers_lock:
        return list(active_workers)
class MainWindow(QMainWindow):
    def __init__(self):
        print("starting __init__...")
        try:
            self.inProgressItems = []
            self.localList = []
            self.threadpool = QThreadPool()
            thread_count = self.threadpool.maxThreadCount()
            print(f"Multithreading with maximum {thread_count} threads")
            print("Constructing MainWindow instance", id(self))
            super(MainWindow, self).__init__()
            self.ui = Ui_MainWindow()
            self.ui.setupUi(self)
            #status indicator setup
            try:
                placeholder = self.ui.indicator_widget  # placeholder created by .ui
                if placeholder.layout() is None:
                    placeholder.setLayout(QHBoxLayout())
                while placeholder.layout().count():
                    it = placeholder.layout().takeAt(0)
                    w = it.widget()
                    if w:
                        w.setParent(None)
                self.status_indicator = StatusIndicator(self)
                placeholder.layout().setContentsMargins(0,0,0,0)
                placeholder.layout().addWidget(self.status_indicator, 0, Qt.AlignmentFlag.AlignCenter)
            except Exception:
                pass
            
            #graph setup
            try:
                #prevents window flicker during startup
                self.ui.mainGraph.page().setBackgroundColor(QColor(255,255,255,0))
                self.ui.mainGraph.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                # calling winId() forces creation of the native window handle
                _ = self.ui.mainGraph.winId()
            except Exception:
                pass
            
            self.setupAlertList()
            self.loopWorker = Worker(self.itemPriceLoop)
            self.signals = signals()
            self.setup_signals()

            self.ui.history_list.setVisible(False)
            self.updateConfigBoxes()

            #graph page setup
            self.ui.main_stack_widget.setCurrentIndex(0)

            #confirm that database exists and build has been finished
            if os.path.isfile("database.db"):
                try:
                    database = sqlite3.connect('database.db')
                    cursor = database.cursor()
                    cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
                    cursor.execute("SELECT id FROM filteredDB WHERE tracked=FALSE")
                    result = cursor.fetchall()
                    self.updateLocalList()
                    if len(result) == 0:
                        self.ui.item_count_label.setText("Items: " + str(len(self.localList)))
                        repairList = {}
                        curTime = int(time.time())
                        for item in self.localList:
                            tableName = "priceHistory5m.itemID" + item[0]
                            command = "SELECT timeStamp from " + tableName + " ORDER BY timeStamp DESC LIMIT 1"
                            lastEntryTime = int(cursor.execute(command).fetchone()[0])
                            if (curTime - lastEntryTime) > 60*9:
                                repairList[item[0]] = lastEntryTime
                        if len(repairList) > 0:
                            print(f"found ({len(repairList)}) items needing repair")
                            self.repairWorker = Worker(self.repairDB, repairList)
                            self.threadpool.start(self.repairWorker)
                        self.activateMainWindow()
                        database.close()
                    else:
                        database.close()
                        worker = Worker(self.buildPriceHistoryDB)
                        self.threadpool.start(worker)
                except Exception as e:
                    print(e)
            else:
                print("no DB exists")
            print("MainWindow.__init__ complete")
            print("__init__ ended...\n")
        except Exception as e:
            print(f"Critical error in MainWindow.__init__: {e}")
            import traceback
            traceback.print_exc()
            raise
    def setup_signals(self):
        #button connections
        self.ui.rebuild_db_button.clicked.connect(self.rebuildDBPressed)
        self.ui.history_button.toggled['bool'].connect(self.onHistoryButtonToggle)
        self.ui.config_button.clicked.connect(self.onConfigButtonToggle)
        self.ui.graph_button.clicked.connect(self.onGraphButtonToggle)
        self.ui.save_alert_button.clicked.connect(self.saveAlertConfig)

        #loading screen control
        self.signals.progBarChange.connect(self.updateBar)
        self.signals.loadTextChange.connect(self.updateLoadingText)

        self.signals.buildDBComplete.connect(self.startPriceLoop)
        self.signals.priceHistoryComplete.connect(self.priceHistoryComplete)
        self.signals.killPriceLoop.connect(self.loopWorker.kill)
        self.signals.newItem.connect(self.newItem)
        self.signals.graphReady.connect(self.updatePlot)
        self.signals.newAlerts.connect(self.updateAlerts)
        self.signals.alertConfigSaved.connect(self.updateConfigBoxes)

        self.signals.newInProgressItem.connect(self.addInProgressItem)
        self.signals.newProgressUpdate.connect(self.updateStatus)
        self.signals.inProgressItemComplete.connect(self.removeInProgressItem)
        self.signals.newUpdate.connect(self.newUpdate)

    def setupAlertList(self):
        #minimumSectionSize : int
        self.ui.alert_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ui.alert_list.hideColumn(6)

    def newUpdate(self, timestamp):
        time = datetime.fromtimestamp(timestamp)
        self.ui.last_update_label.setText("Last Updated: " + datetime.strftime(time, "%H:%M"))

    def addInProgressItem(self, worker):
        self.inProgressItems.append(worker)
        self.updateStatus()

    def updateStatus(self):
        if len(self.inProgressItems) == 0:
            self.status_indicator.set_status(name_or_color="ok", tooltip= "No background tasks")
        else:
            statusText = ""
            for worker in self.inProgressItems:
                statusText = (statusText + worker.getStatusString() + "\n")
            self.status_indicator.set_status(name_or_color="working", tooltip=statusText)

    def removeInProgressItem(self, worker):
        self.inProgressItems.remove(worker)
        self.updateStatus()

    def newItem(self, itemID):
        print("new item received:", itemID)
        self.updateGraphPage(itemID)

    def updatePlot(self, fig):
        html = fig.to_html(include_plotlyjs='cdn')
        try:
            self.ui.mainGraph.setHtml(html, QUrl())
        except Exception as e:
            print(f"Error updating plot: {e}")

    def startPriceLoop(self):
        self.threadpool.start(self.loopWorker)
        print("Starting price loop")

    def activateMainWindow(self):
        print("Setting up main window")
        self.startPriceLoop()
        self.updateGraphPage(self.localList[0][0])
        self.ui.main_stack_widget.setCurrentIndex(1)
        self.ui.graph_button.setEnabled(True)
        self.ui.graph_button.setChecked(True)
        self.setupSearch()
        self.ui.search_bar.setEnabled(True)
        print("main window setup complete")
       
    def updateGraphPage(self, itemID):
        print(f"updating graph with {itemID}")
        try:
            database = sqlite3.connect('database.db')
            cursor = database.cursor()
            command = f"SELECT id, itemName, buyLimit, lowPrice, highPrice, value, highAlch, lowVolume, highVolume FROM filteredDB WHERE id={itemID}"
            result = cursor.execute(command).fetchall()
            database.close()
            values = {}
            for i in range(len(result[0])):
                values[i] = str(result[0][i])
            self.ui.id_label.setText(values[0])
            self.ui.name_label.setText(values[1])
            self.ui.limit_label.setText(values[2])
            self.ui.avgSell_label.setText(values[3])
            self.ui.avgBuy_label.setText(values[4])
            self.ui.highAlch_label.setText(values[6])
            self.ui.sellVol_label.setText(values[7])
            self.ui.buyVol_label.setText(values[8])
            worker = Worker(self.plotPrep, itemID)
            self.threadpool.start(worker)
        except Exception as e:
            print(e)

    def setupSearch(self, debounce_ms = 200):
        try:
            #timer for debounce while user is typing
            self.search_debounce_ms = debounce_ms
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            #when timer expires offer suggestions in drop down
            self._search_timer.timeout.connect(self._do_suggest)
            
            # completer + model
            self._completer_model = QStringListModel(self)
            self._completer = QCompleter(self._completer_model, self)
            self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self._completer.activated.connect(self.on_completer_activated)

            # allow substring matching (not only starts-with)
            self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
            
            # limit ammount of suggestions in drop down
            try:
                self._completer.setMaxVisibleItems(6)
            except Exception:
                pass

            self.ui.search_bar.setCompleter(self._completer)
            self.ui.search_bar.textEdited.connect(self.on_search_text_edited)
            self.ui.search_bar.returnPressed.connect(self.on_search_entered)

            # intercept Return/Enter when the completer popup is visible so we can
            # perform the selection without leaving the selected text in the edit.
            self.ui.search_bar.installEventFilter(self)
        except Exception as e:
            print("setup_search failed:", e)

    def on_search_text_edited(self, text: str):
        # restart debounce timer
        try:
            self._last_search_text = text
            self._search_timer.start(self.search_debounce_ms)
        except Exception as e:
            print("on_search_text_edited:", e)

    def _do_suggest(self):
        #after debounce timer expires offer search suggestions
        try:
            q = (self._last_search_text or "").strip()
            if q == "":
                self._completer_model.setStringList([])
                # hide popup when empty
                try:
                    self._completer.popup().hide()
                except Exception:
                    pass
                return
            suggestions = self._get_suggestions(q, max_items=6)
            # suggestions are "ID: name" strings
            self._completer_model.setStringList(suggestions)
            self._completer.setCompletionPrefix(q)

            # adjust popup width to match the edit (optional)
            try:
                popup = self._completer.popup()
                popup.setFixedWidth(max(self.ui.search_bar.width(), 200))
            except Exception:
                popup = None
            # show popup explicitly if we have suggestions
            if suggestions:
                self._completer.complete()
            else:
                try:
                    self._completer.popup().hide()
                except Exception:
                    pass
            # show popup explicitly
            self._completer.complete()
        except Exception as e:
            print("_do_suggest:", e)

    def _get_suggestions(self, query: str, max_items: int = 6):
        # return list of 'ID: name' suggestion strings.
        # numeric queries match ID prefix
        # non-numeric: substring matches first, then difflib fallback
        try:
            q = query.strip()
            suggestions = []
            items = getattr(self, "localList", [])
            # numeric -> match id prefix or exact
            if q.isdigit():
                for id_, name in items:
                    if id_.startswith(q):
                        suggestions.append(f"{id_}: {name.replace('_',' ')}")
                        if len(suggestions) >= max_items:
                            return suggestions
                return suggestions
            ql = q.lower()
            # substring matches (name contains)
            for id_, name in items:
                if ql in name.lower():
                    suggestions.append(f"{id_}: {name.replace('_',' ')}")
                    if len(suggestions) >= max_items:
                        return suggestions
            # fallback fuzzy match on names using difflib
            #adjust cutoff to change how closely the results must match (higher cutoff = closer match)
            names = [n for (_id, n) in items]
            fuzzy = difflib.get_close_matches(query, names, n=max_items, cutoff=0.7)
            # map fuzzy names back to ids and format
            for fname in fuzzy:
                for id_, name in items:
                    if name == fname:
                        s = f"{id_}: {name.replace('_',' ')}"
                        if s not in suggestions:
                            suggestions.append(s)
                            break
                if len(suggestions) >= max_items:
                    break
            return suggestions
        except Exception as e:
            print("_get_suggestions:", e)
            return []

    def on_completer_activated(self, text: str):
        #user selected a suggestion from the popup. Perform final search
        try:
            # suggestion format is "ID: name"
            id_part = text.split(":", 1)[0].strip()
            self.perform_search(id_part)
            QTimer.singleShot(0, self.ui.search_bar.clear)
        except Exception as e:
            print("on_completer_activated:", e)

    def on_search_entered(self):
        #user pressed enter in search bar: do final search
        try:
            text = self.ui.search_bar.text().strip()
            self.ui.search_bar.clear()
            if text == "":
                return
            # if text looks like "ID: name" extract id, else pass through
            if ":" in text and text.split(":", 1)[0].strip().isdigit():
                id_part = text.split(":", 1)[0].strip()
                self.perform_search(id_part)
            elif text.isdigit():
                self.perform_search(text)
            else:
                # perform fuzzy/substring search and show results dialog
                results = self._perform_query(text)
                self.show_search_results(results, query=text)
        except Exception as e:
            print("on_search_entered:", e)

    def _perform_query(self, query: str, max_results: int = 50):
        # return list of (id, name) matching the query (ordered)
        try:
            q = query.strip()
            items = getattr(self, "localList", [])
            results = []
            if q.isdigit():
                for id_, name in items:
                    if id_ == q:
                        results.append((id_, name))
                        return results
                return results
            ql = q.lower()
            # prioritize substring matches
            for id_, name in items:
                if ql in name.lower():
                    results.append((id_, name))
                    if len(results) >= max_results:
                        return results
            # fallback fuzzy matches
            names = [n for (_id, n) in items]
            fuzzy = difflib.get_close_matches(query, names, n=max_results, cutoff=0.7)
            for fname in fuzzy:
                for id_, name in items:
                    if name == fname and (id_, name) not in results:
                        results.append((id_, name))
                        break
                if len(results) >= max_results:
                    break
            return results
        except Exception as e:
            print("_perform_query:", e)
            return []

    def show_search_results(self, results, query: str | None = None):
        # show a simple modal results dialog with a list. double click selects item
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Search results{(' — ' + query) if query else ''}")
            dlg.setModal(True)
            dlg.setMinimumSize(420, 300)
            layout = QVBoxLayout(dlg)
            listw = QListWidget(dlg)
            for id_, name in results:
                listw.addItem(f"{id_}: {name.replace('_',' ')}")
            layout.addWidget(listw)
            btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            btn_box.rejected.connect(dlg.reject)
            layout.addWidget(btn_box)
            # double-click => open graph for selected id
            def on_item_activated(item):
                try:
                    text = item.text()
                    id_part = text.split(":", 1)[0].strip()
                    dlg.accept()
                    self.perform_search(id_part)
                except Exception as e:
                    print("on_item_activated:", e)
            listw.itemDoubleClicked.connect(on_item_activated)
            dlg.exec()
        except Exception as e:
            print("show_search_results:", e)

    def eventFilter(self, obj, event):
        # intercept Enter/Return on the search bar when completer popup is visible
        try:
            if obj is self.ui.search_bar and event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    try:
                        popup = self._completer.popup()
                        if popup and popup.isVisible():
                            # get the current completer selection (string "ID: name")
                            sel = self._completer.currentCompletion()
                            if sel:
                                id_part = sel.split(":", 1)[0].strip()
                                self.perform_search(id_part)

                                QTimer.singleShot(0, self.ui.search_bar.clear)
                                return True  # consume event
                    except Exception:
                        pass
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def perform_search(self, id_str: str):
        #Final action: show item details / graph for the id.
        try:
            # ensure id exists in localList
            for id_, name in getattr(self, "localList", []):
                if id_ == id_str:
                    # switch UI to graph page and load item
                    try:
                        self.ui.search_bar.clear()
                    except Exception:
                        pass
                    self.signals.newItem.emit(id_)
                    # ensure graph page visible
                    try:
                        self.ui.main_stack_widget.setCurrentIndex(1)
                    except Exception:
                        pass
                    return
            # not found -> show results dialog with fuzzy suggestions
            results = self._perform_query(id_str)
            self.show_search_results(results, query=id_str)
            self.ui.search_bar.clear()
        except Exception as e:
            print("perform_search:", e)

    def updateBar(self, progress):
        self.ui.progressBar.setValue(progress)
    def updateLoadingText(self, text):
        self.ui.loading_label.setText(text)
    def onGraphButtonToggle(self):
        self.ui.main_stack_widget.setCurrentIndex(1)
    def onConfigButtonToggle(self):
        self.updateConfigBoxes()
        self.ui.main_stack_widget.setCurrentIndex(0)
    def onHistoryButtonToggle(self, state):
        if state:
            self.ui.history_list.setVisible(True)
        else:
            self.ui.history_list.setVisible(False)
    
    def updateAlerts(self, alerts, updateTime):
        for alert in alerts:
            self.ui.alert_list.insertRow(0)
            self.ui.alert_list.setItem(0, 0, QTableWidgetItem(f"{alert.id}: {alert.name} "))
            self.ui.alert_list.setItem(0, 1, QTableWidgetItem(alert.highPriceChange))
            self.ui.alert_list.setItem(0, 2, QTableWidgetItem(alert.lowPriceChange))
            self.ui.alert_list.setItem(0, 3, QTableWidgetItem(alert.highVolChange))
            self.ui.alert_list.setItem(0, 4, QTableWidgetItem(alert.lowVolChange))

            time = datetime.fromtimestamp(int(alert.timestamp))
            self.ui.alert_list.setItem(0, 5, QTableWidgetItem(datetime.strftime(time, "%H:%M")))
            self.ui.alert_list.setItem(0, 6, QTableWidgetItem(alert.timestamp))
            for j in range(self.ui.alert_list.columnCount()):
                    self.ui.alert_list.item(0, j).setForeground(QBrush(QColor(229, 137, 255)))
        i = 0
        while i < self.ui.alert_list.rowCount():
            if int(self.ui.alert_list.item(i, 6).text()) != updateTime:
                print("make it yellow or gray or something to show it's old")
                for j in range(self.ui.alert_list.columnCount()):
                    self.ui.alert_list.item(i, j).setForeground(QBrush(QColor(255, 254, 178)))
                if updateTime - int(self.ui.alert_list.item(i, 6).text())  >= 8*60: # over 8 minutes old
                    print("removing old alert")
                    self.ui.alert_list.removeRow(i)
                else:
                    # i is only iterated when the row stays in the table to prevent indexing errors
                    i = i+1
            else:
                # i is only iterated when the row stays in the table to prevent indexing errors
                i = i+1

    def rebuildDBPressed(self):
        self.ui.splash_stacked.setCurrentIndex(1)
        worker = Worker(self.buildDB)
        self.threadpool.start(worker)

    def updateConfigBoxes(self, worker = None):
        try:
            with open(filterConfigFile, "r") as f:
                    filterConfig = json.load(f)
                    minBuyLimitValue = filterConfig.get('minBuyLimitValue')
                    minHourlyThroughput = filterConfig.get('minHourlyThroughput')
                    minHourlyVolume = filterConfig.get('minHourlyVolume')
                    maxPrice = filterConfig.get('maxPrice')
        except:
            print("no filter config exists.  Using default values")
            minBuyLimitValue = def_minBuyLimitValue
            minHourlyThroughput = def_minHourlyThroughput
            minHourlyVolume = def_minHourlyVolume
            maxPrice = def_maxPrice
        
        self.ui.mblv_line.setPlaceholderText(str(minBuyLimitValue))
        self.ui.mhvt_line.setPlaceholderText(str(minHourlyThroughput))
        self.ui.mhv_line.setPlaceholderText(str(minHourlyVolume))
        self.ui.mp_line.setPlaceholderText(str(maxPrice))

        self.ui.mblv_line.clear()
        self.ui.mhvt_line.clear()
        self.ui.mhv_line.clear()
        self.ui.mp_line.clear()
        
        try:
            with open(alertConfigFile, "r") as f:
                alertConfig = json.load(f)
                minLowPriceChange = alertConfig.get("minLowPriceChange")
                minHighPriceChange = alertConfig.get("minHighPriceChange")
                minLowVolChange = alertConfig.get("minLowVolChange")
                minHighVolChange = alertConfig.get("minHighVolChange")
                onlyHighDrops = alertConfig.get("onlyHighDrops")
        except Exception as e:
            print("no alert config exists.  Using default values")
            print(e)
            minLowPriceChange = def_priceChangePercent
            minHighPriceChange = def_priceChangePercent
            minLowVolChange = def_volChangePercent
            minHighVolChange = def_volChangePercent
            onlyHighDrops = False
        
        self.ui.mlpc_line.setPlaceholderText(str(minLowPriceChange))
        self.ui.mhpc_line.setPlaceholderText(str(minHighPriceChange))
        self.ui.mlvc_line.setPlaceholderText(str(minLowVolChange))
        self.ui.mhvc_line.setPlaceholderText(str(minHighVolChange))
        self.ui.mlpc_line.clear()
        self.ui.mhpc_line.clear()
        self.ui.mlvc_line.clear()
        self.ui.mhvc_line.clear()

        self.ui.high_price_drop_check.setChecked(onlyHighDrops)

    def buildPriceHistoryDB(self, worker = None):
        print("price history build starting...")
        self.ui.splash_stacked.setCurrentIndex(1)
        self.signals.progBarChange.emit(0)
        self.signals.loadTextChange.emit("Building price history")
        #self.ui.loading_label.setText()

        database = sqlite3.connect("database.db")
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        cursor.execute("SELECT id FROM filteredDB WHERE tracked=FALSE")
        itemList = cursor.fetchall()
        totalCount = len(itemList)
        count = 0
        for id in itemList:
            count = count + 1
            self.signals.progBarChange.emit(int((count/totalCount)*100))
            self.signals.loadTextChange.emit(f"Getting price history for item {count}/{totalCount}")
            tableName = "priceHistory5m.itemID" + ''.join(str(value) for value in id)
            command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + ''.join(str(value) for value in id) + "';"
            query = cursor.execute(command)
            if query.fetchone() == None:
                command = "CREATE TABLE " + tableName + " " + priceHistory5mValues
                cursor.execute(command)
                response = json.loads(requests.get(priceHistory5mURL + ''.join(str(value) for value in id), headers=headers).text).get('data')
                for item in response:
                    timestamp = item.get('timestamp')
                    avgHighPrice = item.get('avgHighPrice')
                    avgLowPrice = item.get('avgLowPrice')
                    highPriceVolume = item.get('highPriceVolume')
                    lowPriceVolume = item.get('lowPriceVolume')
                    cursor.execute("INSERT INTO " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume) VALUES(?, ?, ?, ?, ?);", (timestamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume))
                
                oneDayAvg = self.getOneDayAvg(database, tableName, timestamp)
                try:
                    lowPriceChange = (avgLowPrice / oneDayAvg.get("avgLowPrice"))*100 - 100
                except:
                    lowPriceChange = 0
                try:
                    highPriceChange = (avgHighPrice / oneDayAvg.get("avgHighPrice"))*100 - 100
                except:
                    highPriceChange = 0
                try:
                    lowVolChange = (lowPriceVolume / oneDayAvg.get("avgLowVol"))*100 - 100
                except:
                    lowVolChange = 0
                try:
                    highVolChange = (highPriceVolume / oneDayAvg.get("avgHighVol"))*100 - 100
                except:
                    highVolChange = 0
                cursor.execute("UPDATE filteredDB set lowPrice=?, highPrice=?, lowVolume=?, highVolume=?, lowPriceChange=?, highPriceChange=?, lowVolumeChange=?, highVolumeChange=?, timestamp=?, tracked=? WHERE id=?", 
                    (avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp, True, id[0]))
                database.commit()
                time.sleep(1)
        database.close()
        print("price history build complete...")
        self.signals.priceHistoryComplete.emit()

    def itemPriceLoop(self, worker = None):
        lastUpdate = -1
        while True:
            if worker.is_killed:
                break
            if (int(time.time()) - int(lastUpdate)) > 305:
                database = sqlite3.connect('database.db')
                cursor = database.cursor()
                cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
                alerts = []
                url = "https://prices.runescape.wiki/api/v1/osrs/5m"
                response = json.loads(requests.get(url, headers = headers).text)
                if response.get('timestamp') > lastUpdate:
                    lastUpdate = response.get('timestamp')
                    print(lastUpdate)
                    trackedIDs = cursor.execute('SELECT id from filteredDB WHERE tracked=TRUE').fetchall()
                    try:
                        with open(alertConfigFile, "r") as f:
                            alertConfig = json.load(f)
                            print("Using alert config")
                            print(alertConfig)
                            minLowPriceChange = alertConfig.get("minLowPriceChange")
                            minHighPriceChange = alertConfig.get("minHighPriceChange")
                            minLowVolChange = alertConfig.get("minLowVolChange")
                            minHighVolChange = alertConfig.get("minHighVolChange")
                            onlyHighDrops = alertConfig.get("onlyHighDrops")
                    except:
                        print("no alert config exists.  Using default values")
                        minLowPriceChange = def_priceChangePercent
                        minHighPriceChange = def_priceChangePercent
                        minLowVolChange = def_volChangePercent
                        minHighVolChange = def_volChangePercent
                        onlyHighDrops = False
                    if onlyHighDrops:
                        # -200% drop is not possible
                        minLowPriceChange = 200
                    for id in trackedIDs:
                        id_str = ''.join(str(value) for value in id)
                        command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + id_str + "';"
                        query = cursor.execute(command)
                        if not query.fetchone() == None:
                            if (not response.get('data').get(id_str) == None):
                                tableName = "priceHistory5m.itemID" + id_str
                                command = "SELECT timeStamp from " + tableName + " ORDER BY timeStamp DESC LIMIT 1"
                                try:
                                    lastEntryTime = int(cursor.execute(command).fetchone()[0])
                                except:
                                    lastEntryTime = 0
                                if not lastEntryTime == lastUpdate:
                                    avgLowPrice = response.get('data').get(id_str).get('avgLowPrice')
                                    avgHighPrice = response.get('data').get(id_str).get('avgHighPrice')
                                    lowPriceVolume = response.get('data').get(id_str).get('lowPriceVolume')
                                    highPriceVolume = response.get('data').get(id_str).get('highPriceVolume')
                                    command = "INSERT OR IGNORE INTO " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume) VALUES(?, ?, ?, ?, ?);"
                                    cursor.execute(command, (lastUpdate, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume))
                                    
                                    ##  price and volume change metrics, alerts.
                                    oneDayAvg = self.getOneDayAvg(database, tableName, lastUpdate)
                                    try:
                                        lowPriceChange = (avgLowPrice / oneDayAvg.get("avgLowPrice"))*100 - 100
                                    except:
                                        lowPriceChange = 0
                                    try:
                                        highPriceChange = (avgHighPrice / oneDayAvg.get("avgHighPrice"))*100 - 100
                                    except:
                                        highPriceChange = 0
                                    try:
                                        lowVolChange = (lowPriceVolume / oneDayAvg.get("avgLowVol"))*100 - 100
                                    except:
                                        lowVolChange = 0
                                    try:
                                        highVolChange = (highPriceVolume / oneDayAvg.get("avgHighVol"))*100 - 100
                                    except:
                                        highVolChange = 0
                                    command = "UPDATE filteredDB set lowPrice = ?, highPrice = ?, lowVolume = ?, highVolume = ?, lowPriceChange = ?, highPriceChange = ?, lowVolumeChange = ?, highVolumeChange = ? WHERE id = ?"
                                    cursor.execute(command, (avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume, lowPriceChange, highPriceChange, lowVolChange, highVolChange, id[0]))
                                    if (lowPriceChange <= -abs(minLowPriceChange) or highPriceChange <= -abs(minHighPriceChange)) and (lowVolChange >= minLowVolChange or highVolChange >= minHighVolChange):
                                        command = "SELECT itemName FROM filteredDB WHERE id = ?"
                                        name = cursor.execute(command, id).fetchone()[0]
                                        a = alert(id= str(id[0]), name = name, lowPriceChange = lowPriceChange, highPriceChange = highPriceChange, 
                                                    lowVolChange = lowVolChange, highVolChange = highVolChange, timestamp = lastUpdate)
                                        alerts.append(a)
                                        print(f"{name}: low price {lowPriceChange}%, high price {highPriceChange}%, low volume {lowVolChange}%, high volume {highVolChange}%, timeStamp {lastUpdate}")
                    self.signals.newAlerts.emit(alerts, lastUpdate)
                    self.signals.newUpdate.emit(lastUpdate)
                    database.commit()
                    database.close()
                    timeSinceUpdate = time.time() - lastUpdate
                    if timeSinceUpdate < 250:
                        time.sleep(250 - timeSinceUpdate)
                    else:
                        print(f"time since last update: {timeSinceUpdate}")
                        time.sleep(60)
            time.sleep(1)

    def buildDB(self, worker = None):
        print("buildDB starting...")
        try:
            #kill workers with lengthy DB connections
            #kill has no effect on short functions or functions without DB connections
            for worker in get_active_workers_snapshot():
                try:
                    worker.kill()
                except Exception as e:
                    print("worker ", worker)
                    print("Exception ", e)
            self.signals.progBarChange.emit(0)
            self.signals.loadTextChange.emit("Building filtered list")
            #determine filter values
            if self.ui.mblv_line.text() == '':
                minBuyLimitValue = self.ui.mblv_line.placeholderText()
            else:
                minBuyLimitValue = self.ui.mblv_line.text()
            if self.ui.mp_line.text() == '':
                maxPrice = self.ui.mp_line.placeholderText()
            else:
                maxPrice = self.ui.mp_line.text()
            if self.ui.mhvt_line.text() == '':
                minHourlyThroughput = self.ui.mhvt_line.placeholderText()
            else:
                minHourlyThroughput = self.ui.mhvt_line.text()
            if self.ui.mhv_line.text() == '':
                minHourlyVolume = self.ui.mhv_line.placeholderText()
            else:
                minHourlyVolume = self.ui.mhv_line.text()
            
            try:
                minBuyLimitValue = textToInt(minBuyLimitValue)
                maxPrice = textToInt(maxPrice)
                minHourlyThroughput = textToInt(minHourlyThroughput)
                minHourlyVolume = textToInt(minHourlyVolume)
            except Exception as e:
                print("invalid input: ")
                print(e)
                return False
            
            filterConfig = {"minBuyLimitValue": minBuyLimitValue, "minHourlyThroughput": minHourlyThroughput, "minHourlyVolume": minHourlyVolume, "maxPrice": maxPrice}
            with open(filterConfigFile, "w") as f:
                json.dump(filterConfig, f)
            print("filter config saved")
            try:
                minBuyLimitValue = filterConfig.get('minBuyLimitValue')
                minHourlyThroughput = filterConfig.get('minHourlyThroughput')
                minHourlyVolume = filterConfig.get('minHourlyVolume')
                maxPrice = filterConfig.get('maxPrice')
            except Exception as e:
                print("invalid filter config")
                raise e
            #delete prior DB if exists
            while os.path.isfile("database.db"):
                try:
                    os.remove("database.db")
                    print("deleted database.db")
                except Exception as e:
                    print(e)
                    time.sleep(1)
            while os.path.isfile("priceHistory5m.db"):
                try:
                    os.remove("priceHistory5m.db")
                    print("deleted priceHistory5m.db")
                except Exception as e:
                    print(e)
                    time.sleep(1)

            #build filtered item list
            itemList = json.loads(requests.get(itemListURL, headers = headers).text)
            tempItemList = {}
            watchCount = 0
            for item in itemList.keys():
                if isinstance(itemList[item], int) or isinstance(itemList[item], float):
                    print("invalid item")
                else:
                    try:
                        limitValue = itemList[item].get("limit") * itemList[item].get("price")
                        hourlyThroughput = itemList[item].get("volume") * itemList[item].get("price")
                        itemPrice = itemList[item].get("price")
                        if (hourlyThroughput > minHourlyThroughput and limitValue > minBuyLimitValue and itemPrice < maxPrice and itemList[item].get("volume") > minHourlyVolume):
                            tempItemList[item] = itemList[item]
                            watchCount = watchCount + 1
                    except:
                        print("error in entry for item {item}", item)

            
            database = sqlite3.connect("database.db")
            cursor = database.cursor()
            cursor.execute("CREATE TABLE if NOT EXISTS filteredDB" + filteredItemListValues)
            for item in tempItemList:
                id = tempItemList[item].get('id')
                name = tempItemList[item].get('name').replace(" ", "_")
                limit = tempItemList[item].get('limit')
                value = tempItemList[item].get('value')
                highAlch = tempItemList[item].get('highalch')
                cursor.execute("INSERT INTO filteredDB (id, itemName, buyLimit, value, highAlch, tracked) VALUES(?, ?, ?, ?, ?, ?);", (id, name, limit, value, highAlch, False))
            database.commit()
            database.close()
            ### placeholder for updating watchcount in gui
            self.signals.buildDBComplete.emit()
            self.buildPriceHistoryDB()
        except Exception as e:
            print(f"Error in buildDB: {e}")
            import traceback
            traceback.print_exc()

    def saveAlertConfig(self, worker = None):
        if self.ui.mlpc_line.text() == '':
            minLowPriceChange = self.ui.mlpc_line.placeholderText()
        else:
            minLowPriceChange = self.ui.mlpc_line.text()
        if self.ui.mhpc_line.text() == '':
            minHighPriceChange = self.ui.mhpc_line.placeholderText()
        else:
            minHighPriceChange = self.ui.mhpc_line.text()
        if self.ui.mlvc_line.text() == '':
            minLowVolChange = self.ui.mlvc_line.placeholderText()
        else:
            minLowVolChange = self.ui.mlvc_line.text()
        if self.ui.mhvc_line.text() == '':
            minHighVolChange = self.ui.mhvc_line.placeholderText()
        else:
            minHighVolChange = self.ui.mhvc_line.text()
        
        onlyHighDrops = self.ui.high_price_drop_check.isChecked()
        
        try:
            minLowPriceChange = textToInt(minLowPriceChange)
            minHighPriceChange = textToInt(minHighPriceChange)
            minLowVolChange = textToInt(minLowVolChange)
            minHighVolChange = textToInt(minHighVolChange)
        except Exception as e:
            print("invalid input: ")
            print(e)
            return False
        
        alertConfig = {"minLowPriceChange": minLowPriceChange, "minHighPriceChange": minHighPriceChange, "minLowVolChange": minLowVolChange, "minHighVolChange": minHighVolChange, "onlyHighDrops": onlyHighDrops}
        
        with open(alertConfigFile, "w") as f:
            json.dump(alertConfig, f)
            print("alert config saved")
        self.signals.alertConfigSaved.emit()
    
    def updateLocalList(self):
        try:
            database = sqlite3.connect('database.db')
            cursor = database.cursor()
            query = cursor.execute("SELECT id, itemName from filteredDB")
            itemList = []
            for item in query.fetchall():
                itemList.append((str(item[0]), str(item[1])))
            self.localList = itemList
            database.close()
        except Exception as e:
            print(e)
    
    def priceHistoryComplete(self):
        self.signals.progBarChange.emit(100)
        self.signals.loadTextChange.emit("you shouldn't be here")
        self.updateLocalList()
        self.ui.splash_stacked.setCurrentIndex(0)
        self.activateMainWindow()

    def getOneDayAvg(self, database, tableName, lastUpdate):
        startTime = lastUpdate - 60*60*24
        cursor = database.cursor()

        command = "SELECT avgLowPrice FROM " + tableName + " WHERE timeStamp > ? AND avgLowPrice is NOT NULL;"
        lowPrices = cursor.execute(command, (startTime,)).fetchall()
        avgLowPrice = 0
        if len(lowPrices) > 0:
            for price in lowPrices:
                avgLowPrice = avgLowPrice + price[0]
            avgLowPrice = avgLowPrice / len(lowPrices)
        
        command = "SELECT avgHighPrice FROM " + tableName + " WHERE timeStamp > ? AND avgHighPrice is NOT NULL;"
        highPrices = cursor.execute(command, (startTime,)).fetchall()
        avgHighPrice = 0
        if len(highPrices) > 0:
            for price in highPrices:
                avgHighPrice = avgHighPrice + price[0]
            avgHighPrice = avgHighPrice / len(highPrices)

        command = "SELECT lowPriceVolume FROM " + tableName + " WHERE timeStamp > ? AND lowPriceVolume is NOT NULL;"
        lowVolumes = cursor.execute(command, (startTime,)).fetchall()
        avgLowVol = 0
        if len(lowVolumes) > 0:
            for vol in lowVolumes:
                avgLowVol = avgLowVol + vol[0]
            avgLowVol = avgLowVol / len(lowVolumes)

        command = "SELECT highPriceVolume FROM " + tableName + " WHERE timeStamp > ? AND highPriceVolume is NOT NULL;"
        highVolumes = cursor.execute(command, (startTime,)).fetchall()
        avgHighVol = 0
        if len(highVolumes) > 0:
            for vol in lowVolumes:
                avgHighVol = avgHighVol + vol[0]
            avgHighVol = avgHighVol / len(highVolumes)
        return {"avgLowPrice": avgLowPrice, "avgHighPrice": avgHighPrice, "avgLowVol": avgLowVol, "avgHighVol": avgHighVol}
    
    def plotPrep(self, itemID, worker = None):
        database = sqlite3.connect('database.db')
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + itemID + "';"
        query = cursor.execute(command)
        minTime = time.time() - 24*60*60 #24 hours ago
        if not query.fetchone() == None:
            tableName = "priceHistory5m.itemID" + itemID
            command = "SELECT timestamp, avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume FROM " + tableName + " WHERE timestamp >= " + str(minTime) + ";"
            query = cursor.execute(command)
            dat = query.fetchall()
            database.close()

            data = {
                'time': np.fromiter((row[0] for row in dat), dtype=np.int64),
                'highPrice': np.fromiter((row[1] if row[1] is not None else np.nan for row in dat), dtype=np.float64),
                'lowPrice':  np.fromiter((row[2] if row[2] is not None else np.nan for row in dat), dtype=np.float64),
                'highVol':   np.fromiter((row[3] if row[3] is not None else 0 for row in dat), dtype=np.float64),
                'lowVol':    np.fromiter((row[4] if row[4] is not None else 0 for row in dat), dtype=np.float64)
            }
            df = pd.DataFrame(data)
            #convert to datetime
            df['datetime'] = pd.to_datetime(df['time'], unit='s', utc=True)

            #Downsample / aggregate if dataset is large to keep interactive performance
            max_points = 3000
            n = len(df)
            if n == 0:
                print("no data points")
                return

            if n > max_points:
                step = max(1, n // max_points)
                df_price = df.iloc[::step].copy()   
            else:
                df_price = df

            #Aggregate volumes into bins
            max_bins = 200
            #choose bin frequency based on total span
            total_seconds = (df['datetime'].iloc[-1] - df['datetime'].iloc[0]).total_seconds()
            if total_seconds <= 0:
                vol_bins = '1H'
            else:
                approx_bin_seconds = max(60, int(total_seconds / max_bins))
                mins = max(1, approx_bin_seconds // 60)
                vol_bins = f'{mins}min'

            try:
                vol_group = df.set_index('datetime').resample(vol_bins).sum()[['highVol','lowVol']].reset_index()
            except Exception:
                vol_group = df[['datetime','highVol','lowVol']]

            fig = make_subplots(rows=2, cols=1, row_heights=[0.78, 0.22], shared_xaxes=True, vertical_spacing=0.03)

            fig.add_trace(
                go.Scattergl(
                    x=df_price['datetime'].to_numpy(),
                    y=df_price['highPrice'].to_numpy(),
                    mode='lines+markers',
                    line=dict(color='orange', width=1),
                    connectgaps=True,
                    hovertemplate='%{x}<br>High: %{y}<extra></extra>'
                ),
                row=1, col=1
            )
            fig.add_trace(
                go.Scattergl(
                    x=df_price['datetime'].to_numpy(),
                    y=df_price['lowPrice'].to_numpy(),
                    mode='lines+markers',
                    line=dict(color='dodgerblue', width=1),
                    connectgaps=True,
                    hovertemplate='%{x}<br>Low: %{y}<extra></extra>'
                ),
                row=1, col=1
            )

            fig.add_trace(
                go.Bar(
                    x=vol_group['datetime'],
                    y=vol_group['highVol'],
                    marker_color='orange',
                    name='highVol',
                    showlegend=False
                ),
                row=2, col=1
            )
            fig.add_trace(
                go.Bar(
                    x=vol_group['datetime'],
                    y=vol_group['lowVol'],
                    marker_color='dodgerblue',
                    name='lowVol',
                    showlegend=False
                ),
                row=2, col=1
            )

 
            fig.update_layout(
                margin=dict(l=6, r=6, t=6, b=6),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                hovermode='x unified',
                showlegend=False,
                autosize=True,
                font=dict(color="#F9F6EE")
            )
            fig.update_xaxes(type='date', tickformat='%H:%M\n%d-%m-%Y', row=1, col=1)
            fig.update_yaxes(automargin=True)

            # Emit the prepared figure back to the main thread for rendering
            self.signals.graphReady.emit(fig)
        else:
            print(f"no table for {itemID}")
            database.close()

    def repairDB(self, repairList, worker = None):
        print("Starting DB repair...")
        itemLen = len(repairList)
        worker.setStatusString("Updating price hisotry: 0/%d" % itemLen)
        self.signals.newInProgressItem.emit(worker)
        try:
            db = sqlite3.connect('database.db')
            cursor = db.cursor()
            cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
            count = 0
            for item in repairList:
                if worker.is_killed:
                    print("stopping DB repair")
                    db.close()
                    return None
                tableName = "priceHistory5m.itemID" + item
                lastEntryTime = repairList[item]
                curTime = int(time.time())
                if (curTime - lastEntryTime) > 60*5:  #if more than 5 minutes old
                    response = json.loads(requests.get(priceHistory5mURL + ''.join(item), headers=headers).text).get('data')
                    for entry in response:
                        timestamp = entry.get('timestamp')
                        avgHighPrice = entry.get('avgHighPrice')
                        avgLowPrice = entry.get('avgLowPrice')
                        highPriceVolume = entry.get('highPriceVolume')
                        lowPriceVolume = entry.get('lowPriceVolume')
                        command = "INSERT OR IGNORE INTO " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume) VALUES(?, ?, ?, ?, ?);"
                        cursor.execute(command, (timestamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume))
                        db.commit()
                    time.sleep(1)
                count = count + 1
                worker.setStatusString("Updating price history: %d/%d" % (count, itemLen))
                self.signals.newProgressUpdate.emit(worker)
            db.close()
            print("DB repair complete")
            worker.setStatusString("")
            self.signals.inProgressItemComplete.emit(worker)
            

        except Exception as e:
            print("error in repairDB")
            print(e)

    def closeEvent(self, event):
        print("Window close event triggered!")
        super().closeEvent(event)
        print(event)

    def showEvent(self, event):
        print("MainWindow.showEvent()")
        traceback.print_stack(limit=10)
        super().showEvent(event)

    def hideEvent(self, event):
        print("MainWindow.hideEvent()")
        traceback.print_stack(limit=10)
        super().hideEvent(event)

    def changeEvent(self, event):
        # captures minimize/restore and other state changes
        if event.type() == QEvent.Type.WindowStateChange:
            print(f"MainWindow.changeEvent: state={self.windowState()}")
        super().changeEvent(event)

if __name__ == "__main__":
    try:
        if QApplication.instance() is None:
            app = QApplication(sys.argv)
        else:
            app = QApplication.instance()
        
        ## load style
        with open("theme.qss") as theme:
            theme_str = theme.read()
            app.setStyleSheet(theme_str)
        
        if not hasattr(app, "main_window"):
            app.main_window = MainWindow()
        window = app.main_window

        print("About to show window")
        window.show()
        
        # debug: print top-level widgets now and in 1s
        def dump_toplevels():
            tops = QApplication.topLevelWidgets()
            print("Top-level widgets:", [type(w).__name__ for w in tops])
            print("QApplication.instance():", QApplication.instance())
        dump_toplevels()
        QTimer.singleShot(1000, dump_toplevels)
        print("Window shown, about to exec()\n")
        app.exec()
    except Exception as e:
            print(f"Error in startup: {e}")
            import traceback
            traceback.print_exc()

