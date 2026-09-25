"""Status-Panel der Bruecke im FreeCAD-Hauptfenster.

Bewusst schlank: Zustand anzeigen, starten, stoppen, Browser oeffnen. Die
eigentliche Oberflaeche lebt im Browser -- FreeCAD 1.1 bringt kein QtWebEngine
mit, eine eingebettete React-App ist also ausgeschlossen.

Idiom: immer ``setObjectName`` + ``findChild``, denn FreeCAD stellt Dock-Widgets
ueber ihren ObjectName wieder her. Ohne das entstehen bei jedem Workbench-
Wechsel neue, uebereinandergestapelte Panels.
"""

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

from freecad_bridge import state as bridge_state

OBJECT_NAME = "SysMLCadBridgePanel"
_REFRESH_MS = 1000


class BridgePanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(BridgePanel, self).__init__(parent)
        self.setObjectName(OBJECT_NAME + "Content")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._status = QtWidgets.QLabel("-")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._detail = QtWidgets.QLabel("-")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._detail)

        # Adresse und Token -- dasselbe, was auch in der Handshake-Datei steht.
        # Das Backend liest sie von dort; hier stehen sie fuer curl und zum
        # Nachsehen, wenn etwas nicht verbindet.
        self._token_box = QtWidgets.QGroupBox("Zugang")
        token_layout = QtWidgets.QFormLayout(self._token_box)
        token_layout.setContentsMargins(8, 8, 8, 8)

        self._url_field = QtWidgets.QLineEdit()
        self._url_field.setReadOnly(True)
        token_layout.addRow("Adresse", self._url_field)

        token_row = QtWidgets.QHBoxLayout()
        self._token_field = QtWidgets.QLineEdit()
        self._token_field.setReadOnly(True)
        self._copy_btn = QtWidgets.QPushButton("Kopieren")
        self._copy_btn.setFixedWidth(80)
        token_row.addWidget(self._token_field)
        token_row.addWidget(self._copy_btn)
        token_layout.addRow("Token", token_row)

        layout.addWidget(self._token_box)

        buttons = QtWidgets.QHBoxLayout()
        self._start_btn = QtWidgets.QPushButton("Starten")
        self._stop_btn = QtWidgets.QPushButton("Stoppen")
        buttons.addWidget(self._start_btn)
        buttons.addWidget(self._stop_btn)
        layout.addLayout(buttons)

        self._open_btn = QtWidgets.QPushButton("Oberflaeche oeffnen")
        layout.addWidget(self._open_btn)

        layout.addStretch(1)

        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn.clicked.connect(self._on_stop)
        self._open_btn.clicked.connect(self._on_open_ui)
        self._copy_btn.clicked.connect(self._on_copy_token)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self.destroyed.connect(self._timer.stop)
        self._timer.start()

        self.refresh()

    # -- Aktionen -------------------------------------------------------

    def _on_start(self):
        FreeCADGui.runCommand("SysMLCadBridge_Start")
        self.refresh()

    def _on_stop(self):
        FreeCADGui.runCommand("SysMLCadBridge_Stop")
        self.refresh()

    def _on_open_ui(self):
        FreeCADGui.runCommand("SysMLCadBridge_OpenUI")

    def _on_copy_token(self):
        token = self._token_field.text()
        if not token:
            return
        QtWidgets.QApplication.clipboard().setText(token)
        self._copy_btn.setText("Kopiert")
        QtCore.QTimer.singleShot(1500, lambda: self._copy_btn.setText("Kopieren"))

    # -- Anzeige --------------------------------------------------------

    def refresh(self):
        st = bridge_state.get_state()
        running = bool(st.running)

        dot = "\u25cf"
        if st.last_error:
            colour, text = "#c0392b", "Fehler"
        elif running:
            colour, text = "#27ae60", "verbunden"
        else:
            colour, text = "#7f8c8d", "gestoppt"

        self._status.setText(
            '<span style="color:%s">%s</span> <b>Bruecke %s</b>' % (colour, dot, text)
        )
        self._detail.setText(st.describe())

        if running:
            self._url_field.setText("http://%s:%s" % (st.host, st.port))
            self._token_field.setText(st.token or "")
        else:
            self._url_field.setText("")
            self._token_field.setText("")
        self._token_box.setEnabled(running)

        self._start_btn.setEnabled(not running and not st.shutting_down)
        self._stop_btn.setEnabled(running and not st.shutting_down)
        self._open_btn.setEnabled(running)
        self._copy_btn.setEnabled(running)


def show_panel():
    """Panel anlegen oder wieder sichtbar machen (idempotent)."""
    main_window = FreeCADGui.getMainWindow()
    if main_window is None:
        return None

    dock = main_window.findChild(QtWidgets.QDockWidget, OBJECT_NAME)
    if dock is None:
        dock = QtWidgets.QDockWidget(main_window)
        dock.setObjectName(OBJECT_NAME)
        dock.setWindowTitle("SysML-CAD Bruecke")
        dock.setWidget(BridgePanel(dock))
        main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    dock.show()
    dock.raise_()
    return dock


def refresh_panel():
    """Von aussen (Befehle) aufrufbar, damit die Anzeige sofort nachzieht."""
    main_window = FreeCADGui.getMainWindow()
    if main_window is None:
        return
    dock = main_window.findChild(QtWidgets.QDockWidget, OBJECT_NAME)
    if dock is not None and dock.widget() is not None:
        try:
            dock.widget().refresh()
        except Exception as exc:
            FreeCAD.Console.PrintLog("[Bruecke] Panel-Refresh fehlgeschlagen: %s\n" % exc)
