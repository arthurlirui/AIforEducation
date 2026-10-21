"""模块 1.1：基于 YOLO 的多物体图像分割。

将油画或水墨画的不同部分分割出来，形成多个物体的 mask，并保留背景。
YOLO 未安装时退化为基于颜色聚类的 mock 分割（连通域 + 上下分层），保证流程可测试。

支持模型：YOLOv8-seg / YOLO11-seg / YOLO26-seg（ultralytics 框架统一接口）。
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..config import Settings
from ..schemas import ObjectCategory, SegmentedObject

logger = logging.getLogger(__name__)

# YOLO COCO 标签到画作物体类别的映射
_COCO_TO_CATEGORY: dict[str, ObjectCategory] = {
    "person": ObjectCategory.PERSON,
    "bird": ObjectCategory.ANIMAL, "cat": ObjectCategory.ANIMAL,
    "dog": ObjectCategory.ANIMAL, "horse": ObjectCategory.ANIMAL,
    "sheep": ObjectCategory.ANIMAL, "cow": ObjectCategory.ANIMAL,
    "elephant": ObjectCategory.ANIMAL, "bear": ObjectCategory.ANIMAL,
    "zebra": ObjectCategory.ANIMAL, "giraffe": ObjectCategory.ANIMAL,
    "car": ObjectCategory.VEHICLE, "truck": ObjectCategory.VEHICLE,
    "boat": ObjectCategory.VEHICLE, "bicycle": ObjectCategory.VEHICLE,
    "motorcycle": ObjectCategory.VEHICLE, "bus": ObjectCategory.VEHICLE,
    "potted plant": ObjectCategory.PLANT,
    "house": ObjectCategory.BUILDING, "building": ObjectCategory.BUILDING,
    "bottle": ObjectCategory.OBJECT, "vase": ObjectCategory.OBJECT,
    "bowl": ObjectCategory.OBJECT, "cup": ObjectCategory.OBJECT,
    "book": ObjectCategory.OBJECT, "clock": ObjectCategory.OBJECT,
}


def _label_to_category(label: str) -> ObjectCategory:
    """将 YOLO 标签映射到画作物体类别。"""
    return _COCO_TO_CATEGORY.get(label.lower(), ObjectCategory.OBJECT)


def segment_with_yolo(
    image_rgb: np.ndarray,
    model_name: str,
    conf_threshold: float,
    iou_threshold: float,
) -> list[dict]:
    """用 YOLO 分割模型检测物体。

    返回 list of {label, confidence, mask, bbox}。
    需要 ultralytics 包已安装。
    """
    from ultralytics import YOLO

    logger.info("YOLO 分割中 (model=%s)...", model_name)
    model = YOLO(model_name)
    results = model(
        image_rgb,
        conf=conf_threshold,
        iou=iou_threshold,
        verbose=False,
    )

    detections: list[dict] = []
    for result in results:
        if result.masks is None:
            continue
        masks_data = result.masks.data.cpu().numpy()       # (N, H, W)
        boxes = result.boxes
        for i in range(len(masks_data)):
            mask = (masks_data[i] * 255).astype(np.uint8)
            # 缩放到原图尺寸
            if mask.shape[:2] != image_rgb.shape[:2]:
                mask = cv2.resize(mask, (image_rgb.shape[1], image_rgb.shape[0]),
                                  interpolation=cv2.INTER_NEAREST)
            cls_id = int(boxes.cls[i].item())
            label = model.names[cls_id]
            conf = float(boxes.conf[i].item())
            x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().tolist()
            detections.append({
                "label": label,
                "confidence": conf,
                "mask": mask,
                "bbox": (int(x1), int(y1), int(x2), int(y2)),
            })

    logger.info("YOLO 检测到 %d 个物体", len(detections))
    return detections


def segment_mock(image_rgb: np.ndarray) -> list[dict]:
    """无 YOLO 时的 fallback：基于颜色聚类的连通域分割。

    策略：K-Means 聚类 → 连通域分析 → 按面积筛选物体候选。
    """
    h, w = image_rgb.shape[:2]
    # 降采样加速 K-Means
    small = cv2.resize(image_rgb, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)

    # K-Means 聚类（K=5 个颜色簇）
    k = 5
    _, labels, centers = cv2.kmeans(
        pixels, k, None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
        3, cv2.KMEANS_PP_CENTERS,
    )
    labels = labels.reshape(small.shape[:2])

    detections: list[dict] = []
    object_id = 0

    # 对每个聚类做连通域分析
    for cluster_idx in range(k):
        cluster_mask = (labels == cluster_idx).astype(np.uint8) * 255
        # 缩放回原尺寸
        cluster_mask = cv2.resize(cluster_mask, (w, h), interpolation=cv2.INTER_NEAREST)

        # 连通域分析
        num_labels, comp_labels, stats, centroids = cv2.connectedComponentsWithStats(
            cluster_mask, connectivity=8)

        for comp_idx in range(1, num_labels):  # 跳过背景
            area = stats[comp_idx, cv2.CC_STAT_AREA]
            if area < (h * w * 0.01):  # 过滤太小的区域
                continue
            if area > (h * w * 0.6):   # 过滤太大的区域（通常是背景）
                continue

            comp_mask = (comp_labels == comp_idx).astype(np.uint8) * 255
            x0 = int(stats[comp_idx, cv2.CC_STAT_LEFT])
            y0 = int(stats[comp_idx, cv2.CC_STAT_TOP])
            x1 = x0 + int(stats[comp_idx, cv2.CC_STAT_WIDTH])
            y1 = y0 + int(stats[comp_idx, cv2.CC_STAT_HEIGHT])

            # 根据位置推测类别（油画常见构图）
            cy = (y0 + y1) / 2 / h
            cx = (x0 + x1) / 2 / w
            if cy > 0.6:
                label = "person"
            elif cy < 0.4:
                label = "building"
            else:
                label = "object"

            detections.append({
                "label": label,
                "confidence": 0.7 + np.random.rand() * 0.2,
                "mask": comp_mask,
                "bbox": (x0, y0, x1, y1),
            })
            object_id += 1

    # 如果没检测到任何物体，用上下分层确保至少有一个前景
    if not detections:
        logger.warning("Mock 分割未检测到物体，使用上下分层 fallback")
        fg_mask = np.zeros((h, w), dtype=np.uint8)
        fg_mask[2 * h // 3:, :] = 255
        detections.append({
            "label": "person",
            "confidence": 0.6,
            "mask": fg_mask,
            "bbox": (0, 2 * h // 3, w, h),
        })

    logger.info("Mock 分割完成: %d 个物体", len(detections))
    return detections


def _create_background(
    image_rgb: np.ndarray,
    object_masks: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """生成背景掩码和背景图像（前景区域填为周围均值色）。

    返回 (background_mask, background_image)。
    """
    h, w = image_rgb.shape[:2]
    # 合并所有前景掩码
    fg_union = np.zeros((h, w), dtype=np.uint8)
    for mask in object_masks:
        fg_union |= (mask > 0).astype(np.uint8)

    # 背景掩码 = 1 - 前景并集
    bg_mask = (1 - fg_union) * 255

    # 背景图像：前景区域用 inpaint 填充
    bg_image = image_rgb.copy()
    if fg_union.any():
        inpaint_mask = fg_union * 255
        bg_image = cv2.inpaint(bg_image, inpaint_mask, 3, cv2.INPAINT_TELEA)

    return bg_mask, bg_image


def run_segmentation(
    painting_path: Path,
    output_dir: Path,
    settings: Settings,
) -> tuple[list[SegmentedObject], Path, Path, str]:
    """执行多物体分割。

    返回 (objects, background_mask_path, background_path, detector_name)。
    """
    image = cv2.imread(str(painting_path))
    if image is None:
        raise FileNotFoundError(f"无法读取图像: {painting_path}")
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # 尝试 YOLO，失败则 mock
    detector = "mock"
    try:
        detections = segment_with_yolo(
            image_rgb,
            settings.yolo_model,
            settings.yolo_conf_threshold,
            settings.yolo_iou_threshold,
        )
        detector = "yolo"
    except (ImportError, Exception) as e:
        logger.warning("YOLO 不可用 (%s)，使用 mock 分割", e)
        detections = segment_mock(image_rgb)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存各物体 mask 和裁剪图
    objects: list[SegmentedObject] = []
    object_masks: list[np.ndarray] = []

    for i, det in enumerate(detections):
        mask = det["mask"]
        object_masks.append(mask)
        mask_path = output_dir / f"mask_obj{i:02d}_{det['label']}.png"
        cv2.imwrite(str(mask_path), mask)

        # 裁剪物体区域（背景透明）
        x0, y0, x1, y1 = det["bbox"]
        crop = image_rgb[y0:y1, x0:x1].copy()
        mask_crop = mask[y0:y1, x0:x1]
        # mask 外区域设为白
        crop[~(mask_crop > 0)] = 255
        crop_path = output_dir / f"crop_obj{i:02d}_{det['label']}.png"
        cv2.imwrite(str(crop_path), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))

        category = _label_to_category(det["label"])
        near, far = settings.depth_range_for(category.value)
        objects.append(SegmentedObject(
            object_id=i,
            category=category,
            label=det["label"],
            confidence=det["confidence"],
            mask_path=mask_path,
            bbox=(x0, y0, x1, y1),
            crop_path=crop_path,
            depth_range=(near, far),
        ))

    # 生成背景
    bg_mask, bg_image = _create_background(image_rgb, object_masks)
    bg_mask_path = output_dir / "mask_background.png"
    bg_path = output_dir / "background.png"
    cv2.imwrite(str(bg_mask_path), bg_mask)
    cv2.imwrite(str(bg_path), cv2.cvtColor(bg_image, cv2.COLOR_RGB2BGR))

    logger.info("分割完成: %d 个物体 + 背景 (detector=%s)", len(objects), detector)
    return objects, bg_mask_path, bg_path, detector
