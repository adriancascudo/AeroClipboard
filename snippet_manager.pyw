"""
Baúl de Snippets — barra lateral acoplable con captura OCR y soporte multimonitor.
Versión PySide6 (Qt) con estética "liquid": bordes redondeados, transparencia,
animaciones fluidas sencillas y personalización dinámica de temas.

Dependencias: pip install PySide6 pillow  (+ las de text_from_image)
"""

import faulthandler
import io
import json
import math
import os
import sys
import threading
import traceback
from datetime import datetime

from PIL import Image
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QBuffer,
    QIODevice,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    QtMsgType,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QRegion,
    QShortcut,
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QSizeGrip,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

def _is_frozen():
    """Indica si la aplicación se ejecuta compilada (PyInstaller o Nuitka).
    Returns:
        True si es un ejecutable compilado.
    """
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def _resolve_data_dir():
    """Elige la carpeta de datos: junto al script, junto al exe (modo portable) o %APPDATA%.
    Returns:
        Ruta de la carpeta donde guardar snippets.json y el registro de errores.
    """
    if _is_frozen():
        base = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.exists(os.path.join(base, "snippets.json")):
            return base
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(root, "SnippetBaul")
        try:
            os.makedirs(folder, exist_ok=True)
            return folder
        except OSError:
            return base
    return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = _resolve_data_dir()
LOG_FILE = os.path.join(DATA_DIR, "snippet_manager_errors.log")
_fault_stream = None


def log_error(text):
    """Añade un mensaje con marca de tiempo al archivo de registro de errores.
    Args:
        text: Texto a registrar.
    Returns:
        None
    """
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 500000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except Exception:
        pass
    try:
        if sys.stderr is not None:
            print(text, file=sys.stderr)
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    """Registra excepciones no capturadas (también bajo pythonw, sin consola).
    Args:
        exc_type: Clase de la excepción.
        exc: Instancia de la excepción.
        tb: Traza asociada.
    Returns:
        None
    """
    log_error("".join(traceback.format_exception(exc_type, exc, tb)))


def _qt_message_handler(mode, context, message):
    """Redirige avisos y errores internos de Qt al archivo de registro.
    Args:
        mode: Tipo de mensaje QtMsgType.
        context: Contexto del mensaje.
        message: Texto del mensaje.
    Returns:
        None
    """
    if mode in (
        QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg
    ):
        log_error(f"Qt [{mode.name}]: {message}")


def install_crash_logging():
    """Activa el registro de excepciones, mensajes de Qt y caídas nativas.
    Returns:
        None
    """
    global _fault_stream
    sys.excepthook = _excepthook
    threading.excepthook = lambda a: _excepthook(
        a.exc_type, a.exc_value, a.exc_traceback
    )
    try:
        _fault_stream = open(LOG_FILE, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_stream, all_threads=True)
    except Exception:
        pass
    qInstallMessageHandler(_qt_message_handler)


try:
    import text_from_image as ocr_script
    OCR_IMPORT_ERROR = ""
except Exception as _ocr_exc:
    ocr_script = None
    OCR_IMPORT_ERROR = str(_ocr_exc) or _ocr_exc.__class__.__name__
    log_error(f"No se pudo importar text_from_image: {OCR_IMPORT_ERROR}")

# ==============================================================================
# CONFIGURACIÓN GLOBAL Y SISTEMA DE TEMAS
# ==============================================================================
APP_NAME = "SnippetBaulSidebar"
DATA_FILE = os.path.join(DATA_DIR, "snippets.json")
AUTOSTART_ENABLED = False

FONT_UI = "Segoe UI"

DUR_PANEL = 640
DUR_TAB = 400
DUR_HOVER = 340
DUR_FOCUS = 250
FRAME_MS = 8

GLASS_ALPHA = 238
BUBBLE_MARGIN = 48
EXT_DOCK = 30
QWIDGETSIZE_MAX = 16777215

DEFAULT_USER_THEME = {
    "primary": "#FF6B00",
    "btn_text": "#FFFFFF",
    "bg": "#FFFFFF",
    "surface": "#F8F9FA",
    "border": "#E9ECEF",
    "text": "#212529",
    "text_muted": "#868E96",
}

DEFAULT_ALPHA = {"primary": 255, "bg": 255, "surface": 255, "border": 255}
ALPHA_KEYS = tuple(DEFAULT_ALPHA)
MIN_ALPHA = 25
THEME_ALPHA = dict(DEFAULT_ALPHA)
ALPHA_SOURCE = {
    "primary_light": "primary",
    "primary_hover": "primary",
    "primary_soft": "surface",
    "card_hover": "surface",
    "card_hover_sel": "surface",
    "card_border_sel": "border",
    "bg_tint": "bg",
    "surface_hover": "surface",
}

PRESETS = [
    {"name": "Naranja", "colors": dict(DEFAULT_USER_THEME), "alpha": {}},
    {"name": "Océano", "colors": {
        "primary": "#1971C2", "btn_text": "#FFFFFF", "bg": "#FFFFFF",
        "surface": "#F1F5F9", "border": "#DEE2E6", "text": "#1A1B1E",
        "text_muted": "#868E96"}, "alpha": {}},
    {"name": "Bosque", "colors": {
        "primary": "#2F9E44", "btn_text": "#FFFFFF", "bg": "#FFFFFF",
        "surface": "#F3F8F4", "border": "#DDE8DF", "text": "#1B2A1F",
        "text_muted": "#7A8B7E"}, "alpha": {}},
    {"name": "Violeta", "colors": {
        "primary": "#7048E8", "btn_text": "#FFFFFF", "bg": "#FFFFFF",
        "surface": "#F6F3FF", "border": "#E5DBFF", "text": "#212529",
        "text_muted": "#868E96"}, "alpha": {}},
    {"name": "Noche", "colors": {
        "primary": "#FF6B00", "btn_text": "#FFFFFF", "bg": "#1E1F24",
        "surface": "#2A2C33", "border": "#3A3D46", "text": "#E9ECEF",
        "text_muted": "#9AA0AA"}, "alpha": {}},
    {"name": "Cristal", "colors": {
        "primary": "#1971C2", "btn_text": "#FFFFFF", "bg": "#FFFFFF",
        "surface": "#FFFFFF", "border": "#CED4DA", "text": "#1A1B1E",
        "text_muted": "#495057"},
     "alpha": {"bg": 150, "surface": 130, "border": 200}},
]

DEFAULT_PANEL_W = 320
DEFAULT_PANEL_H = 480
MIN_PANEL_W = 260
MIN_PANEL_H = 300

THEME = {}


def _hex_to_rgb(h):
    """Convierte un color hexadecimal a una tupla RGB.
    Args:
        h: Cadena hexadecimal (ej. '#FF6B00').
    Returns:
        Tupla de tres enteros (R, G, B).
    """
    h = str(h).lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def _rgb_to_hex(rgb):
    """Convierte una tupla RGB a una cadena hexadecimal.
    Args:
        rgb: Iterable con tres valores numéricos (R, G, B).
    Returns:
        Cadena hexadecimal formateada.
    """
    return "#%02x%02x%02x" % tuple(
        max(0, min(255, int(round(c)))) for c in rgb
    )


def blend(color_a, color_b, t):
    """Interpola linealmente entre dos colores hexadecimales.
    Args:
        color_a: Color hexadecimal inicial.
        color_b: Color hexadecimal final.
        t: Factor de interpolación en el rango [0.0, 1.0].
    Returns:
        Color hexadecimal resultante.
    """
    t = max(0.0, min(1.0, t))
    a, b = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def is_valid_hex(val):
    """Valida si una cadena representa un color hexadecimal de 6 dígitos.
    Args:
        val: Cadena de texto a comprobar.
    Returns:
        Booleano indicando si el formato hexadecimal es válido.
    """
    if not isinstance(val, str) or not val.startswith("#") or len(val) != 7:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in val[1:])


def rebuild_theme(custom_dict=None):
    """Reconstruye el diccionario global THEME calculando tonos derivados.
    Args:
        custom_dict: Diccionario opcional con claves personalizadas del usuario.
    Returns:
        Diccionario con los colores base validados y la clave 'alpha'.
    """
    base = dict(DEFAULT_USER_THEME)
    if isinstance(custom_dict, dict):
        for k, v in custom_dict.items():
            if k in base and is_valid_hex(v):
                base[k] = v.upper()

    alpha = dict(DEFAULT_ALPHA)
    raw_alpha = (
        custom_dict.get("alpha") if isinstance(custom_dict, dict) else None
    )
    if isinstance(raw_alpha, dict):
        for k in ALPHA_KEYS:
            try:
                alpha[k] = int(max(MIN_ALPHA, min(255, int(raw_alpha[k]))))
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
    THEME_ALPHA.clear()
    THEME_ALPHA.update(alpha)

    p = base["primary"]
    bg = base["bg"]
    surf = base["surface"]
    bdr = base["border"]

    lum_bg = sum(_hex_to_rgb(bg)) / 3.0
    hover_target = "#FFFFFF" if lum_bg < 128 else "#000000"

    THEME.clear()
    THEME.update({
        "primary": p,
        "primary_light": blend(p, "#FFFFFF", 0.24),
        "primary_hover": blend(p, "#000000", 0.14),
        "primary_soft": blend(surf, p, 0.16),
        "card_hover": blend(surf, p, 0.10),
        "card_hover_sel": blend(surf, p, 0.24),
        "card_border_sel": blend(bdr, p, 0.45),
        "btn_text": base["btn_text"],
        "bg": bg,
        "bg_tint": blend(bg, p, 0.05),
        "surface": surf,
        "surface_hover": blend(surf, hover_target, 0.06),
        "border": bdr,
        "text": base["text"],
        "text_muted": base["text_muted"],
        "danger": "#E03131",
        "danger_hover": "#C92A2A",
        "danger_soft": blend(bg, "#E03131", 0.12),
    })
    result = dict(base)
    result["alpha"] = dict(alpha)
    return result


rebuild_theme()


def get_scroll_qss():
    """Genera la hoja de estilos QSS para las barras de desplazamiento.
    Returns:
        Cadena QSS adaptada a los colores actuales de THEME.
    """
    handle_idle = blend(THEME["border"], THEME["text_muted"], 0.35)
    return f"""
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget {{ background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 6px; margin: 4px 0 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {handle_idle}; border-radius: 3px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {THEME['text_muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    """


def alpha_of(key):
    """Devuelve la opacidad (0-255) elegida por el usuario para una clave de THEME.
    Args:
        key: Clave de THEME (también las derivadas, p. ej. 'primary_hover').
    Returns:
        Entero de opacidad; 255 si la clave no admite transparencia.
    """
    return THEME_ALPHA.get(ALPHA_SOURCE.get(key, key), 255)


def qk(color, key, alpha=None):
    """Crea un QColor calculado aplicando la opacidad de usuario de una clave.
    Args:
        color: Color hexadecimal ya calculado (p. ej. resultado de blend).
        key: Clave de THEME cuya opacidad se aplica.
        alpha: Opacidad base opcional (0-255).
    Returns:
        Instancia QColor.
    """
    c = QColor(color)
    a = 255 if alpha is None else alpha
    c.setAlpha(max(0, min(255, int(a * alpha_of(key) / 255))))
    return c


def resolve_color(val, alpha=None, solid=False):
    """Resuelve una clave de THEME, cadena hex, callable o QColor a QColor.
    Args:
        val: Identificador de color, función sin argumentos o instancia QColor.
        alpha: Canal alfa opcional (0-255).
        solid: Si es True ignora la transparencia elegida por el usuario.
    Returns:
        Instancia QColor resultante.
    """
    if callable(val):
        val = val()
    themed = isinstance(val, str) and val in THEME
    if isinstance(val, QColor):
        c = QColor(val)
    elif themed:
        c = QColor(THEME[val])
    else:
        c = QColor(val)
    if themed and not solid:
        ua = alpha_of(val)
        a = ua if alpha is None else int(alpha * ua / 255)
        c.setAlpha(max(0, min(255, a)))
    elif alpha is not None:
        c.setAlpha(alpha)
    return c


def resolve_hex(val):
    """Resuelve una clave de THEME, QColor o cadena a formato hexadecimal.
    Args:
        val: Clave de THEME, QColor o cadena hexadecimal.
    Returns:
        Cadena hexadecimal '#RRGGBB'.
    """
    if callable(val):
        val = val()
    if isinstance(val, QColor):
        return val.name()
    if isinstance(val, str) and val in THEME:
        return THEME[val]
    return str(val)


def qc(color, alpha=None, solid=False):
    """Alias corto de resolve_color para mantener limpieza en el pintado.
    Args:
        color: Clave de THEME, hex o QColor.
        alpha: Valor de opacidad opcional (0-255).
        solid: Si es True ignora la transparencia elegida por el usuario.
    Returns:
        Objeto QColor configurado.
    """
    return resolve_color(color, alpha, solid)


AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command():
    """Construye el comando de inicio: el exe compilado o pythonw + script.
    Returns:
        Cadena de comando para el registro de Windows.
    """
    exe = os.path.abspath(sys.executable)
    if _is_frozen():
        return f'"{exe}" --hidden'
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.abspath(__file__)}" --hidden'


def is_autostart_on():
    """Comprueba si la aplicación está registrada para iniciar con Windows.
    Returns:
        True si existe la entrada de inicio automático.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enable=True):
    """Configura el inicio automático de la aplicación en el registro de Windows.
    Args:
        enable: Booleano para activar o desactivar el autoarranque.
    Returns:
        None
    """
    if sys.platform != "win32":
        return
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
        if enable:
            winreg.SetValueEx(
                key, APP_NAME, 0, winreg.REG_SZ, _autostart_command()
            )
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        log_error(f"Error en inicio automático: {e}")


def _backup_corrupt_data():
    """Aparta un archivo de datos ilegible para no sobrescribirlo después.
    Returns:
        None
    """
    try:
        os.replace(DATA_FILE, DATA_FILE + ".bak")
    except OSError:
        pass


def load_data():
    """Carga los datos de configuración, tema y snippets desde el archivo JSON.
    Returns:
        Diccionario con la configuración de posición, monitor, tema y snippets.
    """
    default_data = {
        "edge": "right",
        "pos_x": None,
        "pos_y": None,
        "monitor_idx": 0,
        "panel_w": None,
        "panel_h": None,
        "theme": dict(DEFAULT_USER_THEME),
        "snippets": {
            "Plantilla Correo": (
                "Hola,\n\nQuedo a la espera de confirmación.\n\nUn saludo."
            ),
            "Comando Git": "git status && git log --oneline -n 5",
        },
    }
    if not os.path.exists(DATA_FILE):
        save_data(default_data)
        return default_data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log_error(f"snippets.json ilegible, se conserva como .bak: {e}")
        _backup_corrupt_data()
        return default_data
    if not isinstance(data, dict) or not isinstance(data.get("snippets"), dict):
        _backup_corrupt_data()
        return default_data
    data["snippets"] = {
        str(k): ("" if v is None else str(v))
        for k, v in data["snippets"].items()
    }
    if not isinstance(data.get("theme"), dict):
        data["theme"] = dict(DEFAULT_USER_THEME)
    return data


def save_data(data):
    """Guarda el diccionario de datos de la aplicación en el archivo JSON.
    Args:
        data: Diccionario con el estado, tema y snippets a persistir.
    Returns:
        None
    """
    tmp = DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        log_error(f"No se pudo guardar los datos: {e}")


# ==============================================================================
# FUENTES Y ANIMACIÓN
# ==============================================================================
def ui_font(size, bold=False, family=FONT_UI):
    """Crea una fuente de interfaz con tamaño en puntos y negrita opcional.
    Args:
        size: Tamaño de la fuente en puntos.
        bold: Booleano para activar negrita.
        family: Nombre de la familia tipográfica.
    Returns:
        Instancia QFont configurada.
    """
    f = QFont(family)
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


def clamp01(v):
    """Limita un valor numérico flotante al intervalo cerrado [0.0, 1.0].
    Args:
        v: Valor numérico de entrada.
    Returns:
        Valor restringido entre 0.0 y 1.0.
    """
    return max(0.0, min(1.0, v))


class Tweener:
    """Animador de propiedades basado en QVariantAnimation (progreso 0 a 1)."""

    def __init__(self):
        """Inicializa el gestor de animaciones identificadas por clave.
        Returns:
            None
        """
        self._anims = {}

    def start(self, key, duration, on_frame, on_done=None,
              easing=QEasingCurve.OutCubic, overshoot=None):
        """Inicia una interpolación identificada por clave.
        Args:
            key: Identificador único de la animación.
            duration: Duración en milisegundos.
            on_frame: Callback que recibe el progreso actual.
            on_done: Callback opcional al finalizar.
            easing: Tipo de curva de QEasingCurve.
            overshoot: Intensidad del rebote para curvas Back.
        Returns:
            None
        """
        self.cancel(key)
        anim = QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(max(1, int(duration)))
        curve = QEasingCurve(easing)
        if overshoot is not None:
            curve.setOvershoot(overshoot)
        anim.setEasingCurve(curve)

        def _frame(v):
            try:
                on_frame(float(v))
            except RuntimeError:
                # El widget animado ya fue destruido por Qt.
                if self._anims.get(key) is anim:
                    self.cancel(key)

        anim.valueChanged.connect(_frame)

        def _finished():
            if self._anims.get(key) is not anim:
                return
            self._anims.pop(key, None)
            try:
                if on_done:
                    on_done()
            except RuntimeError:
                pass
            anim.deleteLater()

        anim.finished.connect(_finished)
        self._anims[key] = anim
        anim.start()

    def cancel(self, key):
        """Cancela una animación activa según su clave.
        Args:
            key: Identificador de la animación a detener.
        Returns:
            None
        """
        anim = self._anims.pop(key, None)
        if anim is not None:
            anim.stop()
            anim.deleteLater()

    def cancel_all(self):
        """Cancela todas las animaciones activas en curso.
        Returns:
            None
        """
        for key in list(self._anims):
            self.cancel(key)


def pop_in(widget, rise=18, dur=520):
    """Ejecuta una animación de aparición fluida con fundido y rebote vertical.
    Args:
        widget: Ventana o widget sobre el que aplicar la animación.
        rise: Desplazamiento vertical inicial en píxeles.
        dur: Duración total en milisegundos.
    Returns:
        None
    """
    tw = getattr(widget, "_pop_tw", None)
    if tw is None:
        tw = widget._pop_tw = Tweener()
    end = widget.pos()
    widget.setWindowOpacity(0.0)

    def frame(t):
        widget.move(end.x(), end.y() + int(round(rise * (1.0 - t))))
        widget.setWindowOpacity(clamp01(t * 1.8))

    def done():
        widget.move(end)
        widget.setWindowOpacity(1.0)

    tw.start(
        "pop", dur, frame, done, easing=QEasingCurve.OutBack, overshoot=1.3
    )


def paint_glass(widget, radius=20, solid=False):
    """Pinta el fondo de cristal redondeado adaptándose al color de fondo actual.
    Args:
        widget: Widget de destino a pintar.
        radius: Radio de redondeo de las esquinas en píxeles.
        solid: Si es True ignora la transparencia elegida por el usuario.
    Returns:
        None
    """
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing, True)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, qc("bg", 246, solid))
    grad.setColorAt(1.0, qc("bg_tint", 240, solid))
    p.fillPath(path, grad)
    p.setPen(QPen(qc("border", 220, solid), 1))
    p.drawPath(path)


# ==============================================================================
# ICONOS VECTORIALES (QPainter)
# ==============================================================================
def _pen(color, width):
    """Crea un lápiz redondeado para trazado de iconos vectoriales.
    Args:
        color: Color del trazo (clave THEME, hex o QColor).
        width: Grosor del trazo en píxeles.
    Returns:
        Instancia QPen configurada.
    """
    pen = QPen(qc(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def icon_clipboard(p, cx, cy, s, color, width=1.6):
    """Dibuja un icono vectorial de portapapeles centrado en (cx, cy).
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Escala o tamaño base del icono.
        color: Color del icono.
        width: Grosor de línea.
    Returns:
        None
    """
    w, h = s * 0.62, s * 0.82
    x1, y1 = cx - w / 2, cy - h / 2 + s * 0.06
    x2 = cx + w / 2
    p.setPen(_pen(color, width))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(x1, y1, w, h), 2.2, 2.2)
    cw = s * 0.28
    p.setBrush(qc(color))
    p.drawRoundedRect(
        QRectF(cx - cw / 2, y1 - s * 0.1, cw, s * 0.16), 1.5, 1.5
    )
    p.setBrush(Qt.NoBrush)
    for ly in (0.32, 0.5, 0.68):
        yy = y1 + h * ly
        p.drawLine(QPointF(x1 + s * 0.1, yy), QPointF(x2 - s * 0.1, yy))


def icon_palette(p, cx, cy, s, color, width=1.6):
    """Dibuja un icono discreto de paleta de colores centrado en (cx, cy).
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Escala o tamaño base del icono.
        color: Color del trazo y muestras.
        width: Grosor del contorno.
    Returns:
        None
    """
    r = s * 0.44
    p.setPen(_pen(color, width))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r * 0.92)
    p.setPen(Qt.NoPen)
    p.setBrush(qc(color))
    dot_r = max(1.1, s * 0.075)
    for angle_deg in (215, 145, 75, 10):
        rad = math.radians(angle_deg)
        dx = cx + math.cos(rad) * (r * 0.54)
        dy = cy - math.sin(rad) * (r * 0.50)
        p.drawEllipse(QPointF(dx, dy), dot_r, dot_r)


def icon_plus(p, cx, cy, s, color, width=2.2):
    """Dibuja un icono vectorial de suma (+).
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Tamaño base del icono.
        color: Color del trazo.
        width: Grosor de línea.
    Returns:
        None
    """
    r = s * 0.42
    p.setPen(_pen(color, width))
    p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
    p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))


def icon_close(p, cx, cy, s, color, width=1.8):
    """Dibuja un icono vectorial de cierre (X).
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Tamaño base del icono.
        color: Color del trazo.
        width: Grosor de línea.
    Returns:
        None
    """
    r = s * 0.34
    p.setPen(_pen(color, width))
    p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
    p.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))


def icon_search(p, cx, cy, s, color, width=1.7):
    """Dibuja un icono vectorial de lupa de búsqueda.
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Tamaño base del icono.
        color: Color del trazo.
        width: Grosor de línea.
    Returns:
        None
    """
    r = s * 0.3
    ox, oy = cx - s * 0.08, cy - s * 0.08
    p.setPen(_pen(color, width))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(ox, oy), r, r)
    p.drawLine(
        QPointF(ox + r * 0.72, oy + r * 0.72),
        QPointF(cx + s * 0.34, cy + s * 0.34),
    )


def icon_camera(p, cx, cy, s, color, width=1.6):
    """Dibuja un icono vectorial de cámara fotográfica.
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Tamaño base del icono.
        color: Color del trazo.
        width: Grosor de línea.
    Returns:
        None
    """
    w, h = s * 0.84, s * 0.6
    x1, y1 = cx - w / 2, cy - h / 2 + s * 0.06
    p.setPen(_pen(color, width))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(x1, y1, w, h), 2.5, 2.5)
    p.drawLine(
        QPointF(cx - s * 0.16, y1), QPointF(cx - s * 0.08, y1 - s * 0.12)
    )
    p.drawLine(
        QPointF(cx + s * 0.16, y1), QPointF(cx + s * 0.08, y1 - s * 0.12)
    )
    p.drawLine(
        QPointF(cx - s * 0.08, y1 - s * 0.12),
        QPointF(cx + s * 0.08, y1 - s * 0.12),
    )
    r = s * 0.17
    p.drawEllipse(QPointF(cx, cy + s * 0.06), r, r)


def icon_chevron(p, cx, cy, s, color, direction="right", width=2.0):
    """Dibuja un icono chevron apuntando en la dirección indicada.
    Args:
        p: Instancia activa de QPainter.
        cx: Coordenada X del centro.
        cy: Coordenada Y del centro.
        s: Tamaño base del icono.
        color: Color del trazo.
        direction: Dirección ('left', 'right', 'up' o 'down').
        width: Grosor de línea.
    Returns:
        None
    """
    r = s * 0.34
    if direction == "right":
        pts = [
            (cx - r * 0.5, cy - r), (cx + r * 0.5, cy), (cx - r * 0.5, cy + r)
        ]
    elif direction == "left":
        pts = [
            (cx + r * 0.5, cy - r), (cx - r * 0.5, cy), (cx + r * 0.5, cy + r)
        ]
    elif direction == "up":
        pts = [
            (cx - r, cy + r * 0.5), (cx, cy - r * 0.5), (cx + r, cy + r * 0.5)
        ]
    else:
        pts = [
            (cx - r, cy - r * 0.5), (cx, cy + r * 0.5), (cx + r, cy - r * 0.5)
        ]
    p.setPen(_pen(color, width))
    p.drawLine(QPointF(*pts[0]), QPointF(*pts[1]))
    p.drawLine(QPointF(*pts[1]), QPointF(*pts[2]))


# ==============================================================================
# WIDGETS REUTILIZABLES
# ==============================================================================
class HoverLiquid(QWidget):
    """Base con hover líquido: un círculo de color crece desde el cursor."""

    def __init__(self, parent=None):
        """Inicializa el estado de hover y su animador interno.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self._hv = 0.0
        self._origin = QPointF(0, 0)
        self._hv_tween = Tweener()

    def enterEvent(self, event):
        """Inicia la expansión líquida desde el punto de entrada del cursor.
        Args:
            event: Evento de entrada QEnterEvent.
        Returns:
            None
        """
        self._origin = QPointF(event.position())
        self._hover_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Retira el efecto líquido hacia el punto de salida del cursor.
        Args:
            event: Evento de salida QEvent.
        Returns:
            None
        """
        self._origin = QPointF(self.mapFromGlobal(QCursor.pos()))
        self._hover_to(0.0)
        super().leaveEvent(event)

    def _hover_to(self, target):
        """Anima el progreso de hover hacia el objetivo indicado.
        Args:
            target: Valor flotante objetivo (0.0 o 1.0).
        Returns:
            None
        """
        start = self._hv
        self._hv_tween.start(
            "hv", DUR_HOVER,
            lambda p: self._set_hv(start + (target - start) * p),
            easing=QEasingCurve.OutCubic,
        )

    def _set_hv(self, value):
        """Actualiza el valor interno de hover y solicita repintado.
        Args:
            value: Nuevo progreso de interpolación.
        Returns:
            None
        """
        self._hv = value
        self.update()

    def paint_liquid(self, painter, path, color):
        """Pinta el círculo líquido recortado por la ruta geométrica del widget.
        Args:
            painter: Instancia activa de QPainter.
            path: QPainterPath que delimita la máscara del widget.
            color: Instancia QColor para el relleno líquido.
        Returns:
            None
        """
        if self._hv <= 0.001:
            return
        w, h = self.width(), self.height()
        o = self._origin
        far = max(
            math.hypot(o.x() - cx, o.y() - cy)
            for cx in (0, w) for cy in (0, h)
        )
        r = far * clamp01(self._hv)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(o, r, r)
        painter.restore()


class IconButton(HoverLiquid):
    """Botón circular con icono vectorial y relleno líquido dinámico."""

    def __init__(self, icon_fn, command, size=30, idle_fill=None,
                 hover_fill="primary", idle_icon="text_muted",
                 hover_icon="btn_text", tooltip="", parent=None,
                 **icon_kwargs):
        """Inicializa el botón circular de icono.
        Args:
            icon_fn: Función de dibujo vectorial del icono.
            command: Callback ejecutado al hacer clic.
            size: Diámetro del botón en píxeles.
            idle_fill: Color o clave THEME en reposo (None = transparente).
            hover_fill: Color o clave THEME del efecto líquido en hover.
            idle_icon: Color o clave THEME del icono en reposo.
            hover_icon: Color o clave THEME del icono en hover.
            tooltip: Texto descriptivo emergente opcional.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.icon_fn = icon_fn
        self.command = command
        self.idle_fill = idle_fill
        self.hover_fill = hover_fill
        self.idle_icon = idle_icon
        self.hover_icon = hover_icon
        self.icon_kwargs = icon_kwargs
        self._down = False

    def mousePressEvent(self, e):
        """Registra la pulsación izquierda para feedback visual.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self._down = True
            self.update()
        e.accept()

    def mouseReleaseEvent(self, e):
        """Ejecuta el comando asignado si se suelta dentro del área del botón.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self._down:
            self._down = False
            self.update()
            if self.rect().contains(e.position().toPoint()) and self.command:
                self.command()
        e.accept()

    def paintEvent(self, event):
        """Pinta el fondo circular, la transición líquida y el icono vectorial.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self.width()
        if self._down:
            p.translate(s / 2, s / 2)
            p.scale(0.9, 0.9)
            p.translate(-s / 2, -s / 2)
        path = QPainterPath()
        path.addEllipse(QRectF(1, 1, s - 2, s - 2))
        solid = getattr(self.window(), "SOLID_WINDOW", False)
        if self.idle_fill is not None:
            p.fillPath(path, qc(self.idle_fill, None, solid))
        self.paint_liquid(p, path, qc(self.hover_fill, None, solid))
        c_idle = resolve_hex(self.idle_icon)
        c_hover = resolve_hex(self.hover_icon)
        color = blend(c_idle, c_hover, self._hv)
        self.icon_fn(p, s / 2, s / 2, s * 0.62, color, **self.icon_kwargs)


class TextButton(HoverLiquid):
    """Botón en forma de píldora con texto, icono opcional y soporte de temas."""

    def __init__(self, text, command, icon_fn=None, height=34, width=None,
                 idle_fill="primary", hover_fill="primary_hover",
                 fg="btn_text", border=None, bold=True, idle_alpha=None,
                 parent=None):
        """Inicializa el botón de acción con texto.
        Args:
            text: Etiqueta visible del botón.
            command: Callback ejecutado al hacer clic.
            icon_fn: Función opcional para pintar un icono a la izquierda.
            height: Altura fija en píxeles.
            width: Anchura fija opcional en píxeles.
            idle_fill: Clave THEME o color de relleno en reposo.
            hover_fill: Clave THEME o color del relleno líquido en hover.
            fg: Clave THEME o color del texto e icono.
            border: Clave THEME o color de borde opcional.
            bold: Booleano para texto en negrita.
            idle_alpha: Opacidad opcional (0-255) para el relleno en reposo.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        self.setCursor(Qt.PointingHandCursor)
        self.text = text
        self.command = command
        self.icon_fn = icon_fn
        self.idle_fill = idle_fill
        self.hover_fill = hover_fill
        self.fg = fg
        self.border = border
        self.idle_alpha = idle_alpha
        self._font = ui_font(9, bold)
        self._down = False

    def mousePressEvent(self, e):
        """Registra la pulsación aplicando efecto de compresión.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self._down = True
            self.update()
        e.accept()

    def mouseReleaseEvent(self, e):
        """Ejecuta el callback al soltar el botón izquierdo dentro del área.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self._down:
            self._down = False
            self.update()
            if self.rect().contains(e.position().toPoint()) and self.command:
                self.command()
        e.accept()

    def paintEvent(self, event):
        """Renderiza la píldora, animación líquida, borde, icono y etiqueta.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if self._down:
            p.translate(w / 2, h / 2)
            p.scale(0.975, 0.93)
            p.translate(-w / 2, -h / 2)
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, h / 2, h / 2)
        solid = getattr(self.window(), "SOLID_WINDOW", False)
        p.fillPath(path, qc(self.idle_fill, self.idle_alpha, solid))
        self.paint_liquid(p, path, qc(self.hover_fill, None, solid))
        if self.border:
            p.setPen(QPen(qc(self.border, None, solid), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        fm = QFontMetrics(self._font)
        tw = fm.horizontalAdvance(self.text)
        fg_col = qc(self.fg)
        p.setFont(self._font)
        p.setPen(fg_col)
        if self.icon_fn:
            block = 16 + 8 + tw
            x0 = (w - block) / 2
            self.icon_fn(p, x0 + 8, h / 2, 16, fg_col)
            p.setPen(fg_col)
            p.drawText(
                QRectF(x0 + 24, 0, tw + 6, h),
                Qt.AlignVCenter | Qt.AlignLeft,
                self.text,
            )
        else:
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self.text)


class SnippetCard(HoverLiquid):
    """Tarjeta de snippet redondeada con hover líquido y colores reactivos."""

    def __init__(self, key, preview, on_select, on_activate, on_delete,
                 selected=False, parent=None):
        """Inicializa la tarjeta representativa de un snippet.
        Args:
            key: Título identificador del snippet.
            preview: Texto resumen del contenido.
            on_select: Callback al hacer clic simple.
            on_activate: Callback al hacer doble clic.
            on_delete: Callback para eliminar el snippet.
            selected: Estado booleano de selección inicial.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.key = key
        self.preview = preview
        self.on_select = on_select
        self.on_activate = on_activate
        self.on_delete = on_delete
        self._selected = selected
        self._sel = 1.0 if selected else 0.0
        self._sel_tween = Tweener()
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)
        self._title_font = ui_font(9, True)
        self._prev_font = ui_font(8)

        self.btn_delete = IconButton(
            icon_close, lambda: self.on_delete(self.key), size=26,
            idle_fill=None, hover_fill="danger_soft",
            idle_icon="text_muted", hover_icon="danger", parent=self,
        )

    def resizeEvent(self, event):
        """Mantiene el botón de eliminar anclado a la derecha de la tarjeta.
        Args:
            event: Evento de redimensionado QResizeEvent.
        Returns:
            None
        """
        b = self.btn_delete
        b.move(
            self.width() - b.width() - 10,
            (self.height() - b.height()) // 2,
        )
        super().resizeEvent(event)

    def set_selected(self, selected):
        """Cambia el estado de selección ejecutando una transición suave.
        Args:
            selected: Booleano indicando si la tarjeta queda seleccionada.
        Returns:
            None
        """
        self._selected = selected
        start, end = self._sel, 1.0 if selected else 0.0
        self._sel_tween.start(
            "sel", DUR_HOVER + 60,
            lambda t: self._set_sel(start + (end - start) * t),
            easing=QEasingCurve.OutBack if selected else QEasingCurve.OutCubic,
            overshoot=1.6,
        )

    def _set_sel(self, v):
        """Actualiza el factor de selección y fuerza repintado.
        Args:
            v: Valor flotante de selección actual.
        Returns:
            None
        """
        self._sel = v
        self.update()

    def mousePressEvent(self, e):
        """Gestiona clic izquierdo para copiar y derecho para eliminar.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self.on_select(self.key)
        elif e.button() == Qt.RightButton:
            self.on_delete(self.key)

    def mouseDoubleClickEvent(self, e):
        """Abre el editor del snippet al hacer doble clic izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self.on_activate(self.key)

    def paintEvent(self, event):
        """Pinta el fondo de la tarjeta, acento lateral y textos con THEME.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        rect = QRectF(1, 1, w - 2, h - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        s = clamp01(self._sel)
        base = qk(
            blend(THEME["surface"], THEME["primary_soft"], s),
            "surface", int(200 + 55 * s),
        )
        p.fillPath(path, base)
        liq_key = "card_hover_sel" if self._selected else "card_hover"
        self.paint_liquid(p, path, qc(liq_key, 235))
        p.setPen(
            QPen(
                qk(blend(THEME["border"], THEME["card_border_sel"], s),
                   "border", 220), 1
            )
        )
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        if self._sel > 0.01:
            bh = 24 * self._sel
            p.setPen(Qt.NoPen)
            p.setBrush(qc("primary"))
            p.drawRoundedRect(
                QRectF(7, h / 2 - bh / 2, 3.2, max(0.0, bh)), 1.6, 1.6
            )

        x = 20
        avail = max(10, w - x - 46)
        title = QFontMetrics(self._title_font).elidedText(
            self.key, Qt.ElideRight, avail
        )
        prev = QFontMetrics(self._prev_font).elidedText(
            self.preview, Qt.ElideRight, avail
        )
        p.setFont(self._title_font)
        p.setPen(qc("text"))
        p.drawText(
            QRectF(x, 7, avail, 20), Qt.AlignVCenter | Qt.AlignLeft, title
        )
        p.setFont(self._prev_font)
        p.setPen(qc("text_muted"))
        p.drawText(
            QRectF(x, 27, avail, 18), Qt.AlignVCenter | Qt.AlignLeft, prev
        )


class ScrollableList(QScrollArea):
    """Lista desplazable vertical con desplazamiento suavizado exponencial."""

    def __init__(self, parent=None):
        """Inicializa el área desplazable y su contenedor interno.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.apply_theme()
        self.viewport().setAutoFillBackground(False)
        self.inner = QWidget()
        self.inner.setAutoFillBackground(False)
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 0, 4, 0)
        self.inner_layout.setSpacing(5)
        self.inner_layout.addStretch(1)
        self.setWidget(self.inner)

        self._target = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._smooth)

    def apply_theme(self):
        """Actualiza la hoja de estilos de la barra de scroll según THEME.
        Returns:
            None
        """
        self.setStyleSheet(get_scroll_qss())

    def add_widget(self, widget):
        """Inserta un widget justo antes del espaciador elástico final.
        Args:
            widget: Instancia QWidget a insertar en la lista.
        Returns:
            None
        """
        self.inner_layout.insertWidget(self.inner_layout.count() - 1, widget)

    def clear(self):
        """Elimina todas las tarjetas de la lista y reinicia la posición.
        Returns:
            None
        """
        self._timer.stop()
        self._target = 0.0
        self.verticalScrollBar().setValue(0)
        while self.inner_layout.count() > 1:
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def wheelEvent(self, e):
        """Captura la rueda del ratón para aplicar desplazamiento suave.
        Args:
            e: Evento de rueda QWheelEvent.
        Returns:
            None
        """
        self._scroll_px(-(e.angleDelta().y() / 120.0) * 70)
        e.accept()

    def _scroll_px(self, px):
        """Acumula píxeles objetivo y arranca el temporizador de interpolación.
        Args:
            px: Desplazamiento relativo en píxeles.
        Returns:
            None
        """
        bar = self.verticalScrollBar()
        if bar.maximum() <= 0:
            return
        if not self._timer.isActive():
            self._target = float(bar.value())
        self._target = min(float(bar.maximum()), max(0.0, self._target + px))
        if not self._timer.isActive():
            self._timer.start()

    def _smooth(self):
        """Acerca progresivamente el valor actual del scroll hacia el objetivo.
        Returns:
            None
        """
        bar = self.verticalScrollBar()
        cur = bar.value()
        delta = self._target - cur
        if abs(delta) < 1:
            bar.setValue(int(round(self._target)))
            self._timer.stop()
            return
        step = delta * 0.30
        if abs(step) < 1:
            step = 1 if delta > 0 else -1
        bar.setValue(int(cur + step))


class Header(QWidget):
    """Cabecera en píldora con título, botón discreto de tema y cierre."""

    def __init__(self, on_theme, on_close, parent=None):
        """Inicializa la cabecera superior del panel.
        Args:
            on_theme: Callback para abrir el personalizador de colores.
            on_close: Callback para cerrar la aplicación.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setFixedHeight(42)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(2)
        lay.addStretch(1)

        hover_tint = lambda: qc("btn_text", 55)
        self.btn_theme = IconButton(
            icon_palette, on_theme, size=26, idle_fill=None,
            hover_fill=hover_tint, idle_icon="btn_text", hover_icon="btn_text",
            tooltip="Personalizar colores",
        )
        self.btn_close = IconButton(
            icon_close, on_close, size=26, idle_fill=None,
            hover_fill=hover_tint, idle_icon="btn_text", hover_icon="btn_text",
            tooltip="Cerrar aplicación",
        )
        lay.addWidget(self.btn_theme)
        lay.addWidget(self.btn_close)
        self._font = ui_font(10, True)

    def paintEvent(self, event):
        """Pinta la píldora degradada con el icono y título de la aplicación.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        grad.setColorAt(0.0, qc("primary_light"))
        grad.setColorAt(1.0, qc("primary"))
        p.fillPath(path, grad)
        fg = qc("btn_text")
        icon_clipboard(p, 24, self.height() / 2, 18, fg, width=1.5)
        p.setFont(self._font)
        p.setPen(fg)
        p.drawText(
            QRectF(42, 0, self.width() - 108, self.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            "Baúl de snippets",
        )


class SearchEdit(QLineEdit):
    """Campo de texto de búsqueda con señales de Escape y cambio de foco."""

    escaped = Signal()
    focusChanged = Signal(bool)

    def keyPressEvent(self, e):
        """Emite señal escaped al pulsar la tecla Escape.
        Args:
            e: Evento de teclado QKeyEvent.
        Returns:
            None
        """
        if e.key() == Qt.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        """Notifica la ganancia de foco del campo.
        Args:
            e: Evento de foco QFocusEvent.
        Returns:
            None
        """
        super().focusInEvent(e)
        self.focusChanged.emit(True)

    def focusOutEvent(self, e):
        """Notifica la pérdida de foco del campo.
        Args:
            e: Evento de foco QFocusEvent.
        Returns:
            None
        """
        super().focusOutEvent(e)
        self.focusChanged.emit(False)


class SearchBox(QWidget):
    """Caja de búsqueda en píldora adaptable al tema activo."""

    def __init__(self, parent=None):
        """Inicializa el buscador e integra el QLineEdit interno.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setFixedHeight(38)
        self._f = 0.0
        self._tween = Tweener()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(36, 0, 14, 0)
        self.edit = SearchEdit()
        self.edit.setFont(ui_font(9))
        self.edit.setPlaceholderText("Buscar por título")
        lay.addWidget(self.edit)
        self.edit.focusChanged.connect(self._on_focus)
        self.apply_theme()

    def apply_theme(self):
        """Actualiza los colores de texto, selección y placeholder del campo.
        Returns:
            None
        """
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; "
            f"color: {THEME['text']}; "
            f"selection-background-color: {THEME['primary']}; "
            f"selection-color: {THEME['btn_text']}; }}"
        )
        pal = self.edit.palette()
        pal.setColor(QPalette.PlaceholderText, qc("text_muted"))
        self.edit.setPalette(pal)
        self.update()

    def _on_focus(self, focused):
        """Anima el realce del borde cuando el campo gana o pierde foco.
        Args:
            focused: Booleano indicando estado de foco.
        Returns:
            None
        """
        start, end = self._f, 1.0 if focused else 0.0
        self._tween.start(
            "f", DUR_FOCUS, lambda t: self._set_f(start + (end - start) * t)
        )

    def _set_f(self, v):
        """Actualiza el progreso de foco y repinta el contenedor.
        Args:
            v: Valor flotante de progreso.
        Returns:
            None
        """
        self._f = v
        self.update()

    def paintEvent(self, event):
        """Pinta el fondo de superficie, el borde interpolado y la lupa.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.fillPath(path, qc("surface", 225))
        f = clamp01(self._f)
        p.setPen(
            QPen(
                qk(blend(THEME["border"], THEME["primary"], f), "border"),
                1.0 + 0.7 * f,
            )
        )
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        icon_search(
            p, 19, self.height() / 2, 16,
            blend(THEME["text_muted"], THEME["primary"], f),
        )


class Rail(HoverLiquid):
    """Raíl lateral con chevron para arrastrar o plegar/desplegar el panel."""

    pressed = Signal(QPoint)
    moved = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, parent=None):
        """Inicializa el raíl acoplable.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.direction = "right"
        self.vertical = True

    def mousePressEvent(self, e):
        """Emite señal de inicio de pulsación global.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self.pressed.emit(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        """Emite señal de movimiento durante arrastre activo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.buttons() & Qt.LeftButton:
            self.moved.emit(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        """Emite señal al soltar el botón izquierdo del ratón.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self.released.emit(e.globalPosition().toPoint())

    def paintEvent(self, event):
        """Pinta el raíl con el color primario actual y su chevron.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        r = (
            r.adjusted(3, 0, -3, 0)
            if self.vertical
            else r.adjusted(0, 3, 0, -3)
        )
        path = QPainterPath()
        rad = min(r.width(), r.height()) / 2
        path.addRoundedRect(r, rad, rad)
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0.0, qc("primary_light"))
        grad.setColorAt(1.0, qc("primary"))
        p.fillPath(path, grad)
        if self._hv > 0.001:
            o = self._origin
            far = max(
                math.hypot(o.x() - cx, o.y() - cy)
                for cx in (r.left(), r.right())
                for cy in (r.top(), r.bottom())
            )
            p.save()
            p.setClipPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(qc("primary_hover"))
            rr = far * clamp01(self._hv)
            p.drawEllipse(o, rr, rr)
            p.restore()
        icon_chevron(
            p, self.width() / 2, self.height() / 2, 18, qc("btn_text"),
            direction=self.direction, width=2.0,
        )


# ==============================================================================
# DIÁLOGOS (Carga, Mensajes y Personalizador de Tema)
# ==============================================================================
class LoadingDialog(QWidget):
    """Ventana flotante con spinner líquido para procesos OCR."""

    SOLID_WINDOW = True

    def __init__(self, monitor_rect, text="Reconociendo texto..."):
        """Inicializa y centra el indicador de carga en el monitor activo.
        Args:
            monitor_rect: Diccionario con geometría del monitor ('left', 'top'...).
            text: Texto informativo a mostrar.
        Returns:
            None
        """
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._text = text
        self._phase = 0.0
        self._popped = False
        w, h = 250, 105
        self.setFixedSize(w, h)
        self.move(
            monitor_rect["left"] + (monitor_rect["width"] - w) // 2,
            monitor_rect["top"] + (monitor_rect["height"] - h) // 2,
        )

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1400)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)
        self._anim.start()
        self.show()

    def showEvent(self, e):
        """Aplica la animación de entrada al mostrarse por primera vez.
        Args:
            e: Evento QShowEvent.
        Returns:
            None
        """
        super().showEvent(e)
        if not self._popped:
            self._popped = True
            pop_in(self)

    def _tick(self, v):
        """Actualiza la fase de oscilación del indicador.
        Args:
            v: Valor actual de la animación.
        Returns:
            None
        """
        self._phase = float(v)
        self.update()

    def paintEvent(self, event):
        """Pinta el fondo de cristal, los puntos animados y el mensaje.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        paint_glass(self, 22, solid=True)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = self.width() / 2, 38
        for i in range(3):
            ph = self._phase * 2 * math.pi - i * 0.9
            y = cy + math.sin(ph) * 8
            r = 5.5 + math.cos(ph) * 1.8
            col = qc(
                blend(THEME["primary_light"], THEME["primary_hover"], i / 2)
            )
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(cx + (i - 1) * 20, y), r, r)
        p.setFont(ui_font(9, True))
        p.setPen(qc("text"))
        p.drawText(
            QRectF(0, 62, self.width(), 30), Qt.AlignCenter, self._text
        )

    def close(self):
        """Detiene el bucle de animación y destruye el widget de forma segura.
        Returns:
            None
        """
        self._anim.stop()
        super().close()
        self.deleteLater()


class GlassDialog(QDialog):
    """Diálogo modal de cristal redondeado adaptado a THEME."""

    SOLID_WINDOW = True

    def __init__(self, parent, title, text, kind="info",
                 confirm_text="Aceptar", cancel_text="Cancelar", danger=False):
        """Inicializa el diálogo modal informativo o de confirmación.
        Args:
            parent: Widget padre.
            title: Título del diálogo.
            text: Cuerpo del mensaje.
            kind: Tipo ('info', 'warning', 'error' o 'question').
            confirm_text: Etiqueta del botón principal.
            cancel_text: Etiqueta del botón secundario.
            danger: Booleano para usar colores de alerta roja.
        Returns:
            None
        """
        super().__init__(
            parent,
            Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self._popped = False
        self.setMinimumWidth(340)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        accent = (
            THEME["danger"]
            if (kind == "error" or danger)
            else THEME["primary"]
        )
        t = QLabel(title)
        t.setFont(ui_font(10, True))
        t.setStyleSheet(f"color: {accent}; background: transparent;")
        m = QLabel(text)
        m.setFont(ui_font(9))
        m.setWordWrap(True)
        m.setMaximumWidth(380)
        m.setStyleSheet(f"color: {THEME['text']}; background: transparent;")
        lay.addWidget(t)
        lay.addWidget(m)
        lay.addSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        if kind == "question":
            row.addWidget(TextButton(
                cancel_text, self.reject, height=32, width=96,
                idle_fill="surface", hover_fill="surface_hover",
                fg="text_muted", border="border",
            ))
        row.addWidget(TextButton(
            confirm_text, self.accept, height=32, width=110,
            idle_fill="danger" if danger else "primary",
            hover_fill="danger_hover" if danger else "primary_hover",
            fg="#FFFFFF" if danger else "btn_text",
        ))
        lay.addLayout(row)
        QShortcut(QKeySequence("Return"), self, activated=self.accept)
        QShortcut(QKeySequence("Enter"), self, activated=self.accept)
        self.adjustSize()

    def center_on(self, parent):
        """Centra el diálogo en el monitor del widget padre.
        Args:
            parent: Widget de referencia para ubicar la pantalla.
        Returns:
            None
        """
        scr = None
        if parent is not None:
            try:
                scr = parent.screen()
            except Exception:
                scr = None
        scr = scr or QGuiApplication.primaryScreen()
        geo = scr.geometry()
        self.move(
            geo.center() - QPoint(self.width() // 2, self.height() // 2)
        )

    def showEvent(self, e):
        """Ejecuta animación de entrada la primera vez que se muestra.
        Args:
            e: Evento QShowEvent.
        Returns:
            None
        """
        super().showEvent(e)
        if not self._popped:
            self._popped = True
            pop_in(self)

    def paintEvent(self, event):
        """Pinta el fondo traslúcido del diálogo.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        paint_glass(self, 22, solid=True)

    def mousePressEvent(self, e):
        """Permite arrastrar la ventana del diálogo con el botón izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()


def show_dialog(parent, title, text, kind="info", **kwargs):
    """Muestra un diálogo modal y devuelve True si el usuario acepta.
    Args:
        parent: Widget padre.
        title: Título de la ventana.
        text: Contenido descriptivo.
        kind: Categoría del diálogo ('info', 'warning', 'error', 'question').
    Returns:
        Booleano indicando si la respuesta fue afirmativa.
    """
    dlg = GlassDialog(parent, title, text, kind, **kwargs)
    dlg.center_on(parent)
    accepted = dlg.exec() == QDialog.Accepted
    dlg.deleteLater()
    return accepted


def paint_checker(p, path, cell=6):
    """Pinta un tablero de ajedrez claro/gris recortado por una ruta.
    Args:
        p: Instancia activa de QPainter.
        path: QPainterPath que delimita el área a rellenar.
        cell: Tamaño de cada casilla en píxeles.
    Returns:
        None
    """
    r = path.boundingRect()
    p.save()
    p.setClipPath(path)
    p.fillPath(path, QColor("#FFFFFF"))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#D0D4D9"))
    nx = int(r.width() // cell) + 1
    ny = int(r.height() // cell) + 1
    for j in range(ny):
        for i in range(nx):
            if (i + j) % 2:
                p.drawRect(
                    QRectF(r.left() + i * cell, r.top() + j * cell, cell, cell)
                )
    p.restore()


def parse_hex(text):
    """Normaliza texto escrito por el usuario a '#RRGGBB' o None si no es válido.
    Args:
        text: Cadena con o sin '#', de 3 o 6 dígitos hexadecimales.
    Returns:
        Cadena '#RRGGBB' en mayúsculas o None.
    """
    t = str(text).strip().lstrip("#")
    if len(t) == 3:
        t = "".join(ch * 2 for ch in t)
    cand = "#" + t.upper()
    return cand if is_valid_hex(cand) else None


class SVSquare(QWidget):
    """Cuadrado de saturación (horizontal) y brillo (vertical) para un tono."""

    changed = Signal(float, float)

    def __init__(self, parent=None):
        """Inicializa el selector bidimensional.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setFixedHeight(120)
        self.setCursor(Qt.CrossCursor)
        self._h, self._s, self._v = 0.0, 1.0, 1.0

    def set_state(self, h, s, v):
        """Actualiza tono, saturación y brillo sin emitir señales.
        Args:
            h: Tono (0-1).
            s: Saturación (0-1).
            v: Brillo (0-1).
        Returns:
            None
        """
        self._h, self._s, self._v = h, s, v
        self.update()

    def _pick(self, pos):
        """Calcula saturación y brillo a partir de la posición del ratón.
        Args:
            pos: QPointF local.
        Returns:
            None
        """
        w = max(1.0, self.width() - 2.0)
        h = max(1.0, self.height() - 2.0)
        self._s = clamp01((pos.x() - 1.0) / w)
        self._v = clamp01(1.0 - (pos.y() - 1.0) / h)
        self.update()
        self.changed.emit(self._s, self._v)

    def mousePressEvent(self, e):
        """Inicia la selección con el botón izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self._pick(e.position())
        e.accept()

    def mouseMoveEvent(self, e):
        """Continúa la selección mientras se arrastra.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.buttons() & Qt.LeftButton:
            self._pick(e.position())
        e.accept()

    def paintEvent(self, event):
        """Pinta el degradado, el borde y el tirador circular.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.save()
        p.setClipPath(path)
        g1 = QLinearGradient(rect.left(), 0, rect.right(), 0)
        g1.setColorAt(0.0, QColor("#FFFFFF"))
        g1.setColorAt(1.0, QColor.fromHsvF(min(self._h, 0.9999), 1.0, 1.0))
        p.fillRect(rect, g1)
        g2 = QLinearGradient(0, rect.top(), 0, rect.bottom())
        g2.setColorAt(0.0, QColor(0, 0, 0, 0))
        g2.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(rect, g2)
        p.restore()
        p.setPen(QPen(QColor(THEME["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        hx = rect.left() + self._s * rect.width()
        hy = rect.top() + (1.0 - self._v) * rect.height()
        p.setPen(QPen(QColor(0, 0, 0, 110), 1))
        p.drawEllipse(QPointF(hx, hy), 7.6, 7.6)
        p.setPen(QPen(QColor("#FFFFFF"), 2.2))
        p.drawEllipse(QPointF(hx, hy), 6.0, 6.0)


class BarSlider(QWidget):
    """Barra deslizante horizontal de tono ('hue') u opacidad ('alpha')."""

    changed = Signal(float)

    def __init__(self, kind, parent=None):
        """Inicializa la barra.
        Args:
            kind: 'hue' o 'alpha'.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.kind = kind
        self._t = 0.0
        self._base = QColor("#000000")
        self._active = True
        self.setFixedHeight(20)
        self.setCursor(Qt.PointingHandCursor)

    def set_value(self, t):
        """Fija la posición (0-1) sin emitir señales.
        Args:
            t: Posición normalizada.
        Returns:
            None
        """
        self._t = clamp01(t)
        self.update()

    def set_base_color(self, color):
        """Establece el color base del degradado de opacidad.
        Args:
            color: QColor o cadena hexadecimal.
        Returns:
            None
        """
        self._base = QColor(color)
        self.update()

    def set_active(self, active):
        """Activa o desactiva la interacción de la barra.
        Args:
            active: Booleano de estado.
        Returns:
            None
        """
        self._active = bool(active)
        self.setCursor(
            Qt.PointingHandCursor if self._active else Qt.ForbiddenCursor
        )
        self.update()

    def _pick(self, pos):
        """Calcula el valor a partir de la posición horizontal del ratón.
        Args:
            pos: QPointF local.
        Returns:
            None
        """
        if not self._active:
            return
        span = max(1.0, self.width() - 20.0)
        self._t = clamp01((pos.x() - 10.0) / span)
        self.update()
        self.changed.emit(self._t)

    def mousePressEvent(self, e):
        """Inicia la selección con el botón izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self._pick(e.position())
        e.accept()

    def mouseMoveEvent(self, e):
        """Continúa la selección mientras se arrastra.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.buttons() & Qt.LeftButton:
            self._pick(e.position())
        e.accept()

    def paintEvent(self, event):
        """Pinta la pista con su degradado y el tirador.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(10, 5, max(1.0, self.width() - 20.0), self.height() - 10)
        path = QPainterPath()
        path.addRoundedRect(track, 5, 5)
        if self.kind == "hue":
            g = QLinearGradient(track.left(), 0, track.right(), 0)
            for i in range(7):
                g.setColorAt(i / 6.0, QColor.fromHsvF(min(i / 6.0, 0.9999), 1, 1))
            p.fillPath(path, g)
            knob = QColor.fromHsvF(min(self._t, 0.9999), 1, 1)
        else:
            paint_checker(p, path, 5)
            c0, c1 = QColor(self._base), QColor(self._base)
            c0.setAlpha(0)
            c1.setAlpha(255)
            g = QLinearGradient(track.left(), 0, track.right(), 0)
            g.setColorAt(0.0, c0)
            g.setColorAt(1.0, c1)
            p.fillPath(path, g)
            knob = QColor(self._base)
        p.setPen(QPen(QColor(THEME["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if not self._active:
            dim = QColor(THEME["bg"])
            dim.setAlpha(150)
            p.fillPath(path, dim)
        hx = track.left() + self._t * track.width()
        cy = self.height() / 2.0
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(hx, cy), 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QPointF(hx, cy), 4.8, 4.8)


class ColorPicker(QWidget):
    """Selector de color integrado: cuadrado SV, tono, opacidad y campo hex."""

    changed = Signal()

    def __init__(self, parent=None):
        """Construye los controles y sus conexiones.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self._h, self._s, self._v = 0.0, 1.0, 1.0
        self._a = 255
        self._hex = "#000000"
        self._alpha_on = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.sv = SVSquare()
        self.hue = BarSlider("hue")
        self.alpha = BarSlider("alpha")
        lay.addWidget(self.sv)
        lay.addWidget(self.hue)
        lay.addWidget(self.alpha)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.edit = QLineEdit()
        self.edit.setFixedWidth(96)
        self.edit.setMaxLength(7)
        self.edit.setFont(QFont("Consolas", 9))
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: {THEME['surface']}; "
            f"border: 1px solid {THEME['border']}; border-radius: 8px; "
            f"padding: 4px 8px; color: {THEME['text']}; }}"
            f"QLineEdit:focus {{ border: 1.5px solid {THEME['primary']}; }}"
        )
        self.lbl_alpha = QLabel("")
        self.lbl_alpha.setFont(ui_font(8.5))
        self.lbl_alpha.setStyleSheet(
            f"color: {THEME['text_muted']}; background: transparent;"
        )
        row.addWidget(self.edit)
        row.addStretch(1)
        row.addWidget(self.lbl_alpha)
        lay.addLayout(row)

        self.sv.changed.connect(self._on_sv)
        self.hue.changed.connect(self._on_hue)
        self.alpha.changed.connect(self._on_alpha)
        self.edit.textEdited.connect(self._on_hex_typed)

    def hex(self):
        """Devuelve el color actual como '#RRGGBB'.
        Returns:
            Cadena hexadecimal en mayúsculas.
        """
        return self._hex

    def alpha_value(self):
        """Devuelve la opacidad actual (MIN_ALPHA-255).
        Returns:
            Entero de opacidad.
        """
        return self._a

    def set_color(self, hexval, alpha, alpha_enabled):
        """Carga un color externo en el selector sin emitir 'changed'.
        Args:
            hexval: Color '#RRGGBB'.
            alpha: Opacidad actual (0-255).
            alpha_enabled: Booleano; False si el rol no admite transparencia.
        Returns:
            None
        """
        norm = parse_hex(hexval) or "#000000"
        self._load_hsv(norm)
        self._hex = norm
        try:
            self._a = int(max(MIN_ALPHA, min(255, int(alpha))))
        except (TypeError, ValueError):
            self._a = 255
        self._alpha_on = bool(alpha_enabled)
        self._sync(update_edit=True)

    def _load_hsv(self, hexval):
        """Extrae tono, saturación y brillo de un hexadecimal conservando el tono previo en grises.
        Args:
            hexval: Color '#RRGGBB'.
        Returns:
            None
        """
        c = QColor(hexval)
        if not c.isValid():
            return
        hue = c.hsvHueF()
        if hue >= 0.0:
            self._h = min(hue, 0.9999)
        self._s = clamp01(c.hsvSaturationF())
        self._v = clamp01(c.valueF())

    def _hsv_hex(self):
        """Convierte el estado HSV actual a '#RRGGBB'.
        Returns:
            Cadena hexadecimal en mayúsculas.
        """
        return QColor.fromHsvF(
            min(self._h, 0.9999), clamp01(self._s), clamp01(self._v)
        ).name().upper()

    def _sync(self, update_edit):
        """Sincroniza los controles hijos con el estado interno.
        Args:
            update_edit: Si True reescribe también el campo hexadecimal.
        Returns:
            None
        """
        self.sv.set_state(self._h, self._s, self._v)
        self.hue.set_value(self._h)
        self.alpha.set_base_color(self._hex)
        span = float(255 - MIN_ALPHA)
        self.alpha.set_value((self._a - MIN_ALPHA) / span)
        self.alpha.set_active(self._alpha_on)
        if self._alpha_on:
            self.lbl_alpha.setText(f"Opacidad {round(self._a * 100 / 255)} %")
        else:
            self.lbl_alpha.setText("Sin transparencia")
        if update_edit:
            self.edit.blockSignals(True)
            self.edit.setText(self._hex)
            self.edit.blockSignals(False)

    def _on_sv(self, s, v):
        """Procesa cambios del cuadrado de saturación y brillo.
        Args:
            s: Saturación (0-1).
            v: Brillo (0-1).
        Returns:
            None
        """
        self._s, self._v = s, v
        self._hex = self._hsv_hex()
        self._sync(update_edit=True)
        self.changed.emit()

    def _on_hue(self, t):
        """Procesa cambios en la barra de tono.
        Args:
            t: Tono normalizado.
        Returns:
            None
        """
        self._h = min(t, 0.9999)
        self._hex = self._hsv_hex()
        self._sync(update_edit=True)
        self.changed.emit()

    def _on_alpha(self, t):
        """Procesa cambios en la barra de opacidad.
        Args:
            t: Posición normalizada.
        Returns:
            None
        """
        if not self._alpha_on:
            return
        self._a = int(round(MIN_ALPHA + clamp01(t) * (255 - MIN_ALPHA)))
        self._sync(update_edit=False)
        self.changed.emit()

    def _on_hex_typed(self, text):
        """Aplica el hexadecimal escrito a mano en cuanto es válido.
        Args:
            text: Texto actual del campo.
        Returns:
            None
        """
        norm = parse_hex(text)
        if norm is None:
            return
        self._hex = norm
        self._load_hsv(norm)
        self._sync(update_edit=False)
        self.changed.emit()


class RoleChip(QWidget):
    """Píldora que representa un color editable y muestra su muestra actual."""

    def __init__(self, key, label, get_color, on_click, parent=None):
        """Inicializa la píldora selectora.
        Args:
            key: Clave del color en el tema.
            label: Etiqueta visible.
            get_color: Función key -> (hex, opacidad).
            on_click: Callback que recibe la clave pulsada.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.key = key
        self.label = label
        self.get_color = get_color
        self.on_click = on_click
        self.selected = False
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        """Selecciona el rol si se suelta dentro de la píldora.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self.rect().contains(
            e.position().toPoint()
        ):
            self.on_click(self.key)
        e.accept()

    def paintEvent(self, event):
        """Pinta la píldora con su muestra de color y etiqueta.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, QColor(THEME["surface"]))
        pen_col = QColor(THEME["primary"] if self.selected else THEME["border"])
        p.setPen(QPen(pen_col, 1.8 if self.selected else 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        hexv, alpha = self.get_color(self.key)
        dot = QPainterPath()
        dot.addEllipse(QPointF(15, self.height() / 2), 6.5, 6.5)
        paint_checker(p, dot, 4)
        col = QColor(hexv)
        col.setAlpha(int(alpha))
        p.fillPath(dot, col)
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(dot)
        font = ui_font(8, self.selected)
        p.setFont(font)
        p.setPen(QColor(THEME["text"]))
        txt = QFontMetrics(font).elidedText(
            self.label, Qt.ElideRight, max(10, self.width() - 32)
        )
        p.drawText(
            QRectF(27, 0, self.width() - 30, self.height()),
            Qt.AlignVCenter | Qt.AlignLeft, txt,
        )


class PresetDot(QWidget):
    """Círculo bicolor (fondo / principal) que aplica un tema rápido."""

    def __init__(self, preset, on_click, parent=None):
        """Inicializa el punto de tema rápido.
        Args:
            preset: Diccionario del tema (name, colors, alpha).
            on_click: Callback que recibe el nombre del tema.
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.preset = preset
        self.on_click = on_click
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(preset["name"])

    def mouseReleaseEvent(self, e):
        """Aplica el tema si se suelta dentro del círculo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self.rect().contains(
            e.position().toPoint()
        ):
            self.on_click(self.preset["name"])
        e.accept()

    def paintEvent(self, event):
        """Pinta las dos mitades del círculo.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addEllipse(r)
        p.save()
        p.setClipPath(path)
        p.fillRect(
            QRectF(r.left(), r.top(), r.width() / 2, r.height()),
            QColor(self.preset["colors"]["bg"]),
        )
        p.fillRect(
            QRectF(r.center().x(), r.top(), r.width() / 2, r.height()),
            QColor(self.preset["colors"]["primary"]),
        )
        p.restore()
        p.setPen(QPen(QColor(THEME["border"]), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class ThemePreview(QWidget):
    """Vista previa con tablero que muestra cómo se verán colores y opacidades."""

    def __init__(self, get_cfg, parent=None):
        """Inicializa la vista previa.
        Args:
            get_cfg: Función que devuelve (colores, opacidades).
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.get_cfg = get_cfg
        self.setFixedHeight(92)

    def paintEvent(self, event):
        """Pinta un panel, una tarjeta y un botón de ejemplo.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        colors, alphas = self.get_cfg()

        def col(key, mult=255):
            c = QColor(colors[key])
            c.setAlpha(int(alphas.get(key, 255) * mult / 255))
            return c

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        op = QPainterPath()
        op.addRoundedRect(outer, 16, 16)
        paint_checker(p, op, 8)

        panel = outer.adjusted(8, 8, -8, -8)
        pp = QPainterPath()
        pp.addRoundedRect(panel, 14, 14)
        p.fillPath(pp, col("bg", 246))
        p.setPen(QPen(col("border", 220), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(pp)

        card = QRectF(
            panel.left() + 10, panel.top() + 12,
            panel.width() * 0.58, panel.height() - 24,
        )
        cp = QPainterPath()
        cp.addRoundedRect(card, 12, 12)
        p.fillPath(cp, col("surface", 230))
        p.setPen(QPen(col("border", 220), 1))
        p.drawPath(cp)
        p.setFont(ui_font(9, True))
        p.setPen(QColor(colors["text"]))
        p.drawText(
            QRectF(card.left() + 12, card.top() + 5, card.width() - 20, 20),
            Qt.AlignVCenter | Qt.AlignLeft, "Snippet de ejemplo",
        )
        p.setFont(ui_font(8))
        p.setPen(QColor(colors["text_muted"]))
        p.drawText(
            QRectF(card.left() + 12, card.top() + 24, card.width() - 20, 18),
            Qt.AlignVCenter | Qt.AlignLeft, "Texto secundario",
        )

        btn = QRectF(
            card.right() + 12, panel.center().y() - 14,
            max(20.0, panel.right() - card.right() - 24), 28,
        )
        bp = QPainterPath()
        bp.addRoundedRect(btn, 14, 14)
        p.fillPath(bp, col("primary"))
        p.setFont(ui_font(9, True))
        p.setPen(QColor(colors["btn_text"]))
        p.drawText(btn, Qt.AlignCenter, "Botón")


class ThemeDialog(QDialog):
    """Diálogo sencillo de colores y transparencias, sin ventanas anidadas."""

    SOLID_WINDOW = True

    FIELDS = [
        ("primary", "Principal"),
        ("btn_text", "Txt. botón"),
        ("bg", "Fondo"),
        ("surface", "Tarjetas"),
        ("border", "Bordes"),
        ("text", "Texto"),
        ("text_muted", "Texto 2º"),
    ]

    def __init__(self, app):
        """Inicializa el editor cargando la configuración actual.
        Args:
            app: Instancia principal de SnippetApp.
        Returns:
            None
        """
        super().__init__(
            app,
            Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.app = app
        self._popped = False
        self.setFixedWidth(404)

        cfg = app.app_data.get("theme", DEFAULT_USER_THEME)
        if not isinstance(cfg, dict):
            cfg = DEFAULT_USER_THEME
        self._colors = {}
        for key, _lbl in self.FIELDS:
            val = str(cfg.get(key, DEFAULT_USER_THEME[key])).upper()
            self._colors[key] = (
                val if is_valid_hex(val) else DEFAULT_USER_THEME[key]
            )
        self._alphas = dict(THEME_ALPHA)
        self._sel = "primary"

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 18)
        root.setSpacing(10)

        head = DragHeader()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Personalizar apariencia")
        title.setFont(ui_font(10.5, True))
        title.setStyleSheet(
            f"color: {THEME['primary']}; background: transparent;"
        )
        hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(IconButton(
            icon_close, self.reject, size=26, idle_fill=None,
            hover_fill="danger_soft", idle_icon="text_muted",
            hover_icon="danger",
        ))
        root.addWidget(head)

        prow = QHBoxLayout()
        prow.setSpacing(6)
        plbl = QLabel("Temas rápidos")
        plbl.setFont(ui_font(8, True))
        plbl.setStyleSheet(
            f"color: {THEME['text_muted']}; background: transparent;"
        )
        prow.addWidget(plbl)
        prow.addStretch(1)
        for preset in PRESETS:
            prow.addWidget(PresetDot(preset, self._apply_preset))
        root.addLayout(prow)

        self.preview = ThemePreview(lambda: (self._colors, self._alphas))
        root.addWidget(self.preview)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self._chips = {}
        for idx, (key, label) in enumerate(self.FIELDS):
            chip = RoleChip(key, label, self._chip_color, self._select)
            grid.addWidget(chip, idx // 4, idx % 4)
            self._chips[key] = chip
        for c in range(4):
            grid.setColumnStretch(c, 1)
        root.addLayout(grid)

        self.picker = ColorPicker()
        self.picker.changed.connect(self._on_picker)
        root.addWidget(self.picker)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(TextButton(
            "Restaurar", self._restore_defaults, height=32, width=92,
            idle_fill="surface", hover_fill="surface_hover",
            fg="text_muted", border="border", bold=False,
        ))
        actions.addStretch(1)
        actions.addWidget(TextButton(
            "Cancelar", self.reject, height=32, width=86,
            idle_fill="surface", hover_fill="surface_hover",
            fg="text_muted", border="border",
        ))
        actions.addWidget(TextButton(
            "Guardar", self._save_theme, height=32, width=102,
            idle_fill="primary", hover_fill="primary_hover", fg="btn_text",
        ))
        root.addLayout(actions)

        QShortcut(QKeySequence("Escape"), self, activated=self.reject)
        self._select("primary")
        self.adjustSize()
        x = app.mon_x + (app.screen_w - self.width()) // 2
        y = app.mon_y + (app.screen_h - self.height()) // 2
        self.move(max(app.mon_x, x), max(app.mon_y, y))

    def _chip_color(self, key):
        """Devuelve color y opacidad actuales de un rol.
        Args:
            key: Clave del color.
        Returns:
            Tupla (hex, opacidad).
        """
        return self._colors[key], self._alphas.get(key, 255)

    def _select(self, key):
        """Selecciona un rol y carga su color en el selector.
        Args:
            key: Clave del color a editar.
        Returns:
            None
        """
        self._sel = key
        for k, chip in self._chips.items():
            chip.selected = (k == key)
            chip.update()
        self.picker.set_color(
            self._colors[key], self._alphas.get(key, 255), key in ALPHA_KEYS
        )

    def _on_picker(self):
        """Guarda en el estado el color editado y repinta muestras.
        Returns:
            None
        """
        key = self._sel
        self._colors[key] = self.picker.hex()
        if key in ALPHA_KEYS:
            self._alphas[key] = self.picker.alpha_value()
        self._chips[key].update()
        self.preview.update()

    def _apply_preset(self, name):
        """Aplica un tema rápido completo al editor.
        Args:
            name: Nombre del tema en PRESETS.
        Returns:
            None
        """
        for preset in PRESETS:
            if preset["name"] == name:
                self._colors.update(preset["colors"])
                self._alphas = dict(DEFAULT_ALPHA)
                self._alphas.update(preset.get("alpha", {}))
                break
        self._select(self._sel)
        for chip in self._chips.values():
            chip.update()
        self.preview.update()

    def _restore_defaults(self):
        """Restablece la paleta original.
        Returns:
            None
        """
        self._apply_preset(PRESETS[0]["name"])

    def _save_theme(self):
        """Guarda los colores y opacidades y actualiza la app al instante.
        Returns:
            None
        """
        theme = dict(self._colors)
        theme["alpha"] = dict(self._alphas)
        self.app.update_theme(theme)
        self.accept()

    def showEvent(self, e):
        """Ejecuta animación de aparición suave al abrir el diálogo.
        Args:
            e: Evento QShowEvent.
        Returns:
            None
        """
        super().showEvent(e)
        if not self._popped:
            self._popped = True
            pop_in(self)

    def paintEvent(self, event):
        """Pinta el fondo de cristal del diálogo.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        paint_glass(self, 22, solid=True)


# ==============================================================================
# CAPTURA DE PANTALLA MULTIMONITOR
# ==============================================================================
class _Overlay(QWidget):
    """Ventana superpuesta de selección de recorte para un monitor."""

    def __init__(self, ctrl, geom, pixmap):
        """Inicializa el overlay sobre la geometría del monitor correspondiente.
        Args:
            ctrl: Instancia controladora RegionSelector.
            geom: QRect con las coordenadas del monitor.
            pixmap: Captura QPixmap congelada del monitor.
        Returns:
            None
        """
        super().__init__(
            None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.ctrl = ctrl
        self.geom = geom
        self.pm = pixmap
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(geom)

    def paintEvent(self, event):
        """Pinta la pantalla oscurecida, el recorte activo y las dimensiones.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(0, 0, self.pm)
        p.fillRect(self.rect(), QColor(0, 0, 0, 153))
        ctrl = self.ctrl
        sel = ctrl.sel
        if sel is not None and sel.width() >= 2 and sel.height() >= 2:
            local = QRectF(sel.translated(-self.geom.topLeft()))
            path = QPainterPath()
            path.addRoundedRect(local, 8, 8)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(0, 0, self.pm)
            p.restore()
            p.setPen(QPen(qc("primary", None, True), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            text = f"{sel.width()} × {sel.height()}"
            p.setFont(ui_font(9, True))
            tw = QFontMetrics(p.font()).horizontalAdvance(text) + 16
            tag = QRectF(local.left(), max(4.0, local.top() - 26), tw, 21)
            tp = QPainterPath()
            tp.addRoundedRect(tag, 10.5, 10.5)
            p.fillPath(tp, qc("primary", None, True))
            p.setPen(qc("btn_text"))
            p.drawText(tag, Qt.AlignCenter, text)
        elif ctrl.hint_visible and self.geom == ctrl.hint_geom:
            text = (
                "Arrastra para seleccionar la zona de texto  ·  "
                "Esc para cancelar"
            )
            p.setFont(ui_font(11))
            tw = QFontMetrics(p.font()).horizontalAdvance(text) + 36
            box = QRectF((self.width() - tw) / 2, 14, tw, 34)
            bp = QPainterPath()
            bp.addRoundedRect(box, 17, 17)
            p.fillPath(bp, QColor(20, 20, 20, 190))
            p.setPen(QColor("#FFFFFF"))
            p.drawText(box, Qt.AlignCenter, text)

    def mousePressEvent(self, e):
        """Notifica al controlador el inicio de la selección.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self.ctrl.press(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        """Actualiza el área seleccionada mientras se arrastra el cursor.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.buttons() & Qt.LeftButton:
            self.ctrl.drag(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        """Finaliza la selección al soltar el botón izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self.ctrl.release(e.globalPosition().toPoint())

    def keyPressEvent(self, e):
        """Cancela el modo captura al pulsar Escape.
        Args:
            e: Evento de teclado QKeyEvent.
        Returns:
            None
        """
        if e.key() == Qt.Key_Escape:
            self.ctrl.cancel()


class RegionSelector(QObject):
    """Selector de región coordinado entre todos los monitores activos."""

    finished = Signal(object)

    def __init__(self, hint_geom, parent=None):
        """Inicializa el selector multimonitor.
        Args:
            hint_geom: QRect del monitor donde mostrar la ayuda superior.
            parent: Objeto padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.hint_geom = hint_geom
        self.shots = []
        self.overlays = []
        self.sel = None
        self.start_pt = None
        self.hint_visible = True
        self._done = False

    def start(self):
        """Captura las pantallas disponibles y despliega los overlays.
        Returns:
            None
        """
        for scr in QGuiApplication.screens():
            pm = scr.grabWindow(0)
            if pm.isNull():
                raise RuntimeError("No se pudo capturar la pantalla.")
            img = pm.toImage()
            img.setDevicePixelRatio(1.0)
            self.shots.append(
                (scr.geometry(), pm, img, pm.devicePixelRatio())
            )
        for geom, pm, _img, _dpr in self.shots:
            ov = _Overlay(self, geom, pm)
            self.overlays.append(ov)
            ov.show()
        target = next(
            (o for o in self.overlays if o.geom == self.hint_geom),
            self.overlays[0],
        )
        target.activateWindow()
        target.setFocus()
        QShortcut(
            QKeySequence("Esc"), target, activated=self.cancel,
            context=Qt.ApplicationShortcut,
        )

    def _update_all(self):
        """Solicita el repintado simultáneo de todos los overlays.
        Returns:
            None
        """
        for ov in self.overlays:
            ov.update()

    def _rect(self, a, b):
        """Construye un QRect normalizado a partir de dos puntos globales.
        Args:
            a: QPoint inicial.
            b: QPoint final.
        Returns:
            QRect con ancho y alto positivos.
        """
        return QRect(
            QPoint(min(a.x(), b.x()), min(a.y(), b.y())),
            QSize(abs(a.x() - b.x()), abs(a.y() - b.y())),
        )

    def press(self, g):
        """Registra la coordenada inicial de arrastre.
        Args:
            g: QPoint en coordenadas globales.
        Returns:
            None
        """
        self.start_pt = g
        self.hint_visible = False
        self._update_all()

    def drag(self, g):
        """Actualiza el rectángulo de recorte activo.
        Args:
            g: QPoint actual en coordenadas globales.
        Returns:
            None
        """
        if self.start_pt is None:
            return
        self.sel = self._rect(self.start_pt, g)
        self._update_all()

    def release(self, g):
        """Cierra los overlays y emite la imagen recortada o None.
        Args:
            g: QPoint final en coordenadas globales.
        Returns:
            None
        """
        if self.start_pt is None or self._done:
            return
        sel = self._rect(self.start_pt, g)
        self._close()
        if sel.width() >= 8 and sel.height() >= 8:
            self.finished.emit(self._crop(sel))
        else:
            self.finished.emit(None)

    def cancel(self):
        """Cancela la captura y emite None.
        Returns:
            None
        """
        if self._done:
            return
        self._close()
        self.finished.emit(None)

    def _close(self):
        """Cierra y libera todas las ventanas superpuestas.
        Returns:
            None
        """
        self._done = True
        for ov in self.overlays:
            ov.close()
            ov.deleteLater()
        self.overlays = []

    def _crop(self, sel):
        """Compone la región seleccionada como una imagen PIL RGB.
        Args:
            sel: QRect global seleccionado por el usuario.
        Returns:
            Objeto PIL.Image con el recorte resultante.
        """
        used = [s for s in self.shots if sel.intersects(s[0])]
        scale = max((s[3] for s in used), default=1.0)
        w_px = max(1, round(sel.width() * scale))
        h_px = max(1, round(sel.height() * scale))
        out = QImage(w_px, h_px, QImage.Format_RGB32)
        out.fill(Qt.black)
        pt = QPainter(out)
        pt.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for geom, _pm, img, dpr in used:
            inter = sel.intersected(geom)
            if inter.isEmpty():
                continue
            src = QRectF(
                (inter.x() - geom.x()) * dpr, (inter.y() - geom.y()) * dpr,
                inter.width() * dpr, inter.height() * dpr,
            )
            dst = QRectF(
                (inter.x() - sel.x()) * scale, (inter.y() - sel.y()) * scale,
                inter.width() * scale, inter.height() * scale,
            )
            pt.drawImage(dst, img, src)
        pt.end()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        if not out.save(buf, "PNG"):
            raise RuntimeError("No se pudo codificar la captura.")
        buf.close()
        return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGB")


class OcrBridge(QObject):
    """Puente de señales Qt para comunicar resultados OCR desde hilos worker."""

    done = Signal(str, str)


# ==============================================================================
# VENTANA DE EDICIÓN
# ==============================================================================
class DragHeader(QWidget):
    """Cabecera arrastrable para mover ventanas sin marco del sistema."""

    def mousePressEvent(self, e):
        """Inicia el movimiento nativo de ventana al arrastrar con clic izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()


class EditWindow(QWidget):
    """Ventana flotante de creación y edición de snippets con soporte de tema."""

    SOLID_WINDOW = True

    def __init__(self, app, original_key=None, original_content="",
                 prefill_title=None):
        """Inicializa la ventana de edición adaptada a los colores actuales.
        Args:
            app: Instancia principal de SnippetApp.
            original_key: Clave original del snippet al editar, o None si es nuevo.
            original_content: Texto inicial del contenido.
            prefill_title: Título sugerido (ej. tras captura OCR).
        Returns:
            None
        """
        super().__init__(
            app,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.app = app
        self.original_key = original_key
        self.is_edit = original_key is not None
        self._popped = False
        self.setMinimumSize(360, 280)

        win_w, win_h = app._calculate_edit_win_size(original_content)
        self.resize(win_w, win_h)
        self.move(
            app.mon_x + (app.screen_w - win_w) // 2,
            app.mon_y + (app.screen_h - win_h) // 2,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(6)

        head = DragHeader()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 4)
        self.ttl = QLabel(
            "Editar snippet" if self.is_edit else "Nuevo snippet"
        )
        self.ttl.setFont(ui_font(11, True))
        hl.addWidget(self.ttl)
        hl.addStretch(1)
        hl.addWidget(IconButton(
            icon_close, self.close, size=26, idle_fill=None,
            hover_fill="danger_soft", idle_icon="text_muted",
            hover_icon="danger",
        ))
        root.addWidget(head)

        self.l1 = QLabel("Título")
        self.l1.setFont(ui_font(8, True))
        root.addWidget(self.l1)

        self.title_entry = QLineEdit()
        self.title_entry.setFont(ui_font(9))
        if self.is_edit:
            self.title_entry.setText(original_key)
        elif prefill_title:
            self.title_entry.setText(prefill_title)
        root.addWidget(self.title_entry)
        root.addSpacing(4)

        self.l2 = QLabel("Contenido")
        self.l2.setFont(ui_font(8, True))
        root.addWidget(self.l2)

        self.content_text = QPlainTextEdit()
        self.content_text.setFont(QFont("Consolas", 9))
        self.content_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        if self.is_edit or original_content:
            self.content_text.setPlainText(original_content)
        root.addWidget(self.content_text, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(TextButton(
            "Cancelar", self.cancel, height=32, width=96,
            idle_fill="surface", hover_fill="surface_hover",
            fg="text_muted", border="border",
        ))
        row.addWidget(TextButton(
            "Guardar snippet", self.save, height=32, width=140,
            idle_fill="primary", hover_fill="primary_hover", fg="btn_text",
        ))
        row.addWidget(QSizeGrip(self), 0, Qt.AlignBottom | Qt.AlignRight)
        root.addSpacing(4)
        root.addLayout(row)

        self.apply_theme()

        QShortcut(QKeySequence("Escape"), self, activated=self.cancel)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.save)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.save)
        self.title_entry.setFocus()

    def apply_theme(self):
        """Aplica los colores actuales de THEME a todos los campos del editor.
        Returns:
            None
        """
        sr, sg, sb = _hex_to_rgb(THEME["surface"])
        field_qss = (
            f"background: rgba({sr},{sg},{sb},235); "
            f"border: 1px solid {THEME['border']}; border-radius: 12px; "
            f"color: {THEME['text']}; "
            f"selection-background-color: {THEME['primary']}; "
            f"selection-color: {THEME['btn_text']};"
        )
        lbl_qss = f"color: {THEME['text_muted']}; background: transparent;"

        self.ttl.setStyleSheet(
            f"color: {THEME['primary']}; background: transparent;"
        )
        self.l1.setStyleSheet(lbl_qss)
        self.l2.setStyleSheet(lbl_qss)
        self.title_entry.setStyleSheet(
            f"QLineEdit {{ {field_qss} padding: 7px 12px; }}"
            f"QLineEdit:focus {{ border: 1.5px solid {THEME['primary']}; }}"
        )
        self.content_text.setStyleSheet(
            f"QPlainTextEdit {{ {field_qss} padding: 6px 8px; }}"
            f"QPlainTextEdit:focus {{ "
            f"border: 1.5px solid {THEME['primary']}; }}"
            + get_scroll_qss()
        )
        self.update()

    def showEvent(self, e):
        """Ejecuta animación de aparición la primera vez que se visualiza.
        Args:
            e: Evento QShowEvent.
        Returns:
            None
        """
        super().showEvent(e)
        if not self._popped:
            self._popped = True
            pop_in(self)

    def paintEvent(self, event):
        """Pinta el fondo de cristal redondeado de la ventana de edición.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        paint_glass(self, 22, solid=True)

    def cancel(self):
        """Cierra el editor descartando cambios.
        Returns:
            None
        """
        self.close()

    def save(self):
        """Valida los campos, guarda el snippet en disco y actualiza la lista.
        Returns:
            None
        """
        app = self.app
        t = self.title_entry.text().strip()
        c = self.content_text.toPlainText().strip()
        if not t or not c:
            show_dialog(
                self, "Faltan datos",
                "Escribe un título y un contenido para guardar el snippet.",
                "warning",
            )
            return
        if t in app.snippets and t != self.original_key:
            if not show_dialog(
                self, "Sobrescribir",
                f"Ya existe un snippet llamado «{t}». ¿Sobrescribirlo?",
                "question", confirm_text="Sobrescribir",
            ):
                return
        if (self.is_edit and t != self.original_key
                and self.original_key in app.snippets):
            del app.snippets[self.original_key]
        app.snippets[t] = c
        app.app_data["snippets"] = app.snippets
        save_data(app.app_data)
        app.selected_key = t
        app._refresh_list()
        app._flash_status(f"Guardado «{t}»", "primary")
        self.close()


# ==============================================================================
# TIRADOR DE TAMAÑO
# ==============================================================================
class ResizeGrip(QWidget):
    """Tirador de esquina para cambiar el tamaño del panel desplegado."""

    pressed = Signal(QPoint)
    moved = Signal(QPoint)
    released = Signal()

    def __init__(self, parent=None):
        """Inicializa el tirador.
        Args:
            parent: Widget padre opcional.
        Returns:
            None
        """
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setToolTip("Arrastra para cambiar el tamaño")
        self.corner = "br"
        self._down = False
        self.set_corner("br")

    def set_corner(self, corner):
        """Define la esquina que ocupa ('bl', 'br' o 'tr') y el cursor adecuado.
        Args:
            corner: Identificador de esquina.
        Returns:
            None
        """
        self.corner = corner
        self.setCursor(
            Qt.SizeBDiagCursor if corner in ("bl", "tr") else Qt.SizeFDiagCursor
        )
        self.update()

    def mousePressEvent(self, e):
        """Inicia el redimensionado con el botón izquierdo.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton:
            self._down = True
            self.pressed.emit(e.globalPosition().toPoint())
        e.accept()

    def mouseMoveEvent(self, e):
        """Emite la posición global mientras se arrastra.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if self._down and (e.buttons() & Qt.LeftButton):
            self.moved.emit(e.globalPosition().toPoint())
        e.accept()

    def mouseReleaseEvent(self, e):
        """Finaliza el redimensionado.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self._down:
            self._down = False
            self.released.emit()
        e.accept()

    def paintEvent(self, event):
        """Pinta tres líneas diagonales en la esquina correspondiente.
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self.width()
        p.setPen(_pen(blend(THEME["text_muted"], THEME["bg"], 0.25), 1.6))
        for d in (5, 9, 13):
            if self.corner == "br":
                p.drawLine(QPointF(s - 3 - d, s - 3), QPointF(s - 3, s - 3 - d))
            elif self.corner == "bl":
                p.drawLine(QPointF(3 + d, s - 3), QPointF(3, s - 3 - d))
            else:
                p.drawLine(QPointF(s - 3 - d, 3), QPointF(s - 3, 3 + d))


# ==============================================================================
# APLICACIÓN PRINCIPAL
# ==============================================================================
class SnippetApp(QWidget):
    """Ventana principal: barra lateral acoplable con animaciones líquidas."""

    def __init__(self):
        """Inicializa estado, tema personalizado, monitores e interfaz gráfica.
        Returns:
            None
        """
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setWindowTitle(APP_NAME)

        self.app_data = load_data()
        self.app_data["theme"] = rebuild_theme(self.app_data.get("theme"))
        self.snippets = self.app_data.get("snippets", {})
        self.selected_key = None
        self.cards = {}
        self._open_editors = []
        self._ignore_focus = False
        self.tween = Tweener()
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._reset_status)
        self._ocr_bridge = OcrBridge()
        self._ocr_bridge.done.connect(self._on_ocr_complete)
        self._loader = None
        self._selector = None

        self.expanded_width = self._saved_dim("panel_w", DEFAULT_PANEL_W)
        self.rail_width = 38
        self.collapsed_width = 6
        self.hover_tab_width = 38
        self.panel_h = self._saved_dim("panel_h", DEFAULT_PANEL_H)

        self.monitors = self._get_monitors()
        mon_idx = self.app_data.get("monitor_idx", 0)
        if not isinstance(mon_idx, int) or not (
                0 <= mon_idx < len(self.monitors)):
            mon_idx = 0
        self.current_mon = self.monitors[mon_idx]
        self._update_monitor_metrics()

        self._bub = None
        self._mask_key = None
        self._c_back_d = QEasingCurve(QEasingCurve.OutBack)
        self._c_back_d.setOvershoot(1.5)
        self._c_back_l = QEasingCurve(QEasingCurve.OutBack)
        self._c_back_l.setOvershoot(0.9)
        self._c_inout = QEasingCurve(QEasingCurve.InOutCubic)
        self._p = 0.0
        self._vis = float(self.collapsed_width)
        self.is_expanded = False
        self._animating = False
        self._tab_hovered = False
        self._last_geometry = None
        self._win_origin = (0, 0)

        self.edge = self.app_data.get("edge", "right")
        if self.edge not in ("left", "right", "top", "bottom"):
            self.edge = "right"

        saved_x = self.app_data.get("pos_x")
        saved_y = self.app_data.get("pos_y")
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in (saved_x, saved_y)
        ):
            saved_x = saved_y = None
        else:
            saved_x, saved_y = int(saved_x), int(saved_y)

        is_valid_pos = False
        if saved_x is not None and saved_y is not None:
            for m in self.monitors:
                if (m["left"] <= saved_x < m["left"] + m["width"]
                        and m["top"] <= saved_y < m["top"] + m["height"]):
                    is_valid_pos = True
                    self.current_mon = m
                    break

        if is_valid_pos:
            self.current_x = saved_x
            self.current_y = saved_y
            self._update_monitor_metrics()
        else:
            self.current_mon = self.monitors[0]
            self._update_monitor_metrics()
            self.current_x = (
                self.mon_x + (self.screen_w - self.collapsed_height) // 2
            )
            self.current_y = (
                self.mon_y + (self.screen_h - self.collapsed_height) // 2
            )
            self.edge = "right"

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._is_dragging = False
        self._pressed = False
        self._rs_start = None
        self._theme_dlg_open = False
        self._pending_copy_key = None
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._flush_pending_copy)

        self.setCursor(Qt.PointingHandCursor)
        self._build_gui()
        self._apply_frame(self._p, self._vis, force=True)

        self._hidden_mode = False
        self._screen_timer = QTimer(self)
        self._screen_timer.setSingleShot(True)
        self._screen_timer.timeout.connect(self._refit_to_screens)
        gapp = QGuiApplication.instance()
        gapp.screenAdded.connect(self._on_screen_added)
        gapp.screenRemoved.connect(self._on_screens_changed)
        gapp.primaryScreenChanged.connect(self._on_screens_changed)
        for scr in QGuiApplication.screens():
            scr.geometryChanged.connect(self._on_screens_changed)
        self._heal_timer = QTimer(self)
        self._heal_timer.timeout.connect(self._heal)
        self._heal_timer.start(4000)

    # --------------------------------------------------------------------------
    # Gestión de Temas en Tiempo Real
    # --------------------------------------------------------------------------
    def _open_theme_dialog(self):
        """Abre el diálogo modal de personalización evitando colapsar el panel.
        Returns:
            None
        """
        if self._theme_dlg_open:
            return
        self._theme_dlg_open = True
        self._ignore_focus = True
        dlg = None
        try:
            dlg = ThemeDialog(self)
            dlg.exec()
        except Exception:
            log_error(traceback.format_exc())
        finally:
            self._theme_dlg_open = False
            if dlg is not None:
                dlg.deleteLater()
            self._release_focus_soon()

    def update_theme(self, new_user_theme):
        """Aplica nuevos colores instantáneamente a toda la interfaz y persiste.
        Args:
            new_user_theme: Diccionario con los colores hexadecimales elegidos.
        Returns:
            None
        """
        validated = rebuild_theme(new_user_theme)
        self.app_data["theme"] = validated
        save_data(self.app_data)

        self.search_box.apply_theme()
        self.scroll_list.apply_theme()
        self._filter_snippets()

        for editor in list(self._open_editors):
            if editor is not None:
                try:
                    editor.apply_theme()
                except RuntimeError:
                    pass

        self._flash_status("Colores actualizados", "primary")
        self.header.update()
        self.rail.update()
        self.grip.update()
        self.btn_new.update()
        self.btn_ocr.update()
        self.panel.update()
        self.update()

    # --------------------------------------------------------------------------
    # Gestión Multimonitor
    # --------------------------------------------------------------------------
    def _get_monitors(self):
        """Obtiene la lista de monitores conectados en coordenadas lógicas Qt.
        Returns:
            Lista de diccionarios con dimensiones de cada pantalla.
        """
        mons = []
        for s in QGuiApplication.screens():
            g = s.geometry()
            mons.append({
                "left": g.x(), "top": g.y(),
                "width": g.width(), "height": g.height(),
            })
        return mons or [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

    def _get_monitor_at(self, x, y):
        """Devuelve el monitor que contiene el punto (x, y) o el más cercano.
        Args:
            x: Coordenada global X.
            y: Coordenada global Y.
        Returns:
            Diccionario descriptivo del monitor correspondiente.
        """
        self.monitors = self._get_monitors()
        for m in self.monitors:
            if (m["left"] <= x < m["left"] + m["width"]
                    and m["top"] <= y < m["top"] + m["height"]):
                return m

        def dist_sq(m):
            cx = max(m["left"], min(x, m["left"] + m["width"]))
            cy = max(m["top"], min(y, m["top"] + m["height"]))
            return (x - cx) ** 2 + (y - cy) ** 2

        return min(self.monitors, key=dist_sq)

    def _update_monitor_metrics(self):
        """Actualiza las métricas activas según el monitor seleccionado.
        Returns:
            None
        """
        self.mon_x = self.current_mon["left"]
        self.mon_y = self.current_mon["top"]
        self.screen_w = self.current_mon["width"]
        self.screen_h = self.current_mon["height"]
        self.collapsed_height = int(self.screen_h * 0.18)
        if hasattr(self, "grip") and self._clamp_panel_size():
            self.panel.setFixedSize(self.expanded_width, self.panel_h)
            self._place_grip()
        elif not hasattr(self, "panel"):
            self._clamp_panel_size()

    # --------------------------------------------------------------------------
    # Construcción de la interfaz
    # --------------------------------------------------------------------------
    def _build_gui(self):
        """Construye y ensambla los widgets hijos del panel principal.
        Returns:
            None
        """
        self.panel = QWidget(self)
        self.panel.setFixedSize(self.expanded_width, self.panel_h)
        self.panel.setCursor(Qt.ArrowCursor)
        self.panel.hide()
        self.panel_layout = QBoxLayout(QBoxLayout.LeftToRight, self.panel)
        self.panel_layout.setContentsMargins(8, 8, 8, 8)
        self.panel_layout.setSpacing(8)

        self.grip = ResizeGrip(self.panel)
        self.grip.pressed.connect(self._on_grip_press)
        self.grip.moved.connect(self._on_grip_move)
        self.grip.released.connect(self._on_grip_release)

        self.rail = Rail()
        self.rail.pressed.connect(self._on_press)
        self.rail.moved.connect(self._on_motion)
        self.rail.released.connect(lambda g: self._on_release())

        self.content_frame = QWidget()
        cl = QVBoxLayout(self.content_frame)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)

        self.header = Header(self._open_theme_dialog, self._close_app)
        cl.addWidget(self.header)

        self.search_box = SearchBox()
        self.search_entry = self.search_box.edit
        self.search_entry.textChanged.connect(self._filter_snippets)
        self.search_entry.escaped.connect(self._clear_search)
        cl.addWidget(self.search_box)

        self.scroll_list = ScrollableList()
        cl.addWidget(self.scroll_list, 1)

        self.btn_new = TextButton(
            "Nuevo snippet", lambda: self._open_edit_window(),
            icon_fn=icon_plus, idle_fill="primary",
            hover_fill="primary_hover", fg="btn_text",
        )
        cl.addWidget(self.btn_new)

        self.btn_ocr = TextButton(
            "Capturar texto de pantalla", self._start_ocr,
            icon_fn=icon_camera, idle_fill="surface", idle_alpha=220,
            hover_fill="primary_soft", fg="text", border="border",
        )
        cl.addWidget(self.btn_ocr)

        self.status_label = QLabel("Clic para copiar · doble clic para editar")
        self.status_label.setFont(ui_font(8))
        self.status_label.setContentsMargins(10, 0, 0, 0)
        self._update_status_default()
        cl.addWidget(self.status_label)

        self._pack_panel_children()
        self._refresh_list()

    def _pack_panel_children(self):
        """Reordena la disposición del raíl y contenido según el borde activo.
        Returns:
            None
        """
        lay = self.panel_layout
        lay.removeWidget(self.rail)
        lay.removeWidget(self.content_frame)
        rail = self.rail
        rail.setMinimumSize(0, 0)
        rail.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        if self.edge in ("left", "right"):
            lay.setDirection(QBoxLayout.LeftToRight)
            rail.setFixedWidth(self.rail_width)
            rail_first = self.edge == "right"
        else:
            lay.setDirection(QBoxLayout.TopToBottom)
            rail.setFixedHeight(self.rail_width)
            rail_first = self.edge == "bottom"
        if rail_first:
            lay.addWidget(rail)
            lay.addWidget(self.content_frame, 1)
        else:
            lay.addWidget(self.content_frame, 1)
            lay.addWidget(rail)
        self._render_rail()
        self._place_grip()

    def _render_rail(self):
        """Orienta el icono chevron del raíl hacia el borde acoplado.
        Returns:
            None
        """
        self.rail.direction = {
            "right": "right", "left": "left", "top": "up", "bottom": "down"
        }[self.edge]
        self.rail.vertical = self.edge in ("left", "right")
        self.rail.update()

    # --------------------------------------------------------------------------
    # Geometría en coordenadas de pantalla multimonitor
    # --------------------------------------------------------------------------
    def _clamp(self, v, lo, hi):
        """Restringe un valor numérico dentro de los límites [lo, hi].
        Args:
            v: Valor de entrada.
            lo: Límite inferior.
            hi: Límite superior.
        Returns:
            Valor acotado dentro del rango.
        """
        return max(lo, min(v, hi))

    def _tab_box(self, vis):
        """Calcula las coordenadas globales (x1, y1, x2, y2) de la pestaña.
        Args:
            vis: Grosor visible actual de la pestaña en píxeles.
        Returns:
            Tupla de cuatro enteros (x1, y1, x2, y2).
        """
        vis = max(0, int(round(vis)))
        ch = self.collapsed_height
        mx, my, mw, mh = self.mon_x, self.mon_y, self.screen_w, self.screen_h

        if self.edge in ("left", "right"):
            top = self._clamp(self.current_y, my, my + mh - ch)
            x = mx if self.edge == "left" else (mx + mw - vis)
            return (x, top, x + vis, top + ch)

        left = self._clamp(self.current_x, mx, mx + mw - ch)
        y = my if self.edge == "top" else (my + mh - vis)
        return (left, y, left + ch, y + vis)

    def _panel_box(self, p):
        """Calcula las coordenadas globales (x1, y1, x2, y2) del panel.
        Args:
            p: Progreso de despliegue (0.0 a 1.0).
        Returns:
            Tupla de cuatro enteros (x1, y1, x2, y2).
        """
        ew, ph = self.expanded_width, self.panel_h
        ch = self.collapsed_height
        mx, my, mw, mh = self.mon_x, self.mon_y, self.screen_w, self.screen_h

        if self.edge in ("left", "right"):
            tab_top = self._clamp(self.current_y, my, my + mh - ch)
            top = self._clamp(tab_top + ch / 2 - ph / 2, my, my + mh - ph)
            if self.edge == "right":
                left = mx + mw - ew * p
            else:
                left = mx - ew + ew * p
            return (
                int(round(left)), int(top),
                int(round(left)) + ew, int(top) + ph,
            )

        tab_left = self._clamp(self.current_x, mx, mx + mw - ch)
        left = self._clamp(tab_left + ch / 2 - ew / 2, mx, mx + mw - ew)
        if self.edge == "top":
            top = my - ph + ph * p
        else:
            top = my + mh - ph * p
        return (int(left), int(round(top)), int(left) + ew, int(round(top)) + ph)

    def _stage_box(self):
        """Determina el área fija de escenario para evitar parpadeos al animar.
        Returns:
            Tupla global (x1, y1, x2, y2) recortada al monitor actual.
        """
        a = self._panel_box(1.0)
        b = self._tab_box(self.hover_tab_width)
        m = BUBBLE_MARGIN
        x1, y1 = min(a[0], b[0]) - m, min(a[1], b[1]) - m
        x2, y2 = max(a[2], b[2]) + m, max(a[3], b[3]) + m
        return (
            max(x1, self.mon_x),
            max(y1, self.mon_y),
            min(x2, self.mon_x + self.screen_w),
            min(y2, self.mon_y + self.screen_h),
        )

    def _window_box(self, p, vis):
        """Devuelve la caja constante de escenario de la ventana principal.
        Args:
            p: Progreso de expansión.
            vis: Visibilidad de pestaña.
        Returns:
            Tupla (x1, y1, x2, y2).
        """
        return self._stage_box()

    def _set_mask(self, box, ox, oy):
        """Actualiza la máscara de región clicable/visible de la ventana.
        Args:
            box: Tupla global (x1, y1, x2, y2) o None para limpiar máscara.
            ox: Origen X de la ventana.
            oy: Origen Y de la ventana.
        Returns:
            None
        """
        if box is None:
            key = None
        else:
            x1 = max(0, int(box[0] - ox))
            y1 = max(0, int(box[1] - oy))
            x2 = min(self.width(), int(box[2] - ox))
            y2 = min(self.height(), int(box[3] - oy))
            key = (x1, y1, max(1, x2 - x1), max(1, y2 - y1))
        if key == self._mask_key:
            return
        self._mask_key = key
        if key is None:
            self.clearMask()
        else:
            self.setMask(QRegion(*key))

    def _apply_frame(self, p, vis, force=False):
        """Sincroniza geometría, posición del panel y máscara en cada frame.
        Args:
            p: Factor de apertura del panel.
            vis: Grosor actual de la pestaña acoplada.
            force: Booleano para forzar actualización geométrica.
        Returns:
            None
        """
        self._p, self._vis = p, vis
        win = self._window_box(p, vis)
        geom = (
            win[0], win[1], max(1, win[2] - win[0]), max(1, win[3] - win[1])
        )
        if force or geom != self._last_geometry:
            self.setGeometry(*geom)
            self._last_geometry = geom
        self._win_origin = (win[0], win[1])
        ox, oy = win[0], win[1]

        resting_open = (
            self._bub is None and self.is_expanded and not self._animating
        )
        if resting_open:
            panel = self._panel_box(1.0)
            self.panel.move(panel[0] - ox, panel[1] - oy)
            if not self.panel.isVisible():
                self.panel.show()
            self._set_mask(panel, ox, oy)
        else:
            if self.panel.isVisible():
                self.panel.hide()
            if self._bub is not None or self._animating:
                self._set_mask(None, ox, oy)
            else:
                self._set_mask(
                    self._tab_box(max(vis, self.collapsed_width) + 2), ox, oy
                )
        self.update()

    def _extend(self, rect, ext):
        """Prolonga un rectángulo hacia el borde de pantalla acoplado.
        Args:
            rect: QRectF base.
            ext: Píxeles de extensión.
        Returns:
            QRectF extendido.
        """
        if self.edge == "right":
            return rect.adjusted(0, 0, ext, 0)
        if self.edge == "left":
            return rect.adjusted(-ext, 0, 0, 0)
        if self.edge == "top":
            return rect.adjusted(0, -ext, 0, 0)
        return rect.adjusted(0, 0, 0, ext)

    def _tab_radius(self, vis):
        """Calcula el radio de esquina de la pestaña según su grosor visible.
        Args:
            vis: Grosor visible en píxeles.
        Returns:
            Radio flotante en píxeles.
        """
        return max(3.0, min(14.0, vis * 0.45))

    def _draw_blob(self, p, rect, radius, k):
        """Pinta la transición de masa líquida entre color primario y fondo.
        Args:
            p: Instancia activa de QPainter.
            rect: QRectF del cuerpo a dibujar.
            radius: Radio de redondeo.
            k: Factor de transición (0.0 = pestaña primaria, 1.0 = cristal).
        Returns:
            QPainterPath trazado.
        """
        path = QPainterPath()
        ext = self._extend(rect, EXT_DOCK)
        path.addRoundedRect(ext, radius, radius)
        if k < 0.999:
            if self.edge in ("left", "right"):
                grad = QLinearGradient(ext.topLeft(), ext.bottomLeft())
            else:
                grad = QLinearGradient(ext.topLeft(), ext.topRight())
            a = int(245 * (1.0 - k))
            grad.setColorAt(0.0, qc("primary_light", a))
            grad.setColorAt(1.0, qc("primary", a))
            p.fillPath(path, grad)
        if k > 0.001:
            grad = QLinearGradient(ext.topLeft(), ext.bottomRight())
            grad.setColorAt(0.0, qc("bg", int(GLASS_ALPHA * k)))
            grad.setColorAt(1.0, qc("bg_tint", int((GLASS_ALPHA - 6) * k)))
            p.fillPath(path, grad)
            p.setPen(QPen(qc("border", int(220 * k)), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        return path

    def _tab_icon_pos(self, tab):
        """Calcula el centro óptimo del icono dentro de la pestaña colapsada.
        Args:
            tab: QRectF de la pestaña.
        Returns:
            Tupla (cx, cy) con las coordenadas del centro.
        """
        cx, cy = tab.center().x(), tab.center().y()
        if self.edge == "right":
            cx = tab.left() + tab.width() * 0.45
        elif self.edge == "left":
            cx = tab.left() + tab.width() * 0.55
        elif self.edge == "top":
            cy = tab.top() + tab.height() * 0.55
        else:
            cy = tab.top() + tab.height() * 0.45
        return cx, cy

    def _bubble_rect(self, b):
        """Interpola el rectángulo global de la burbuja entre pestaña y panel.
        Args:
            b: Diccionario de estado de la burbuja activa.
        Returns:
            QRectF interpolado.
        """
        s0, r1 = b["s0"], self._panel_box(1.0)
        ed, el = b["ed"], b["el"]
        kx, ky = (ed, el) if self.edge in ("left", "right") else (el, ed)
        x1 = s0[0] + (r1[0] - s0[0]) * kx
        x2 = s0[2] + (r1[2] - s0[2]) * kx
        y1 = s0[1] + (r1[1] - s0[1]) * ky
        y2 = s0[3] + (r1[3] - s0[3]) * ky
        return QRectF(x1, y1, max(1.0, x2 - x1), max(1.0, y2 - y1))

    def _bubble_frame(self, t):
        """Actualiza los parámetros de animación de la burbuja en el instante t.
        Args:
            t: Progreso temporal normalizado (0.0 a 1.0).
        Returns:
            None
        """
        b = self._bub
        if b is None:
            return
        if b["open"]:
            b["ed"] = self._c_back_d.valueForProgress(t)
            b["el"] = self._c_back_l.valueForProgress(t)
            b["k"] = clamp01(t * 1.5)
            b["ca"] = clamp01((t - 0.3) / 0.4)
            b["ia"] = b["ia0"] * (1.0 - clamp01(t * 3.0))
        else:
            e = self._c_inout.valueForProgress(t)
            b["ed"] = b["el"] = 1.0 - e
            b["k"] = clamp01(1.0 - t * 1.5)
            b["ca"] = clamp01(1.0 - t / 0.3)
            b["ia"] = 0.0
        self.update()

    def _paint_bubble(self, p, ox, oy):
        """Renderiza la burbuja mórfica durante la apertura o cierre del panel.
        Args:
            p: Instancia activa de QPainter.
            ox: Coordenada X de origen de la ventana.
            oy: Coordenada Y de origen de la ventana.
        Returns:
            None
        """
        b = self._bub
        rect = self._bubble_rect(b).translated(-ox, -oy)
        ed = clamp01(b["ed"])
        r0 = b["r0"]
        radius = r0 + (22.0 - r0) * ed
        radius = max(2.0, min(radius, 0.5 * min(rect.width(), rect.height())))
        path = self._draw_blob(p, rect, radius, b["k"])
        img = b["img"]
        if b["ca"] > 0.01 and img is not None and not img.isNull():
            p.save()
            p.setClipPath(path)
            p.setOpacity(b["ca"])
            p.drawImage(rect, img, QRectF(img.rect()))
            p.restore()
        if b["ia"] > 0.01:
            cx, cy = self._tab_icon_pos(rect)
            p.setOpacity(b["ia"])
            icon_clipboard(p, cx, cy, 18, qc("btn_text"), width=1.5)
            p.setOpacity(1.0)

    def paintEvent(self, event):
        """Pinta el estado actual de la ventana (burbuja, panel o pestaña).
        Args:
            event: Evento de pintado QPaintEvent.
        Returns:
            None
        """
        ox, oy = self._win_origin
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setClipRect(
            QRect(self.mon_x - ox, self.mon_y - oy, self.screen_w, self.screen_h)
        )

        if self._bub is not None:
            self._paint_bubble(p, ox, oy)
            return
        if self.is_expanded:
            bx = self._panel_box(1.0)
            rect = QRectF(
                bx[0] - ox, bx[1] - oy, self.expanded_width, self.panel_h
            )
            self._draw_blob(p, rect, 22, 1.0)
        elif self._vis >= 1:
            t = self._tab_box(self._vis)
            tab = QRectF(t[0] - ox, t[1] - oy, t[2] - t[0], t[3] - t[1])
            self._draw_blob(p, tab, self._tab_radius(self._vis), 0.0)
            if self._vis >= 14:
                cx, cy = self._tab_icon_pos(tab)
                p.setOpacity(clamp01((self._vis - 14) / 16))
                icon_clipboard(p, cx, cy, 18, qc("btn_text"), width=1.5)

    # --------------------------------------------------------------------------
    # Hover de la pestaña
    # --------------------------------------------------------------------------
    def enterEvent(self, event):
        """Asoma la pestaña acoplada cuando entra el cursor.
        Args:
            event: Evento QEnterEvent.
        Returns:
            None
        """
        if not self.is_expanded and not self._pressed:
            self._set_tab_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Pliega la pestaña a su grosor mínimo al salir el cursor.
        Args:
            event: Evento QEvent.
        Returns:
            None
        """
        if not self._pressed:
            self._set_tab_hover(False)
        super().leaveEvent(event)

    def _set_tab_hover(self, hovered):
        """Anima el grosor de la pestaña lateral en respuesta al cursor.
        Args:
            hovered: Booleano indicando presencia del ratón.
        Returns:
            None
        """
        if (hovered == self._tab_hovered or self.is_expanded
                or self._animating or self._pressed):
            return
        self._tab_hovered = hovered
        target = self.hover_tab_width if hovered else self.collapsed_width
        start = self._vis
        self._apply_frame(self._p, self._vis)
        self.tween.start(
            "tab", DUR_TAB,
            lambda t: self._apply_frame(self._p, start + (target - start) * t),
            lambda: self._apply_frame(self._p, self._vis),
            easing=QEasingCurve.OutBack if hovered else QEasingCurve.OutCubic,
            overshoot=1.4,
        )

    # --------------------------------------------------------------------------
    # Expandir / colapsar
    # --------------------------------------------------------------------------
    def _snapshot_panel(self):
        """Renderiza los controles del panel en una imagen transparente auxiliar.
        Returns:
            QImage con la captura del contenido o None si falla.
        """
        try:
            self.panel.ensurePolished()
            self.panel.layout().activate()
            img = QImage(self.panel.size(), QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            self.panel.render(
                img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren
            )
            return img
        except Exception:
            return None

    def toggle_panel(self):
        """Alterna entre estado colapsado y desplegado mediante animación líquida.
        Returns:
            None
        """
        if self._animating:
            return
        opening = not self.is_expanded
        self.is_expanded = opening
        self.tween.cancel("tab")
        self._tab_hovered = False

        vis0 = max(self._vis, float(self.collapsed_width))
        if opening:
            s0 = self._tab_box(vis0)
            ia0 = clamp01((self._vis - 14) / 16)
            self._render_rail()
            self.setCursor(Qt.ArrowCursor)
            self.activateWindow()
            self.raise_()
        else:
            s0 = self._tab_box(self.collapsed_width)
            ia0 = 0.0
            self.setCursor(Qt.PointingHandCursor)

        img = self._snapshot_panel()
        v = 0.0 if opening else 1.0
        self._bub = {
            "open": opening, "s0": s0, "img": img, "ed": v, "el": v,
            "k": v, "ca": v, "ia": ia0 if opening else 0.0, "ia0": ia0,
            "r0": self._tab_radius(vis0 if opening else self.collapsed_width),
        }
        self._animating = True
        self._apply_frame(
            1.0 if opening else 0.0,
            self._vis if opening else float(self.collapsed_width),
            force=True,
        )
        self.repaint()

        def done():
            self._animating = False
            self._bub = None
            self._apply_frame(
                1.0 if opening else 0.0,
                0.0 if opening else float(self.collapsed_width),
            )
            if opening:
                self.activateWindow()
                self.search_entry.setFocus()

        dur = DUR_PANEL if opening else DUR_PANEL - 120
        self.tween.start(
            "panel", dur, self._bubble_frame, done, easing=QEasingCurve.Linear
        )

    # --------------------------------------------------------------------------
    # Foco y arrastre libre entre monitores
    # --------------------------------------------------------------------------
    def _saved_dim(self, key, default):
        """Lee una dimensión guardada validando su tipo.
        Args:
            key: Clave en app_data.
            default: Valor por defecto.
        Returns:
            Entero con la dimensión.
        """
        v = self.app_data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
        return default

    def _clamp_panel_size(self):
        """Limita el tamaño del panel a los márgenes del monitor activo.
        Returns:
            True si el tamaño cambió.
        """
        max_w = max(MIN_PANEL_W, int(self.screen_w * 0.9))
        max_h = max(MIN_PANEL_H, int(self.screen_h * 0.95))
        w = self._clamp(int(self.expanded_width), MIN_PANEL_W, max_w)
        h = self._clamp(int(self.panel_h), MIN_PANEL_H, max_h)
        changed = (w, h) != (self.expanded_width, self.panel_h)
        self.expanded_width, self.panel_h = w, h
        return changed

    def _set_panel_size(self, w, h):
        """Cambia el tamaño del panel en vivo y reajusta la geometría.
        Args:
            w: Ancho deseado en píxeles.
            h: Alto deseado en píxeles.
        Returns:
            None
        """
        old = (self.expanded_width, self.panel_h)
        self.expanded_width, self.panel_h = int(w), int(h)
        self._clamp_panel_size()
        if (self.expanded_width, self.panel_h) == old:
            return
        self.panel.setFixedSize(self.expanded_width, self.panel_h)
        self._place_grip()
        self._apply_frame(self._p, self._vis, force=True)

    def _place_grip(self):
        """Coloca el tirador en la esquina libre según el borde acoplado.
        Returns:
            None
        """
        if not hasattr(self, "grip"):
            return
        g = self.grip
        s = g.width()
        w, h = self.expanded_width, self.panel_h
        if self.edge == "right":
            g.move(0, h - s)
            g.set_corner("bl")
        elif self.edge == "bottom":
            g.move(w - s, 0)
            g.set_corner("tr")
        else:
            g.move(w - s, h - s)
            g.set_corner("br")
        g.raise_()

    def _on_grip_press(self, gpos):
        """Guarda el tamaño y cursor iniciales del redimensionado.
        Args:
            gpos: QPoint global.
        Returns:
            None
        """
        if self._animating:
            return
        self._rs_start = (
            gpos.x(), gpos.y(), self.expanded_width, self.panel_h
        )

    def _on_grip_move(self, gpos):
        """Calcula el nuevo tamaño según el desplazamiento y el borde acoplado.
        Args:
            gpos: QPoint global actual.
        Returns:
            None
        """
        if self._rs_start is None or self._animating:
            return
        x0, y0, w0, h0 = self._rs_start
        dx, dy = gpos.x() - x0, gpos.y() - y0
        if self.edge == "right":
            w, h = w0 - dx, h0 + 2 * dy
        elif self.edge == "left":
            w, h = w0 + dx, h0 + 2 * dy
        elif self.edge == "top":
            w, h = w0 + 2 * dx, h0 + dy
        else:
            w, h = w0 + 2 * dx, h0 - dy
        self._set_panel_size(w, h)

    def _on_grip_release(self):
        """Persiste el tamaño elegido al soltar el tirador.
        Returns:
            None
        """
        if self._rs_start is None:
            return
        self._rs_start = None
        self.app_data["panel_w"] = self.expanded_width
        self.app_data["panel_h"] = self.panel_h
        save_data(self.app_data)

    def _release_focus_soon(self):
        """Reactiva el plegado por foco tras un breve margen de estabilización.
        Returns:
            None
        """
        QTimer.singleShot(300, self._release_focus_guard)

    def _release_focus_guard(self):
        """Desactiva la protección de foco y recupera la ventana activa.
        Returns:
            None
        """
        self._ignore_focus = False
        if self.is_expanded and not self._animating:
            self.activateWindow()

    def event(self, e):
        """Intercepta eventos de ventana para detectar desactivación de foco.
        Args:
            e: Instancia QEvent recibida.
        Returns:
            Booleano devuelto por la clase base QWidget.
        """
        if e.type() == QEvent.WindowDeactivate:
            QTimer.singleShot(80, self._check_focus)
        return super().event(e)

    def _check_focus(self):
        """Pliega automáticamente la barra si ninguna ventana propia está activa.
        Returns:
            None
        """
        if not self.is_expanded or self._ignore_focus:
            return
        if self._animating:
            QTimer.singleShot(150, self._check_focus)
            return
        if (QApplication.activeWindow() is None
                and QApplication.activeModalWidget() is None):
            self.toggle_panel()

    def mousePressEvent(self, e):
        """Registra pulsación inicial sobre la pestaña colapsada.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self._p < 0.5 and not self._animating:
            self._on_press(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        """Gestiona arrastre o hover sobre la pestaña colapsada.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if self._pressed and (e.buttons() & Qt.LeftButton):
            self._on_motion(e.globalPosition().toPoint())
        elif not self.is_expanded and not self._pressed:
            self._set_tab_hover(True)

    def mouseReleaseEvent(self, e):
        """Finaliza la interacción de clic o arrastre sobre la pestaña.
        Args:
            e: Evento de ratón QMouseEvent.
        Returns:
            None
        """
        if e.button() == Qt.LeftButton and self._pressed:
            self._on_release()

    def _on_press(self, gpos):
        """Almacena las coordenadas globales de inicio de arrastre.
        Args:
            gpos: QPoint en coordenadas globales.
        Returns:
            None
        """
        self._drag_start_x = gpos.x()
        self._drag_start_y = gpos.y()
        self._is_dragging = False
        self._pressed = True

    def _on_motion(self, gpos):
        """Desplaza y acopla dinámicamente el panel al borde más cercano.
        Args:
            gpos: QPoint actual del cursor en coordenadas globales.
        Returns:
            None
        """
        if not self._pressed:
            return
        dx = gpos.x() - self._drag_start_x
        dy = gpos.y() - self._drag_start_y
        if not self._is_dragging and (abs(dx) > 4 or abs(dy) > 4):
            self._is_dragging = True
        if not self._is_dragging:
            return

        target_mon = self._get_monitor_at(gpos.x(), gpos.y())
        if target_mon != self.current_mon:
            self.current_mon = target_mon
            self._update_monitor_metrics()

        ch = self.collapsed_height
        self.current_x = gpos.x() - ch // 2
        self.current_y = gpos.y() - ch // 2

        mx, my, mw, mh = self.mon_x, self.mon_y, self.screen_w, self.screen_h
        dists = {
            "left": abs(gpos.x() - mx),
            "right": abs((mx + mw) - gpos.x()),
            "top": abs(gpos.y() - my),
            "bottom": abs((my + mh) - gpos.y()),
        }
        new_edge = min(dists, key=dists.get)
        if new_edge != self.edge:
            self.edge = new_edge
            self._pack_panel_children()

        self._apply_frame(self._p, self._vis, force=True)

    def _on_release(self):
        """Persiste la nueva posición tras arrastrar o conmuta el panel.
        Returns:
            None
        """
        if not self._pressed:
            return
        self._pressed = False
        if self._is_dragging:
            self.app_data["pos_x"] = self.current_x
            self.app_data["pos_y"] = self.current_y
            self.app_data["edge"] = self.edge
            try:
                self.app_data["monitor_idx"] = self.monitors.index(
                    self.current_mon
                )
            except ValueError:
                self.app_data["monitor_idx"] = 0
            save_data(self.app_data)
            self._is_dragging = False
        else:
            self.toggle_panel()

    def _on_screen_added(self, scr):
        """Engancha el aviso de cambios del nuevo monitor y reajusta la barra.
        Args:
            scr: QScreen recién conectado.
        Returns:
            None
        """
        scr.geometryChanged.connect(self._on_screens_changed)
        self._on_screens_changed()

    def _on_screens_changed(self, *args):
        """Programa un reajuste tras cambios de monitores, resolución o escala.
        Returns:
            None
        """
        log_error("DIAG cambio de pantallas: " + describe_screens())
        self._screen_timer.start(400)

    def _refit_to_screens(self):
        """Recalcula monitores y reubica la barra dentro de una pantalla válida.
        Returns:
            None
        """
        try:
            self.monitors = self._get_monitors()
            self.current_mon = self._get_monitor_at(
                self.current_x, self.current_y
            )
            self._update_monitor_metrics()
            self.current_x = self._clamp(
                self.current_x, self.mon_x,
                self.mon_x + self.screen_w - self.collapsed_height,
            )
            self.current_y = self._clamp(
                self.current_y, self.mon_y,
                self.mon_y + self.screen_h - self.collapsed_height,
            )
            self._apply_frame(self._p, self._vis, force=True)
        except Exception:
            log_error(traceback.format_exc())

    def _heal(self):
        """Recupera la ventana si desaparece sin que el usuario la haya ocultado.
        Returns:
            None
        """
        if self._hidden_mode or self._selector is not None:
            return
        try:
            if not self.isVisible():
                log_error("DIAG ventana oculta sin motivo: se vuelve a mostrar")
                self.show()
                self._refit_to_screens()
                return
            geo = self.geometry()
            if not any(
                geo.intersects(scr.geometry())
                for scr in QGuiApplication.screens()
            ):
                log_error("DIAG ventana fuera de pantalla: se reubica")
                self._refit_to_screens()
        except Exception:
            log_error(traceback.format_exc())

    def hideEvent(self, e):
        """Registra con su origen cada vez que se oculta la ventana principal.
        Args:
            e: Evento QHideEvent.
        Returns:
            None
        """
        log_error(
            "DIAG ocultar ventana principal (usuario=%s)\n%s"
            % (self._hidden_mode, "".join(traceback.format_stack(limit=6)))
        )
        super().hideEvent(e)

    def closeEvent(self, e):
        """Registra con su origen cada cierre de la ventana principal.
        Args:
            e: Evento QCloseEvent.
        Returns:
            None
        """
        log_error(
            "DIAG closeEvent ventana principal\n"
            + "".join(traceback.format_stack(limit=6))
        )
        super().closeEvent(e)

    def reveal(self):
        """Muestra la ventana si estaba oculta y despliega el panel.
        Returns:
            None
        """
        self._hidden_mode = False
        if not self.isVisible():
            self.show()
        self._refit_to_screens()
        if not self.is_expanded and not self._animating:
            self.toggle_panel()
        self.raise_()
        self.activateWindow()

    def toggle_tab_visibility(self):
        """Oculta o muestra por completo la pestaña acoplada (modo segundo plano).
        Returns:
            None
        """
        if self.isVisible():
            self._hidden_mode = True
            self.hide()
        else:
            self._hidden_mode = False
            self.show()
            self._refit_to_screens()

    def _close_app(self):
        """Detiene animaciones y temporizadores y cierra la aplicación limpiamente.
        Returns:
            None
        """
        log_error("DIAG cierre solicitado (_close_app)")
        self.tween.cancel_all()
        for name in ("_heal_timer", "_screen_timer", "_copy_timer"):
            t = getattr(self, name, None)
            if t is not None:
                t.stop()
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.hide()
        QApplication.quit()

    # --------------------------------------------------------------------------
    # Buscador y lista
    # --------------------------------------------------------------------------
    def _clear_search(self):
        """Vacía el texto de búsqueda y retira el foco del campo.
        Returns:
            None
        """
        self.search_entry.clear()
        self.search_entry.clearFocus()
        self.setFocus()

    def _update_status_default(self):
        """Restaura el mensaje y estilo predeterminados de la barra inferior.
        Returns:
            None
        """
        if not self._status_timer.isActive():
            self.status_label.setText(
                "Clic para copiar · doble clic para editar"
            )
            self.status_label.setStyleSheet(
                f"color: {THEME['text_muted']}; background: transparent;"
            )

    def _make_preview(self, content, limit=42):
        """Compacta el contenido multilínea en un resumen de una sola línea.
        Args:
            content: Texto completo del snippet.
            limit: Número máximo de caracteres permitidos.
        Returns:
            Cadena resumida truncada con elipsis si excede el límite.
        """
        flat = " ".join(content.split())
        return flat if len(flat) <= limit else flat[:limit - 1] + "…"

    def _refresh_list(self, keys=None):
        """Reconstruye los widgets SnippetCard mostrados en el área desplazable.
        Args:
            keys: Lista opcional de claves filtradas a renderizar.
        Returns:
            None
        """
        self.scroll_list.clear()
        self.cards = {}
        items = keys if keys is not None else list(self.snippets.keys())

        if not items:
            empty = (
                "Aún no hay snippets. Crea el primero abajo."
                if not self.snippets
                else "Ningún título coincide con la búsqueda."
            )
            lbl = QLabel(empty)
            lbl.setFont(ui_font(9))
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setContentsMargins(0, 24, 0, 24)
            lbl.setStyleSheet(
                f"color: {THEME['text_muted']}; background: transparent;"
            )
            self.scroll_list.add_widget(lbl)
            return

        for key in items:
            preview = self._make_preview(self.snippets.get(key, ""))
            card = SnippetCard(
                key, preview,
                on_select=self._click_key, on_activate=self._edit_key,
                on_delete=self._delete_key,
                selected=(key == self.selected_key),
            )
            self.scroll_list.add_widget(card)
            self.cards[key] = card

    def _filter_snippets(self, *args):
        """Filtra las tarjetas visibles en función del texto del buscador.
        Returns:
            None
        """
        query = self.search_entry.text().lower().strip()
        filtered = [k for k in self.snippets if query in k.lower()]
        self._refresh_list(filtered)

    def _mark_selected(self, key):
        """Resalta visualmente un snippet sin copiar nada al portapapeles.
        Args:
            key: Título del snippet a resaltar.
        Returns:
            None
        """
        if self.selected_key and self.selected_key in self.cards:
            self.cards[self.selected_key].set_selected(False)
        self.selected_key = key
        if key in self.cards:
            self.cards[key].set_selected(True)

    def _select_key(self, key):
        """Marca como seleccionado un snippet y copia su valor al portapapeles.
        Args:
            key: Título del snippet seleccionado.
        Returns:
            None
        """
        self._mark_selected(key)
        QGuiApplication.clipboard().setText(self.snippets.get(key, ""))
        self._flash_status(f"Copiado «{key}»", "primary")

    def _cancel_pending_copy(self):
        """Anula una copia diferida que estaba esperando un posible doble clic.
        Returns:
            None
        """
        self._copy_timer.stop()
        self._pending_copy_key = None

    def _click_key(self, key):
        """Gestiona un clic simple: resalta ya y copia al acabar el intervalo de doble clic.
        Args:
            key: Título del snippet pulsado.
        Returns:
            None
        """
        self._mark_selected(key)
        self._pending_copy_key = key
        self._copy_timer.start(max(150, QApplication.doubleClickInterval()))

    def _flush_pending_copy(self):
        """Copia el snippet pendiente si sigue existiendo cuando vence el temporizador.
        Returns:
            None
        """
        key, self._pending_copy_key = self._pending_copy_key, None
        if key is not None and key in self.snippets:
            self._select_key(key)

    def _edit_key(self, key):
        """Abre la ventana de edición del snippet sin copiarlo al portapapeles.
        Args:
            key: Título del snippet a editar.
        Returns:
            None
        """
        self._cancel_pending_copy()
        if key not in self.snippets:
            return
        self._mark_selected(key)
        self._open_edit_window(key, self.snippets.get(key, ""))

    def _flash_status(self, text, color="primary", ms=1800):
        """Muestra un aviso temporal coloreado en la etiqueta de estado.
        Args:
            text: Mensaje a mostrar.
            color: Clave de THEME o código hexadecimal.
            ms: Tiempo de permanencia en milisegundos.
        Returns:
            None
        """
        col_hex = resolve_hex(color)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {col_hex}; background: transparent;"
        )
        self._status_timer.start(ms)

    def _reset_status(self):
        """Restablece la etiqueta inferior cuando expira el aviso temporal.
        Returns:
            None
        """
        self._update_status_default()

    # ==========================================================================
    # Operaciones CRUD y ventana de edición auto-dimensionable
    # ==========================================================================
    def _delete_key(self, key):
        """Pide confirmación modal y elimina el snippet seleccionado.
        Args:
            key: Título del snippet a borrar.
        Returns:
            None
        """
        self._cancel_pending_copy()
        self._ignore_focus = True
        try:
            if show_dialog(
                self, "Confirmar", f"¿Eliminar «{key}»?", "question",
                confirm_text="Eliminar", danger=True,
            ):
                del self.snippets[key]
                if self.selected_key == key:
                    self.selected_key = None
                self.app_data["snippets"] = self.snippets
                save_data(self.app_data)
                self._filter_snippets()
                self._flash_status(f"Eliminado «{key}»", "danger")
        finally:
            self._release_focus_soon()

    def _calculate_edit_win_size(self, content):
        """Calcula dimensiones óptimas de ventana según longitud del texto.
        Args:
            content: Cadena de texto que contendrá el editor.
        Returns:
            Tupla (ancho, alto) en píxeles.
        """
        base_w, base_h = 460, 360
        max_w = int(self.screen_w * 0.80)
        max_h = int(self.screen_h * 0.80)
        if not content:
            return base_w, base_h

        fm = QFontMetrics(QFont("Consolas", 9))
        char_w = max(6, fm.horizontalAdvance("0"))
        line_h = max(14, fm.lineSpacing())

        lines = content.splitlines() or [""]
        max_chars = max(len(line) for line in lines)
        calc_w = max(base_w, min(max_w, max_chars * char_w + 110))
        chars_per_line = max(40, (calc_w - 80) // char_w)
        visual_lines = sum(
            max(1, (len(line) // chars_per_line) + 1) for line in lines
        )
        calc_h = max(base_h, min(max_h, visual_lines * line_h + 230))
        return int(calc_w), int(calc_h)

    def _open_edit_window(self, original_key=None, original_content="",
                          prefill_title=None):
        """Instancia, registra y muestra una ventana EditWindow.
        Args:
            original_key: Título original si se edita, o None si es creación.
            original_content: Texto inicial para poblar el editor.
            prefill_title: Título predefinido opcional.
        Returns:
            None
        """
        win = EditWindow(self, original_key, original_content, prefill_title)
        self._open_editors.append(win)
        win.destroyed.connect(
            lambda *_: (
                self._open_editors.remove(win)
                if win in self._open_editors else None
            )
        )
        win.show()
        win.activateWindow()
        win.title_entry.setFocus()

    # ==========================================================================
    # Captura de pantalla multimonitor y OCR asíncrono
    # ==========================================================================
    def _start_ocr(self):
        """Pliega el panel si está abierto e inicia la secuencia de captura.
        Returns:
            None
        """
        if ocr_script is None:
            show_dialog(
                self, "OCR no disponible",
                "No se pudo cargar el módulo text_from_image:\n"
                f"{OCR_IMPORT_ERROR}", "error",
            )
            return
        if self._selector is not None or self._loader is not None:
            return
        if self.is_expanded:
            self.toggle_panel()
        QTimer.singleShot(DUR_PANEL + 140, self._show_selector)

    def _show_selector(self):
        """Oculta temporalmente la pestaña antes de capturar los monitores.
        Returns:
            None
        """
        self.setWindowOpacity(0.0)
        QTimer.singleShot(80, self._launch_selector)

    def _launch_selector(self):
        """Inicia el selector de región multimonitor.
        Returns:
            None
        """
        m = self.current_mon
        try:
            sel = RegionSelector(
                QRect(m["left"], m["top"], m["width"], m["height"]), self
            )
            sel.finished.connect(self._on_region_selected)
            self._selector = sel
            sel.start()
        except Exception as e:
            self.setWindowOpacity(1.0)
            show_dialog(
                self, "Error de captura",
                f"No se pudo capturar la pantalla:\n{e}", "error",
            )
            if not self.is_expanded:
                self.toggle_panel()

    def _on_region_selected(self, region):
        """Restaura la opacidad y lanza el OCR si existe un recorte válido.
        Args:
            region: Imagen PIL recortada o None si se canceló.
        Returns:
            None
        """
        self.setWindowOpacity(1.0)
        self._selector = None
        if region is None:
            if not self.is_expanded:
                self.toggle_panel()
            return
        self._process_ocr_region(region)

    def _process_ocr_region(self, region):
        """Ejecuta el reconocimiento óptico de caracteres en un hilo daemon.
        Args:
            region: Imagen PIL seleccionada por el usuario.
        Returns:
            None
        """
        self._ignore_focus = True
        self._loader = LoadingDialog(self.current_mon)
        bridge = self._ocr_bridge

        def worker():
            texto = ""
            error_msg = ""
            try:
                imagen_procesada = ocr_script.preprocesar_para_ocr(region)
                texto = ocr_script.extraer_texto(imagen_procesada)
                if texto is None:
                    texto = ""
            except Exception as e:
                error_msg = str(e) or e.__class__.__name__
            bridge.done.emit(texto, error_msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_ocr_complete(self, texto, error_msg):
        """Recibe el texto extraído en el hilo principal y abre el editor.
        Args:
            texto: Cadena reconocida por el módulo OCR.
            error_msg: Mensaje de error en caso de excepción, o cadena vacía.
        Returns:
            None
        """
        if self._loader is not None:
            self._loader.close()
            self._loader = None
        self._release_focus_soon()

        if error_msg:
            show_dialog(
                self, "Error en OCR",
                f"Ocurrió un fallo al procesar la imagen:\n{error_msg}",
                "error",
            )

        if not self.is_expanded:
            self.toggle_panel()

        nombre = f"Captura {datetime.now().strftime('%H:%M:%S')}"
        QTimer.singleShot(
            DUR_PANEL + 60,
            lambda: self._open_edit_window(None, texto.strip(), nombre),
        )


def describe_screens():
    """Resume los monitores detectados (geometría y escala) para el registro.
    Returns:
        Cadena de una línea.
    """
    parts = []
    for scr in QGuiApplication.screens():
        g = scr.geometry()
        parts.append(
            f"{scr.name()} {g.x()},{g.y()} {g.width()}x{g.height()} "
            f"@{scr.devicePixelRatio():.2f}"
        )
    return " | ".join(parts) or "sin pantallas"


def make_app_pixmap(size):
    """Dibuja el icono de la aplicación (portapapeles sobre cuadrado redondeado).
    Args:
        size: Lado del icono en píxeles.
    Returns:
        QPixmap con fondo transparente.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    base = DEFAULT_USER_THEME["primary"]
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(0.5, 0.5, size - 1, size - 1), size * 0.24, size * 0.24
    )
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor(blend(base, "#FFFFFF", 0.24)))
    grad.setColorAt(1.0, QColor(base))
    p.fillPath(path, grad)
    icon_clipboard(
        p, size / 2, size / 2, size * 0.62, QColor("#FFFFFF"),
        width=max(1.2, size * 0.07),
    )
    p.end()
    return pm


def make_app_icon():
    """Crea un QIcon multiresolución para la ventana y la bandeja.
    Returns:
        Instancia QIcon.
    """
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(make_app_pixmap(size))
    return icon


def _instance_key():
    """Nombre del canal local usado para detectar otra instancia del mismo usuario.
    Returns:
        Cadena identificadora.
    """
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"SnippetBaulSidebar.{user}"


def notify_running_instance():
    """Avisa a una instancia ya abierta y comprueba que realmente responde.
    Returns:
        True solo si otra instancia respondió "ok" (esta debe cerrarse).
        Si existe pero no responde (bloqueada o sin ventana), devuelve False
        para que esta copia arranque con normalidad.
    """
    sock = QLocalSocket()
    sock.connectToServer(_instance_key())
    if not sock.waitForConnected(500):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(500)
    answered = False
    if sock.waitForReadyRead(2500):
        answered = bytes(sock.readAll()).startswith(b"ok")
    sock.abort()
    if not answered:
        log_error(
            "Había una instancia previa que no respondió (posible proceso "
            "bloqueado); se inicia una nueva."
        )
    return answered


def start_instance_server(win):
    """Escucha avisos de nuevas ejecuciones para mostrar la ventana existente.
    Args:
        win: Instancia principal de SnippetApp.
    Returns:
        QLocalServer activo o None si no pudo iniciarse.
    """
    QLocalServer.removeServer(_instance_key())
    server = QLocalServer(win)
    if not server.listen(_instance_key()):
        log_error(f"No se pudo abrir el canal de instancia única: "
                  f"{server.errorString()}")
        return None

    def _answer(sock):
        sock.readAll()
        try:
            win.reveal()
            sock.write(b"ok")
        except Exception:
            log_error(traceback.format_exc())
            sock.write(b"err")
        sock.flush()

    def _on_connection():
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()
            if sock is None:
                break
            sock.readyRead.connect(lambda s=sock: _answer(s))
            sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(_on_connection)
    return server


def build_tray(win):
    """Crea el icono de la bandeja del sistema con su menú contextual.
    Args:
        win: Instancia principal de SnippetApp.
    Returns:
        QSystemTrayIcon, o None si el sistema no dispone de bandeja.
    """
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log_error("Bandeja del sistema no disponible.")
        return None
    tray = QSystemTrayIcon(make_app_icon(), win)
    tray.setToolTip("Baúl de snippets")
    menu = QMenu()

    act_open = QAction("Abrir panel", menu)
    act_open.triggered.connect(win.reveal)
    act_tab = QAction("Mostrar / ocultar pestaña", menu)
    act_tab.triggered.connect(win.toggle_tab_visibility)
    act_auto = QAction("Iniciar con Windows", menu)
    act_auto.setCheckable(True)
    act_auto.setVisible(sys.platform == "win32")
    act_auto.toggled.connect(lambda on: set_autostart(on))
    act_dir = QAction("Abrir carpeta de datos", menu)
    act_dir.triggered.connect(
        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR))
    )
    act_quit = QAction("Salir", menu)

    def _quit():
        tray.hide()
        win._close_app()

    act_quit.triggered.connect(_quit)

    def _refresh():
        act_auto.blockSignals(True)
        act_auto.setChecked(is_autostart_on())
        act_auto.blockSignals(False)

    menu.aboutToShow.connect(_refresh)
    for act in (act_open, act_tab, act_auto, act_dir):
        menu.addAction(act)
    menu.addSeparator()
    menu.addAction(act_quit)

    def _on_activated(reason):
        if reason in (
            QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick
        ):
            if win.isVisible() and win.is_expanded:
                win.toggle_panel()
            else:
                win.reveal()

    tray.activated.connect(_on_activated)
    tray.setContextMenu(menu)
    tray._menu = menu
    tray.show()
    return tray


def main():
    """Punto de entrada principal de la aplicación Qt.
    Returns:
        None
    """
    install_crash_logging()
    if AUTOSTART_ENABLED:
        set_autostart(True)
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SnippetBaul.Sidebar"
            )
        except Exception:
            pass
    app = QApplication(sys.argv)
    if notify_running_instance():
        return
    log_error(
        f"DIAG inicio pid={os.getpid()} args={sys.argv[1:]} "
        f"frozen={_is_frozen()} datos={DATA_DIR} "
        f"bandeja={QSystemTrayIcon.isSystemTrayAvailable()} "
        f"pantallas: {describe_screens()}"
    )
    app.aboutToQuit.connect(lambda: log_error("DIAG aboutToQuit"))
    app.setQuitOnLastWindowClosed(False)
    app.setFont(ui_font(9))
    app.setWindowIcon(make_app_icon())
    win = SnippetApp()
    win._instance_server = start_instance_server(win)
    win._tray = build_tray(win)
    if "--hidden" in sys.argv[1:] and win._tray is not None:
        win._hidden_mode = True
    else:
        win.show()

    if win._tray is None:
        # Al iniciar sesión, el explorador puede no tener aún bandeja: reintenta.
        attempts = {"n": 0}
        retry = QTimer(win)

        def _retry_tray():
            attempts["n"] += 1
            if win._tray is None and QSystemTrayIcon.isSystemTrayAvailable():
                win._tray = build_tray(win)
            if win._tray is not None or attempts["n"] >= 40:
                retry.stop()

        retry.timeout.connect(_retry_tray)
        retry.start(3000)

    code = app.exec()
    log_error(f"DIAG fin del bucle de eventos, código {code}")
    server = getattr(win, "_instance_server", None)
    if server is not None:
        server.close()
    # Salida inmediata: evita procesos huérfanos por el cierre de Qt/hilos.
    os._exit(code)


if __name__ == "__main__":
    main()