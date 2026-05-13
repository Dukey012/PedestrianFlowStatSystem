from ultralytics import YOLO

from core.types import DetectionBox


class PersonDetector:
    def __init__(self, model_path="models/yolo11n.pt", conf_threshold=0.55, image_size=640):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.image_size = image_size
        self.model = None

    def load(self):
        self.model = YOLO(self.model_path)
        self.model.classes = [0]

    def detect(self, frame):
        if self.model is None:
            self.load()

        results = self.model(frame, imgsz=self.image_size, verbose=False)[0]
        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = box.conf[0].item()
            if conf > self.conf_threshold:
                detections.append(
                    DetectionBox([x1, y1, x2 - x1, y2 - y1], conf, 0)
                )
        return detections
