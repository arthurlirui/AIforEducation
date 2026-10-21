"""Generate synthetic test images for the Kusama polka dot demo."""
import cv2
import numpy as np
import os

os.makedirs("inputs", exist_ok=True)
H, W = 800, 800


# 1. Radial gradient sphere on light background (tests density gradient)
def make_sphere():
    img = np.full((H, W, 3), 235, np.uint8)
    cy, cx = H // 2, W // 2
    Y, X = np.ogrid[:H, :W]
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    R = 300
    mask = dist <= R
    # shade sphere: darker at edges (limb darkening)
    shade = np.clip(1.0 - 0.85 * (dist / R) ** 2, 0, 1)
    for c in range(3):
        ch = img[:, :, c].astype(np.float64)
        ch[mask] = 235 * shade[mask] + 20
        img[:, :, c] = np.clip(ch, 0, 255).astype(np.uint8)
    cv2.imwrite("inputs/sphere.png", img)
    print("Saved inputs/sphere.png")


# 2. Geometric still life: overlapping shapes with shading
def make_still_life():
    img = np.full((H, W, 3), 240, np.uint8)
    # dark circle (pumpkin-like)
    cv2.circle(img, (300, 400), 220, (60, 40, 30), -1)
    # highlight
    cv2.circle(img, (240, 340), 80, (140, 100, 80), -1)
    # a triangle
    pts = np.array([[550, 200], [700, 500], [450, 500]], np.int32)
    cv2.fillPoly(img, [pts], (80, 80, 120))
    # a rectangle
    cv2.rectangle(img, (100, 600), (350, 720), (50, 50, 50), -1)
    # smooth a bit
    img = cv2.GaussianBlur(img, (7, 7), 0)
    cv2.imwrite("inputs/still_life.png", img)
    print("Saved inputs/still_life.png")


# 3. Portrait silhouette (face profile) — high contrast
def make_portrait():
    img = np.full((H, W, 3), 250, np.uint8)
    # face oval (dark)
    cv2.ellipse(img, (400, 380), (180, 240), 0, 0, 360, (40, 35, 35), -1)
    # neck
    cv2.rectangle(img, (340, 580), (460, 800), (40, 35, 35), -1)
    # hair (darker, surrounding)
    cv2.ellipse(img, (400, 300), (220, 180), 0, 180, 360, (20, 15, 15), -1)
    # subtle shading on face: highlight cheekbone
    mask = np.zeros((H, W), np.uint8)
    cv2.ellipse(mask, (470, 380), (60, 90), -20, 0, 360, 255, -1)
    highlight = cv2.GaussianBlur(mask, (51, 51), 0)[:, :, None] / 255.0
    img = img.astype(np.float64)
    img += highlight * 60
    img = np.clip(img, 0, 255).astype(np.uint8)
    cv2.imwrite("inputs/portrait.png", img)
    print("Saved inputs/portrait.png")


# 4. Pumpkin (Kusama's iconic subject)
def make_pumpkin():
    img = np.full((H, W, 3), 250, np.uint8)
    # pumpkin body: lobed ellipse
    cx, cy = 400, 440
    Y, X = np.ogrid[:H, :W]
    # vertical lobes
    lobe = np.abs(np.cos((X - cx) * 0.018)) * 0.18 + 0.82
    dist = np.sqrt(((X - cx) / 280 * lobe) ** 2 + ((Y - cy) / 200) ** 2)
    body = dist < 1.0
    shade = np.clip(1.0 - 0.7 * dist, 0.3, 1.0)
    img_f = img.astype(np.float64)
    for c in range(3):
        img_f[:, :, c][body] = 200 * shade[body] + 30
    # stem
    cv2.rectangle(img_f.astype(np.uint8), (385, 230), (415, 300), (60, 90, 40), -1)
    img_f = img_f.astype(np.uint8)
    img_f = cv2.GaussianBlur(img_f, (5, 5), 0)
    cv2.imwrite("inputs/pumpkin.png", img_f)
    print("Saved inputs/pumpkin.png")


make_sphere()
make_still_life()
make_portrait()
make_pumpkin()
print("\nAll test images generated in inputs/")
