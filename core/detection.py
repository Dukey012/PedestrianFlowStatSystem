from ultralytics import YOLO

from core.types import DetectionBox


class PersonDetector:
    def __init__(
        self,
        model_path="models/yolo11n.pt",
        conf_threshold=0.5,
        image_size=640,
        person_class_id=0,
    ):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.image_size = image_size
        self.person_class_id = person_class_id
        self.model = None

    def load(self):
        self.model = YOLO(self.model_path)
        self.model.classes = [self.person_class_id]

    def detect(self, frame):
        if self.model is None:
            self.load()

        results = self.model(
            frame,
            imgsz=self.image_size,
            classes=[self.person_class_id],
            verbose=False,
        )[0]
        detections = []
        for box in results.boxes:
            class_id = int(box.cls[0].item())
            if class_id != self.person_class_id:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = box.conf[0].item()
            if conf > self.conf_threshold:
                detections.append(
                    DetectionBox([x1, y1, x2 - x1, y2 - y1], conf, class_id)
                )
        return detections
