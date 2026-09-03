"""
Vision Detector
Receive a photo, detect it with NudeNet. According the rule of config to make choose whther it 
need to block. Returing the spot that trigger the block
"""
from nudenet import NudeDetector
from app import config


class Detector:

    def __init__(self):
      self.model = NudeDetector()

    def check(self, image):
       """checking a photo, make decision whether to block
          image: photo path
       """
       check_points = self.model.detect(image) # return the list of dictionaries ,each dict is body parts

       for element in check_points:
          body_part = element["class"]
          score = element["score"]

          if body_part in config.BLOCK_LABELS: # whether it's a block part
             is_block_part = True

          if score >= config.DETECTION_THRESHOLD:
             is_over_threshold = True

          if is_block_part and is_over_threshold:
             return {
                "blocked": True,
             }
