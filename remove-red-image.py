from PIL import Image
import cv2
import numpy as np

def remove_red_by_color(
    pil_image,
    dilation_kernel_size=(4, 4),
    inpaint_radius=3
):
    """
    1) Convert PIL image (RGB) to OpenCV BGR np.array.
    2) Identify red pixels based on RGB conditions:
       - Red > Blue and Red > Green
       - Blue ~ Green (almost equal)
       - min(R, G, B) > 15 and max(R, G, B) < 245 (avoid extreme values)
    3) Create a mask and dilate it.
    4) Inpaint the removed areas using cv2.inpaint.
    5) Convert back to PIL (RGB) and return.
    """
    # --- Convert PIL (RGB) -> OpenCV (BGR) ---
    cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    # --- Extract B, G, R channels ---
    b, g, r = cv2.split(cv_image)
    
    # --- Create mask based on RGB conditions ---
    red_mask = (
        # (r > g) & (r > b) & 
        (np.abs(b - g) < 10)  # Ensure blue and green are close
        # (np.minimum(r, np.minimum(g, b)) > 15) &
        # (np.maximum(r, np.maximum(g, b)) < 245)
    )
    mask = np.uint8(red_mask) * 255  # Convert boolean mask to uint8
    
    # --- Dilate the mask to remove a bit more around red areas ---
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, dilation_kernel_size)
    mask_dilated = cv2.dilate(mask, kernel, iterations=1)
    
    # --- Inpaint (fill) the removed red areas using surrounding pixels ---
    inpainted = cv2.inpaint(cv_image, mask_dilated, inpaint_radius, cv2.INPAINT_TELEA)
    
    # --- Convert back to PIL (BGR -> RGB) ---
    inpainted_rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
    pil_result = Image.fromarray(inpainted_rgb)
    
    return pil_result

# Load image
input_image_path = "sample.png"  # Change this to your image path
output_image_path = "output.png"

image = Image.open(input_image_path)

# Apply red removal function
processed_image = remove_red_by_color(image)

# Save the result
processed_image.save(output_image_path)
print(f"Processed image saved as {output_image_path}")
