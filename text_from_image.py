#!/usr/bin/env python3
"""
Captura de pantalla + OCR + portapapeles.

Flujo:
1. Congela la pantalla (captura completa como imagen estática).
2. Permite seleccionar una región arrastrando el ratón sobre esa captura.
3. Extrae el texto de la región con Tesseract OCR, aplicando un pipeline
   de preprocesado (escala de grises, sobremuestreo, filtrado de ruido,
   binarización adaptativa) y probando varios modos de segmentación (PSM)
   para maximizar la precisión con independencia de la complejidad de
   la imagen (bajo contraste, texto pequeño, fondos irregulares, etc.).
4. Copia el texto resultante al portapapeles (equivalente a Ctrl+C).

Dependencias Python:
    pip install mss pillow pytesseract opencv-python numpy pyperclip

Requiere también el motor Tesseract instalado en el sistema (no es un
paquete pip, es un binario aparte):
    Linux:   sudo apt install tesseract-ocr tesseract-ocr-spa
    macOS:   brew install tesseract tesseract-lang
    Windows: instalador oficial de Tesseract-OCR + añadirlo al PATH

En Linux, pyperclip necesita además xclip o xsel:
    sudo apt install xclip

Modo manuscrito (--manuscrito, solo Windows):
    Usa el motor de OCR nativo de Windows (el mismo que el Recorte o
    PowerToys Text Extractor) en vez de Tesseract. Gratis, sin cuenta,
    sin nube. Se ejecuta vía PowerShell (interop WinRT de .NET, más
    estable que los bindings Python), así que no necesita paquetes pip
    adicionales — solo que ocr_windows.ps1 esté en la misma carpeta que
    este script, y el paquete de idioma con OCR instalado en Windows:
    Configuración > Hora e idioma > Idioma y región > Añadir idioma (o
    pulsa sobre el que ya tengas), marcando "Reconocimiento óptico de
    caracteres".
"""

import sys
import tkinter as tk

import cv2
import mss
import numpy as np
import pyperclip
import pytesseract
from PIL import Image, ImageEnhance, ImageTk

# En Windows, Tesseract no suele quedar en el PATH automáticamente.
# Se busca en las rutas típicas de instalación; si tu instalación está en
# otro sitio, añade la ruta a RUTAS_TESSERACT_WINDOWS o edita _localizar_tesseract().
RUTAS_TESSERACT_WINDOWS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\{}\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    r"C:\Users\{}\AppData\Local\Tesseract-OCR\tesseract.exe",
]


def _localizar_tesseract():
    """Configura pytesseract con la ruta del binario de Tesseract en Windows.
    Si no lo encuentra en ninguna ruta conocida, lanza un error claro en
    vez de dejar que pytesseract falle más abajo con un traceback críptico.
    """
    if sys.platform != "win32":
        return  # en Linux/macOS se asume que está en el PATH

    import os
    import shutil

    # 0. Tesseract incluido en el paquete (ejecutable compilado con PyInstaller):
    # carpeta "tesseract" dentro del paquete (_MEIPASS) o junto al .exe.
    bases = [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
    for base in filter(None, bases):
        ruta = os.path.join(base, "tesseract", "tesseract.exe")
        if os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            os.environ["TESSDATA_PREFIX"] = os.path.join(
                base, "tesseract", "tessdata"
            )
            return

    # 1. ¿Ya está en el PATH?
    ruta_en_path = shutil.which("tesseract")
    if ruta_en_path:
        pytesseract.pytesseract.tesseract_cmd = ruta_en_path
        return

    # 2. Rutas típicas de instalación
    usuario = os.environ.get("USERNAME", "")
    for plantilla in RUTAS_TESSERACT_WINDOWS:
        ruta = plantilla.format(usuario) if "{}" in plantilla else plantilla
        if os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            return

    raise RuntimeError(
        "No se encontró Tesseract-OCR instalado.\n"
        "Descárgalo desde https://github.com/UB-Mannheim/tesseract/wiki "
        "e instálalo (o, si ya lo instalaste, añade su ruta a "
        "RUTAS_TESSERACT_WINDOWS al principio de este script)."
    )


_localizar_tesseract()

# Windows aplica escalado de DPI por monitor que desalinea las coordenadas
# del ratón respecto a los píxeles reales capturados si no se declara el
# proceso como "DPI aware". Esto es imprescindible para que el rectángulo
# de selección coincida con la región realmente capturada.
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

IDIOMAS_OCR = "spa+eng"  # ajusta según los idiomas del texto a reconocer


class SelectorRegion:
    """
    Congela la pantalla completa y permite seleccionar una región con el
    ratón, con el mismo efecto visual que el Recorte de Windows: toda la
    pantalla se atenúa y, mientras arrastras, el interior del rectángulo
    se muestra con el brillo normal.
    """

    FACTOR_ATENUADO = 0.35  # 0 = negro total, 1 = sin atenuar

    def __init__(self):
        self.captura_completa = self._capturar_pantalla_completa()
        self.captura_atenuada = self._crear_version_atenuada(self.captura_completa)

        self.inicio = None
        self.rect_id = None
        self.overlay_img_id = None
        self.overlay_photo = None  # referencia viva, si no la GC la borra
        self.region_seleccionada = None

        ancho, alto = self.captura_completa.size

        self.root = tk.Tk()
        # overrideredirect + geometry explícita en vez de "-fullscreen":
        # con DPI awareness activada, "-fullscreen" puede dimensionar la
        # ventana en unidades lógicas distintas de los píxeles físicos de
        # la captura, dejando huecos por los que se ve el escritorio real
        # (la sensación de que "las cosas se siguen moviendo") y desajusta
        # las coordenadas del ratón, con lo que cualquier arrastre parece
        # un simple clic y la selección se cancela.
        self.root.overrideredirect(True)
        self.root.geometry(f"{ancho}x{alto}+0+0")
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")
        self.root.lift()
        self.root.focus_force()

        self.tk_img_atenuado = ImageTk.PhotoImage(self.captura_atenuada)
        self.canvas = tk.Canvas(
            self.root, width=ancho, height=alto, highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img_atenuado, anchor="nw")

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self._cancelar())

    def _capturar_pantalla_completa(self):
        with mss.MSS() as sct:
            # monitors[1] = monitor primario; monitors[0] = todos combinados
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img

    def _crear_version_atenuada(self, img):
        negro = Image.new("RGB", img.size, (0, 0, 0))
        return Image.blend(img, negro, 1 - self.FACTOR_ATENUADO)

    def _coords_validas(self, event):
        ancho, alto = self.captura_completa.size
        x = min(max(event.x, 0), ancho)
        y = min(max(event.y, 0), alto)
        return x, y

    def _on_press(self, event):
        self.inicio = self._coords_validas(event)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        if self.overlay_img_id:
            self.canvas.delete(self.overlay_img_id)
            self.overlay_img_id = None

    def _on_drag(self, event):
        if self.inicio is None:
            return
        x0, y0 = self.inicio
        x1, y1 = self._coords_validas(event)
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left < 1 or bottom - top < 1:
            return

        # Recorta la imagen ORIGINAL (brillo normal) solo en la zona
        # seleccionada y la superpone sobre el fondo atenuado.
        recorte = self.captura_completa.crop((left, top, right, bottom))
        self.overlay_photo = ImageTk.PhotoImage(recorte)
        if self.overlay_img_id:
            self.canvas.delete(self.overlay_img_id)
        self.overlay_img_id = self.canvas.create_image(
            left, top, image=self.overlay_photo, anchor="nw"
        )

        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            left, top, right, bottom, outline="#00A2FF", width=2
        )

    def _on_release(self, event):
        if self.inicio is None:
            self._cancelar()
            return
        x0, y0 = self.inicio
        x1, y1 = self._coords_validas(event)
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left < 3 or bottom - top < 3:
            self._cancelar()
            return
        self.region_seleccionada = (left, top, right, bottom)
        self.root.destroy()

    def _cancelar(self):
        self.region_seleccionada = None
        self.root.destroy()

    def seleccionar(self):
        self.root.mainloop()
        if self.region_seleccionada is None:
            return None
        return self.captura_completa.crop(self.region_seleccionada)


def preprocesar_para_ocr(imagen_pil: Image.Image) -> np.ndarray:
    """
    Pipeline de preprocesado para maximizar la precisión del OCR con
    independencia del contraste, ruido o tamaño del texto original.
    """
    img = cv2.cvtColor(np.array(imagen_pil), cv2.COLOR_RGB2BGR)

    # 1. Escala de grises
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Sobremuestreo: Tesseract rinde mejor con texto grande
    escala = 3
    alto, ancho = gris.shape
    gris = cv2.resize(
        gris, (ancho * escala, alto * escala),
        interpolation=cv2.INTER_CUBIC
    )

    # 3. Detección de polaridad: Tesseract espera texto oscuro sobre fondo
    # claro. Con capturas de texto claro sobre fondo oscuro (temas oscuros
    # de editores, terminales, etc.) hay que invertir antes de binarizar,
    # si no el resultado sale con los colores cambiados y el OCR falla.
    _, otsu = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    proporcion_clara = np.mean(otsu == 255)
    if proporcion_clara < 0.5:
        # la clase mayoritaria (el fondo) es oscura -> invertir
        gris = 255 - gris

    # 4. Eliminación de ruido conservando bordes del texto
    gris = cv2.bilateralFilter(gris, 9, 75, 75)

    # 5. Binarización adaptativa (robusta ante iluminación/fondo irregular)
    binaria = cv2.adaptiveThreshold(
        gris, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 11
    )

    # 6. Limpieza morfológica ligera de puntos sueltos
    kernel = np.ones((1, 1), np.uint8)
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE, kernel)

    return binaria


def extraer_texto(imagen_bin: np.ndarray, idiomas: str = IDIOMAS_OCR) -> str:
    """
    Ejecuta OCR probando varios modos de segmentación de página (PSM)
    de Tesseract y se queda con el resultado más largo, para adaptarse
    a distintos tipos de layout (párrafo, columna, texto disperso...).
    """
    modos_psm = [6, 4, 11, 3]
    mejor_texto = ""

    for psm in modos_psm:
        config = f"--oem 3 --psm {psm}"
        try:
            texto = pytesseract.image_to_string(imagen_bin, lang=idiomas, config=config)
        except pytesseract.TesseractError:
            continue
        texto = texto.strip()
        if len(texto) > len(mejor_texto):
            mejor_texto = texto

    return mejor_texto


def extraer_texto_manuscrito(imagen_pil: Image.Image) -> str:
    """
    OCR especializado en escritura manuscrita usando el motor OCR nativo
    de Windows (Windows.Media.Ocr) — el mismo que usan el Recorte y
    PowerToys Text Extractor. Gratis, sin cuenta, sin nube.

    Se ejecuta vía PowerShell (ocr_windows.ps1, debe estar en la misma
    carpeta que este script) en vez de con los bindings winrt de Python:
    el interop WinRT de .NET/PowerShell es mucho más maduro y estable
    que la proyección Python (winrt), que en Python 3.14 dio resultados
    erráticos e impredecibles.

    Requiere solo que el paquete de idioma con OCR esté instalado en
    Windows (Configuración > Hora e idioma > Idioma y región).
    """
    if sys.platform != "win32":
        raise RuntimeError("El modo manuscrito con Windows OCR solo está disponible en Windows.")

    import os
    import subprocess
    import tempfile

    script_ps1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_windows.ps1")
    if not os.path.isfile(script_ps1):
        raise RuntimeError(
            f"No se encontró {script_ps1}.\n"
            "Coloca ocr_windows.ps1 en la misma carpeta que este script."
        )

    # Modificación: Escala de grises, aumento de contraste y reescalado
    imagen_pil = imagen_pil.convert("L")
    imagen_pil = ImageEnhance.Contrast(imagen_pil).enhance(2.0)

    ALTURA_MINIMA_RECOMENDADA = 250
    ancho, alto = imagen_pil.size
    lado_menor = min(ancho, alto)
    
    if lado_menor < ALTURA_MINIMA_RECOMENDADA:
        factor = min(ALTURA_MINIMA_RECOMENDADA / lado_menor, 6.0)
        imagen_pil = imagen_pil.resize(
            (round(ancho * factor), round(alto * factor)), Image.LANCZOS
        )

    fd_in, ruta_entrada = tempfile.mkstemp(suffix=".png")
    os.close(fd_in)
    fd_out, ruta_salida = tempfile.mkstemp(suffix=".txt")
    os.close(fd_out)
    try:
        imagen_pil.convert("RGB").save(ruta_entrada, format="PNG")

        proceso = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", script_ps1,
                "-ImagePath", ruta_entrada,
                "-OutputPath", ruta_salida,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

        if proceso.returncode != 0:
            raise RuntimeError(
                "Error al ejecutar el OCR de Windows vía PowerShell:\n"
                f"{proceso.stderr.strip()}"
            )

        # utf-8-sig por si Out-File/WriteAllText deja BOM al principio
        with open(ruta_salida, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    finally:
        for ruta in (ruta_entrada, ruta_salida):
            try:
                os.remove(ruta)
            except OSError:
                pass

def main():
    modo_manuscrito = "--manuscrito" in sys.argv

    selector = SelectorRegion()
    region = selector.seleccionar()

    if region is None:
        print("Selección cancelada.")
        sys.exit(0)

    if modo_manuscrito:
        texto = extraer_texto_manuscrito(region)
    else:
        imagen_procesada = preprocesar_para_ocr(region)
        texto = extraer_texto(imagen_procesada)

    if not texto:
        print("No se detectó texto en la región seleccionada.")
        sys.exit(1)

    pyperclip.copy(texto)
    print("Texto copiado al portapapeles:\n")
    print(texto)


if __name__ == "__main__":
    main()