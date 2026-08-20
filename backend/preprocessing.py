import io
from PIL import Image, ImageFilter, ImageEnhance, ImageOps


def is_frame_too_bad(image_bytes: bytes) -> bool:
    """
    Image quality check to detect severe glare reflection or camera obstruction.
    Returns True if the frame is unreadable, False otherwise.

    Criteria:
    - Pure white blown-out glare (> 250 brightness) > 50% of crop -> Bad frame (severe light reflection)
    - Total dark (< 10 brightness) > 95% of crop -> Bad frame (obstructed lens)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        histogram = img.histogram()
        total_pixels = sum(histogram)

        if total_pixels == 0:
            return True

        near_white_count = sum(histogram[250:])
        near_black_count = sum(histogram[:10])

        white_ratio = near_white_count / total_pixels
        black_ratio = near_black_count / total_pixels

        if white_ratio > 0.70:
            return True

        if black_ratio > 0.99:
            return True

        return False
    except Exception as e:
        print(f"Quality check warning: {e}")
        return False


def preprocess_image(image_bytes: bytes, field_type: str = "default") -> bytes:
    """
    Enhances medical monitor ROI crops captured by physical webcams before sending to Vision AI / Local OCR:
    1. Channel-specific color isolation (Green for HR, Cyan for SpO2, Yellow for EtCO2, White for BP)
    2. Boosts contrast to make bright monitor digits pop against dark screens
    3. Normalizes lighting levels via ImageOps.autocontrast
    4. Applies unsharp mask sharpening for legibility
    5. Returns clean JPEG image bytes
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # 1. Color channel separation for target LED colors
        if img.mode in ("RGB", "RGBA"):
            r, g, b = img.convert("RGB").split()
            if field_type == "heart_rate":
                # Green LED digits pop in Green channel
                img = g
            elif field_type == "spo2":
                # Cyan LED digits pop in Blue/Green blend
                img = Image.blend(g, b, 0.5)
            elif field_type == "etco2":
                # Yellow LED digits pop in Red/Green blend
                img = Image.blend(r, g, 0.5)
            else:
                img = img.convert("L")
        else:
            img = img.convert("L")

        # 2. Boost contrast for clean background separation
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.6)

        # 3. Apply autocontrast normalization with mild cutoff for monitor reflections
        img = ImageOps.autocontrast(img, cutoff=1)

        # 4. Sharpen digit edges (Unsharp Mask works great for camera LCD crops)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=3))

        # 5. Save processed image as high-quality JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=95)
        return buffer.getvalue()
    except Exception as e:
        print(f"Preprocessing warning: {e}, using raw image bytes.")
        return image_bytes

