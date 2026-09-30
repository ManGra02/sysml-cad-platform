"""Status panel of the bridge in the FreeCAD main window.

Deliberately lean: show state, start, stop, open the browser. The
actual user interface lives in the browser -- FreeCAD 1.1 ships without
QtWebEngine, so an embedded React app is out of the question.

Idiom: always ``setObjectName`` + ``findChild``, because FreeCAD restores dock
widgets via their ObjectName. Without it, every workbench switch creates
new panels stacked on top of each other.
"""

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

from bridge_addon.i18n import tr
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

        # Address and token -- the same as in the handshake file.
        # The backend reads them from there; they are shown here for curl and
        # for checking when something does not connect.
        self._token_box = QtWidgets.QGroupBox(tr("panel.access"))
        token_layout = QtWidgets.QFormLayout(self._token_box)
        token_layout.setContentsMargins(8, 8, 8, 8)

        self._url_field = QtWidgets.QLineEdit()
        self._url_field.setReadOnly(True)
        token_layout.addRow(tr("panel.address"), self._url_field)

        token_row = QtWidgets.QHBoxLayout()
        self._token_field = QtWidgets.QLineEdit()
        self._token_field.setReadOnly(True)
        self._copy_btn = QtWidgets.QPushButton(tr("panel.copy"))
        self._copy_btn.setFixedWidth(80)
        token_row.addWidget(self._token_field)
        token_row.addWidget(self._copy_btn)
        token_layout.addRow("Token", token_row)

        layout.addWidget(self._token_box)

        buttons = QtWidgets.QHBoxLayout()
        self._start_btn = QtWidgets.QPushButton(tr("panel.start"))
        self._stop_btn = QtWidgets.QPushButton(tr("panel.stop"))
        buttons.addWidget(self._start_btn)
        buttons.addWidget(self._stop_btn)
        layout.addLayout(buttons)

        self._open_btn = QtWidgets.QPushButton(tr("panel.open"))
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

    # -- Actions --------------------------------------------------------

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
        self._copy_btn.setText(tr("panel.copied"))
        QtCore.QTimer.singleShot(1500, lambda: self._copy_btn.setText(tr("panel.copy")))

    # -- Display --------------------------------------------------------

    def refresh(self):
        st = bridge_state.get_state()
        running = bool(st.running)

        dot = "\u25cf"
        if st.last_error:
            colour, text = "#c0392b", tr("panel.error")
        elif running:
            colour, text = "#27ae60", tr("panel.connected")
        else:
            colour, text = "#7f8c8d", tr("panel.stopped")

        self._status.setText(
            '<span style="color:%s">%s</span> <b>%s: %s</b>' % (colour, dot, tr("panel.bridge"), text)
        )
        self._detail.setText(_describe(st))

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


def _describe(st):
    """One-liner below the status -- the error message itself comes from the bridge in English."""
    if st.last_error:
        return st.last_error
    if st.shutting_down:
        return tr("panel.shutting_down")
    if st.running:
        return tr("panel.running_on", address="%s:%s" % (st.host, st.port))
    return tr("panel.stopped")


def show_panel():
    """Create the panel or make it visible again (idempotent)."""
    main_window = FreeCADGui.getMainWindow()
    if main_window is None:
        return None

    dock = main_window.findChild(QtWidgets.QDockWidget, OBJECT_NAME)
    if dock is None:
        dock = QtWidgets.QDockWidget(main_window)
        dock.setObjectName(OBJECT_NAME)
        dock.setWindowTitle(tr("panel.title"))
        dock.setWidget(BridgePanel(dock))
        main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    dock.show()
    dock.raise_()
    return dock


def refresh_panel():
    """Callable from outside (commands) so the display updates immediately."""
    main_window = FreeCADGui.getMainWindow()
    if main_window is None:
        return
    dock = main_window.findChild(QtWidgets.QDockWidget, OBJECT_NAME)
    if dock is not None and dock.widget() is not None:
        try:
            dock.widget().refresh()
        except Exception as exc:
            FreeCAD.Console.PrintLog("[Bridge] Panel refresh failed: %s\n" % exc)
