import sys
import os.path
import json
import sqlite3
import requests
import traceback
import weakref
import threading
import webbrowser

import numpy as np
import difflib
import pandas as pd

import time
from datetime import datetime
from dateutil import tz

from plotly.subplots import make_subplots
import plotly.graph_objects as go

from PyQt6.QtSql import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QFontDatabase, QPaintEvent, QEnterEvent, QKeyEvent, QFocusEvent, QCursor
from output import Ui_MainWindow
from contextMenuOutput import Ui_Form as Ui_contextMenu
from historyBarOutput import Ui_Form as Ui_historyBar
from sidebar import SideBar
#pyuic6 -o .\GE_helper\output.py .\GE_helper\newUI.ui
#pyuic6 -o .\GE_helper\contextMenuOutput.py .\GE_helper\muteDialog.ui
#pyuic6 -o .\GE_helper\historyBarOutput.py .\GE_helper\historyBar.ui 

# URLS for API calls
itemListURL = "https://chisel.weirdgloop.org/gazproj/gazbot/rs_dump.json"
priceHistory5mURL =  "https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=5m&id=" **change**
latest5mURL = "https://prices.runescape.wiki/api/v1/osrs/5m"**change**
itemLookupURL = "https://www.ge-tracker.com/item/"**change**
itemIconURL = "https://secure.runescape.com/m=itemdb_rs/obj_sprite.gif?id="**change**
latestURL = "https://prices.runescape.wiki/api/v1/osrs/latest"**change**
headers = {
    'User-Agent': 'GE price trend tracking wip discord @kat6541'
}

web_lookup_url = "https://www.ge-tracker.com/item/"**change**

# database table schemas
filteredItemListValues = "(id INTEGER PRIMARY KEY, itemName, buyLimit, lowPrice, highPrice, value, highAlch, lowVolume, highVolume, lowPriceChange, highPriceChange, lowVolumeChange, highVolumeChange, timestamp, tracked)"
priceHistory5mValues = "(timeStamp INTEGER NOT NULL PRIMARY KEY, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume)"

# config file paths
alertConfigFile = "rscfg/alertConfig.json"
filterConfigFile = "rscfg/filterConfig.json"
quickAlertMuteFile = "rscfg/quickAlertMute.json"
alertMuteFile = "rscfg/alertMute.json"
lastState = "rscfg/stateMemory.json"

## default item filter values
def_minBuyLimitValue = 2000000
def_minHourlyThroughput = 5000000
def_minHourlyVolume = 1000
def_maxPrice = 10000000
def_priceChangePercent = 10
def_volChangePercent = 100

# global registry of active Worker instances (weakrefs avoid leaks)
active_workers = weakref.WeakSet()
active_workers_lock = threading.Lock()

def textToVal(string):
    """Attempts to convert strings to integers, allowing suffixed k, m, and b for thousand, milliod, and billion
    Used in config input parsing"""
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

def textToTime(string):
    """Attempts to convert strings to integers, allowing suffixed k, m, and b for thousand, milliod, and billion
    Used in config input parsing"""
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
            case 's':
                return(num)
            case 'm':
                return(num*60)
            case 'h':
                return(num*60*60)
            case 'd':
                return(num*60*60*24)
            case default:
                raise ValueError

def net_request(self, url, worker=None):
    try:
        data = requests.get(url, headers=headers)
        return data
    except Exception as e:
        if worker is not None:
            status = [True, f"Failed network request to {url}: {e}"]
            worker.updateStatus("Error", status)
            self.signals.statusChange.emit(worker)
            start_time = time.time()
        for i in range(0,10):
            time.sleep(30)
            try:
                data = requests.get(url, headers=headers)
                status = [False, ""]
                worker.updateStatus("Error", status)
                self.signals.statusChange.emit(worker)
                wait_time = time.time() - start_time
                print("successfully completed  net request after " + str(wait_time) + " seconds")
                return data
            except Exception as e:
                pass
        while True:
            # infinite while loop feels stupid
            time.sleep(60*5)
            try:
                data = requests.get(url, headers=headers)
                status = [False, ""]
                worker.updateStatus("Error", status)
                self.signals.statusChange.emit(worker)
                wait_time = time.time() - start_time
                print("successfully completed  net request after " + str(wait_time) + " seconds")
                # I think I want to adjust this so all the items are checked within the repairDB function instead of supplying it a list
                if wait_time > 60*12:
                    repairList = {}
                    # if the worker is not already running, repair the DB
                    if not self.repairWorker.getStatus()["Running"][0]:
                        for item in self.localList:
                            # this will just force repairDB to update ever item since all items haven't been updated in 23 minutes
                            # this assumes that the request failed due to the host device not being conencted to the internet
                            # should be adjusted later
                            repairList[item[0]] = 0
                        self.repairWorker = Worker(self.repairDB, repairList)
                        self.threadpool.start(self.repairWorker)
                return data
            except Exception as e:
                pass

class StatusIndicator(QWidget):
    """Circular indicator widget for showing app status
     Main status indicated via color, tooltip shows details on hover"""
    PRESETS = {
        "initializing": QColor("#FFFFFF"),
        "ok": QColor("#41e968"), #normal app behavior
        "working": QColor("#f5cd49"), #background tasks in progress (database rebuilds, )
        "warning": QColor("#d16806"), #potential issue
        "error": QColor("#db4c0a"), #critical error (refused connections, unhandled exceptions)
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
        """Set named status (ok/warn/error/off/busy) or pass a QColor / hex string
        Optionally update the tooltip text"""
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

class Alert:
    """Represents a 5m alert detected in itemPriceLoop
    Each alert stores id, name, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp
    All alerts are stored in dict _alerts keyed by id"""
    _alerts = {}
    def __init__(self, id, name, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp):
        self.id = str(id)
        self.name = str(name)
        self.lowPriceChange = f"{lowPriceChange:.2f}%"
        self.highPriceChange = f"{highPriceChange:.2f}%"
        self.lowVolChange = f"{lowVolChange:.2f}%"
        self.highVolChange = f"{highVolChange:.2f}%"
        self.timestamp = str(timestamp)
        self.startTimestamp = str(timestamp)
        Alert._alerts[self.id] = self
    
    @classmethod
    def updateAlert(cls, id, name, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp):
        """update an existing alert by id with new values"""
        if id in cls._alerts:
            a = cls._alerts[str(id)]
            a.name = str(name)
            a.lowPriceChange = f"{lowPriceChange:.2f}%"
            a.highPriceChange = f"{highPriceChange:.2f}%"
            a.lowVolChange = f"{lowVolChange:.2f}%"
            a.highVolChange = f"{highVolChange:.2f}%"
            a.timestamp = str(timestamp)
        else:
            print("Attempted to update nonexistent alert: " + str(id))
    
    @classmethod
    def getAlerts(cls):
        """returns dict of alerts keyed by id as stored in class"""
        return cls._alerts
    
    @classmethod
    def getAlertsList(cls):
        """ returns ordered list of alert objects
        latest timestamp first, if tied then highest startTimeStamp, if tied then highest highVolChange"""
        return sorted(cls._alerts.values(), 
            key=lambda a: (-int(a.timestamp), -int(a.startTimestamp), -float(a.highVolChange.rstrip('%'))))
    
    @classmethod
    def removeOldAlerts(cls, cutoffTime):
        """removes alerts older than cutofftime (unix timestamp)"""
        removeIDs = []
        for a in cls._alerts:
            if int(cls._alerts[a].timestamp) < cutoffTime:
                removeIDs.append(a)
        for id in removeIDs:
            del cls._alerts[id]
    
    @classmethod
    def alertExists(cls,id):
        """returns true if alert mathching id exists"""
        return id in cls._alerts
    @classmethod
    def del_alert(cls, id):
        try:
            del cls._alerts[id]
        except Exception:
            pass

class signals(QObject): #organize this better
    newUpdate = pyqtSignal(int)
    newAlerts = pyqtSignal(list, int)
    newItem = pyqtSignal(str)
    

    #GUI updating requests
    graphReady = pyqtSignal(object)
    progBarChange = pyqtSignal(int)
    loadTextChange = pyqtSignal(str)


    buildDBComplete = pyqtSignal()
    priceHistoryComplete = pyqtSignal()
    killPriceLoop = pyqtSignal()
    alertConfigSaved = pyqtSignal()

    statusChange = pyqtSignal(object)

    newUpdate = pyqtSignal(int)
    newQuickAlerts = pyqtSignal(list)
class ContextMenu(QFrame):
    """Custom context menu widget that appears at cursor position.
    Emits actionSelected(action_name) when user clicks an option.
    Closes on outside clicks, Escape key, or action selection.
    """
    new_quickAlert_mute = pyqtSignal(str, int)
    new_alert_mute = pyqtSignal(str, int)
    def __init__(self, parent = None, table=None, item_id = None):
        super().__init__(parent)
        self.ui = Ui_contextMenu()
        self.ui.setupUi(self)
        self.setup_signals()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


        self.item_id = item_id


        parentTable = table.objectName()
        if parentTable == "alert_list" or parentTable == "page_alert_list":
            self.ui.alerts_check.setChecked(True)
        elif parentTable == "page_quickAlerts_list":
            self.ui.quickAlerts_check.setChecked(True)

        self._global_filter_installed = False

    def setup_signals(self):
        self.ui.m_30_button.clicked.connect(self.m_30_button_clicked)
        self.ui.h_1_button.clicked.connect(self.h_1_button_clicked)
        self.ui.h_4_button.clicked.connect(self.h_4_button_clicked)
        self.ui.h_8_button.clicked.connect(self.h_8_button_clicked)
        self.ui.d_1_button.clicked.connect(self.d_1_button_clicked)
        self.ui.inf_button.clicked.connect(self.inf_button_clicked)

        self.ui.mute_button.clicked.connect(self.custom_time_entered)

        self.ui.custom_time_entry.returnPressed.connect(self.custom_time_entered)

    def m_30_button_clicked(self):
        mute_time = 30*60
        self.timeSelected(mute_time)
    def h_1_button_clicked(self):
        mute_time = 1*60*60
        self.timeSelected(mute_time)
    def h_4_button_clicked(self):
        mute_time = 1*60*60*4
        self.timeSelected(mute_time)
    def h_8_button_clicked(self):
        mute_time = 1*60*60*8
        self.timeSelected(mute_time)
    def d_1_button_clicked(self):
        mute_time = 1*60*60*24
        self.timeSelected(mute_time)
    def inf_button_clicked(self):
        mute_time = -1
        self.timeSelected(mute_time)

    def custom_time_entered(self):
        enteredString = self.ui.custom_time_entry.text()
        if enteredString == None:
            mute_time = -1
            self.timeSelected(mute_time)
        else:
            mute_time = textToTime(enteredString)
            if mute_time == None:
                print("no valid time entered")
            else:
                self.timeSelected(mute_time)

    def timeSelected(self, mute_time):
        if not mute_time == -1:
            if self.ui.quickAlerts_check.isChecked():
                self.new_quickAlert_mute.emit(self.item_id, mute_time)
            if self.ui.alerts_check.isChecked():
                self.new_alert_mute.emit(self.item_id, mute_time)
        self.close()
    
    def keyPressEvent(self, event: QKeyEvent):
        """Close on Escape."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
    
    def eventFilter(self, obj, event):
        """Detect clicks outside the menu and close."""
        # Only process mouse button press events
        if event.type() == QEvent.Type.MouseButtonPress:
            # Check if the click was outside this menu
            menu_geo = self.geometry()
            pos = QCursor.pos()

            # If click is outside menu bounds, close it
            if not menu_geo.contains(self.parent().mapFromGlobal(pos)):
                self.close()
                return False  # let the event continue
        
        return super().eventFilter(obj, event)
    
    def hideEvent(self, event):
        """Uninstall the global event filter when menu closes."""
        if self._global_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._global_filter_installed = False
    
        super().hideEvent(event)
    
    def show_at_cursor(self):
        """Show the menu at the current cursor position."""
        pos = self.parent().mapFromGlobal(QCursor.pos())
        self.move(pos.x(), pos.y())
        

        # Ensure the menu stays on-screen (adjust if it goes off the right/bottom edge)
        app_geo = self.parent().size()
        menu_geo = self.size() # includes window frame
        
        # Check if menu extends past right edge
        if menu_geo.width() + pos.x()  > app_geo.width():
            self.move(-menu_geo.width() + app_geo.width(), pos.y())
        
        # Check if menu extends past bottom edge
        if menu_geo.height() + pos.y() > app_geo.height():
            self.move(pos.x(), -menu_geo.height() + app_geo.height())

        if not self._global_filter_installed:
            QApplication.instance().installEventFilter(self)
            self._global_filter_installed = True
            
        self.setFocus()
        self.raise_()
        self.show()
        self.activateWindow()
class Worker(QRunnable):
    """Worker thread."""
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.is_killed = False
        self.status = {"Running": [False, ""],
                        "workItem":  [False, ""],
                        "Warning": [False, ""],
                        "Error": [False, ""]}
        


    @pyqtSlot()
    def run(self):
        """Initialise the runner function with passed args, kwargs."""
        try:
            # register self as active
            with active_workers_lock:
                active_workers.add(self)
            self.status["Running"] = [True, f"Running {self.fn.__name__}"]
            print(f"Worker starting: {self.fn.__name__}\n")
            self.is_killed = False
            self.fn(*self.args, **self.kwargs, worker= self)
            print(f"Worker completed: {self.fn.__name__}\n")
        except Exception as e:
            print(f"Error in worker thread: {e}")
            traceback.print_exc()
        finally:
            with active_workers_lock:
                try:
                    active_workers.discard(self)
                except Exception as e:
                    print(f"failed  to discard worker after completion {e}")
            self.status["Running"] = [False, ""]
    def kill(self):
        self.is_killed = True
    def getStatus(self):
        return self.status
    def updateStatus(self, statusType, status):
        """
        statusType is a string that indicates status to be updated ("workItem", "Warning", or "Error")
        status is a list containing first the boolean indicating whether the status is active,
        and second a string describing the status if it is active.
        """
        try:
            if statusType in self.status:
                if len(status) == 2:
                    if isinstance(status[0], bool) and isinstance(status[1], str):
                        self.status[statusType] = status
                    else:
                        print("status contains invalid types.  Expected [bool, str]")
                else:
                    print("status contains invalid number of elements. Expected 2 [bool, str]")
            else:
                print("invalid statusType. Expected 'workItem', 'Warning', or 'Error'")
        except Exception as e:
            print(f"Error updating worker status: {e}")

def get_active_workers_snapshot():
    """Returns a snapshot of currently active workers as a list"""
    with active_workers_lock:
        return list(active_workers)
class MainWindow(QMainWindow):
    def __init__(self):
        print("starting __init__...")
        try:
            self.repairWorker = None
            self.statusWorkers = []
            self.localList = []
            self.alertMutes = {}
            self.quickAlertMutes = {}
            self.currentItemID = None
            self.currentTimeFrame = "24h"
            if os.path.isfile(quickAlertMuteFile):
                try:
                    with open(quickAlertMuteFile, "r") as f:
                        self.quickAlertMutes = json.load(f)
                except Exception:
                    pass
            if os.path.isfile(alertMuteFile):
                try:
                    with open(alertMuteFile, "r") as f:
                        self.alertMutes = json.load(f)
                except Exception:
                    pass
            
            self.context_menu = None
            self.threadpool = QThreadPool()
            thread_count = self.threadpool.maxThreadCount()
            print(f"Multithreading with maximum {thread_count} threads")
            print("Constructing MainWindow instance", id(self))
            super(MainWindow, self).__init__()
            self.ui = Ui_MainWindow()
            self.ui.setupUi(self)
            
            # history bar setup
            try:
                # get header bar height for sidebar positioning
                header_height = self.ui.header_bar.height() if hasattr(self.ui, 'header_bar') else 40
                    
                # creating sidebar as child of main_widget, positioned below header
                self.sidebar = SideBar(self.ui.main_widget, top_offset=header_height)
                self.sidebar.raise_()  # Ensure it draws on top
                    
                # event filter to handle main_widget resizing
                class SidebarResizeFilter(QObject):
                    def __init__(self, sidebar):
                        super().__init__()
                        self.sidebar = sidebar
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Type.Resize:
                            self.sidebar.position_sidebar()
                        return False
                    
                self.sidebar_filter = SidebarResizeFilter(self.sidebar)
                self.ui.main_widget.installEventFilter(self.sidebar_filter)
            except Exception as e:
                print(f"Error setting up sidebar: {e}")
                import traceback
                traceback.print_exc()

            self.ui.page_quickAlerts_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.ui.page_alert_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.ui.alert_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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
            self.updateConfigBoxes()

            #graph page setup
            self.ui.main_stack_widget.setCurrentIndex(0)

            # hiding unimplemented / testing features
            self.ui.alert_p_tool_drawer_button.setVisible(False)

            self.ui.alert_page_tools_frame.setVisible(False)

            self.ui.stylesheet_button.setVisible(False)

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
                            if (curTime - lastEntryTime) > 60*23: #23 minutes
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
        #self.ui.history_button.toggled['bool'].connect(self.onHistoryButtonToggle)
        self.ui.config_button.clicked.connect(self.onConfigButtonToggle)
        self.ui.graph_button.clicked.connect(self.onGraphButtonToggle)
        self.ui.alerts_button.clicked.connect(self.onAlertsButtonToggle)
        self.ui.save_alert_button.clicked.connect(self.saveAlertConfig)

        self.ui.graph_refresh_button.clicked.connect(self.onGraphRefreshButtonClicked)
        self.ui.graph_web_button.clicked.connect(self.fetchItemWebpage)
        self.ui.one_day_button.clicked.connect(self.onOneDayButtonClicked)
        self.ui.two_week_button.clicked.connect(self.onTwoWeekButtonClicked)
        self.ui.three_month_button.clicked.connect(self.onThreeMonthButtonClicked)
        self.ui.one_year_button.clicked.connect(self.onOneYearButtonClicked)

        self.ui.main_stack_widget.currentChanged['int'].connect(self.pageChange)

        self.ui.stylesheet_button.clicked.connect(self.updateStylesheet)
        
        self.ui.alert_list.itemDoubleClicked.connect(self.onAlertDoubleClick)
        self.ui.page_alert_list.itemDoubleClicked.connect(self.onAlertDoubleClick)
        self.ui.page_quickAlerts_list.itemDoubleClicked.connect(self.onAlertDoubleClick)


        #loading screen control
        self.signals.progBarChange.connect(self.updateBar)
        self.signals.loadTextChange.connect(self.updateLoadingText)

        # table context menus
        self.ui.page_quickAlerts_list.customContextMenuRequested.connect(self.show_context_menu)
        self.ui.page_alert_list.customContextMenuRequested.connect(self.show_context_menu)
        self.ui.alert_list.customContextMenuRequested.connect(self.show_context_menu)


        self.signals.buildDBComplete.connect(self.startPriceLoop)
        self.signals.priceHistoryComplete.connect(self.priceHistoryComplete)
        self.signals.killPriceLoop.connect(self.loopWorker.kill)
        self.signals.newItem.connect(self.newItem)
        self.signals.graphReady.connect(self.updatePlot)
        self.signals.newAlerts.connect(self.updateAlerts)
        self.signals.alertConfigSaved.connect(self.updateConfigBoxes)

        self.signals.statusChange.connect(self.updateStatusIndicator)
        
        self.signals.newUpdate.connect(self.newUpdate)
        self.signals.newQuickAlerts.connect(self.updateQuickAlerts)
        
        # history item clicks
        self.sidebar.history_item_clicked.connect(self.onHistoryItemClicked)

    def updateStylesheet(self):
        print("updating stylesheet")
        try:
            with open("theme.qss") as theme:
                theme_str = theme.read()
                app.setStyleSheet(theme_str)
        except Exception as e:
            print(f"Error updating stylesheet: {e}")

    def show_context_menu(self, pos: QPoint):
        sender = self.sender()
        if  isinstance(sender, QTableWidget):
            index = sender.indexAt(pos)
            if index.isValid():
                itemString = sender.item(index.row(), 0).text()
                print(f"context menu requested for {itemString}")
                if self.context_menu is not None:
                    self.context_menu.close()
                # create new context menu with actions
                try:
                    item_id = itemString.split(":")[0].strip()
                    self.context_menu = ContextMenu(self, table = sender, item_id = item_id)
                    self.context_menu.new_quickAlert_mute.connect(self.add_quickAlert_block)
                    self.context_menu.new_alert_mute.connect(self.add_alert_block)
                    self.context_menu.show_at_cursor()
                except Exception as e:
                    print(e)
    
    def add_alert_block(self, item_id: str, mute_time: int):
        """Add to to or update alert block list"""
        try:
            print(f"muted alerts for id {item_id} for {mute_time}s")
            if item_id in self.alertMutes:
                del self.alertMutes[item_id]
            if mute_time > 0:
                timestamp = int(time.time())
                block_expiry = timestamp + mute_time
                self.alertMutes[item_id] = block_expiry
                self.remove_blocked_alerts()
        except Exception as e:
            print(e)
        try:
            with open(alertMuteFile, "w") as f:
                json.dump(self.alertMutes, f)
                print("alert mutes saved")
        except Exception as e:
            print(e)
    def add_quickAlert_block(self, item_id: str, mute_time: int):
        """Add to to or update alert block list"""
        try:
            print(f"muted quickAlerts for id {item_id} for {mute_time}s")
            if item_id in self.quickAlertMutes:
                del self.quickAlertMutes[item_id]
            if mute_time > 0:
                timestamp = int(time.time())
                block_expiry = timestamp + mute_time
                self.quickAlertMutes[item_id] = block_expiry
                self.remove_blocked_quickAlerts()
        except Exception as e:
            print(e)
        try:
            with open(quickAlertMuteFile, "w") as f:
                json.dump(self.quickAlertMutes, f)
                print("quick alert mutes saved")
        except Exception as e:
            print(e)

    def remove_blocked_alerts(self):
            #both alert tables should always have the same content
        num_rows = self.ui.alert_list.rowCount()
        for i in reversed(range(num_rows)):
            itemString = self.ui.alert_list.item(i, 0).text()
            id_str = itemString.split(':')[0]
            if id_str in self.alertMutes:
                if time.time() > self.alertMutes[id_str]:
                    del self.alertMutes[id_str]
                else:
                    Alert.del_alert(id_str)
                    self.ui.alert_list.removeRow(i)
                    self.ui.page_alert_list.removeRow(i)

    def remove_blocked_quickAlerts(self):
        num_rows = self.ui.page_quickAlerts_list.rowCount()
        for i in reversed(range(num_rows)):
            itemString = self.ui.page_quickAlerts_list.item(i, 0).text()
            id_str = itemString.split(':')[0]
            if id_str in self.quickAlertMutes:
                if time.time() > self.quickAlertMutes[id_str]:
                    del self.quickAlertMutes[id_str]
                else:
                    self.ui.page_quickAlerts_list.removeRow(i)

    def setupAlertList(self):
        self.ui.alert_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ui.page_alert_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ui.page_quickAlerts_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.ui.alert_list.horizontalHeader().setFixedHeight(32)

        self.ui.page_quickAlerts_list.horizontalHeader().setFixedHeight(32)
        self.ui.page_alert_list.horizontalHeader().setFixedHeight(40)
        
    def onAlertDoubleClick(self, item):
        self.ui.alert_list.clearSelection()
        if item.column() == 0:
            itemID = item.text().split(":")[0]
            self.signals.newItem.emit(itemID)
            self.ui.main_stack_widget.setCurrentIndex(1)
            self.ui.graph_button.setChecked(True)

    def newUpdate(self, timestamp):
        time = datetime.fromtimestamp(timestamp)
        self.ui.last_update_label.setText("Last Updated: " + datetime.strftime(time, "%H:%M"))
        self.updateAlerts(timestamp)

    def updateQuickAlerts(self, quickAlerts):
        self.ui.page_quickAlerts_list.setRowCount(0)
        for alert in quickAlerts:
            row = self.ui.page_quickAlerts_list.rowCount()
            self.ui.page_quickAlerts_list.insertRow(row)
            self.ui.page_quickAlerts_list.setItem(row, 0, QTableWidgetItem(f"{alert['id']}: {alert['name']}"))
            self.ui.page_quickAlerts_list.setItem(row, 1, QTableWidgetItem(alert["highPrice"]))
            self.ui.page_quickAlerts_list.setItem(row, 2, QTableWidgetItem(alert["highPriceChange"]))
            self.ui.page_quickAlerts_list.setItem(row, 3, QTableWidgetItem(alert["highTime"]))

    def updateStatusIndicator(self, worker):
        try:
            updatedStatus = worker.getStatus()
        except Exception as e:
            print(f"Error getting worker status: {e}")
            try:
                self.statusWorkers.remove(worker)
            except Exception:
                pass
        if not (updatedStatus["Error"][0] or updatedStatus["Warning"][0] or updatedStatus["workItem"][0]):
            # no active status, try to remove worker from statusWorkers list.
            if worker in self.statusWorkers:
                self.statusWorkers.remove(worker)
            else:
                print("Failed to find worker with no status in statusWorkers list")
        else:
            if not worker in self.statusWorkers:
                self.statusWorkers.append(worker)
        workItemString = ""
        warningString = ""
        errorString = ""
        for w in self.statusWorkers:
            try:
                status = w.getStatus()
            except Exception as e:
                print(f"Error getting worker status: {e}")
            try:
                self.statusWorkers.remove(w)
            except Exception:
                pass
            
            if status["workItem"][0]:
                workItemString += status["workItem"][1] + "\n"
            if status["Warning"][0]:
                warningString += status["Warning"][1] + "\n"
            if status["Error"][0]:
                errorString += status["Error"][1] + "\n"
        if not errorString == "":
            statusString = "Error:\n" + errorString
            self.status_indicator.set_status("error", statusString)
        elif not warningString == "":
            statusString = "Warning:\n" + warningString
            self.status_indicator.set_status("warning", statusString)
        elif not workItemString == "":
            statusString = "In progress:\n" + workItemString
            self.status_indicator.set_status("working", statusString)
        else:
            self.status_indicator.set_status("ok", "")

    def newItem(self, itemID):
        print("new item received:", itemID)
        self.currentItemID = itemID
        self.updateGraphPage(itemID)
        item = list(filter(lambda tup: itemID in tup, self.localList))
        if len(item) > 1:
            print("found more than one result when searching for item in localList")
        elif len(item) ==  0:
            print("found no results when searching for item in localList")
        else:
            item_name  = item[0][1]
            self.sidebar.add_history_item(item_name, itemID)

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
        itemID = self.localList[0][0]
        self.updateGraphPage(itemID)
        self.currentItemID = itemID
        self.currentTimeFrame = "24h"
        self.ui.main_stack_widget.setCurrentIndex(1)
        self.ui.graph_button.setEnabled(True)
        self.ui.graph_button.setChecked(True)
        self.ui.alerts_button.setEnabled(True)

        self.setupSearch()
        self.ui.search_bar.setEnabled(True)
        print("main window setup complete")
       
    def updateGraphPage(self, itemID = None):
        if itemID is None:
            itemID = self.currentItemID
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
            #self.ui.history_list.setVisible(True)
            print("temp")
        else:
            #self.ui.history_list.setVisible(False)
            print("temp")
    
    def onHistoryItemClicked(self, item_id, item_name):
        print(f"History item clicked: {item_name} (ID: {item_id})")
        self.newItem(item_id)
    
    def onAlertsButtonToggle(self):
        self.ui.main_stack_widget.setCurrentIndex(2)
    
    def fetchItemWebpage(self):
        try:
            url  = web_lookup_url + self.currentItemID
            webbrowser.open(url)
        except Exception as e:
            print(f"Error opening web page: {e}")
    def onOneDayButtonClicked(self):
        #  debounce to prevent spam requests if someone tries to mash the buttons
        self.ui.one_day_button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.ui.one_day_button.setEnabled(True))
        self.currentTimeFrame = "24h"
        self.updateGraphPage()

    def onTwoWeekButtonClicked(self):
        #  debounce to prevent spam requests if someone tries to mash the buttons
        self.ui.two_week_button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.ui.two_week_button.setEnabled(True))
        self.currentTimeFrame = "2w"
        self.updateGraphPage()
    def onThreeMonthButtonClicked(self):
        #  debounce to prevent spam requests if someone tries to mash the buttons
        self.ui.three_month_button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.ui.three_month_button.setEnabled(True))
        self.currentTimeFrame = "3m"
        self.updateGraphPage()
    def onOneYearButtonClicked(self):
        #  debounce to prevent spam requests if someone tries to mash the buttons
        self.ui.one_year_button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.ui.one_year_button.setEnabled(True))
        self.currentTimeFrame = "1y"
        self.updateGraphPage()
    def onGraphRefreshButtonClicked(self):
        #  debounce to prevent spam requests if someone tries to mash the buttons
        self.ui.graph_refresh_button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.ui.graph_refresh_button.setEnabled(True))
        self.updateGraphPage()

    def pageChange(self, index):
        if index == 0:
            self.ui.config_button.setEnabled(True)
            self.ui.config_button.setChecked(True)
            self.ui.alert_scroll_area.setVisible(True)
        elif index == 1:
            self.ui.graph_button.setEnabled(True)
            self.ui.graph_button.setChecked(True)
            self.ui.alert_scroll_area.setVisible(True)
        if index == 2:
            self.ui.alerts_button.setEnabled(True)
            self.ui.alerts_button.setChecked(True)
            self.ui.alert_scroll_area.setVisible(False)
        else:
            self.ui.alert_scroll_area.setVisible(True)

    def updateAlerts(self, updateTime):
        Alert.removeOldAlerts(updateTime - 10*60) # remove alerts older than 10 minutes (since last update)
        alerts = Alert.getAlertsList()
        if len(alerts) > 0:
            for i in range(len(alerts)):
                a = alerts[i]
                self.ui.alert_list.insertRow(i)
                self.ui.page_alert_list.insertRow(i)

                self.ui.alert_list.setItem(i, 0, QTableWidgetItem(f"{a.id}: {a.name} "))
                self.ui.page_alert_list.setItem(i, 0, QTableWidgetItem(f"{a.id}: {a.name} "))

                self.ui.alert_list.setItem(i, 1, QTableWidgetItem(a.highPriceChange))
                self.ui.page_alert_list.setItem(i, 1, QTableWidgetItem(a.highPriceChange))

                self.ui.alert_list.setItem(i, 2, QTableWidgetItem(a.lowPriceChange))
                self.ui.page_alert_list.setItem(i, 2, QTableWidgetItem(a.lowPriceChange))

                self.ui.alert_list.setItem(i, 3, QTableWidgetItem(a.highVolChange))
                self.ui.page_alert_list.setItem(i, 3, QTableWidgetItem(a.highVolChange))

                self.ui.alert_list.setItem(i, 4, QTableWidgetItem(a.lowVolChange))
                self.ui.page_alert_list.setItem(i, 4, QTableWidgetItem(a.lowVolChange))

                time = datetime.fromtimestamp(int(a.timestamp))
                self.ui.alert_list.setItem(i, 5, QTableWidgetItem(datetime.strftime(time, "%H:%M")))
                self.ui.page_alert_list.setItem(i, 5, QTableWidgetItem(datetime.strftime(time, "%H:%M")))

                if int(a.timestamp)!= updateTime: # old alert coloring
                    for j in range(self.ui.alert_list.columnCount()):
                        self.ui.alert_list.item(i, j).setForeground(QBrush(QColor(255, 254, 178)))
                        self.ui.page_alert_list.item(i, j).setForeground(QBrush(QColor(255, 254, 178)))
                else:
                    for j in range(self.ui.alert_list.columnCount()): # new alert coloring
                        self.ui.alert_list.item(i, j).setForeground(QBrush(QColor(229, 137, 255)))
                        self.ui.page_alert_list.item(i, j).setForeground(QBrush(QColor(229, 137, 255)))
        self.ui.alert_list.setRowCount(len(alerts))
        self.ui.page_alert_list.setRowCount(len(alerts))

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
                try:
                    response = json.loads(net_request(self=self, url=(priceHistory5mURL + ''.join(str(value) for value in id)), worker=worker).text).get('data')
                except Exception as e:
                    print(f"Failed to retrieve 5m price: {e}")
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
            try:
                response = json.loads(net_request(self=self, url=latestURL, worker=worker).text)
            except Exception as e:
                print(f"Failed to retrieve latest price: {e}")
            try:
                data = response.get("data")
                database = sqlite3.connect('database.db')
                cursor = database.cursor()
                cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
                trackedIDs = cursor.execute('SELECT id from filteredDB WHERE tracked=TRUE').fetchall()
                quickAlerts = []
                for id in trackedIDs:
                    id_str = ''.join(str(value) for value in id)
                    highPrice = data.get(id_str).get("high")
                    tableName = "priceHistory5m.itemID" + id_str
                    oneDayAvg = self.getOneDayAvg(database, tableName, lastUpdate)
                    try:
                        highPriceChange = (highPrice / oneDayAvg.get("avgHighPrice"))*100 - 100
                    except:
                        highPriceChange = 0

                    # quick alert condition
                    if highPriceChange < -40:
                        print(f"quick alert {id_str}")
                        if id_str in self.quickAlertMutes:
                            if time.time() > self.quickAlertMutes[id_str]:
                                del self.quickAlertMutes[id_str]
                                try:
                                    with open(quickAlertMuteFile, "w") as f:
                                        json.dump(self.quickAlertMutes, f)
                                        print("quick alert mutes saved")
                                except Exception as e:
                                    print(e)
                        if not id_str in self.quickAlertMutes:
                            name = cursor.execute(f'SELECT itemName from filteredDB WHERE id = {id_str}').fetchall()[0][0]
                            timestamp = data.get(id_str).get("highTime")
                            highTime = datetime.fromtimestamp(int(timestamp))
                            quickAlerts.append({"id": id_str, "name": name, "highPrice": f"{highPrice}", 
                                                "highPriceChange": f"{highPriceChange:.2f}%", "highTime": datetime.strftime(highTime, "%H:%M")})
                            print(f"{id_str}: {name} highPrice: {f"{highPrice}"}  Change: {f"{highPriceChange:.2f}%"}")
                self.signals.newQuickAlerts.emit(quickAlerts)
                            
            except Exception as e:
                print(e)
            database.close()
            if (int(time.time()) - int(lastUpdate)) > 305:
                database = sqlite3.connect('database.db')
                cursor = database.cursor()
                cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
                try:
                    response = json.loads(net_request(self=self, url=latest5mURL, worker=worker).text)
                except Exception as e:
                    print(f"Failed to retrieve 5m price: {e}")
                if response.get('timestamp') > lastUpdate:
                    lastUpdate = response.get('timestamp')
                    print(lastUpdate)
                    trackedIDs = cursor.execute('SELECT id from filteredDB WHERE tracked=TRUE').fetchall()
                    try:
                        with open(alertConfigFile, "r") as f:
                            alertConfig = json.load(f)
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
                                    
                                    # alert conditions
                                    if (lowPriceChange <= -abs(minLowPriceChange) or highPriceChange <= -abs(minHighPriceChange)) and (lowVolChange >= minLowVolChange or highVolChange >= minHighVolChange):
                                        if id_str in self.alertMutes:
                                            if time.time() > self.alertMutes[id_str]:
                                                del self.alertMutes[id_str]
                                                try:
                                                    with open(alertMuteFile, "w") as f:
                                                        json.dump(self.alertMutes, f)
                                                        print("alert mutes saved")
                                                except Exception as e:
                                                    print(e)
                                        if not id_str in self.alertMutes:
                                            command = "SELECT itemName FROM filteredDB WHERE id = ?"
                                            name = cursor.execute(command, id).fetchone()[0]
                                            if Alert.alertExists(id[0]):
                                                Alert.updateAlert(id= id[0], name = name, lowPriceChange = lowPriceChange, highPriceChange = highPriceChange, 
                                                        lowVolChange = lowVolChange, highVolChange = highVolChange, timestamp = lastUpdate)
                                            else:
                                                a = Alert(id= id[0], name = name, lowPriceChange = lowPriceChange, highPriceChange = highPriceChange, 
                                                    lowVolChange = lowVolChange, highVolChange = highVolChange, timestamp = lastUpdate)
                                            print(f"{name}: low price {lowPriceChange}%, high price {highPriceChange}%, low volume {lowVolChange}%, high volume {highVolChange}%, timeStamp {lastUpdate}")
                    self.signals.newUpdate.emit(lastUpdate)
                    database.commit()
                    database.close()
                    timeSinceUpdate = time.time() - lastUpdate
                    print(f"time since last update: {timeSinceUpdate}")
                else:
                    database.close()
            time.sleep(30)

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
                minBuyLimitValue = textToVal(minBuyLimitValue)
                maxPrice = textToVal(maxPrice)
                minHourlyThroughput = textToVal(minHourlyThroughput)
                minHourlyVolume = textToVal(minHourlyVolume)
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
            itemList = json.loads(net_request(self=self, url=itemListURL, worker=worker).text)
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
            minLowPriceChange = textToVal(minLowPriceChange)
            minHighPriceChange = textToVal(minHighPriceChange)
            minLowVolChange = textToVal(minLowVolChange)
            minHighVolChange = textToVal(minHighVolChange)
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
    
    def plotPrep(self, itemID=None, worker = None, timeFrame = None):
        data = None
        if timeFrame is None:
            timeFrame = self.currentTimeFrame
        if itemID is None:
            itemID = self.currentItemID


        if timeFrame == "24h":
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
                'timestamp': np.fromiter((row[0] for row in dat), dtype=np.int64),
                'avgHighPrice': np.fromiter((row[1] if row[1] is not None else np.nan for row in dat), dtype=np.float64),
                'avgLowPrice':  np.fromiter((row[2] if row[2] is not None else np.nan for row in dat), dtype=np.float64),
                'highPriceVolume':   np.fromiter((row[3] if row[3] is not None else 0 for row in dat), dtype=np.float64),
                'lowPriceVolume':    np.fromiter((row[4] if row[4] is not None else 0 for row in dat), dtype=np.float64)
            }
            else:
                print(f"no table for {itemID}")
                database.close()
        elif timeFrame == "2w":
            minTime = time.time() - 14*24*60*60 # 2 weeks ago
            try:
                response = json.loads(net_request(self=self, url=("https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=1h&id=" + itemID), worker=worker).text).get("data")
            except Exception as e:
                print(f"Failed to retrieve 1h timeseries: {e}")
            for item in response:
                if item.get("timestamp") < minTime:
                    response.remove(item)
                else:
                    break
            data = response
        elif timeFrame == "3m":
            minTime = time.time() - 90*24*60*60 # 3 months ago
            try:
                response = json.loads(net_request(self=self, url=("https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=6h&id=" + itemID), worker=worker).text).get("data")
            except Exception as e:
                print(f"Failed to retrieve 6h timeseries: {e}")
            for item in response:
                if item.get("timestamp") < minTime:
                    response.remove(item)
                else:
                    break
            data = response
        elif timeFrame == "1y":
            minTime = time.time() - 365*24*60*60 # 1 year ago
            try:
                response = json.loads(net_request(self=self, url=("https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=24h&id=" + itemID), worker=worker).text).get("data")
            except Exception as e:
                print(f"Failed to retrieve 24h timeseries: {e}")
            for item in response:
                if item.get("timestamp") < minTime:
                    response.remove(item)
                else:
                    break
            data = response
        else:
            print("Invalid time frame in plotprep")
        if data is not None:
            df = pd.DataFrame(data)
            df = df.fillna(np.nan)
            #convert to datetime
            local_tz = tz.tzlocal()
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc = True).dt.tz_convert(local_tz)

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
                vol_group = df.set_index('datetime').resample(vol_bins).sum()[['highPriceVolume','lowPriceVolume']].reset_index()
            except Exception:
                vol_group = df[['datetime','highVol','lowVol']]

            fig = make_subplots(rows=2, cols=1, row_heights=[0.78, 0.22], shared_xaxes=True, vertical_spacing=0.03)

            fig.add_trace(
                go.Scattergl(
                    x=df_price['datetime'].to_numpy(),
                    y=df_price['avgHighPrice'].to_numpy(),
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
                    y=df_price['avgLowPrice'].to_numpy(),
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
                    y=vol_group['highPriceVolume'],
                    marker_color='orange',
                    name='highVol',
                    showlegend=False
                ),
                row=2, col=1
            )
            fig.add_trace(
                go.Bar(
                    x=vol_group['datetime'],
                    y=vol_group['lowPriceVolume'],
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
            print("no data for plotPrep")

    def repairDB(self, repairList, worker = None):
        print("Starting DB repair...")
        itemLen = len(repairList)
        worker.updateStatus("workItem", [True, "Updating price history: 0/%d" % itemLen])
        self.signals.statusChange.emit(worker)
        try:
            db = sqlite3.connect('database.db')
            cursor = db.cursor()
            cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
            count = 0
            for item in repairList:
                if worker.is_killed:
                    print("stopping DB repair")
                    db.close()
                    worker.updateStatus("workItem", [False, ""])
                    self.signals.statusChange.emit(worker)
                    return None
                tableName = "priceHistory5m.itemID" + item
                lastEntryTime = repairList[item]
                curTime = int(time.time())
                if (curTime - lastEntryTime) > 60*5:  #if more than 5 minutes old
                    try:
                        response = json.loads(net_request(self=self, url=(priceHistory5mURL + ''.join(item)), worker=worker).text).get('data')
                    except Exception as e:
                        print(f"Failed to retrieve latest 5m timeseries: {e}")
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
                worker.updateStatus("workItem", [True, "Updating price history: %d/%d" % (count, itemLen)])
                self.signals.statusChange.emit(worker)
            db.close()
            print("DB repair complete")
            worker.updateStatus("workItem", [False, ""])
            self.signals.statusChange.emit(worker)
        except Exception as e:
            print("error in repairDB")
            print(e)

    def closeEvent(self, event):
        print("Window close event triggered!")
        # Save current window state
        applicationState = {"windowGeometry": self.saveGeometry().data().hex(), 
         "windowState": self.saveState().data().hex(),
         "alertSplitterState": self.ui.alert_page_splitter.saveState().data().hex(),
         "page": self.ui.main_stack_widget.currentIndex()}
        
        with open(lastState, "w") as f:
            json.dump(applicationState, f)
            print("Application state saved")

        super().closeEvent(event)
        for worker in get_active_workers_snapshot():
            try:
                worker.kill()
            except Exception as e:
                print("worker ", worker)
                print("Exception ", e)
        print(event)

    def showEvent(self, event):
        print("MainWindow.showEvent()")
        super().showEvent(event)

    def resizeEvent(self, event):
        """Handle window resize to reposition sidebar"""
        super().resizeEvent(event)
        # Reposition the sidebar when the main widget is resized
        if hasattr(self, 'sidebar'):
            self.sidebar.position_sidebar()

    def hideEvent(self, event):
        print("MainWindow.hideEvent()")
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
            print("Loaded stylesheet length:", len(theme_str))
            print("Preview:", theme_str[:200].replace("\n"," "))
        
        if not hasattr(app, "main_window"):
            app.main_window = MainWindow()
        window = app.main_window

        print("About to show window")
        # check if last state is saved and attempt to restore it if so

        if os.path.isfile(lastState):
            try:
                with open(lastState, "r") as f:
                    applicationState = json.load(f)
                    window.restoreGeometry(QByteArray.fromHex(applicationState.get("windowGeometry").encode()))
                    window.restoreState(QByteArray.fromHex(applicationState.get("windowState").encode()))
                    window.ui.alert_page_splitter.restoreState(QByteArray.fromHex(applicationState.get("alertSplitterState").encode()))
                    window.ui.main_stack_widget.setCurrentIndex(applicationState.get("page"))
                    print("Restored application state from last session")
            except Exception as e:
                print("Error restoring application state:", e)


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

