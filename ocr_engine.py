"""
OCR Engine module.
Extracts text from screenshots using Tesseract OCR, with preprocessing for optimal accuracy.
Works with pytesseract if installed, or falls back directly to the tesseract CLI binary.
"""

import io
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

logger = logging.getLogger(__name__)


class OCREngine:
    """Handles text extraction (OCR) from images."""

    def __init__(self, lang: str = "eng", tesseract_cmd: Optional[str] = None):
        self.lang = lang
        self.tesseract_cmd = tesseract_cmd or self._find_tesseract()
        if self.tesseract_cmd and PYTESSERACT_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

    def _find_tesseract(self) -> Optional[str]:
        """Locates the tesseract executable across common platform locations."""
        cmd = shutil.which("tesseract")
        if cmd:
            return cmd

        # Common Windows paths
        win_candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in win_candidates:
            if os.path.exists(candidate):
                return candidate

        # Termux / Linux paths
        linux_candidates = [
            "/data/data/com.termux/files/usr/bin/tesseract",
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/opt/homebrew/bin/tesseract",
        ]
        for candidate in linux_candidates:
            if os.path.exists(candidate):
                return candidate

        return None

    def preprocess_image(self, image: "Image.Image") -> "Image.Image":
        """
        Enhance image contrast and convert to grayscale to improve OCR character recognition.
        """
        if not PILLOW_AVAILABLE:
            return image

        try:
            # Convert to grayscale
            gray = image.convert("L")
            # Enhance contrast
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(1.8)
            # Apply slight sharpening
            sharpened = enhanced.filter(ImageFilter.SHARPEN)
            return sharpened
        except Exception as e:
            logger.debug("Image preprocessing skipped due to: %s", e)
            return image

    def extract_text(self, image_input) -> str:
        """
        Extract text from a PIL Image or image file path.
        Returns the extracted text as a string.
        """
        if not self.tesseract_cmd:
            logger.warning(
                "Tesseract executable not found. OCR cannot run. "
                "Install Tesseract (e.g. 'pkg install tesseract' or 'apt install tesseract-ocr')."
            )
            return ""

        # Load image if file path is provided
        img = None
        temp_file_to_clean = None
        try:
            if isinstance(image_input, (str, bytes, os.PathLike)):
                if PILLOW_AVAILABLE:
                    img = Image.open(image_input)
                else:
                    return self._run_tesseract_cli(str(image_input))
            elif PILLOW_AVAILABLE and isinstance(image_input, Image.Image):
                img = image_input
            else:
                logger.error("Unsupported image input type: %s", type(image_input))
                return ""

            # Preprocess image
            processed_img = self.preprocess_image(img)

            # Option 1: Use pytesseract if installed
            if PYTESSERACT_AVAILABLE:
                try:
                    text = pytesseract.image_to_string(processed_img, lang=self.lang)
                    return text.strip()
                except Exception as pe:
                    logger.debug("pytesseract failed, falling back to CLI: %s", pe)

            # Option 2: Fallback to direct Tesseract CLI
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_file_to_clean = tmp.name
                processed_img.save(tmp.name, format="PNG")

            return self._run_tesseract_cli(temp_file_to_clean)

        except Exception as e:
            logger.error("Failed to extract text via OCR: %s", e)
            return ""
        finally:
            if temp_file_to_clean and os.path.exists(temp_file_to_clean):
                try:
                    os.remove(temp_file_to_clean)
                except OSError:
                    pass

    def _run_tesseract_cli(self, image_path: str) -> str:
        """Run tesseract binary directly on an image file."""
        if not self.tesseract_cmd:
            return ""
        try:
            res = subprocess.run(
                [self.tesseract_cmd, image_path, "stdout", "-l", self.lang],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                return res.stdout.strip()
            else:
                logger.debug("Tesseract CLI stderr: %s", res.stderr)
                return ""
        except Exception as e:
            logger.error("Direct Tesseract execution failed: %s", e)
            return ""
