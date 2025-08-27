import sys
import ctypes
from ctypes import byref, sizeof, memset
from ctypes.wintypes import HICON, HDC, HBITMAP, BOOL, DWORD, LONG, WORD, UINT
from enum import Enum
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QPixmap, QImage, QFont, QGuiApplication
import psutil
import os

# --- Windows Structures for Icon Extraction ---
BI_RGB = 0
DIB_RGB_COLORS = 0

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", BOOL), ("xHotspot", DWORD), ("yHotspot", DWORD),
                ("hbmMask", HBITMAP), ("hbmColor", HBITMAP)]

class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_byte), ("rgbGreen", ctypes.c_byte),
                ("rgbRed", ctypes.c_byte), ("rgbReserved", ctypes.c_byte)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG),
                ("biPlanes", WORD), ("biBitCount", WORD), ("biCompression", DWORD),
                ("biSizeImage", DWORD), ("biXPelsPerMeter", LONG),
                ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD), ("biClrImportant", DWORD)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]

# --- Load Windows DLLs ---
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateCompatibleDC.restype = HDC
gdi32.GetDIBits.argtypes = [HDC, HBITMAP, UINT, UINT, ctypes.c_void_p, ctypes.c_void_p, UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [HBITMAP]
gdi32.DeleteObject.restype = BOOL
shell32.ExtractIconExW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(HICON),
                                   ctypes.POINTER(HICON), UINT]
shell32.ExtractIconExW.restype = UINT
user32.GetIconInfo.argtypes = [HICON, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = BOOL
user32.DestroyIcon.argtypes = [HICON]
user32.DestroyIcon.restype = BOOL

class IconSize(Enum):
    SMALL = 1
    LARGE = 2

    @staticmethod
    def to_wh(size):
        return {IconSize.SMALL: (16, 16), IconSize.LARGE: (32, 32)}[size]

def extract_icon(filename: str, size: IconSize):
    dc = gdi32.CreateCompatibleDC(0)
    if dc == 0:
        raise ctypes.WinError()

    hicon = HICON()
    extracted = shell32.ExtractIconExW(
        filename,
        0,
        byref(hicon) if size == IconSize.LARGE else None,
        byref(hicon) if size == IconSize.SMALL else None,
        1
    )
    if extracted != 1:
        raise ctypes.WinError()

    icon_info = ICONINFO()
    if not user32.GetIconInfo(hicon, byref(icon_info)):
        if icon_info.hbmColor:
            gdi32.DeleteObject(icon_info.hbmColor)
        if icon_info.hbmMask:
            gdi32.DeleteObject(icon_info.hbmMask)
        user32.DestroyIcon(hicon)
        raise ctypes.WinError()

    w, h = IconSize.to_wh(size)
    bmi = BITMAPINFO()
    memset(byref(bmi), 0, sizeof(bmi))
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bmi.bmiHeader.biSizeImage = w * h * 4

    bits = ctypes.create_string_buffer(bmi.bmiHeader.biSizeImage)
    copied = gdi32.GetDIBits(dc, icon_info.hbmColor, 0, h, bits, byref(bmi), DIB_RGB_COLORS)
    if copied == 0:
        if icon_info.hbmColor:
            gdi32.DeleteObject(icon_info.hbmColor)
        if icon_info.hbmMask:
            gdi32.DeleteObject(icon_info.hbmMask)
        user32.DestroyIcon(hicon)
        raise ctypes.WinError()

    # Cleanup
    if icon_info.hbmColor:
        gdi32.DeleteObject(icon_info.hbmColor)
    if icon_info.hbmMask:
        gdi32.DeleteObject(icon_info.hbmMask)
    user32.DestroyIcon(hicon)
    return bits

#def pixmap_from_icon_bytes(icon_bytes, w=16, h=16):
#    img = QImage(icon_bytes, w, h, QImage.Format.Format_RGBA8888)
#    return QPixmap.fromImage(img)

def pixmap_from_icon_bytes(icon_bytes, w=16, h=16):
    img = QImage(icon_bytes, w, h, QImage.Format.Format_RGBA8888)
    img = img.rgbSwapped()  # Convert BGRA → RGBA
    return QPixmap.fromImage(img)


# --- AppBar structures ---
ABM_NEW = 0x00000000
ABM_REMOVE = 0x00000001
ABM_SETPOS = 0x00000003
ABE_TOP = 1

class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uCallbackMessage", UINT),
        ("uEdge", UINT),
        ("rc", ctypes.wintypes.RECT),
        ("lParam", ctypes.wintypes.LPARAM),
    ]

shell322 = ctypes.windll.shell32
user32 = ctypes.windll.user32

class TopDock(QWidget):
    def __init__(self):
        super().__init__()

        # Fix for dual screens → always dock on primary
        '''
        QGuiApplication.screenAdded.connect(self.move_to_primary)
        QGuiApplication.screenRemoved.connect(self.move_to_primary)
        '''

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)

        self.setFixedHeight(20)
        self.setStyleSheet("background-color: white;")

        layout = QHBoxLayout()
        layout.setContentsMargins(5,0,5,0)
        layout.setSpacing(5)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16,16)
        layout.addWidget(self.icon_label)

        self.app_label = QLabel("No App")
        font_app = QFont("Segoe UI Variable", 10)
        #font_app.setWeight(57)
        self.app_label.setFont(font_app)
        self.app_label.setStyleSheet("color:black;")
        layout.addWidget(self.app_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch()

        self.clock = QLabel()
        font_clock = QFont("Segoe UI Variable", 10)
        #font_clock.setWeight(57)
        self.clock.setFont(font_clock)
        self.clock.setStyleSheet("color:black;")
        layout.addWidget(self.clock, alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self.setLayout(layout)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

        self.app_timer = QTimer(self)
        self.app_timer.timeout.connect(self.update_active_app)
        self.app_timer.start(500)
        self.update_active_app()

        QTimer.singleShot(100, self.register_appbar)

        self.move_to_primary()

    '''
    def move_to_primary(self, screen):
        """Always move dock to the primary screen only."""
        if screen is None:
            return
        geometry = screen.geometry()
        self.setGeometry(geometry.x(), geometry.y(), geometry.width(), self.height())
    '''

    def move_to_primary(self, *args):
        """Always move dock to primary screen bottom center"""
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.center().x() - self.width() // 2
            y = geo.bottom() - self.height() - 10
            self.move(x, y)

    def update_clock(self):
        now = QDateTime.currentDateTime().toString("hh:mm AP  MM/dd/yyyy")
        self.clock.setText(now)

    def update_active_app(self):
        try:
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value if buff.value.strip() else "Unknown App"
            self.app_label.setText(title)

            # Get exe path
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = psutil.Process(pid.value)
            exe_path = proc.exe()
            if os.path.exists(exe_path):
                icon_bytes = extract_icon(exe_path, IconSize.SMALL)
                pixmap = pixmap_from_icon_bytes(icon_bytes,16,16)
                self.icon_label.setPixmap(pixmap)
            else:
                self.icon_label.clear()
        except Exception:
            self.app_label.setText("No App")
            self.icon_label.clear()

    def register_appbar(self):
        hWnd = int(self.winId())
        appbar = APPBARDATA()
        appbar.cbSize = sizeof(APPBARDATA)
        appbar.hWnd = hWnd
        appbar.uEdge = ABE_TOP

        screen_obj = self.screen()
        if screen_obj is None:
            return
        screen_geo = screen_obj.geometry()

        appbar.rc.left = 0
        appbar.rc.top = 0
        appbar.rc.right = screen_geo.width()
        appbar.rc.bottom = self.height()

        shell32.SHAppBarMessage(ABM_NEW, byref(appbar))
        shell32.SHAppBarMessage(ABM_SETPOS, byref(appbar))

        self.setGeometry(appbar.rc.left, appbar.rc.top,
                         appbar.rc.right - appbar.rc.left,
                         appbar.rc.bottom - appbar.rc.top)

    def closeEvent(self, event):
        hWnd = int(self.winId())
        appbar = APPBARDATA()
        appbar.cbSize = sizeof(APPBARDATA)
        appbar.hWnd = hWnd
        shell32.SHAppBarMessage(ABM_REMOVE, byref(appbar))
        event.accept()

def main():
    app = QApplication(sys.argv)
    dock = TopDock()
    dock.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
