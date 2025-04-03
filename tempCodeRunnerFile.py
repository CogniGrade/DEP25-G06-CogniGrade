import os
from pdf2image import convert_from_path
import cv2
import numpy as np
from PIL import Image

def remove_red_and_inpaint_opencv(
    pil_image,
    # Aggressive lower/upper HSV bounds for wide variety of reds:
    hsv_lower1 = (0,   25,  60),   # H=0,  S=50,  V=20
    hsv_upper1 = (10, 255, 255),  # H=10, S=255, V=255
    hsv_lower2 = (170, 25, 60),
    hsv_upper2 = (179, 255, 255),

    dilation_kernel_size=(4, 4),
    inpaint_radius=3
):
    """
    1) Convert PIL image (RGB) to OpenCV BGR np.array.
    2) Convert to HSV and create a mask for a broad red range 
       (covering dark reds, bright reds, etc.).
    3) Dilate the mask to expand removed areas.
    4) Inpaint the removed areas using cv2.inpaint.
    5) Convert back to PIL (RGB) and return.
    """
    # --- Convert PIL (RGB) -> OpenCV (BGR) ---
    cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    # --- Convert BGR -> HSV ---
    hsv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2HSV)

    # --- Create two broad masks for red in HSV ---
    mask1 = cv2.inRange(
        hsv,
        np.array(hsv_lower1, dtype=np.uint8),
        np.array(hsv_upper1, dtype=np.uint8)
    )
    mask2 = cv2.inRange(
        hsv,
        np.array(hsv_lower2, dtype=np.uint8),
        np.array(hsv_upper2, dtype=np.uint8)
    )

    # Combine the two masks
    mask = cv2.bitwise_or(mask1, mask2)

    # --- Dilate the mask to remove a bit more around red areas ---
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, dilation_kernel_size)
    mask_dilated = cv2.dilate(mask, kernel, iterations=1)

    # --- Inpaint (fill) the removed red areas using surrounding pixels ---
    # You can choose cv2.INPAINT_NS or cv2.INPAINT_TELEA
    inpainted = cv2.inpaint(cv_image, mask_dilated, inpaint_radius, cv2.INPAINT_TELEA)

    # --- Convert back to PIL (BGR -> RGB) ---
    inpainted_rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
    pil_result = Image.fromarray(inpainted_rgb)

    return pil_result

def pdf_remove_red_and_save_opencv(pdf_path, dpi=300):
    """
    1. Convert each PDF page to a PIL image (via pdf2image).
    2. Use OpenCV to remove a broad range of reds (including dark reds) and inpaint.
    3. Save each cleaned page as a JPEG (optional).
    4. Combine all cleaned pages into a single multi-page PDF.
    """
    pdf_dir = os.path.dirname(pdf_path)
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]

    # Create an output folder for optional per-page JPEGs
    output_folder = os.path.join(pdf_dir, f"{pdf_name}_cleaned_pages")
    os.makedirs(output_folder, exist_ok=True)

    # Convert PDF to list of PIL Images
    pages = convert_from_path(pdf_path, dpi=dpi)
    cleaned_images = []

    for i, page in enumerate(pages, start=1):
        cleaned_page = remove_red_and_inpaint_opencv(page)

        # (Optional) Save each cleaned page to JPEG
        # output_filename = os.path.join(output_folder, f"{pdf_name}_page_{i}.jpg")
        # cleaned_page.save(output_filename, "JPEG")
        # print(f"Saved cleaned page {i} to {output_filename}")

        cleaned_images.append(cleaned_page)

    # Merge all cleaned pages into a single PDF
    if cleaned_images:
        output_pdf = os.path.join(pdf_dir, f"{pdf_name}_no_red.pdf")
        cleaned_images[0].save(
            output_pdf,
            "PDF",
            resolution=dpi,
            save_all=True,
            append_images=cleaned_images[1:]
        )
        print(f"\nAll cleaned pages have been combined into: {output_pdf}")
    else:
        print("No pages found or converted.")

# Example usage
if __name__ == "__main__":
    pdf_file_path = "/data-fin/ge103/paper3.pdf"  # Replace with your PDF path
    pdf_remove_red_and_save_opencv(pdf_file_path, dpi=300)
